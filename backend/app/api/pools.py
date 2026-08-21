from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.dependencies import (
    DB,
    PaginationDep,
    WorkspacePrincipal,
    enforce_quota,
    paginate,
    workspace_limits,
)
from app.errors import APIError
from app.models import Endpoint, Filter, JobType, Pool
from app.schemas import OperationView, Page, PoolCreate, PoolUpdate, PoolView
from app.services.audit import record_audit
from app.services.jobs import create_operation, enqueue_job

router = APIRouter(prefix="/pools", tags=["pools"])


async def _tenant_pool(pool_id: UUID, db: DB, workspace_id: UUID) -> Pool:
    pool = await db.scalar(
        select(Pool).where(Pool.id == pool_id, Pool.workspace_id == workspace_id)
    )
    if pool is None:
        raise APIError(404, "POOL_NOT_FOUND", "The pool was not found.")
    return pool


async def _tenant_filter(filter_id: UUID, db: DB, workspace_id: UUID) -> Filter:
    value = await db.scalar(
        select(Filter).where(Filter.id == filter_id, Filter.workspace_id == workspace_id)
    )
    if value is None:
        raise APIError(422, "FILTER_NOT_FOUND", "The selected filter was not found.")
    return value


@router.get("", response_model=Page[PoolView])
async def list_pools(
    db: DB, principal: WorkspacePrincipal, pagination: PaginationDep
) -> Page[PoolView]:
    pools, total = await paginate(
        db,
        select(Pool)
        .where(Pool.workspace_id == principal.workspace_id)
        .order_by(Pool.created_at.desc()),
        pagination,
    )
    return Page(
        items=[PoolView.model_validate(pool) for pool in pools],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("", response_model=PoolView, status_code=status.HTTP_201_CREATED)
async def create_pool(
    payload: PoolCreate, request: Request, db: DB, principal: WorkspacePrincipal
) -> PoolView:
    await enforce_quota(
        db,
        workspace_id=principal.workspace_id,
        model=Pool,
        limit_field="max_pools",
    )
    await _tenant_filter(payload.filter_id, db, principal.workspace_id)
    limits = await workspace_limits(db, principal.workspace_id)
    if not limits.global_catalog_enabled and payload.catalog_selection.value in {
        "global",
        "combined",
    }:
        raise APIError(403, "GLOBAL_CATALOG_DISABLED", "Global catalog access is disabled.")
    pool = Pool(workspace_id=principal.workspace_id, **payload.model_dump())
    db.add(pool)
    await db.flush()
    operation = create_operation(
        db,
        workspace_id=principal.workspace_id,
        kind="pool_materialize",
        progress_total=1,
    )
    enqueue_job(
        db,
        job_type=JobType.MATERIALIZE_POOL,
        workspace_id=principal.workspace_id,
        entity_id=pool.id,
        operation=operation,
        payload={"reason": "pool_created"},
    )
    record_audit(
        db,
        request,
        principal,
        action="pool.created",
        resource_type="pool",
        resource_id=pool.id,
    )
    await db.commit()
    return PoolView.model_validate(pool)


@router.get("/{pool_id}", response_model=PoolView)
async def get_pool(pool_id: UUID, db: DB, principal: WorkspacePrincipal) -> PoolView:
    return PoolView.model_validate(await _tenant_pool(pool_id, db, principal.workspace_id))


@router.patch("/{pool_id}", response_model=PoolView)
async def update_pool(
    pool_id: UUID,
    payload: PoolUpdate,
    request: Request,
    db: DB,
    principal: WorkspacePrincipal,
) -> PoolView:
    pool = await _tenant_pool(pool_id, db, principal.workspace_id)
    changes = payload.model_dump(exclude_unset=True)
    if payload.filter_id is not None:
        await _tenant_filter(payload.filter_id, db, principal.workspace_id)
    if payload.catalog_selection is not None:
        limits = await workspace_limits(db, principal.workspace_id)
        if not limits.global_catalog_enabled and payload.catalog_selection.value in {
            "global",
            "combined",
        }:
            raise APIError(403, "GLOBAL_CATALOG_DISABLED", "Global catalog access is disabled.")
    for field, value in changes.items():
        setattr(pool, field, value.strip() if field == "name" else value)
    operation = create_operation(
        db,
        workspace_id=principal.workspace_id,
        kind="pool_materialize",
        progress_total=1,
    )
    enqueue_job(
        db,
        job_type=JobType.MATERIALIZE_POOL,
        workspace_id=principal.workspace_id,
        entity_id=pool.id,
        operation=operation,
        payload={"reason": "pool_updated"},
    )
    record_audit(
        db,
        request,
        principal,
        action="pool.updated",
        resource_type="pool",
        resource_id=pool.id,
    )
    await db.commit()
    return PoolView.model_validate(pool)


@router.post(
    "/{pool_id}/materialize", response_model=OperationView, status_code=status.HTTP_202_ACCEPTED
)
async def materialize_pool(
    pool_id: UUID, request: Request, db: DB, principal: WorkspacePrincipal
) -> OperationView:
    pool = await _tenant_pool(pool_id, db, principal.workspace_id)
    operation = create_operation(
        db,
        workspace_id=principal.workspace_id,
        kind="pool_materialize",
        progress_total=1,
    )
    enqueue_job(
        db,
        job_type=JobType.MATERIALIZE_POOL,
        workspace_id=principal.workspace_id,
        entity_id=pool.id,
        operation=operation,
        payload={"reason": "manual"},
    )
    record_audit(
        db,
        request,
        principal,
        action="pool.materialization_requested",
        resource_type="pool",
        resource_id=pool.id,
    )
    await db.commit()
    return OperationView.model_validate(operation)


@router.delete("/{pool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pool(
    pool_id: UUID, request: Request, db: DB, principal: WorkspacePrincipal
) -> None:
    pool = await _tenant_pool(pool_id, db, principal.workspace_id)
    endpoint = await db.scalar(
        select(Endpoint.id).where(
            Endpoint.workspace_id == principal.workspace_id, Endpoint.pool_id == pool.id
        )
    )
    if endpoint:
        raise APIError(409, "POOL_IN_USE", "Delete the pool's endpoints before deleting the pool.")
    await db.delete(pool)
    record_audit(
        db,
        request,
        principal,
        action="pool.deleted",
        resource_type="pool",
        resource_id=pool.id,
    )
    await db.commit()
