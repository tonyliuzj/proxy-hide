from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
from typing import Any

from redis.asyncio import Redis

from app.config import get_settings
from app.db import SessionLocal
from app.gateway.connectors import UpstreamConnector
from app.security import KeyRing

from .checks import ProxyCheckRunner
from .feeds import PublicFeedFetcher
from .geoip import GeoIPResolver
from .handlers import WorkerHandlers
from .jobs import RedisStreamWorker
from .materializer import PoolMaterializer, SnapshotPublisher
from .repositories import SQLAlchemyJobRepository
from .telemetry import GatewayTelemetryConsumer, SQLAlchemyTelemetryRepository


def _install_shutdown_handlers(event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is not None:
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(signum, event.set)


async def run_consumer() -> None:
    settings = get_settings()
    keyring = KeyRing.from_settings(settings)
    redis: Any = Redis.from_url(settings.redis_url, decode_responses=False)
    materializer = PoolMaterializer(SessionLocal)
    publisher = SnapshotPublisher(
        SessionLocal,
        redis,
        keyring,
        snapshot_key=settings.gateway_snapshot_key,
        reload_channel=settings.gateway_reload_channel,
    )
    geoip_resolver = GeoIPResolver(settings.geoip_database_path)
    handlers = WorkerHandlers(
        SessionLocal,
        settings,
        keyring,
        ProxyCheckRunner(UpstreamConnector()),
        PublicFeedFetcher(
            request_timeout=settings.source_fetch_timeout_seconds,
            max_bytes=settings.source_max_bytes,
        ),
        materializer,
        publisher,
        geoip_resolver,
    )
    consumer_name = f"{socket.gethostname()}-{os.getpid()}"
    worker = RedisStreamWorker(
        redis,
        SQLAlchemyJobRepository(SessionLocal),
        handlers.mapping(),
        stream=settings.jobs_stream,
        group=settings.jobs_consumer_group,
        consumer=consumer_name,
        dead_letter_stream=settings.jobs_dead_letter_stream,
        reclaim_idle_ms=5 * 60 * 1000,
    )
    telemetry = GatewayTelemetryConsumer(
        redis,
        SQLAlchemyTelemetryRepository(SessionLocal),
        consumer=consumer_name,
    )
    stopped = asyncio.Event()
    _install_shutdown_handlers(stopped)
    task = asyncio.create_task(worker.run(), name="redis-job-consumer")
    telemetry_task = asyncio.create_task(telemetry.run(), name="gateway-telemetry-consumer")
    try:
        stop_task = asyncio.create_task(stopped.wait(), name="consumer-shutdown")
        done, _pending = await asyncio.wait(
            (task, telemetry_task, stop_task), return_when=asyncio.FIRST_COMPLETED
        )
        if task in done:
            await task
        if telemetry_task in done:
            await telemetry_task
    finally:
        worker.stop()
        telemetry.stop()
        for running in (task, telemetry_task):
            running.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await running
        geoip_resolver.close()
        await redis.aclose()


def main() -> None:
    asyncio.run(run_consumer())


if __name__ == "__main__":
    main()
