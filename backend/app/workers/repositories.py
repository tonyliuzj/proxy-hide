from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    AuditEvent,
    CheckAttempt,
    CheckJob,
    JobStatus,
    JobType,
    Operation,
    OperationStatus,
    OutboxEvent,
    Pool,
    PoolRevision,
    ProxyHealth,
    ProxyRoute,
    Source,
    SourceRun,
    Target,
    TrafficRollup,
)
from app.services.jobs import enqueue_job

from .jobs import JobEnvelope, JobRepository
from .outbox import OutboxItem, OutboxRepository
from .scheduler import ScheduleRepository, general_check_interval


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError("job contains an invalid UUID") from exc


class SQLAlchemyJobRepository(JobRepository):
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        running_lease: timedelta = timedelta(minutes=5),
    ) -> None:
        self.sessions = sessions
        self.running_lease = running_lease

    async def claim(self, envelope: JobEnvelope) -> bool:
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            job = await session.scalar(
                select(CheckJob).where(CheckJob.id == _uuid(envelope.job_id)).with_for_update()
            )
            if job is None or job.status in {JobStatus.SUCCEEDED, JobStatus.DEAD}:
                return False
            if (
                job.status is JobStatus.RUNNING
                and job.started_at is not None
                and job.started_at >= now - self.running_lease
            ):
                return False
            job.status = JobStatus.RUNNING
            job.attempt = envelope.attempt
            job.started_at = now
            job.finished_at = None
            job.error = None
            await self._mark_operation_running(session, job)
            return True

    async def succeed(self, envelope: JobEnvelope) -> None:
        async with self.sessions() as session, session.begin():
            job = await session.scalar(
                select(CheckJob).where(CheckJob.id == _uuid(envelope.job_id)).with_for_update()
            )
            if job is None:
                return
            job.status = JobStatus.SUCCEEDED
            job.finished_at = datetime.now(UTC)
            job.error = None
            await self._finish_operation(session, job, succeeded=True)

    async def fail(self, envelope: JobEnvelope, error: str, *, terminal: bool) -> None:
        async with self.sessions() as session, session.begin():
            job = await session.scalar(
                select(CheckJob).where(CheckJob.id == _uuid(envelope.job_id)).with_for_update()
            )
            if job is None:
                return
            job.attempt = envelope.attempt + 1
            job.status = JobStatus.DEAD if terminal else JobStatus.QUEUED
            job.error = {"code": "worker_error", "message": error[:500]}
            job.finished_at = datetime.now(UTC) if terminal else None
            if terminal:
                await self._finish_operation(session, job, succeeded=False)

    async def _mark_operation_running(self, session: AsyncSession, job: CheckJob) -> None:
        operation = await self._operation(session, job)
        if operation is not None and operation.status is OperationStatus.PENDING:
            operation.status = OperationStatus.RUNNING

    async def _finish_operation(
        self, session: AsyncSession, job: CheckJob, *, succeeded: bool
    ) -> None:
        operation = await self._operation(session, job)
        if operation is None:
            return
        operation.progress_current = operation.progress_total or 1
        operation.status = OperationStatus.SUCCEEDED if succeeded else OperationStatus.FAILED
        operation.finished_at = datetime.now(UTC)
        operation.error = None if succeeded else job.error

    @staticmethod
    async def _operation(session: AsyncSession, job: CheckJob) -> Operation | None:
        raw_id = job.payload.get("operation_id") if job.payload else None
        if not raw_id:
            return None
        try:
            operation_id = UUID(str(raw_id))
        except ValueError:
            return None
        return await session.get(Operation, operation_id)


class SQLAlchemyOutboxRepository(OutboxRepository):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def claim_batch(self, limit: int) -> list[OutboxItem]:
        async with self.sessions() as session, session.begin():
            events = (
                await session.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.published_at.is_(None), OutboxEvent.topic == "jobs")
                    .order_by(OutboxEvent.created_at, OutboxEvent.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for event in events:
                event.attempts += 1
            return [OutboxItem(str(event.id), event.topic, dict(event.payload)) for event in events]

    async def mark_published(self, item_id: str) -> None:
        async with self.sessions() as session, session.begin():
            event = await session.get(OutboxEvent, _uuid(item_id), with_for_update=True)
            if event is not None:
                event.published_at = datetime.now(UTC)
                event.last_error = None

    async def mark_failed(self, item_id: str, error: str) -> None:
        async with self.sessions() as session, session.begin():
            event = await session.get(OutboxEvent, _uuid(item_id), with_for_update=True)
            if event is not None:
                event.last_error = error[:500]


class SQLAlchemyScheduleRepository(ScheduleRepository):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def enqueue_due(self, *, batch_size: int) -> int:
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            route_rows = (
                await session.execute(
                    select(ProxyRoute, ProxyHealth)
                    .outerjoin(ProxyHealth, ProxyHealth.proxy_id == ProxyRoute.id)
                    .where(
                        ProxyRoute.active.is_(True),
                        or_(ProxyHealth.proxy_id.is_(None), ProxyHealth.next_check_at <= now),
                    )
                    .order_by(ProxyHealth.next_check_at.asc().nullsfirst(), ProxyRoute.created_at)
                    .limit(batch_size)
                    .with_for_update(of=ProxyRoute, skip_locked=True)
                )
            ).all()
            queued = 0
            for route, health in route_rows:
                if health is None:
                    health = ProxyHealth(proxy_id=route.id)
                    session.add(health)
                health.next_check_at = now + general_check_interval(health.status)
                enqueue_job(
                    session,
                    job_type=JobType.CHECK_PROXY,
                    workspace_id=route.workspace_id,
                    entity_id=route.id,
                    payload={"reason": "scheduled"},
                )
                queued += 1
            remaining = max(0, batch_size - queued)
            if remaining:
                queued += await self._enqueue_sources(session, now, remaining)
            remaining = max(0, batch_size - queued)
            if remaining:
                queued += await self._enqueue_targets(session, now, remaining)
            remaining = max(0, batch_size - queued)
            if remaining:
                queued += await self._enqueue_pools(session, now, remaining)
            return queued

    async def _enqueue_sources(self, session: AsyncSession, now: datetime, limit: int) -> int:
        active_entities = select(CheckJob.entity_id).where(
            CheckJob.type == JobType.REFRESH_SOURCE,
            CheckJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
        )
        sources = (
            await session.scalars(
                select(Source)
                .where(Source.enabled.is_(True), Source.id.not_in(active_entities))
                .order_by(Source.last_run_at.asc().nullsfirst())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        queued = 0
        for source in sources:
            if (
                source.last_run_at is not None
                and source.last_run_at + timedelta(minutes=source.refresh_interval_minutes) > now
            ):
                continue
            enqueue_job(
                session,
                job_type=JobType.REFRESH_SOURCE,
                workspace_id=source.workspace_id,
                entity_id=source.id,
                payload={"reason": "scheduled"},
            )
            queued += 1
        return queued

    async def _enqueue_targets(self, session: AsyncSession, now: datetime, limit: int) -> int:
        active_entities = select(CheckJob.entity_id).where(
            CheckJob.type == JobType.CHECK_TARGET,
            CheckJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
        )
        last_checks = (
            select(
                CheckJob.entity_id.label("target_id"),
                func.max(CheckJob.finished_at).label("last_checked"),
            )
            .where(
                CheckJob.type == JobType.CHECK_TARGET,
                CheckJob.status.in_((JobStatus.SUCCEEDED, JobStatus.DEAD)),
                CheckJob.finished_at.is_not(None),
            )
            .group_by(CheckJob.entity_id)
            .subquery()
        )
        targets = (
            await session.scalars(
                select(Target)
                .outerjoin(last_checks, last_checks.c.target_id == Target.id)
                .where(
                    Target.enabled.is_(True),
                    Target.id.not_in(active_entities),
                    or_(
                        last_checks.c.last_checked.is_(None),
                        last_checks.c.last_checked <= now - timedelta(minutes=15),
                    ),
                )
                .order_by(last_checks.c.last_checked.asc().nullsfirst())
                .limit(limit)
                .with_for_update(of=Target, skip_locked=True)
            )
        ).all()
        for target in targets:
            enqueue_job(
                session,
                job_type=JobType.CHECK_TARGET,
                workspace_id=target.workspace_id,
                entity_id=target.id,
                payload={"reason": "scheduled"},
            )
        return len(targets)

    async def _enqueue_pools(self, session: AsyncSession, now: datetime, limit: int) -> int:
        active_entities = select(CheckJob.entity_id).where(
            CheckJob.type == JobType.MATERIALIZE_POOL,
            CheckJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
        )
        pools = (
            await session.scalars(
                select(Pool)
                .where(
                    Pool.enabled.is_(True),
                    Pool.id.not_in(active_entities),
                    or_(
                        Pool.materialized_at.is_(None),
                        Pool.materialized_at <= now - timedelta(minutes=10),
                    ),
                )
                .order_by(Pool.materialized_at.asc().nullsfirst())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for pool in pools:
            enqueue_job(
                session,
                job_type=JobType.MATERIALIZE_POOL,
                workspace_id=pool.workspace_id,
                entity_id=pool.id,
                payload={"reason": "reconciliation"},
            )
        return len(pools)

    async def run_retention(self) -> None:
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            await session.execute(
                delete(CheckAttempt).where(CheckAttempt.checked_at < now - timedelta(days=30))
            )
            await session.execute(
                delete(SourceRun).where(SourceRun.created_at < now - timedelta(days=90))
            )
            await session.execute(
                delete(TrafficRollup).where(
                    or_(
                        (TrafficRollup.granularity == "minute")
                        & (TrafficRollup.bucket_start < now - timedelta(days=7)),
                        (TrafficRollup.granularity == "hour")
                        & (TrafficRollup.bucket_start < now - timedelta(days=395)),
                    )
                )
            )
            await session.execute(
                delete(AuditEvent).where(AuditEvent.created_at < now - timedelta(days=365))
            )
            pools = (await session.scalars(select(Pool))).all()
            for pool in pools:
                revisions = (
                    await session.scalars(
                        select(PoolRevision)
                        .where(PoolRevision.pool_id == pool.id)
                        .order_by(PoolRevision.revision.desc())
                    )
                ).all()
                for revision in revisions[10:]:
                    if revision.created_at < now - timedelta(days=7):
                        await session.delete(revision)
