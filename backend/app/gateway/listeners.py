from __future__ import annotations

import asyncio
import contextlib
import functools
import logging

from .errors import GatewayError, PoolUnavailable
from .server import GatewayServer
from .snapshots import SnapshotStore
from .socks5 import Socks5Server

LOGGER = logging.getLogger(__name__)

SOCKS5_VERSION_BYTE = b"\x05"


class ListenerManager:
    """Keeps one listening socket per dedicated endpoint port.

    Each port accepts HTTP/CONNECT and SOCKS5 on the same ``ip:port``; the first
    byte decides which. Sockets follow the gateway snapshot, so publishing or
    deleting an endpoint opens or closes its port without a restart.
    """

    def __init__(
        self,
        *,
        snapshots: SnapshotStore,
        gateway: GatewayServer,
        socks: Socks5Server,
        host: str,
        port_range: tuple[int, int] | None,
        reconcile_interval: float = 2.0,
    ) -> None:
        self.snapshots = snapshots
        self.gateway = gateway
        self.socks = socks
        self.host = host
        self.port_range = port_range
        self.reconcile_interval = reconcile_interval
        self._servers: dict[int, asyncio.Server] = {}
        self._stopped = asyncio.Event()

    @property
    def ports(self) -> frozenset[int]:
        return frozenset(self._servers)

    async def run(self) -> None:
        while not self._stopped.is_set():
            await self.reconcile()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopped.wait(), timeout=self.reconcile_interval)

    async def reconcile(self) -> None:
        if self.port_range is None:
            return
        try:
            snapshot = self.snapshots.current()
        except PoolUnavailable:
            # Keep serving what is already bound; handlers fail closed while stale.
            return
        low, high = self.port_range
        wanted = {port for port in snapshot.listeners if low <= port <= high}
        for port in set(self._servers) - wanted:
            # Do not await wait_closed(): it blocks on connections that are still open.
            self._servers.pop(port).close()
        for port in sorted(wanted - set(self._servers)):
            try:
                self._servers[port] = await asyncio.start_server(
                    functools.partial(self._serve, port),
                    self.host,
                    port,
                    limit=self.gateway.config.max_header_bytes + 8192,
                )
            except OSError:
                LOGGER.exception("could not bind dedicated listener port %s", port)

    async def _serve(
        self, port: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            async with asyncio.timeout(self.gateway.config.header_timeout):
                client_ip = await self.gateway._client_ip(reader, writer)
                first = await reader.readexactly(1)
        except (GatewayError, ValueError, OSError, TimeoutError, asyncio.IncompleteReadError):
            writer.close()
            with contextlib.suppress(OSError, RuntimeError):
                await writer.wait_closed()
            return
        handler = self.socks if first == SOCKS5_VERSION_BYTE else self.gateway
        await handler.handle_client(
            reader, writer, listener_port=port, client_ip=client_ip, prefix=first
        )

    def stop(self) -> None:
        self._stopped.set()

    async def close(self) -> None:
        self.stop()
        for server in self._servers.values():
            server.close()
        self._servers.clear()
