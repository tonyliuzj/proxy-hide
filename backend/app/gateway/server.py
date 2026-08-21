from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import time
from dataclasses import dataclass, field
from typing import cast

import h11

from .auth import EndpointAuthenticator
from .connectors import ConnectedUpstream, RequestForm, UpstreamConnector, pinned_absolute_target
from .errors import (
    BadRequest,
    DestinationDenied,
    GatewayError,
    GatewayTimeout,
    PoolUnavailable,
    ProtocolError,
    ProxyAuthenticationRequired,
    UpstreamConnectError,
    UpstreamFailure,
)
from .headers import first_header, sanitized_request_headers, sanitized_response_headers
from .limits import ConnectionLimiter, SlidingWindowRateLimiter
from .models import EndpointSnapshot, PoolSnapshot, ProxyProtocol, decode_basic_credentials
from .proxy_protocol import peer_is_trusted, read_proxy_v2
from .security import PinnedDestination, parse_absolute_http_target, parse_connect_authority
from .selection import CandidateSelector
from .snapshots import SnapshotStore
from .telemetry import GatewayEvent, TelemetryBuffer

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    host: str = "0.0.0.0"
    port: int = 9000
    max_header_bytes: int = 32 * 1024
    max_header_count: int = 100
    max_request_body_bytes: int = 16 * 1024 * 1024
    header_timeout: float = 10.0
    body_timeout: float = 30.0
    attempt_timeout: float = 4.0
    setup_timeout: float = 12.0
    max_attempts: int = 3
    tunnel_idle_timeout: float = 5 * 60.0
    tunnel_lifetime: float = 60 * 60.0
    proxy_protocol_from_trusted: bool = False
    trusted_proxy_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = field(
        default_factory=tuple
    )


@dataclass(slots=True)
class RequestStats:
    started: float = field(default_factory=time.monotonic)
    route_id: str | None = None
    bytes_up: int = 0
    bytes_down: int = 0
    client_response_started: bool = False


class GatewayServer:
    def __init__(
        self,
        *,
        snapshots: SnapshotStore,
        authenticator: EndpointAuthenticator,
        connector: UpstreamConnector | None = None,
        selector: CandidateSelector | None = None,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        connection_limiter: ConnectionLimiter | None = None,
        telemetry: TelemetryBuffer | None = None,
        config: GatewayConfig | None = None,
    ) -> None:
        self.snapshots = snapshots
        self.authenticator = authenticator
        self.connector = connector or UpstreamConnector()
        self.selector = selector or CandidateSelector()
        self.rate_limiter = rate_limiter or SlidingWindowRateLimiter()
        self.connection_limiter = connection_limiter or ConnectionLimiter()
        self.telemetry = telemetry or TelemetryBuffer()
        self.config = config or GatewayConfig()
        self._server: asyncio.Server | None = None

    async def start(self) -> asyncio.Server:
        self._server = await asyncio.start_server(
            self.handle_client,
            self.config.host,
            self.config.port,
            limit=self.config.max_header_bytes + 8192,
        )
        return self._server

    async def serve_forever(self) -> None:
        server = await self.start()
        async with server:
            await server.serve_forever()

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        connection = h11.Connection(
            h11.SERVER, max_incomplete_event_size=self.config.max_header_bytes
        )
        endpoint: EndpointSnapshot | None = None
        pool: PoolSnapshot | None = None
        stats = RequestStats()
        outcome = "internal_error"
        try:
            client_ip = await self._client_ip(reader, writer)
            request = await self._read_request(connection, reader)
            authorization = first_header(request.headers, b"proxy-authorization")
            if decode_basic_credentials(authorization) is None:
                raise ProxyAuthenticationRequired("missing or invalid Proxy-Authorization")
            snapshot = self.snapshots.current()
            authenticated = self.authenticator.authenticate(snapshot, authorization, client_ip)
            endpoint = authenticated.endpoint
            pool = snapshot.pools.get(endpoint.pool_id)
            if pool is None or not pool.routes:
                raise PoolUnavailable("endpoint pool has no active routes")
            if not await self.rate_limiter.allow(
                endpoint.workspace_id, endpoint.requests_per_minute
            ):
                raise PoolUnavailable("endpoint request rate exceeded")
            async with self.connection_limiter.acquire(client_ip, endpoint):
                await self._dispatch(connection, request, reader, writer, endpoint, pool, stats)
            outcome = "ok"
        except GatewayError as exc:
            outcome = exc.code
            if not stats.client_response_started:
                await self._send_error(connection, writer, exc)
        except (h11.RemoteProtocolError, h11.LocalProtocolError, UnicodeError, ValueError) as exc:
            outcome = "protocol_error"
            if not stats.client_response_started:
                await self._send_error(connection, writer, ProtocolError(str(exc)))
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            outcome = "client_disconnect"
        except Exception:
            LOGGER.exception("unhandled gateway connection error")
            if not stats.client_response_started:
                await self._send_error(
                    connection, writer, UpstreamFailure("unexpected gateway error")
                )
        finally:
            if endpoint is not None and pool is not None:
                self.telemetry.emit(
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

    async def _client_ip(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> str:
        peer = writer.get_extra_info("peername")
        if not peer:
            raise ProtocolError("client peer address is unavailable")
        peer_ip = str(peer[0])
        if not self.config.proxy_protocol_from_trusted:
            return peer_ip
        if peer_is_trusted(peer_ip, self.config.trusted_proxy_networks):
            forwarded = await read_proxy_v2(reader, read_timeout=self.config.header_timeout)
            return forwarded.source_ip
        return peer_ip

    async def _read_request(
        self,
        connection: h11.Connection,
        reader: asyncio.StreamReader,
    ) -> h11.Request:
        deadline = asyncio.get_running_loop().time() + self.config.header_timeout
        while True:
            event = connection.next_event()
            if isinstance(event, h11.Request):
                if len(event.headers) > self.config.max_header_count:
                    raise BadRequest("too many request headers")
                if event.http_version != b"1.1":
                    raise BadRequest("only HTTP/1.1 is supported")
                if first_header(event.headers, b"upgrade") is not None:
                    raise BadRequest("HTTP Upgrade is not supported")
                return event
            if event is h11.PAUSED:
                raise BadRequest("HTTP pipelining is not supported")
            if event is not h11.NEED_DATA:
                raise BadRequest("request did not begin with headers")
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise BadRequest("request header timeout")
            chunk = await asyncio.wait_for(reader.read(8192), timeout=remaining)
            if not chunk:
                raise asyncio.IncompleteReadError(b"", 1)
            connection.receive_data(chunk)

    async def _dispatch(
        self,
        client_h11: h11.Connection,
        request: h11.Request,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        endpoint: EndpointSnapshot,
        pool: PoolSnapshot,
        stats: RequestStats,
    ) -> None:
        method = request.method.upper()
        if method == b"CONNECT":
            if (
                first_header(request.headers, b"content-length") is not None
                or first_header(request.headers, b"transfer-encoding") is not None
            ):
                raise BadRequest("CONNECT request bodies are not supported")
            host, port = parse_connect_authority(request.target)
            if port not in endpoint.destination_ports:
                raise DestinationDenied("destination port is not allowed")
            destination = await self.connector.resolve_destination(host, port)
            connected = await self._connect_with_failover(pool, destination, tunnel=True)
            stats.route_id = connected.route.id
            self.selector.quarantine.succeed(connected.route.id)
            await self._send_h11(
                client_h11,
                client_writer,
                h11.Response(status_code=200, reason=b"Connection Established", headers=[]),
            )
            stats.client_response_started = True
            buffered, _ = client_h11.trailing_data
            if buffered:
                connected.writer.write(buffered)
                await connected.writer.drain()
                stats.bytes_up += len(buffered)
            await self._relay_tunnel(client_reader, client_writer, connected, stats)
            return

        _parsed, host, port = parse_absolute_http_target(request.target)
        if port not in endpoint.destination_ports:
            raise DestinationDenied("destination port is not allowed")
        expected_authority = host if port == 80 else f"{host}:{port}"
        supplied_host = first_header(request.headers, b"host")
        if (
            supplied_host is not None
            and supplied_host.decode("ascii").lower() != expected_authority.lower()
        ):
            raise BadRequest("Host header does not match request target")
        destination = await self.connector.resolve_destination(host, port)
        connected = await self._connect_with_failover(pool, destination, tunnel=False)
        stats.route_id = connected.route.id
        self.selector.quarantine.succeed(connected.route.id)
        try:
            await self._forward_http(
                client_h11,
                request,
                client_reader,
                client_writer,
                connected,
                destination,
                expected_authority,
                stats,
            )
        finally:
            await connected.close()

    async def _connect_with_failover(
        self,
        pool: PoolSnapshot,
        destination: PinnedDestination,
        *,
        tunnel: bool,
    ) -> ConnectedUpstream:
        candidates = await self.selector.select(pool, limit=self.config.max_attempts)
        if not candidates:
            raise PoolUnavailable("all pool routes are temporarily unavailable")
        last_error: BaseException | None = None

        async def attempts() -> ConnectedUpstream:
            nonlocal last_error
            for route in candidates:
                try:
                    async with asyncio.timeout(self.config.attempt_timeout):
                        return await self.connector.open(route, destination, tunnel=tunnel)
                except (UpstreamConnectError, OSError, TimeoutError) as exc:
                    last_error = exc
                    self.selector.quarantine.fail(route.id)
                    self.telemetry.emit(
                        GatewayEvent(
                            endpoint_id="",
                            workspace_id="",
                            pool_id=pool.id,
                            route_id=route.id,
                            outcome="upstream_connect_failed",
                            latency_ms=0,
                        )
                    )
            raise UpstreamFailure("all upstream proxy attempts failed") from last_error

        try:
            async with asyncio.timeout(self.config.setup_timeout):
                return await attempts()
        except TimeoutError as exc:
            raise GatewayTimeout("upstream setup budget exceeded") from exc

    async def _forward_http(
        self,
        client_h11: h11.Connection,
        request: h11.Request,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        upstream: ConnectedUpstream,
        destination: PinnedDestination,
        authority: str,
        stats: RequestStats,
    ) -> None:
        upstream_h11 = h11.Connection(h11.CLIENT)
        headers = sanitized_request_headers(request.headers, authority=authority)
        if upstream.route.protocol in (ProxyProtocol.HTTP, ProxyProtocol.HTTPS):
            authorization = self.connector.proxy_authorization(upstream.route)
            if authorization:
                headers.append((b"proxy-authorization", authorization))
        target = (
            pinned_absolute_target(request.target, destination)
            if upstream.request_form is RequestForm.ABSOLUTE
            else _origin_target(request.target)
        )
        outgoing = h11.Request(method=request.method, target=target, headers=headers)
        payload = upstream_h11.send(outgoing)
        upstream.writer.write(payload)
        stats.bytes_up += len(payload)
        await upstream.writer.drain()

        body_size = 0
        while True:
            event = await self._next_event(
                client_h11, client_reader, read_timeout=self.config.body_timeout
            )
            if isinstance(event, h11.Data):
                body_size += len(event.data)
                if body_size > self.config.max_request_body_bytes:
                    raise BadRequest("request body is too large")
                payload = upstream_h11.send(h11.Data(data=event.data))
            elif isinstance(event, h11.EndOfMessage):
                payload = upstream_h11.send(h11.EndOfMessage(headers=event.headers))
            else:
                raise BadRequest("unexpected event in request body")
            upstream.writer.write(payload)
            stats.bytes_up += len(payload)
            await upstream.writer.drain()
            if isinstance(event, h11.EndOfMessage):
                break

        response_started = False
        while True:
            event = await self._next_event(
                upstream_h11, upstream.reader, read_timeout=self.config.body_timeout
            )
            if isinstance(event, h11.InformationalResponse):
                if event.status_code == 100:
                    continue
                payload = client_h11.send(
                    h11.InformationalResponse(
                        status_code=event.status_code,
                        headers=sanitized_response_headers(event.headers),
                    )
                )
            elif isinstance(event, h11.Response):
                if event.status_code == 407:
                    raise UpstreamFailure("upstream proxy authentication failed")
                response_started = True
                stats.client_response_started = True
                payload = client_h11.send(
                    h11.Response(
                        status_code=event.status_code,
                        reason=event.reason,
                        headers=sanitized_response_headers(event.headers),
                    )
                )
            elif isinstance(event, h11.Data):
                if not response_started:
                    raise UpstreamFailure("upstream sent body before response headers")
                payload = client_h11.send(h11.Data(data=event.data))
            elif isinstance(event, h11.EndOfMessage):
                payload = client_h11.send(h11.EndOfMessage(headers=event.headers))
            else:
                raise UpstreamFailure("unexpected upstream HTTP event")
            client_writer.write(payload)
            stats.bytes_down += len(payload)
            await client_writer.drain()
            if isinstance(event, h11.EndOfMessage):
                return

    async def _next_event(
        self,
        connection: h11.Connection,
        reader: asyncio.StreamReader,
        *,
        read_timeout: float,
    ) -> h11.Event:
        while True:
            event = connection.next_event()
            if event is h11.PAUSED:
                raise h11.RemoteProtocolError("HTTP pipelining is not supported")
            if event is not h11.NEED_DATA:
                return cast(h11.Event, event)
            chunk = await asyncio.wait_for(reader.read(64 * 1024), timeout=read_timeout)
            connection.receive_data(chunk)
            if not chunk:
                event = connection.next_event()
                if event is h11.NEED_DATA:
                    raise asyncio.IncompleteReadError(b"", 1)
                if event is h11.PAUSED:
                    raise h11.RemoteProtocolError("HTTP connection paused unexpectedly")
                return cast(h11.Event, event)

    async def _relay_tunnel(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        upstream: ConnectedUpstream,
        stats: RequestStats,
    ) -> None:
        async def pump(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
            direction: str,
        ) -> None:
            while True:
                data = await asyncio.wait_for(
                    reader.read(64 * 1024), timeout=self.config.tunnel_idle_timeout
                )
                if not data:
                    with contextlib.suppress(OSError, RuntimeError):
                        writer.write_eof()
                    return
                writer.write(data)
                await writer.drain()
                if direction == "up":
                    stats.bytes_up += len(data)
                else:
                    stats.bytes_down += len(data)

        try:
            async with asyncio.timeout(self.config.tunnel_lifetime):
                await asyncio.gather(
                    pump(client_reader, upstream.writer, "up"),
                    pump(upstream.reader, client_writer, "down"),
                )
        except (TimeoutError, ConnectionError, OSError):
            pass
        finally:
            await upstream.close()

    async def _send_h11(
        self,
        connection: h11.Connection,
        writer: asyncio.StreamWriter,
        event: h11.Event,
    ) -> None:
        payload = connection.send(event)
        if payload is None:
            raise h11.LocalProtocolError("h11 event produced no wire bytes")
        writer.write(payload)
        await writer.drain()

    async def _send_error(
        self,
        connection: h11.Connection,
        writer: asyncio.StreamWriter,
        error: GatewayError,
    ) -> None:
        if writer.is_closing():
            return
        body = f"{error.status_code} {error.reason}\n".encode("ascii")
        headers = [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"connection", b"close"),
        ]
        if error.status_code == 407:
            headers.append((b"proxy-authenticate", b'Basic realm="Proxy Hide"'))
        try:
            writer.write(
                connection.send(
                    h11.Response(
                        status_code=error.status_code,
                        reason=error.reason.encode("ascii"),
                        headers=headers,
                    )
                )
                + connection.send(h11.Data(data=body))
                + connection.send(h11.EndOfMessage())
            )
        except h11.LocalProtocolError:
            writer.write(
                b"HTTP/1.1 "
                + str(error.status_code).encode("ascii")
                + b" "
                + error.reason.encode("ascii")
                + b"\r\nConnection: close\r\nContent-Length: "
                + str(len(body)).encode("ascii")
                + b"\r\n\r\n"
                + body
            )
        with contextlib.suppress(ConnectionError, OSError):
            await writer.drain()


def _origin_target(absolute_target: bytes) -> bytes:
    from urllib.parse import urlsplit

    parsed = urlsplit(absolute_target.decode("ascii"))
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    return path.encode("ascii")
