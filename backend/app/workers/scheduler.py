from __future__ import annotations

import asyncio
import contextlib
import signal
from datetime import timedelta
from typing import Any, Protocol

from app.models import HealthStatus


def general_check_interval(status: HealthStatus | str) -> timedelta:
    value = status.value if isinstance(status, HealthStatus) else str(status).lower()
    if value == HealthStatus.HEALTHY.value:
        return timedelta(minutes=10)
    if value == HealthStatus.UNHEALTHY.value:
        return timedelta(minutes=30)
    return timedelta(minutes=5)


TARGET_CHECK_INTERVAL = timedelta(minutes=15)


class ScheduleRepository(Protocol):
    async def enqueue_due(self, *, batch_size: int) -> int: ...

    async def run_retention(self) -> None: ...


class Scheduler:
    def __init__(
        self,
        repository: ScheduleRepository,
        *,
        interval_seconds: float = 5.0,
        batch_size: int = 1_000,
        retention_interval_seconds: float = 60 * 60,
    ) -> None:
        self.repository = repository
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self.retention_interval_seconds = retention_interval_seconds
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        next_retention = loop.time()
        while not self._stopped.is_set():
            await self.repository.enqueue_due(batch_size=self.batch_size)
            if loop.time() >= next_retention:
                await self.repository.run_retention()
                next_retention = loop.time() + self.retention_interval_seconds
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stopped.set()


_SCHEDULER_LOCK_ID = 0x50524F5859484944


async def _run_leader(stopped: asyncio.Event, redis: Any) -> None:
    from app.config import get_settings
    from app.db import SessionLocal

    from .outbox import OutboxDispatcher
    from .repositories import SQLAlchemyOutboxRepository, SQLAlchemyScheduleRepository

    settings = get_settings()
    scheduler = Scheduler(SQLAlchemyScheduleRepository(SessionLocal))
    outbox = OutboxDispatcher(
        redis,
        SQLAlchemyOutboxRepository(SessionLocal),
        jobs_stream=settings.jobs_stream,
        priority_jobs_stream=f"{settings.jobs_stream}:priority",
    )
    scheduler_task = asyncio.create_task(scheduler.run(), name="due-work-scheduler")
    outbox_task = asyncio.create_task(outbox.run(), name="database-outbox-relay")
    try:
        stop_task = asyncio.create_task(stopped.wait(), name="scheduler-shutdown")
        done, _pending = await asyncio.wait(
            (scheduler_task, outbox_task, stop_task), return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            if task is not stop_task:
                await task
    finally:
        scheduler.stop()
        outbox.stop()
        for task in (scheduler_task, outbox_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def run_scheduler_process() -> None:
    from redis.asyncio import Redis
    from sqlalchemy import text

    from app.config import get_settings
    from app.db import engine

    settings = get_settings()
    redis: Any = Redis.from_url(settings.redis_url, decode_responses=False)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is not None:
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(signum, stopped.set)
    try:
        if engine.dialect.name != "postgresql":
            await _run_leader(stopped, redis)
            return
        while not stopped.is_set():
            async with engine.connect() as connection:
                acquired = await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": _SCHEDULER_LOCK_ID},
                )
                if acquired:
                    try:
                        await _run_leader(stopped, redis)
                    finally:
                        await connection.execute(
                            text("SELECT pg_advisory_unlock(:lock_id)"),
                            {"lock_id": _SCHEDULER_LOCK_ID},
                        )
                    return
            try:
                await asyncio.wait_for(stopped.wait(), timeout=5)
            except TimeoutError:
                pass
    finally:
        await redis.aclose()


def main() -> None:
    asyncio.run(run_scheduler_process())


if __name__ == "__main__":
    main()
