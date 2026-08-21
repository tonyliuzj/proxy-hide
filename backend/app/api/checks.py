from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.dependencies import DB, PaginationDep, WorkspacePrincipal, paginate
from app.errors import APIError
from app.models import CheckAttempt, CheckJob, JobStatus
from app.schemas import CheckAttemptView, JobView, Page
from app.services.audit import record_audit
from app.services.jobs import enqueue_job

router = APIRouter(prefix="/checks", tags=["checks"])


async def _tenant_job(job_id: UUID, db: DB, workspace_id: UUID) -> CheckJob:
    job = await db.scalar(
        select(CheckJob).where(CheckJob.id == job_id, CheckJob.workspace_id == workspace_id)
    )
    if job is None:
        raise APIError(404, "CHECK_JOB_NOT_FOUND", "The check job was not found.")
    return job


@router.get("", response_model=Page[JobView])
async def list_checks(
    db: DB, principal: WorkspacePrincipal, pagination: PaginationDep
) -> Page[JobView]:
    jobs, total = await paginate(
        db,
        select(CheckJob)
        .where(CheckJob.workspace_id == principal.workspace_id)
        .order_by(CheckJob.created_at.desc()),
        pagination,
    )
    return Page(
        items=[JobView.model_validate(job) for job in jobs],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{job_id}", response_model=JobView)
async def get_check(job_id: UUID, db: DB, principal: WorkspacePrincipal) -> JobView:
    return JobView.model_validate(await _tenant_job(job_id, db, principal.workspace_id))


@router.get("/{job_id}/attempts", response_model=Page[CheckAttemptView])
async def list_attempts(
    job_id: UUID, db: DB, principal: WorkspacePrincipal, pagination: PaginationDep
) -> Page[CheckAttemptView]:
    await _tenant_job(job_id, db, principal.workspace_id)
    attempts, total = await paginate(
        db,
        select(CheckAttempt)
        .where(
            CheckAttempt.job_id == job_id,
            CheckAttempt.workspace_id == principal.workspace_id,
        )
        .order_by(CheckAttempt.checked_at.desc()),
        pagination,
    )
    return Page(
        items=[CheckAttemptView.model_validate(attempt) for attempt in attempts],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("/{job_id}/retry", response_model=JobView, status_code=status.HTTP_202_ACCEPTED)
async def retry_check(
    job_id: UUID, request: Request, db: DB, principal: WorkspacePrincipal
) -> JobView:
    previous = await _tenant_job(job_id, db, principal.workspace_id)
    if previous.status not in {JobStatus.FAILED, JobStatus.DEAD}:
        raise APIError(409, "CHECK_NOT_RETRYABLE", "Only failed check jobs can be retried.")
    job = enqueue_job(
        db,
        job_type=previous.type,
        workspace_id=principal.workspace_id,
        entity_id=previous.entity_id,
        payload={**previous.payload, "retry_of": str(previous.id)},
    )
    record_audit(
        db,
        request,
        principal,
        action="check.retried",
        resource_type="check_job",
        resource_id=job.id,
        details={"retry_of": str(previous.id)},
    )
    await db.commit()
    return JobView.model_validate(job)
