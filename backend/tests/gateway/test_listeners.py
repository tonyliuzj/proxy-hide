from __future__ import annotations

import asyncio
import base64
import socket
from datetime import UTC, datetime
from typing import Any

import pytest

from app.config import Settings
from app.gateway.auth import EndpointAuthenticator
from app.gateway.connectors import ConnectedUpstream, RequestForm
from app.gateway.listeners import ListenerManager
from app.gateway.models import GatewaySnapshot
from app.gateway.security import PinnedDestination
from app.gateway.server import GatewayConfig, GatewayServer
from app.gateway.snapshots import SnapshotStore
from app.gateway.socks5 import Socks5Config, Socks5Server
from app.security import digest_endpoint_secret, endpoint_hmac_key_bytes

HMAC_KEY = b"gateway-test-hmac-key-that-is-long"
SECRET = "endpoint-secret"
TEST_SETTINGS = Settings(
    environment="test",
    endpoint_hmac_key=base64.b64encode(HMAC_KEY).decode(),
    database_url="sqlite+aiosqlite://",
)
OK_RESPONSE = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def snapshot(port: int, **overrides: Any) -> GatewaySnapshot:
    endpoint: dict[str, Any] = {
        "id": "endpoint",
        "workspace_id": "workspace",
        "pool_id": "pool",
        "secret_digest": digest_endpoint_secret(SECRET, TEST_SETTINGS),
        "destination_ports": [80, 443],
        "listen_port": port,
        "require_auth": False,
        "ip_allowlist": ["127.0.0.0/8"],
    }
    endpoint.update(overrides)
    routes = [
        {"id": f"route-{i}", "protocol": "http", "host": f"p{i}.example", "port": 8080, "score": 90}
        for i in range(2)
    ]
    return GatewaySnapshot.from_dict(
        {
            "version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "endpoints": {"open-endpoint": endpoint},
            "pools": {"pool": {"revision": 1, "strategy": "round_robin", "routes": routes}},
        }
    )


class FakeConnector:
    def __init__(self, upstream_port: int) -> None:
        self.upstream_port = upstream_port
        self.opened: list[str] = []

    async def resolve_destination(self, hostname: str, port: int) -> PinnedDestination:
        return PinnedDestination(hostname, port, ("93.184.216.34",))

    async def open(self, route: object, destination: object, *, tunnel: bool) -> ConnectedUpstream:
        self.opened.append(str(route.id))  # type: ignore[attr-defined]
        reader, writer = await asyncio.open_connection("127.0.0.1", self.upstream_port)
        form = RequestForm.ORIGIN if tunnel else RequestForm.ABSOLUTE
        return ConnectedUpstream(reader, writer, form, route)  # type: ignore[arg-type]

    @staticmethod
    def proxy_authorization(route: object) -> None:
        return None


class Harness:
    def __init__(self) -> None:
        self.upstream_seen = b""
        self.connector: FakeConnector
        self.store = SnapshotStore()
        self.manager: ListenerManager
        self._upstream: asyncio.Server

    async def start(self, current: GatewaySnapshot, port: int) -> None:
        async def upstream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            self.upstream_seen = await reader.readuntil(b"\r\n\r\n")
            writer.write(OK_RESPONSE)
            await writer.drain()
            writer.close()

        self._upstream = await asyncio.start_server(upstream, "127.0.0.1", 0)
        self.connector = FakeConnector(int(self._upstream.sockets[0].getsockname()[1]))
        await self.store.install(current)
        authenticator = EndpointAuthenticator(endpoint_hmac_key_bytes(TEST_SETTINGS))
        gateway = GatewayServer(
            snapshots=self.store,
            authenticator=authenticator,
            connector=self.connector,  # type: ignore[arg-type]
            config=GatewayConfig(host="127.0.0.1", port=0, attempt_timeout=0.5, setup_timeout=2),
        )
        socks = Socks5Server(
            snapshots=self.store,
            authenticator=authenticator,
            gateway=gateway,
            config=Socks5Config(host="127.0.0.1", port=0),
        )
        self.manager = ListenerManager(
            snapshots=self.store,
            gateway=gateway,
            socks=socks,
            host="127.0.0.1",
            port_range=(port, port),
        )
        await self.manager.reconcile()

    async def stop(self) -> None:
        await self.manager.close()
        self._upstream.close()
        await self._upstream.wait_closed()


async def http_get(port: int, extra_headers: bytes = b"") -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n" + extra_headers + b"\r\n"
    )
    await writer.drain()
    response = await asyncio.wait_for(reader.read(), timeout=3)
    writer.close()
    return response


@pytest.mark.asyncio
async def test_open_port_serves_allowlisted_clients_without_credentials() -> None:
    port = free_port()
    harness = Harness()
    await harness.start(snapshot(port), port)
    try:
        response = await http_get(port)
    finally:
        await harness.stop()
    assert response.startswith(b"HTTP/1.1 200")
    assert response.endswith(b"ok")
    assert harness.connector.opened == ["route-0"]


@pytest.mark.asyncio
async def test_open_port_rejects_clients_outside_the_allowlist() -> None:
    port = free_port()
    harness = Harness()
    await harness.start(snapshot(port, ip_allowlist=["10.0.0.0/8"]), port)
    try:
        response = await http_get(port)
    finally:
        await harness.stop()
    assert response.startswith(b"HTTP/1.1 403")
    assert harness.connector.opened == []


@pytest.mark.asyncio
async def test_open_port_with_empty_allowlist_fails_closed() -> None:
    port = free_port()
    harness = Harness()
    await harness.start(snapshot(port, ip_allowlist=[]), port)
    try:
        response = await http_get(port)
    finally:
        await harness.stop()
    assert response.startswith(b"HTTP/1.1 403")
    assert harness.connector.opened == []


@pytest.mark.asyncio
async def test_open_port_honours_the_disabled_flag() -> None:
    port = free_port()
    harness = Harness()
    await harness.start(snapshot(port, enabled=False), port)
    try:
        response = await http_get(port)
    finally:
        await harness.stop()
    assert response.startswith(b"HTTP/1.1 503")


@pytest.mark.asyncio
async def test_credentialed_port_requires_its_own_secret() -> None:
    port = free_port()
    harness = Harness()
    await harness.start(snapshot(port, require_auth=True, username="open-endpoint"), port)
    token = base64.b64encode(f"open-endpoint:{SECRET}".encode())
    try:
        missing = await http_get(port)
        valid = await http_get(port, b"Proxy-Authorization: Basic " + token + b"\r\n")
    finally:
        await harness.stop()
    assert missing.startswith(b"HTTP/1.1 407")
    assert valid.startswith(b"HTTP/1.1 200")


@pytest.mark.asyncio
async def test_socks5_shares_the_open_port() -> None:
    port = free_port()
    harness = Harness()
    await harness.start(snapshot(port), port)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"\x05\x01\x00")  # offer "no authentication"
        await writer.drain()
        assert await asyncio.wait_for(reader.readexactly(2), 2) == b"\x05\x00"
        host = b"example.test"
        writer.write(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + (80).to_bytes(2, "big"))
        await writer.drain()
        reply = await asyncio.wait_for(reader.readexactly(10), 2)
        assert reply[:2] == b"\x05\x00"
        writer.write(b"GET / HTTP/1.1\r\nHost: example.test\r\n\r\n")
        await writer.drain()
        tunnelled = await asyncio.wait_for(reader.read(), timeout=3)
        writer.close()
    finally:
        await harness.stop()
    assert tunnelled.endswith(b"ok")
    assert harness.connector.opened == ["route-0"]


@pytest.mark.asyncio
async def test_socks5_open_port_rejects_clients_outside_the_allowlist() -> None:
    port = free_port()
    harness = Harness()
    await harness.start(snapshot(port, ip_allowlist=["10.0.0.0/8"]), port)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        reply = await asyncio.wait_for(reader.read(), timeout=2)
        writer.close()
    finally:
        await harness.stop()
    assert reply[:2] != b"\x05\x00"
    assert harness.connector.opened == []


@pytest.mark.asyncio
async def test_ports_follow_the_snapshot_and_respect_the_configured_range() -> None:
    port = free_port()
    harness = Harness()
    await harness.start(snapshot(port), port)
    try:
        assert harness.manager.ports == {port}

        await harness.store.install(
            GatewaySnapshot.from_dict(
                {
                    "version": 2,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "endpoints": {},
                    "pools": {},
                }
            )
        )
        await harness.manager.reconcile()
        assert harness.manager.ports == frozenset()
        with pytest.raises(OSError):
            await asyncio.open_connection("127.0.0.1", port)

        outside = free_port()
        await harness.store.install(
            GatewaySnapshot.from_dict(
                {
                    "version": 3,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "endpoints": {
                        "x": {
                            "id": "e",
                            "workspace_id": "w",
                            "pool_id": "p",
                            "secret_digest": "0" * 64,
                            "listen_port": outside,
                            "require_auth": False,
                            "ip_allowlist": ["127.0.0.0/8"],
                        }
                    },
                    "pools": {},
                }
            )
        )
        await harness.manager.reconcile()
        assert outside != port and harness.manager.ports == frozenset()
    finally:
        await harness.stop()
