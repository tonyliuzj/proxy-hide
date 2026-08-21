from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    CheckJob,
    Filter,
    HealthStatus,
    JobStatus,
    JobType,
    Pool,
    PoolStrategy,
    Target,
    TargetAvailability,
    TargetKind,
    Workspace,
    WorkspaceLimit,
)
from app.security import KeyRing
from app.workers.checks import CheckErrorCode, CheckSpec, HttpResult, classify_target_response
from app.workers.handlers import WorkerHandlers
from app.workers.jobs import JobEnvelope
from app.workers.repositories import SQLAlchemyScheduleRepository
from app.workers.scheduler import general_check_interval


@pytest.mark.parametrize(
    "status,expected",
    [
        (HealthStatus.HEALTHY, timedelta(minutes=10)),
        (HealthStatus.DEGRADED, timedelta(minutes=5)),
        (HealthStatus.UNKNOWN, timedelta(minutes=5)),
        (HealthStatus.UNHEALTHY, timedelta(minutes=30)),
    ],
)
def test_general_check_intervals(status: HealthStatus, expected: timedelta) -> None:
    assert general_check_interval(status) == expected


def test_target_classification_keeps_rate_limit_and_block_separate() -> None:
    spec = CheckSpec(url="https://example.com")
    limited = HttpResult(429, (), b"too many requests")
    blocked = HttpResult(200, (), b"captcha")
    available = HttpResult(200, (), b"normal result")

    assert classify_target_response(limited, spec) == (
        TargetAvailability.RATE_LIMITED,
        CheckErrorCode.STATUS,
    )
    assert classify_target_response(blocked, spec) == (
        TargetAvailability.BLOCKED,
        CheckErrorCode.CONTENT,
    )
    assert classify_target_response(available, spec) == (TargetAvailability.AVAILABLE, None)


def test_custom_target_patterns_are_compiled_by_re2() -> None:
    spec = CheckSpec(url="https://example.com", required_patterns=(r"item-[0-9]+",))
    response = HttpResult(200, (), b"item-42")
    assert classify_target_response(response, spec) == (TargetAvailability.AVAILABLE, None)
    with pytest.raises(ValueError, match="valid RE2"):
        CheckSpec(url="https://example.com", required_patterns=(r"(?=unsafe)",))


async def test_completed_empty_target_check_is_not_rescheduled_immediately(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        workspace = Workspace(name="Target schedule", slug="target-schedule")
        session.add(workspace)
        await session.flush()
        session.add(WorkspaceLimit(workspace_id=workspace.id))
        session.add_all(
            [
                Target(
                    workspace_id=workspace.id,
                    name="Google",
                    kind=TargetKind.GOOGLE,
                    url="https://www.google.com/search?q=health",
                ),
                Target(
                    workspace_id=workspace.id,
                    name="Bing",
                    kind=TargetKind.BING,
                    url="https://www.bing.com/search?q=health",
                ),
            ]
        )

    repository = SQLAlchemyScheduleRepository(session_factory)
    assert await repository.enqueue_due(batch_size=100) == 2

    async with session_factory() as session, session.begin():
        jobs = (
            await session.scalars(select(CheckJob).where(CheckJob.type == JobType.CHECK_TARGET))
        ).all()
        assert len(jobs) == 2
        for job in jobs:
            job.status = JobStatus.SUCCEEDED
            job.finished_at = datetime.now(UTC)

    assert await repository.enqueue_due(batch_size=100) == 0
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(CheckJob).where(CheckJob.type == JobType.CHECK_TARGET)
        )
        assert count == 2


async def test_empty_target_check_does_not_rematerialize_workspace_pools(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = uuid4()
    async with session_factory() as session, session.begin():
        workspace = Workspace(name="Empty target", slug="empty-target")
        session.add(workspace)
        await session.flush()
        session.add(WorkspaceLimit(workspace_id=workspace.id))
        target = Target(
            workspace_id=workspace.id,
            name="Google",
            kind=TargetKind.GOOGLE,
            url="https://www.google.com/search?q=health",
        )
        filter_row = Filter(
            workspace_id=workspace.id,
            name="Healthy",
            rules={
                "version": 1,
                "root": {
                    "op": "predicate",
                    "field": "health",
                    "operator": "eq",
                    "value": "healthy",
                },
            },
        )
        session.add_all([target, filter_row])
        await session.flush()
        session.add(
            Pool(
                workspace_id=workspace.id,
                filter_id=filter_row.id,
                name="Healthy pool",
                strategy=PoolStrategy.WEIGHTED_HEALTH,
            )
        )
        session.add(
            CheckJob(
                id=job_id,
                workspace_id=workspace.id,
                type=JobType.CHECK_TARGET,
                entity_id=target.id,
                deduplication_key="empty-target-check",
            )
        )
        workspace_id = workspace.id
        target_id = target.id

    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite://")
    handler = WorkerHandlers(
        session_factory,
        settings,
        KeyRing.from_settings(settings),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
    )
    await handler.check_target(
        JobEnvelope(
            job_id=str(job_id),
            type=JobType.CHECK_TARGET.value,
            workspace_id=str(workspace_id),
            entity_id=str(target_id),
        )
    )

    async with session_factory() as session:
        materialize_jobs = await session.scalar(
            select(func.count())
            .select_from(CheckJob)
            .where(CheckJob.type == JobType.MATERIALIZE_POOL)
        )
        target_job = await session.get(CheckJob, job_id)
        assert materialize_jobs == 0
        assert target_job is not None
        assert target_job.progress_total == 0
        assert target_job.progress_current == 0
