from __future__ import annotations

import asyncio
import contextlib
import ipaddress
from typing import Any

from app.config import get_settings
from app.security import KeyRing, endpoint_hmac_key_bytes

from .auth import EndpointAuthenticator
from .server import GatewayConfig, GatewayServer
from .snapshots import EncryptedSnapshotCodec, RedisSnapshotLoader, SnapshotStore
from .telemetry import TelemetryBuffer


async def run_gateway() -> None:
    try:
        from redis.asyncio import Redis
    except ImportError as exc:  # pragma: no cover - dependency failure is explicit at startup
        raise RuntimeError("redis package is required to run the gateway") from exc

    settings = get_settings()
    redis: Any = Redis.from_url(settings.redis_url, decode_responses=False)
    snapshots = SnapshotStore(stale_after=60.0)
    loader = RedisSnapshotLoader(
        redis,
        snapshots,
        EncryptedSnapshotCodec(KeyRing.from_settings(settings)),
        snapshot_key=settings.gateway_snapshot_key,
        reload_channel=settings.gateway_reload_channel,
    )
    telemetry = TelemetryBuffer()
    trusted_networks = tuple(
        ipaddress.ip_network(value, strict=False) for value in settings.trusted_proxy_cidrs
    )
    gateway = GatewayServer(
        snapshots=snapshots,
        authenticator=EndpointAuthenticator(endpoint_hmac_key_bytes(settings)),
        telemetry=telemetry,
        config=GatewayConfig(
            host=settings.gateway_bind_host,
            port=settings.gateway_bind_port,
            proxy_protocol_from_trusted=bool(trusted_networks),
            trusted_proxy_networks=trusted_networks,
        ),
    )
    loader_task = asyncio.create_task(loader.run(), name="gateway-snapshot-loader")
    telemetry_task = asyncio.create_task(telemetry.run(redis), name="gateway-telemetry")
    try:
        await gateway.serve_forever()
    finally:
        loader.stop()
        telemetry.stop()
        await gateway.close()
        for task in (loader_task, telemetry_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await redis.aclose()


def main() -> None:
    asyncio.run(run_gateway())


if __name__ == "__main__":
    main()
