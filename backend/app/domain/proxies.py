from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

from app.models import ProxyProtocol


class ProxyParseError(ValueError):
    """A proxy input line cannot be normalized safely."""


_SCHEME_MAP = {
    "http": ProxyProtocol.HTTP,
    "https": ProxyProtocol.HTTPS,
    "socks4": ProxyProtocol.SOCKS4A,
    "socks4a": ProxyProtocol.SOCKS4A,
    "socks5": ProxyProtocol.SOCKS5,
    "socks5h": ProxyProtocol.SOCKS5,
}
_HOST_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.?$",
    re.I,
)


@dataclass(frozen=True, slots=True)
class ParsedProxy:
    protocol: ProxyProtocol
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def authority(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    @property
    def redacted_uri(self) -> str:
        masked_password = quote("***", safe="")
        userinfo = (
            f"{quote(self.username, safe='')}:{masked_password}@"
            if self.username is not None
            else ""
        )
        return f"{self.protocol.value}://{userinfo}{self.authority}"

    @property
    def identity_hash(self) -> str:
        identity = "\0".join(
            [
                self.protocol.value,
                self.host,
                str(self.port),
                self.username or "",
                self.password or "",
            ]
        )
        return hashlib.sha256(identity.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class InvalidProxyLine:
    line: int
    value: str
    error: str


@dataclass(frozen=True, slots=True)
class ProxyParsePreview:
    valid: tuple[ParsedProxy, ...]
    invalid: tuple[InvalidProxyLine, ...]
    duplicate_lines: tuple[int, ...]


def normalize_host(value: str) -> str:
    host = value.strip().removeprefix("[").removesuffix("]").rstrip(".")
    if not host:
        raise ProxyParseError("host is required")
    try:
        return ipaddress.ip_address(host).compressed.lower()
    except ValueError:
        try:
            ascii_host = host.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ProxyParseError("host is not valid IDNA") from exc
        if not _HOST_RE.fullmatch(ascii_host):
            raise ProxyParseError("host is not a valid IP address or DNS name") from None
        return ascii_host


def _validate_credentials(
    username: str | None, password: str | None
) -> tuple[str | None, str | None]:
    if username == "":
        username = None
    if password == "":
        password = None
    if password is not None and username is None:
        raise ProxyParseError("password requires a username")
    for label, value in (("username", username), ("password", password)):
        if value is not None and (len(value.encode()) > 1024 or "\x00" in value):
            raise ProxyParseError(f"{label} is invalid or too long")
    return username, password


def _build(
    protocol: ProxyProtocol, host: str, port: int, username: str | None, password: str | None
) -> ParsedProxy:
    if not 1 <= port <= 65535:
        raise ProxyParseError("port must be between 1 and 65535")
    username, password = _validate_credentials(username, password)
    return ParsedProxy(protocol, normalize_host(host), port, username, password)


def parse_proxy(value: str, default_protocol: ProxyProtocol = ProxyProtocol.HTTP) -> ParsedProxy:
    raw = value.strip()
    if not raw:
        raise ProxyParseError("proxy line is empty")
    if any(character in raw for character in ("\r", "\n", "\x00")):
        raise ProxyParseError("proxy line contains control characters")

    if "://" in raw:
        parts = urlsplit(raw)
        protocol = _SCHEME_MAP.get(parts.scheme.lower())
        if protocol is None:
            raise ProxyParseError(f"unsupported proxy scheme: {parts.scheme or '(missing)'}")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ProxyParseError("proxy URI must not contain a path, query, or fragment")
        try:
            host, port = parts.hostname, parts.port
        except ValueError as exc:
            raise ProxyParseError("proxy URI has an invalid port") from exc
        if host is None or port is None:
            raise ProxyParseError("proxy URI requires host and port")
        return _build(
            protocol,
            host,
            port,
            unquote(parts.username) if parts.username is not None else None,
            unquote(parts.password) if parts.password is not None else None,
        )

    if "@" in raw:
        if raw.count("@") != 1:
            raise ProxyParseError("proxy credentials contain an unescaped @ character")
        userinfo, authority = raw.split("@", 1)
        if ":" not in userinfo:
            raise ProxyParseError("userinfo must be username:password")
        username, password = userinfo.split(":", 1)
        parsed = urlsplit(f"//{authority}")
        try:
            host, port = parsed.hostname, parsed.port
        except ValueError as exc:
            raise ProxyParseError("proxy authority has an invalid port") from exc
        if host is None or port is None:
            raise ProxyParseError("proxy authority requires host and port")
        return _build(default_protocol, host, port, unquote(username), unquote(password))

    if raw.startswith("["):
        end = raw.find("]")
        if end < 0:
            raise ProxyParseError("IPv6 address is missing closing bracket")
        host = raw[1:end]
        remainder = raw[end + 1 :]
        if not remainder.startswith(":"):
            raise ProxyParseError("proxy requires a port")
        fields = remainder[1:].split(":", 2)
    else:
        fields = raw.split(":", 3)
        host, fields = fields[0], fields[1:]

    if not fields or not fields[0].isdigit():
        raise ProxyParseError("proxy requires a numeric port")
    port = int(fields[0])
    credential_username = fields[1] if len(fields) >= 2 else None
    credential_password = fields[2] if len(fields) >= 3 else None
    if len(fields) == 2:
        raise ProxyParseError("host:port:user requires a password")
    return _build(default_protocol, host, port, credential_username, credential_password)


def parse_proxy_text(
    text: str,
    default_protocol: ProxyProtocol = ProxyProtocol.HTTP,
    existing_hashes: set[str] | None = None,
) -> ProxyParsePreview:
    valid: list[ParsedProxy] = []
    invalid: list[InvalidProxyLine] = []
    duplicate_lines: list[int] = []
    seen = set(existing_hashes or ())
    for line_number, value in enumerate(text.splitlines(), start=1):
        stripped = value.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            proxy = parse_proxy(stripped, default_protocol)
        except ProxyParseError as exc:
            invalid.append(InvalidProxyLine(line_number, stripped[:500], str(exc)))
            continue
        if proxy.identity_hash in seen:
            duplicate_lines.append(line_number)
            continue
        seen.add(proxy.identity_hash)
        valid.append(proxy)
    return ProxyParsePreview(tuple(valid), tuple(invalid), tuple(duplicate_lines))
