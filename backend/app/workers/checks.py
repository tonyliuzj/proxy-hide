from __future__ import annotations

import asyncio
import json
import ssl
import time
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urljoin, urlsplit

import h11
import re2

from app.gateway.connectors import (
    RequestForm,
    UpstreamConnector,
    pinned_absolute_target,
)
from app.gateway.errors import UpstreamConnectError
from app.gateway.headers import sanitized_response_headers
from app.gateway.models import ProxyProtocol, UpstreamRoute
from app.gateway.security import is_public_address
from app.models import TargetAvailability


class CheckErrorCode(StrEnum):
    DNS = "dns"
    CONNECT = "connect"
    TIMEOUT = "timeout"
    TLS = "tls"
    PROTOCOL = "protocol"
    STATUS = "status"
    CONTENT = "content"
    RESPONSE_TOO_LARGE = "response_too_large"


@dataclass(frozen=True, slots=True)
class CheckSpec:
    url: str
    method: str = "GET"
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""
    status_ranges: tuple[tuple[int, int], ...] = ((200, 399),)
    required_literals: tuple[str, ...] = ()
    forbidden_literals: tuple[str, ...] = ()
    required_patterns: tuple[str, ...] = ()
    forbidden_patterns: tuple[str, ...] = ()
    max_redirects: int = 3
    max_response_bytes: int = 256 * 1024
    capture_exit_ip: bool = False

    def __post_init__(self) -> None:
        method = self.method.upper()
        if method not in {"GET", "HEAD", "POST"}:
            raise ValueError("check method must be GET, HEAD, or POST")
        if len(self.body) > 64 * 1024:
            raise ValueError("check request body exceeds 64 KiB")
        for pattern in self.required_patterns + self.forbidden_patterns:
            _compile_safe_pattern(pattern)


@dataclass(frozen=True, slots=True)
class CheckResult:
    success: bool
    latency_ms: float
    status_code: int | None
    availability: TargetAvailability
    error_code: CheckErrorCode | None = None
    error_message: str | None = None
    exit_ip: str | None = None


@dataclass(frozen=True, slots=True)
class HttpResult:
    status_code: int
    headers: tuple[tuple[bytes, bytes], ...]
    body: bytes


class ProxyCheckRunner:
    def __init__(
        self,
        connector: UpstreamConnector | None = None,
        *,
        timeout: float = 12.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.connector = connector or UpstreamConnector()
        self.timeout = timeout
        self.ssl_context = ssl_context or ssl.create_default_context()

    async def check(self, route: UpstreamRoute, spec: CheckSpec) -> CheckResult:
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.timeout):
                response = await self._request(route, spec)
            latency = (time.monotonic() - started) * 1000
            availability, error = classify_target_response(response, spec)
            return CheckResult(
                success=availability is TargetAvailability.AVAILABLE,
                latency_ms=latency,
                status_code=response.status_code,
                availability=availability,
                error_code=error,
                error_message=None if error is None else error.value,
                exit_ip=_extract_exit_ip(response.body) if spec.capture_exit_ip else None,
            )
        except TimeoutError:
            return self._failure(started, CheckErrorCode.TIMEOUT, "check timed out")
        except ssl.SSLError:
            return self._failure(started, CheckErrorCode.TLS, "target TLS validation failed")
        except UpstreamConnectError as exc:
            return self._failure(started, CheckErrorCode.CONNECT, str(exc))
        except (OSError, h11.ProtocolError, ValueError) as exc:
            return self._failure(started, CheckErrorCode.PROTOCOL, str(exc))

    def _failure(self, started: float, code: CheckErrorCode, message: str) -> CheckResult:
        return CheckResult(
            success=False,
            latency_ms=(time.monotonic() - started) * 1000,
            status_code=None,
            availability=TargetAvailability.UNAVAILABLE,
            error_code=code,
            error_message=message[:500],
        )

    async def _request(self, route: UpstreamRoute, spec: CheckSpec) -> HttpResult:
        current_url = spec.url
        method = spec.method.upper()
        body = spec.body
        for redirect_count in range(spec.max_redirects + 1):
            result = await self._request_once(
                route, current_url, method, spec.headers, body, spec.max_response_bytes
            )
            location = _header(result.headers, b"location")
            if result.status_code not in {301, 302, 303, 307, 308} or location is None:
                return result
            if redirect_count >= spec.max_redirects:
                return result
            current_url = urljoin(current_url, location.decode("latin-1"))
            if result.status_code == 303 and method != "HEAD":
                method, body = "GET", b""
        raise AssertionError("redirect loop should return")

    async def _request_once(
        self,
        route: UpstreamRoute,
        url: str,
        method: str,
        headers: tuple[tuple[str, str], ...],
        body: bytes,
        max_response_bytes: int,
    ) -> HttpResult:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
        ):
            raise ValueError("target URL must be public HTTP(S) without userinfo")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        destination = await self.connector.resolve_destination(parsed.hostname, port)
        connected = await self.connector.open(route, destination, tunnel=parsed.scheme == "https")
        try:
            if parsed.scheme == "https":
                await connected.writer.start_tls(self.ssl_context, server_hostname=parsed.hostname)
                request_form = RequestForm.ORIGIN
            else:
                request_form = connected.request_form
            connection = h11.Connection(h11.CLIENT)
            authority = parsed.hostname if port in {80, 443} else f"{parsed.hostname}:{port}"
            outgoing_headers = [(b"host", authority.encode("ascii")), (b"connection", b"close")]
            outgoing_headers.extend(
                (key.encode("ascii"), value.encode("latin-1")) for key, value in headers
            )
            if body:
                outgoing_headers.append((b"content-length", str(len(body)).encode("ascii")))
            if (
                route.protocol in (ProxyProtocol.HTTP, ProxyProtocol.HTTPS)
                and request_form is RequestForm.ABSOLUTE
            ):
                authorization = self.connector.proxy_authorization(route)
                if authorization:
                    outgoing_headers.append((b"proxy-authorization", authorization))
            origin = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
            target = (
                pinned_absolute_target(url.encode("ascii"), destination)
                if request_form is RequestForm.ABSOLUTE
                else origin.encode("ascii")
            )
            connected.writer.write(
                connection.send(
                    h11.Request(
                        method=method.encode("ascii"), target=target, headers=outgoing_headers
                    )
                )
            )
            if body:
                connected.writer.write(connection.send(h11.Data(data=body)))
            connected.writer.write(connection.send(h11.EndOfMessage()))
            await connected.writer.drain()
            return await _read_response(connection, connected.reader, max_response_bytes)
        finally:
            await connected.close()


async def _read_response(
    connection: h11.Connection,
    reader: asyncio.StreamReader,
    max_response_bytes: int,
) -> HttpResult:
    status: int | None = None
    headers: tuple[tuple[bytes, bytes], ...] = ()
    body = bytearray()
    while True:
        event = connection.next_event()
        if event is h11.NEED_DATA:
            data = await reader.read(64 * 1024)
            connection.receive_data(data)
            if not data and connection.next_event() is h11.NEED_DATA:
                raise h11.RemoteProtocolError("upstream closed before response completed")
            continue
        if isinstance(event, h11.InformationalResponse):
            continue
        if isinstance(event, h11.Response):
            status = event.status_code
            headers = tuple(sanitized_response_headers(event.headers))
        elif isinstance(event, h11.Data):
            body.extend(event.data)
            if len(body) > max_response_bytes:
                raise ValueError("response exceeds inspection limit")
        elif isinstance(event, h11.EndOfMessage):
            if status is None:
                raise h11.RemoteProtocolError("response has no status")
            return HttpResult(status, headers, bytes(body))


def classify_target_response(
    response: HttpResult,
    spec: CheckSpec,
) -> tuple[TargetAvailability, CheckErrorCode | None]:
    content = response.body.decode("utf-8", errors="replace")
    lowered = content.lower()
    if response.status_code == 429 or "rate limit" in lowered or "too many requests" in lowered:
        return TargetAvailability.RATE_LIMITED, CheckErrorCode.STATUS
    if response.status_code in {403, 451} or any(
        marker in lowered for marker in ("captcha", "unusual traffic", "access denied")
    ):
        return TargetAvailability.BLOCKED, CheckErrorCode.CONTENT
    if not any(start <= response.status_code <= end for start, end in spec.status_ranges):
        return TargetAvailability.UNAVAILABLE, CheckErrorCode.STATUS
    if any(value not in content for value in spec.required_literals):
        return TargetAvailability.UNAVAILABLE, CheckErrorCode.CONTENT
    if any(value in content for value in spec.forbidden_literals):
        return TargetAvailability.BLOCKED, CheckErrorCode.CONTENT
    if any(
        _compile_safe_pattern(pattern).search(content) is None for pattern in spec.required_patterns
    ):
        return TargetAvailability.UNAVAILABLE, CheckErrorCode.CONTENT
    if any(
        _compile_safe_pattern(pattern).search(content) is not None
        for pattern in spec.forbidden_patterns
    ):
        return TargetAvailability.BLOCKED, CheckErrorCode.CONTENT
    return TargetAvailability.AVAILABLE, None


def google_check_spec() -> CheckSpec:
    return CheckSpec(
        url="https://www.google.com/search?q=proxyhide-connectivity-check",
        headers=(("Accept", "text/html"),),
        status_ranges=((200, 399),),
        forbidden_literals=("Our systems have detected unusual traffic",),
    )


def bing_check_spec() -> CheckSpec:
    return CheckSpec(
        url="https://www.bing.com/search?q=proxyhide-connectivity-check",
        headers=(("Accept", "text/html"),),
        status_ranges=((200, 399),),
    )


def brave_check_spec() -> CheckSpec:
    return CheckSpec(
        url="https://search.brave.com/search?q=proxyhide-connectivity-check",
        headers=(("Accept", "text/html"),),
        status_ranges=((200, 399),),
    )


def startpage_check_spec() -> CheckSpec:
    return CheckSpec(
        url="https://www.startpage.com/sp/search?query=proxyhide-connectivity-check",
        headers=(("Accept", "text/html"),),
        status_ranges=((200, 399),),
    )


def duckduckgo_check_spec() -> CheckSpec:
    return CheckSpec(
        url="https://duckduckgo.com/html/?q=proxyhide-connectivity-check",
        headers=(("Accept", "text/html"),),
        status_ranges=((200, 399),),
    )


def wikipedia_check_spec() -> CheckSpec:
    return CheckSpec(
        url="https://en.wikipedia.org/w/index.php?search=proxyhide-connectivity-check",
        headers=(("Accept", "text/html"),),
        status_ranges=((200, 399),),
    )


def _compile_safe_pattern(pattern: str) -> re2._Regexp:
    if len(pattern) > 512:
        raise ValueError("regex pattern exceeds 512 characters")
    try:
        return re2.compile(pattern)
    except re2.error as exc:
        raise ValueError("regex is not valid RE2") from exc


def _header(headers: tuple[tuple[bytes, bytes], ...], name: bytes) -> bytes | None:
    for key, value in headers:
        if key.lower() == name:
            return value
    return None


def _extract_exit_ip(body: bytes) -> str | None:
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("ip", parsed.get("origin"))
    if not isinstance(value, str):
        return None
    candidate = value.split(",", 1)[0].strip()
    return candidate if is_public_address(candidate) else None
