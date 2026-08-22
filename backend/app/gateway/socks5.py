from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import struct
import time
from dataclasses import dataclass

from .auth import EndpointAuthenticator
from .errors import GatewayError, PoolUnavailable
from .models import EndpointSnapshot
from .server import GatewayServer, RequestStats
from .snapshots import SnapshotStore
from .telemetry import GatewayEvent

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Socks5Config:
    host: str = "0.0.0.0"
    port: int = 1080
    handshake_timeout: float = 10.0


class Socks5Server:
    """Authenticated SOCKS5 TCP CONNECT listener with server-side, pinned DNS."""

    def __init__(
        self,
        *,
        snapshots: SnapshotStore,
        authenticator: EndpointAuthenticator,
        gateway: GatewayServer,
        config: Socks5Config | None = None,
    ) -> None:
        self.snapshots = snapshots
        self.authenticator = authenticator
        self.gateway = gateway
        self.config = config or Socks5Config()
        self._server: asyncio.Server | None = None

    async def start(self) -> asyncio.Server:
        self._server = await asyncio.start_server(
            self.handle_client, self.config.host, self.config.port
        )
        return self._server

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        endpoint = None
        pool = None
        stats = RequestStats()
        outcome = "internal_error"
        try:
            endpoint, client_ip, host, port = await self._negotiate(reader, writer)
            if port not in endpoint.destination_ports:
                raise PoolUnavailable("destination port is not allowed")
            pool = self.snapshots.current().pools.get(endpoint.pool_id)
            if pool is None or not pool.routes:
                raise PoolUnavailable("endpoint pool has no active routes")
            if not await self.gateway.rate_limiter.allow(
                endpoint.workspace_id, endpoint.requests_per_minute
            ):
                raise PoolUnavailable("endpoint request rate exceeded")
            destination = await self.gateway.connector.resolve_destination(host, port)
            async with self.gateway.connection_limiter.acquire(client_ip, endpoint):
                connected = await self.gateway._connect_with_failover(
                    pool, destination, tunnel=True
                )
                stats.route_id = connected.route.id
                self.gateway.selector.quarantine.succeed(connected.route.id)
                writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                await writer.drain()
                await self.gateway._relay_tunnel(reader, writer, connected, stats)
            outcome = "ok"
        except (GatewayError, ValueError, UnicodeError, asyncio.IncompleteReadError) as exc:
            outcome = getattr(exc, "code", "protocol_error")
            with contextlib.suppress(OSError):
                writer.write(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
                await writer.drain()
        except Exception:
            LOGGER.exception("unhandled SOCKS5 connection error")
        finally:
            if endpoint is not None and pool is not None:
                self.gateway.telemetry.emit(
                    GatewayEvent(
                        endpoint_id=endpoint.id,
                        workspace_id=endpoint.workspace_id,
                        pool_id=pool.id,
                        route_id=stats.route_id,
                        outcome=outcome,
                        latency_ms=(time.monotonic() - stats.started) * 1000,
                        bytes_up=stats.bytes_up,
                        bytes_down=stats.bytes_down,
                    )
                )
            writer.close()
            with contextlib.suppress(OSError, RuntimeError):
                await writer.wait_closed()

    async def _negotiate(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> tuple[EndpointSnapshot, str, str, int]:
        async with asyncio.timeout(self.config.handshake_timeout):
            version, methods = await self._greeting(reader)
            if version != 5 or 2 not in methods:
                writer.write(b"\x05\xff")
                await writer.drain()
                raise ValueError("username/password authentication is required")
            writer.write(b"\x05\x02")
            await writer.drain()
            username, password = await self._credentials(reader)
            peer = writer.get_extra_info("peername")
            client_ip = str(peer[0]) if peer else ""
            endpoint = self.authenticator.authenticate_credentials(
                self.snapshots.current(), username, password, client_ip
            ).endpoint
            writer.write(b"\x01\x00")
            await writer.drain()
            host, port = await self._request(reader)
            return endpoint, client_ip, host, port

    @staticmethod
    async def _greeting(reader: asyncio.StreamReader) -> tuple[int, bytes]:
        version, count = await reader.readexactly(2)
        return version, await reader.readexactly(count)

    @staticmethod
    async def _credentials(reader: asyncio.StreamReader) -> tuple[str, str]:
        if (await reader.readexactly(1))[0] != 1:
            raise ValueError("invalid username/password negotiation")
        username = (await reader.readexactly((await reader.readexactly(1))[0])).decode("utf-8")
        password = (await reader.readexactly((await reader.readexactly(1))[0])).decode("utf-8")
        if not username:
            raise ValueError("empty SOCKS5 username")
        return username, password

    @staticmethod
    async def _request(reader: asyncio.StreamReader) -> tuple[str, int]:
        version, command, reserved, atyp = await reader.readexactly(4)
        if version != 5 or command != 1 or reserved != 0:
            raise ValueError("only SOCKS5 TCP CONNECT is supported")
        if atyp == 1:
            host = str(ipaddress.ip_address(await reader.readexactly(4)))
        elif atyp == 4:
            host = str(ipaddress.ip_address(await reader.readexactly(16)))
        elif atyp == 3:
            length = (await reader.readexactly(1))[0]
            if not length:
                raise ValueError("empty SOCKS5 domain")
            host = (await reader.readexactly(length)).decode("idna")
        else:
            raise ValueError("unsupported SOCKS5 address type")
        port = struct.unpack("!H", await reader.readexactly(2))[0]
        return host, port
