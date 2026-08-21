from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

from .errors import BadRequest, DestinationDenied

_EXPLICITLY_DENIED_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "0.0.0.0/8",
        "100.64.0.0/10",
        "169.254.0.0/16",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "64:ff9b:1::/48",
        "100::/64",
        "2001:db8::/32",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)


def is_public_address(value: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    try:
        address = (
            value
            if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address))
            else ipaddress.ip_address(value)
        )
    except ValueError:
        return False
    if not address.is_global:
        return False
    return not any(address in network for network in _EXPLICITLY_DENIED_NETWORKS)


@dataclass(frozen=True, slots=True)
class PinnedDestination:
    hostname: str
    port: int
    addresses: tuple[str, ...]


class PublicResolver:
    """Resolve once, reject every non-public answer, and return pinned addresses."""

    def __init__(self, *, timeout: float = 3.0) -> None:
        self.timeout = timeout

    async def resolve(self, hostname: str, port: int) -> PinnedDestination:
        if not hostname or not 1 <= port <= 65535:
            raise DestinationDenied("invalid destination authority")
        host = hostname.rstrip(".")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            if not is_public_address(literal):
                raise DestinationDenied("destination address is not public")
            return PinnedDestination(host, port, (str(literal),))

        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(
                loop.getaddrinfo(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM),
                timeout=self.timeout,
            )
        except (OSError, TimeoutError) as exc:
            raise DestinationDenied("destination could not be resolved") from exc
        addresses = tuple(dict.fromkeys(str(info[4][0]) for info in infos))
        if not addresses or any(not is_public_address(item) for item in addresses):
            raise DestinationDenied("destination DNS includes a non-public address")
        return PinnedDestination(host, port, addresses)


def parse_connect_authority(value: bytes | str) -> tuple[str, int]:
    try:
        authority = value.decode("ascii") if isinstance(value, bytes) else value
    except UnicodeDecodeError as exc:
        raise BadRequest("CONNECT authority must be ASCII") from exc
    if not authority or "@" in authority or any(char in authority for char in "/?#"):
        raise BadRequest("malformed CONNECT authority")
    if authority.startswith("["):
        closing = authority.find("]")
        if closing < 0 or closing + 1 >= len(authority) or authority[closing + 1] != ":":
            raise BadRequest("malformed IPv6 CONNECT authority")
        host = authority[1:closing]
        raw_port = authority[closing + 2 :]
    else:
        if authority.count(":") != 1:
            raise BadRequest("CONNECT authority must include one port")
        host, raw_port = authority.rsplit(":", 1)
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise BadRequest("CONNECT port must be numeric") from exc
    if not host or not 1 <= port <= 65535:
        raise BadRequest("invalid CONNECT authority")
    return host.rstrip("."), port


def parse_absolute_http_target(value: bytes | str) -> tuple[SplitResult, str, int]:
    try:
        target = value.decode("ascii") if isinstance(value, bytes) else value
    except UnicodeDecodeError as exc:
        raise BadRequest("request target must be ASCII") from exc
    parsed = urlsplit(target)
    if parsed.scheme.lower() != "http" or not parsed.netloc or parsed.fragment:
        raise BadRequest("request target must be an absolute http URI")
    if parsed.username is not None or parsed.password is not None:
        raise BadRequest("userinfo is not allowed in request targets")
    try:
        host = parsed.hostname
        port = parsed.port or 80
    except ValueError as exc:
        raise BadRequest("invalid request authority") from exc
    if not host:
        raise BadRequest("request target has no hostname")
    return parsed, host.rstrip("."), port


def origin_form(parsed: SplitResult) -> bytes:
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path.encode("ascii")
