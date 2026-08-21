from __future__ import annotations

import asyncio
import base64
import contextlib
import ssl
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import h11

from app.gateway.security import PublicResolver


class FeedFetchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FeedResponse:
    url: str
    body: bytes

    def text(self) -> str:
        try:
            return self.body.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise FeedFetchError("feed is not valid UTF-8") from exc


class PublicFeedFetcher:
    """Small pinned-IP HTTP client for public proxy feeds."""

    def __init__(
        self,
        *,
        resolver: PublicResolver | None = None,
        ssl_context: ssl.SSLContext | None = None,
        request_timeout: float = 15.0,
        max_bytes: int = 10 * 1024 * 1024,
        max_redirects: int = 3,
    ) -> None:
        self.resolver = resolver or PublicResolver()
        self.ssl_context = ssl_context or ssl.create_default_context()
        self.request_timeout = request_timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects

    async def fetch(
        self,
        url: str,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> FeedResponse:
        original_origin = _origin(url)
        current = url
        for redirect in range(self.max_redirects + 1):
            send_credentials = _origin(current) == original_origin
            status, headers, body = await self._request_once(
                current,
                username=username if send_credentials else None,
                password=password if send_credentials else None,
            )
            location = _header(headers, b"location")
            if status in {301, 302, 303, 307, 308} and location is not None:
                if redirect >= self.max_redirects:
                    raise FeedFetchError("feed exceeded the redirect limit")
                current = urljoin(current, location.decode("latin-1"))
                continue
            if not 200 <= status < 300:
                raise FeedFetchError(f"feed returned HTTP {status}")
            return FeedResponse(current, body)
        raise AssertionError("redirect loop should have returned")

    async def _request_once(
        self,
        url: str,
        *,
        username: str | None,
        password: str | None,
    ) -> tuple[int, tuple[tuple[bytes, bytes], ...], bytes]:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.fragment
        ):
            raise FeedFetchError("feed URL must be HTTP(S) without userinfo or fragments")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        destination = await self.resolver.resolve(parsed.hostname, port)
        last_error: Exception | None = None
        for address in destination.addresses:
            try:
                async with asyncio.timeout(self.request_timeout):
                    if parsed.scheme == "https":
                        reader, writer = await asyncio.open_connection(
                            address,
                            port,
                            ssl=self.ssl_context,
                            server_hostname=parsed.hostname,
                        )
                    else:
                        reader, writer = await asyncio.open_connection(address, port)
                    try:
                        return await self._exchange(
                            reader,
                            writer,
                            parsed.hostname,
                            port,
                            parsed.path or "/",
                            parsed.query,
                            username,
                            password,
                        )
                    finally:
                        writer.close()
                        with contextlib.suppress(OSError, RuntimeError):
                            await writer.wait_closed()
            except (OSError, TimeoutError, ssl.SSLError) as exc:
                last_error = exc
        raise FeedFetchError("feed connection failed") from last_error

    async def _exchange(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        hostname: str,
        port: int,
        path: str,
        query: str,
        username: str | None,
        password: str | None,
    ) -> tuple[int, tuple[tuple[bytes, bytes], ...], bytes]:
        connection = h11.Connection(h11.CLIENT)
        authority = hostname if port in {80, 443} else f"{hostname}:{port}"
        headers = [
            (b"host", authority.encode("ascii")),
            (b"accept", b"text/plain, */*;q=0.1"),
            (b"accept-encoding", b"identity"),
            (b"connection", b"close"),
        ]
        if username is not None:
            token = base64.b64encode(f"{username}:{password or ''}".encode())
            headers.append((b"authorization", b"Basic " + token))
        target = path + (f"?{query}" if query else "")
        writer.write(
            connection.send(h11.Request(method=b"GET", target=target, headers=headers))
            + connection.send(h11.EndOfMessage())
        )
        await writer.drain()
        status: int | None = None
        response_headers: tuple[tuple[bytes, bytes], ...] = ()
        body = bytearray()
        while True:
            event = connection.next_event()
            if event is h11.NEED_DATA:
                data = await reader.read(64 * 1024)
                connection.receive_data(data)
                if not data and connection.next_event() is h11.NEED_DATA:
                    raise FeedFetchError("feed response ended unexpectedly")
                continue
            if isinstance(event, h11.InformationalResponse):
                continue
            if isinstance(event, h11.Response):
                status = event.status_code
                response_headers = tuple(event.headers)
                length = _header(response_headers, b"content-length")
                if length is not None and int(length) > self.max_bytes:
                    raise FeedFetchError("feed response is too large")
            elif isinstance(event, h11.Data):
                body.extend(event.data)
                if len(body) > self.max_bytes:
                    raise FeedFetchError("feed response is too large")
            elif isinstance(event, h11.EndOfMessage):
                if status is None:
                    raise FeedFetchError("feed response has no status")
                return status, response_headers, bytes(body)


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FeedFetchError("feed URL must be HTTP(S)")
    return (
        parsed.scheme,
        parsed.hostname.lower(),
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )


def _header(headers: tuple[tuple[bytes, bytes], ...], name: bytes) -> bytes | None:
    for key, value in headers:
        if key.lower() == name:
            return value
    return None
