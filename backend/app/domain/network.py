from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit


class DestinationPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PinnedDestination:
    hostname: str
    port: int
    addresses: tuple[str, ...]


def require_public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise DestinationPolicyError("address is not a valid IP") from exc
    if not address.is_global:
        raise DestinationPolicyError("private, reserved, and local addresses are not allowed")
    return address.compressed


async def resolve_public_host(hostname: str, port: int) -> PinnedDestination:
    if not 1 <= port <= 65535:
        raise DestinationPolicyError("port must be between 1 and 65535")
    try:
        direct_ip = require_public_ip(hostname)
    except DestinationPolicyError:
        direct_ip = None
    if direct_ip:
        return PinnedDestination(hostname, port, (direct_ip,))

    loop = asyncio.get_running_loop()
    try:
        results = await loop.getaddrinfo(
            hostname, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror as exc:
        raise DestinationPolicyError("hostname could not be resolved") from exc
    addresses = tuple(dict.fromkeys(require_public_ip(result[4][0]) for result in results))
    if not addresses:
        raise DestinationPolicyError("hostname returned no usable addresses")
    return PinnedDestination(hostname, port, addresses)


async def validate_public_http_url(url: str) -> PinnedDestination:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise DestinationPolicyError("only HTTP and HTTPS URLs are allowed")
    if parts.username is not None or parts.password is not None:
        raise DestinationPolicyError("URL userinfo is not allowed")
    if not parts.hostname:
        raise DestinationPolicyError("URL hostname is required")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise DestinationPolicyError("URL port is invalid") from exc
    return await resolve_public_host(parts.hostname, port)
