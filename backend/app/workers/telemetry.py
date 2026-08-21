from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import CheckJob, JobStatus, JobType, ProxyRoute, TrafficRollup
from app.services.jobs import enqueue_job


def _text(value: object | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return "" if value is None else str(value)


class TelemetryRepository(Protocol):
    async def persist(self, fields: Mapping[object, object]) -> None: ...


class SQLAlchemyTelemetryRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def persist(self, fields: Mapping[object, object]) -> None:
        values = {_text(key): _text(value) for key, value in fields.items()}
        async with self.sessions() as session, session.begin():
            await self._record_rollup(session, values)
            if values.get("outcome") == "upstream_connect_failed":
                await self._enqueue_urgent_check(session, values.get("route_id"))

    async def _record_rollup(self, session: AsyncSession, values: dict[str, str]) -> None:
        try:
            workspace_id = UUID(values["workspace_id"])
            endpoint_id = UUID(values["endpoint_id"])
            pool_id = UUID(values["pool_id"])
        except (KeyError, ValueError):
            return
        occurred_at = float(values.get("occurred_at") or 0) or datetime.now(UTC).timestamp()
        instant = datetime.fromtimestamp(occurred_at, UTC)
        bucket = instant.replace(second=0, microsecond=0)
        key = (workspace_id, endpoint_id, pool_id, bucket, "minute")
        rollup = await session.get(TrafficRollup, key, with_for_update=True)
        if rollup is None:
            rollup = TrafficRollup(
                workspace_id=workspace_id,
                endpoint_id=endpoint_id,
                pool_id=pool_id,
                bucket_start=bucket,
                granularity="minute",
                requests=0,
                successes=0,
                failures=0,
                bytes_up=0,
                bytes_down=0,
                latency_sum_ms=0,
            )
            session.add(rollup)
        succeeded = values.get("outcome") == "ok"
        rollup.requests += 1
        rollup.successes += int(succeeded)
        rollup.failures += int(not succeeded)
        rollup.bytes_up += int(values.get("bytes_up") or 0)
        rollup.bytes_down += int(values.get("bytes_down") or 0)
        rollup.latency_sum_ms += float(values.get("latency_ms") or 0)

    async def _enqueue_urgent_check(self, session: AsyncSession, raw_route_id: str | None) -> None:
        try:
            route_id = UUID(raw_route_id or "")
        except ValueError:
            return
        active = await session.scalar(
            select(CheckJob.id).where(
                CheckJob.type == JobType.CHECK_PROXY,
                CheckJob.entity_id == route_id,
                CheckJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
            )
        )
        if active is not None:
            return
        route = await session.get(ProxyRoute, route_id)
        if route is not None:
            enqueue_job(
                session,
                job_type=JobType.CHECK_PROXY,
                workspace_id=route.workspace_id,
                entity_id=route.id,
                payload={"reason": "gateway_transport_failure"},
            )


class GatewayTelemetryConsumer:
    def __init__(
        self,
        redis: Any,
        repository: TelemetryRepository,
        *,
        stream: str = "proxyhide:gateway:events",
        group: str = "gateway-telemetry-workers",
        consumer: str = "telemetry-1",
    ) -> None:
        self.redis = redis
        self.repository = repository
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        try:
            await self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        while not self._stopped.is_set():
            entries = await self.redis.xreadgroup(
                self.group,
                self.consumer,
                {self.stream: ">"},
                count=100,
                block=5_000,
            )
            for _stream, messages in entries or ():
                for message_id, fields in messages:
                    await self.repository.persist(fields)
                    await self.redis.xack(self.stream, self.group, message_id)

    def stop(self) -> None:
        self._stopped.set()
