from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CheckJob, JobStatus, JobType, Operation, OperationStatus, OutboxEvent


def enqueue_job(
    db: AsyncSession,
    *,
    job_type: JobType,
    workspace_id: UUID | None,
    entity_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    operation: Operation | None = None,
    deduplication_key: str | None = None,
) -> CheckJob:
    job = CheckJob(
        id=uuid4(),
        workspace_id=workspace_id,
        type=job_type,
        status=JobStatus.QUEUED,
        entity_id=entity_id,
        deduplication_key=deduplication_key
        or f"{job_type.value}:{entity_id or workspace_id or 'global'}:{secrets.token_hex(8)}",
        payload={**(payload or {}), **({"operation_id": str(operation.id)} if operation else {})},
    )
    db.add(job)
    db.add(
        OutboxEvent(
            topic=("jobs_priority" if (payload or {}).get("reason") == "manual" else "jobs"),
            aggregate_id=job.id,
            payload={
                "job_id": str(job.id),
                "type": job_type.value,
                "workspace_id": str(workspace_id) if workspace_id else "",
                "entity_id": str(entity_id) if entity_id else "",
                "attempt": "0",
            },
        )
    )
    return job


def create_operation(
    db: AsyncSession,
    *,
    workspace_id: UUID | None,
    kind: str,
    progress_total: int = 0,
) -> Operation:
    operation = Operation(
        id=uuid4(),
        workspace_id=workspace_id,
        kind=kind,
        status=OperationStatus.PENDING,
        progress_total=progress_total,
    )
    db.add(operation)
    return operation
