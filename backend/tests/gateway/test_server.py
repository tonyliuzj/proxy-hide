from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime

import pytest

from app.config import Settings
from app.gateway.auth import EndpointAuthenticator
from app.gateway.connectors import ConnectedUpstream, RequestForm
from app.gateway.errors import DestinationDenied, UpstreamConnectError
from app.gateway.models import GatewaySnapshot
from app.gateway.security import PinnedDestination
from app.gateway.server import GatewayConfig, GatewayServer
from app.gateway.snapshots import SnapshotStore
from app.security import digest_endpoint_secret, endpoint_hmac_key_bytes

HMAC_KEY = b"gateway-test-hmac-key-that-is-long"
SECRET = "endpoint-secret"
TEST_SETTINGS = Settings(
    environment="test",
    endpoint_hmac_key=base64.b64encode(HMAC_KEY).decode(),
    database_url="sqlite+aiosqlite://",
)


def basic_auth(username: str = "edge", password: str = SECRET) -> bytes:
    return b"Basic " + base64.b64encode(f"{username}:{password}".encode())


def snapshot(*, route_count: int = 1) -> GatewaySnapshot:
    routes = [
        {
            "id": f"route-{index}",
            "protocol": "http",
            "host": f"proxy-{index}.example",
            "port": 8080,
            "score": 100 - index,
            "latency_ms": index,
        }
        for index in range(route_count)
    ]
    return GatewaySnapshot.from_dict(
        {
            "version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "endpoints": {
                "edge": {
                    "id": "endpoint",
                    "workspace_id": "workspace",
                    "pool_id": "pool",
                    "secret_digest": digest_endpoint_secret(SECRET, TEST_SETTINGS),
                    "destination_ports": [80, 443],
                }
            },
            "pools": {
                "pool": {
                    "revision": 1,
                    "strategy": "lowest_latency",
                    "routes": routes,
                }
            },
        }
    )


class FakeConnector:
    def __init__(self, upstream_port: int, *, failures: int = 0, denied: bool = False) -> None:
        self.upstream_port = upstream_port
        self.failures = failures
        self.denied = denied
        self.opened: list[str] = []

    async def resolve_destination(self, hostname: str, port: int) -> PinnedDestination:
        if self.denied:
            raise DestinationDenied("blocked by test policy")
        return PinnedDestination(hostname, port, ("93.184.216.34",))

    async def open(self, route: object, destination: object, *, tunnel: bool) -> ConnectedUpstream:
        route_id = str(route.id)
        self.opened.append(route_id)
        if len(self.opened) <= self.failures:
            raise UpstreamConnectError("fixture failure")
        reader, writer = await asyncio.open_connection("127.0.0.1", self.upstream_port)
        form = RequestForm.ORIGIN if tunnel else RequestForm.ABSOLUTE
        return ConnectedUpstream(reader, writer, form, route)  # type: ignore[arg-type]

    @staticmethod
    def proxy_authorization(route: object) -> None:
        return None


async def start_gateway(
    connector: FakeConnector, current: GatewaySnapshot
) -> tuple[GatewayServer, int]:
    store = SnapshotStore()
    await store.install(current)
    gateway = GatewayServer(
        snapshots=store,
        authenticator=EndpointAuthenticator(endpoint_hmac_key_bytes(TEST_SETTINGS)),
        connector=connector,  # type: ignore[arg-type]
        config=GatewayConfig(host="127.0.0.1", port=0, attempt_timeout=0.5, setup_timeout=2),
    )
    server = await gateway.start()
    port = int(server.sockets[0].getsockname()[1])
    return gateway, port


async def start_gateway_without_snapshot(connector: FakeConnector) -> tuple[GatewayServer, int]:
    gateway = GatewayServer(
        snapshots=SnapshotStore(),
        authenticator=EndpointAuthenticator(endpoint_hmac_key_bytes(TEST_SETTINGS)),
        connector=connector,  # type: ignore[arg-type]
        config=GatewayConfig(host="127.0.0.1", port=0),
    )
    server = await gateway.start()
    port = int(server.sockets[0].getsockname()[1])
    return gateway, port


async def request(port: int, payload: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(payload)
    await writer.drain()
    response = await asyncio.wait_for(reader.read(), timeout=2)
    writer.close()
    await writer.wait_closed()
    return response


@pytest.mark.asyncio
async def test_absolute_form_proxying_pins_ip_and_strips_client_proxy_auth() -> None:
    seen = b""

    async def upstream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal seen
        seen = await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: x-hop\r\n"
            b"X-Hop: hidden\r\nX-Upstream: shown\r\n\r\nok"
        )
        await writer.drain()
        writer.close()

    upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    connector = FakeConnector(int(upstream_server.sockets[0].getsockname()[1]))
    gateway, port = await start_gateway(connector, snapshot())
    try:
        response = await request(
            port,
            b"GET http://example.test/path?q=1 HTTP/1.1\r\nHost: example.test\r\n"
            b"Proxy-Authorization: "
            + basic_auth()
            + b"\r\nAuthorization: Bearer origin\r\nConnection: x-remove\r\n"
            b"X-Remove: hidden\r\n\r\n",
        )
    finally:
        await gateway.close()
        upstream_server.close()
        await upstream_server.wait_closed()

    assert response.startswith(b"HTTP/1.1 200")
    assert response.endswith(b"ok")
    assert b"x-upstream: shown" in response.lower()
    assert b"x-hop" not in response.lower()
    assert seen.startswith(b"GET http://93.184.216.34:80/path?q=1 HTTP/1.1")
    assert b"host: example.test" in seen.lower()
    assert b"authorization: bearer origin" in seen.lower()
    assert b"proxy-authorization" not in seen.lower()
    assert b"x-remove" not in seen.lower()


@pytest.mark.asyncio
async def test_auth_empty_pool_and_destination_policy_statuses() -> None:
    async def unused(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()

    fixture = await asyncio.start_server(unused, "127.0.0.1", 0)
    connector = FakeConnector(int(fixture.sockets[0].getsockname()[1]))
    gateway, port = await start_gateway(connector, snapshot(route_count=0))
    try:
        unauthenticated = await request(
            port, b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n\r\n"
        )
        unavailable = await request(
            port,
            b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\nProxy-Authorization: "
            + basic_auth()
            + b"\r\n\r\n",
        )
    finally:
        await gateway.close()
        fixture.close()
        await fixture.wait_closed()
    assert unauthenticated.startswith(b"HTTP/1.1 407")
    assert b"proxy-authenticate" in unauthenticated.lower()
    assert unavailable.startswith(b"HTTP/1.1 503")
    assert connector.opened == []


@pytest.mark.asyncio
async def test_missing_authentication_precedes_snapshot_availability() -> None:
    async def unused(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()

    fixture = await asyncio.start_server(unused, "127.0.0.1", 0)
    connector = FakeConnector(int(fixture.sockets[0].getsockname()[1]))
    gateway, port = await start_gateway_without_snapshot(connector)
    try:
        unauthenticated = await request(
            port, b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n\r\n"
        )
        unavailable = await request(
            port,
            b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n"
            b"Proxy-Authorization: " + basic_auth() + b"\r\n\r\n",
        )
    finally:
        await gateway.close()
        fixture.close()
        await fixture.wait_closed()

    assert unauthenticated.startswith(b"HTTP/1.1 407")
    assert unavailable.startswith(b"HTTP/1.1 503")
    assert connector.opened == []


@pytest.mark.asyncio
async def test_failover_uses_at_most_three_distinct_routes() -> None:
    async def upstream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()

    fixture = await asyncio.start_server(upstream, "127.0.0.1", 0)
    connector = FakeConnector(int(fixture.sockets[0].getsockname()[1]), failures=2)
    gateway, port = await start_gateway(connector, snapshot(route_count=5))
    try:
        response = await request(
            port,
            b"HEAD http://example.test/ HTTP/1.1\r\nHost: example.test\r\nProxy-Authorization: "
            + basic_auth()
            + b"\r\n\r\n",
        )
    finally:
        await gateway.close()
        fixture.close()
        await fixture.wait_closed()
    assert response.startswith(b"HTTP/1.1 204")
    assert connector.opened == ["route-0", "route-1", "route-2"]
    assert len(set(connector.opened)) == 3


@pytest.mark.asyncio
async def test_connect_forwards_optimistic_bytes_after_200() -> None:
    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while data := await reader.read(1024):
            writer.write(data)
            await writer.drain()
        writer.close()

    fixture = await asyncio.start_server(echo, "127.0.0.1", 0)
    connector = FakeConnector(int(fixture.sockets[0].getsockname()[1]))
    gateway, port = await start_gateway(connector, snapshot())
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(
            b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n"
            b"Proxy-Authorization: " + basic_auth() + b"\r\n\r\noptimistic"
        )
        await writer.drain()
        headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2)
        echoed = await asyncio.wait_for(reader.readexactly(len(b"optimistic")), timeout=2)
    finally:
        writer.close()
        await writer.wait_closed()
        await gateway.close()
        fixture.close()
        await fixture.wait_closed()
    assert headers.startswith(b"HTTP/1.1 200")
    assert echoed == b"optimistic"
