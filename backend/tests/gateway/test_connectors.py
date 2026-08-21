from __future__ import annotations

import asyncio
import ipaddress
import struct

import pytest

from app.gateway.connectors import RequestForm, UpstreamConnector
from app.gateway.errors import UpstreamAuthError
from app.gateway.models import ProxyProtocol, UpstreamRoute
from app.gateway.security import PinnedDestination


class LocalResolver:
    def __init__(self, address: str = "127.0.0.1") -> None:
        self.address = address

    async def resolve(self, hostname: str, port: int) -> PinnedDestination:
        return PinnedDestination(hostname, port, (self.address,))


@pytest.mark.asyncio
async def test_authenticated_socks5_connects_to_pinned_ip() -> None:
    destination_seen: tuple[str, int] | None = None

    async def socks(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal destination_seen
        assert await reader.readexactly(4) == b"\x05\x02\x00\x02"
        writer.write(b"\x05\x02")
        await writer.drain()
        version, username_length = await reader.readexactly(2)
        username = await reader.readexactly(username_length)
        password_length = (await reader.readexactly(1))[0]
        password = await reader.readexactly(password_length)
        assert (version, username, password) == (1, b"user", b"pass")
        writer.write(b"\x01\x00")
        await writer.drain()
        head = await reader.readexactly(4)
        assert head == b"\x05\x01\x00\x01"
        address = str(ipaddress.ip_address(await reader.readexactly(4)))
        port = struct.unpack("!H", await reader.readexactly(2))[0]
        destination_seen = (address, port)
        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()
        await reader.read()
        writer.close()

    fixture = await asyncio.start_server(socks, "127.0.0.1", 0)
    port = int(fixture.sockets[0].getsockname()[1])
    connector = UpstreamConnector(upstream_resolver=LocalResolver())
    route = UpstreamRoute("route", ProxyProtocol.SOCKS5, "proxy.test", port, "user", "pass")
    try:
        connected = await connector.open(
            route, PinnedDestination("target.test", 443, ("8.8.8.8",)), tunnel=True
        )
        assert connected.request_form is RequestForm.ORIGIN
        await connected.close()
    finally:
        fixture.close()
        await fixture.wait_closed()
    assert destination_seen == ("8.8.8.8", 443)


@pytest.mark.asyncio
async def test_http_upstream_407_is_never_client_auth_error() -> None:
    async def proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()

    fixture = await asyncio.start_server(proxy, "127.0.0.1", 0)
    port = int(fixture.sockets[0].getsockname()[1])
    connector = UpstreamConnector(upstream_resolver=LocalResolver())
    route = UpstreamRoute("route", ProxyProtocol.HTTP, "proxy.test", port, "user", "bad")
    try:
        with pytest.raises(UpstreamAuthError):
            await connector.open(
                route, PinnedDestination("target.test", 443, ("8.8.8.8",)), tunnel=True
            )
    finally:
        fixture.close()
        await fixture.wait_closed()
