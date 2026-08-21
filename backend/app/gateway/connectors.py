from __future__ import annotations

import asyncio
import base64
import ipaddress
import ssl
import struct
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .errors import DestinationDenied, UpstreamAuthError, UpstreamConnectError
from .models import ProxyProtocol, UpstreamRoute
from .security import PinnedDestination, PublicResolver, is_public_address


class RequestForm(StrEnum):
    ABSOLUTE = "absolute"
    ORIGIN = "origin"


@dataclass(slots=True)
class ConnectedUpstream:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    request_form: RequestForm
    route: UpstreamRoute

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (OSError, RuntimeError):
            pass


class Resolver(Protocol):
    async def resolve(self, hostname: str, port: int) -> PinnedDestination: ...


OpenConnection = Callable[..., Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


class UpstreamConnector:
    """The only network egress primitive; every destination requires a proxy route."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        upstream_resolver: Resolver | None = None,
        ssl_context: ssl.SSLContext | None = None,
        open_connection: OpenConnection = asyncio.open_connection,
        handshake_limit: int = 32 * 1024,
    ) -> None:
        self.resolver = resolver or PublicResolver()
        self.upstream_resolver = upstream_resolver or PublicResolver()
        self.ssl_context = ssl_context or ssl.create_default_context()
        self._open_connection = open_connection
        self.handshake_limit = handshake_limit

    async def resolve_destination(self, hostname: str, port: int) -> PinnedDestination:
        return await self.resolver.resolve(hostname, port)

    async def open(
        self,
        route: UpstreamRoute,
        destination: PinnedDestination,
        *,
        tunnel: bool,
    ) -> ConnectedUpstream:
        if route.protocol in (ProxyProtocol.HTTP, ProxyProtocol.HTTPS):
            return await self._open_http(route, destination, tunnel=tunnel)
        if route.protocol is ProxyProtocol.SOCKS4A:
            return await self._open_socks4a(route, destination)
        if route.protocol is ProxyProtocol.SOCKS5:
            return await self._open_socks5(route, destination)
        raise UpstreamConnectError("unsupported upstream protocol")

    async def _dial_upstream(
        self, route: UpstreamRoute
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if route.resolved_ips:
            addresses = route.resolved_ips
            if any(not is_public_address(item) for item in addresses):
                raise UpstreamConnectError("snapshot contains a non-public upstream address")
        else:
            try:
                resolved = await self.upstream_resolver.resolve(route.host, route.port)
            except DestinationDenied as exc:
                raise UpstreamConnectError("upstream proxy address is not public") from exc
            addresses = resolved.addresses
        error: Exception | None = None
        for address in addresses:
            kwargs: dict[str, object] = {}
            if route.protocol is ProxyProtocol.HTTPS:
                kwargs["ssl"] = self.ssl_context
                kwargs["server_hostname"] = route.tls_server_name or route.host
            try:
                return await self._open_connection(address, route.port, **kwargs)
            except (OSError, ssl.SSLError) as exc:
                error = exc
        raise UpstreamConnectError("could not connect to upstream proxy") from error

    @staticmethod
    def proxy_authorization(route: UpstreamRoute) -> bytes | None:
        if route.username is None:
            return None
        raw = f"{route.username}:{route.password or ''}".encode()
        return b"Basic " + base64.b64encode(raw)

    async def _open_http(
        self,
        route: UpstreamRoute,
        destination: PinnedDestination,
        *,
        tunnel: bool,
    ) -> ConnectedUpstream:
        reader, writer = await self._dial_upstream(route)
        if not tunnel:
            return ConnectedUpstream(reader, writer, RequestForm.ABSOLUTE, route)
        authority = _authority(destination.addresses[0], destination.port).encode("ascii")
        headers = [b"CONNECT " + authority + b" HTTP/1.1", b"Host: " + authority]
        authorization = self.proxy_authorization(route)
        if authorization:
            headers.append(b"Proxy-Authorization: " + authorization)
        writer.write(b"\r\n".join(headers) + b"\r\n\r\n")
        await writer.drain()
        try:
            response = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            writer.close()
            raise UpstreamConnectError("invalid upstream CONNECT response") from exc
        if len(response) > self.handshake_limit:
            writer.close()
            raise UpstreamConnectError("upstream CONNECT response is too large")
        first_line = response.split(b"\r\n", 1)[0].split(b" ", 2)
        if len(first_line) < 2 or not first_line[1].isdigit():
            writer.close()
            raise UpstreamConnectError("malformed upstream CONNECT response")
        status = int(first_line[1])
        if status == 407:
            writer.close()
            raise UpstreamAuthError("upstream proxy rejected credentials")
        if not 200 <= status < 300:
            writer.close()
            raise UpstreamConnectError(f"upstream CONNECT failed with status {status}")
        return ConnectedUpstream(reader, writer, RequestForm.ORIGIN, route)

    async def _open_socks4a(
        self,
        route: UpstreamRoute,
        destination: PinnedDestination,
    ) -> ConnectedUpstream:
        reader, writer = await self._dial_upstream(route)
        address = ipaddress.ip_address(destination.addresses[0])
        if address.version == 4:
            encoded_address = address.packed
            suffix = b""
        else:
            # SOCKS4 cannot carry IPv6; 4a asks the proxy to resolve a pinned textual IP.
            encoded_address = b"\x00\x00\x00\x01"
            suffix = str(address).encode("ascii") + b"\x00"
        user_id = (route.username or "").encode("utf-8")
        if b"\x00" in user_id:
            writer.close()
            raise UpstreamConnectError("invalid SOCKS4 user ID")
        request = (
            b"\x04\x01"
            + struct.pack("!H", destination.port)
            + encoded_address
            + user_id
            + b"\x00"
            + suffix
        )
        writer.write(request)
        await writer.drain()
        try:
            response = await reader.readexactly(8)
        except asyncio.IncompleteReadError as exc:
            writer.close()
            raise UpstreamConnectError("truncated SOCKS4 response") from exc
        if response[0] not in (0, 4) or response[1] != 0x5A:
            writer.close()
            raise UpstreamConnectError("SOCKS4 proxy rejected the connection")
        return ConnectedUpstream(reader, writer, RequestForm.ORIGIN, route)

    async def _open_socks5(
        self,
        route: UpstreamRoute,
        destination: PinnedDestination,
    ) -> ConnectedUpstream:
        reader, writer = await self._dial_upstream(route)
        methods = b"\x00\x02" if route.username is not None else b"\x00"
        writer.write(b"\x05" + bytes((len(methods),)) + methods)
        await writer.drain()
        try:
            choice = await reader.readexactly(2)
        except asyncio.IncompleteReadError as exc:
            writer.close()
            raise UpstreamConnectError("truncated SOCKS5 greeting") from exc
        if choice[0] != 5 or choice[1] == 0xFF:
            writer.close()
            raise UpstreamAuthError("SOCKS5 has no acceptable authentication method")
        if choice[1] == 2:
            username = (route.username or "").encode("utf-8")
            password = (route.password or "").encode("utf-8")
            if not username or len(username) > 255 or len(password) > 255:
                writer.close()
                raise UpstreamAuthError("invalid SOCKS5 credentials")
            writer.write(
                b"\x01" + bytes((len(username),)) + username + bytes((len(password),)) + password
            )
            await writer.drain()
            auth = await reader.readexactly(2)
            if auth != b"\x01\x00":
                writer.close()
                raise UpstreamAuthError("SOCKS5 proxy rejected credentials")
        elif choice[1] != 0:
            writer.close()
            raise UpstreamAuthError("unsupported SOCKS5 authentication method")

        address = ipaddress.ip_address(destination.addresses[0])
        atyp = b"\x01" if address.version == 4 else b"\x04"
        writer.write(b"\x05\x01\x00" + atyp + address.packed + struct.pack("!H", destination.port))
        await writer.drain()
        try:
            head = await reader.readexactly(4)
            if head[0] != 5 or head[1] != 0:
                raise UpstreamConnectError(f"SOCKS5 proxy rejected connection ({head[1]})")
            if head[3] == 1:
                await reader.readexactly(4)
            elif head[3] == 4:
                await reader.readexactly(16)
            elif head[3] == 3:
                length = (await reader.readexactly(1))[0]
                await reader.readexactly(length)
            else:
                raise UpstreamConnectError("invalid SOCKS5 address type")
            await reader.readexactly(2)
        except asyncio.IncompleteReadError as exc:
            writer.close()
            raise UpstreamConnectError("truncated SOCKS5 response") from exc
        except UpstreamConnectError:
            writer.close()
            raise
        return ConnectedUpstream(reader, writer, RequestForm.ORIGIN, route)


def _authority(host: str, port: int) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    formatted = f"[{host}]" if address is not None and address.version == 6 else host
    return f"{formatted}:{port}"


def pinned_absolute_target(original_target: bytes, destination: PinnedDestination) -> bytes:
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(original_target.decode("ascii"))
    authority = _authority(destination.addresses[0], destination.port)
    return urlunsplit(("http", authority, parsed.path or "/", parsed.query, "")).encode("ascii")
