from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.inventory import _route_view
from app.dependencies import (
    DB,
    PaginationDep,
    WorkspacePrincipal,
    enforce_quota,
    paginate,
    workspace_limits,
)
from app.domain.filters import (
    FilterValidationError,
    catalog_scope_clause,
    compile_filter,
    referenced_target_ids,
    validate_filter,
)
from app.errors import APIError
from app.models import Filter, JobType, Pool, ProxyHealth, ProxyRoute, Target
from app.schemas import (
    FilterCreate,
    FilterPreviewRequest,
    FilterPreviewResult,
    FilterUpdate,
    FilterView,
    Page,
)
from app.services.audit import record_audit
from app.services.jobs import create_operation, enqueue_job

router = APIRouter(prefix="/filters", tags=["filters"])


async def _validated_rules(
    db: DB, workspace_id: UUID, rules: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    try:
        validated = validate_filter(rules)
    except FilterValidationError as exc:
        raise APIError(
            422, "FILTER_INVALID", "The filter rules are invalid.", field_errors=exc.errors
        ) from exc
    target_ids = referenced_target_ids(rules)
    if target_ids:
        existing = set(
            (
                await db.scalars(
                    select(Target.id).where(
                        Target.workspace_id == workspace_id, Target.id.in_(target_ids)
                    )
                )
            ).all()
        )
        if existing != target_ids:
            raise APIError(
                422,
                "FILTER_TARGET_INVALID",
                "A target referenced by the filter does not belong to this workspace.",
            )
    return validated.version, {"version": validated.version, "root": validated.root}


async def _tenant_filter(filter_id: UUID, db: DB, workspace_id: UUID) -> Filter:
    value = await db.scalar(
        select(Filter).where(Filter.id == filter_id, Filter.workspace_id == workspace_id)
    )
    if value is None:
        raise APIError(404, "FILTER_NOT_FOUND", "The filter was not found.")
    return value


@router.get("", response_model=Page[FilterView])
async def list_filters(
    db: DB, principal: WorkspacePrincipal, pagination: PaginationDep
) -> Page[FilterView]:
    values, total = await paginate(
        db,
        select(Filter)
        .where(Filter.workspace_id == principal.workspace_id)
        .order_by(Filter.created_at.desc()),
        pagination,
    )
    return Page(
        items=[FilterView.model_validate(value) for value in values],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("", response_model=FilterView, status_code=status.HTTP_201_CREATED)
async def create_filter(
    payload: FilterCreate, request: Request, db: DB, principal: WorkspacePrincipal
) -> FilterView:
    await enforce_quota(
        db,
        workspace_id=principal.workspace_id,
        model=Filter,
        limit_field="max_filters",
    )
    version, rules = await _validated_rules(db, principal.workspace_id, payload.rules)
    value = Filter(
        workspace_id=principal.workspace_id,
        name=payload.name.strip(),
        version=version,
        rules=rules,
    )
    db.add(value)
    await db.flush()
    record_audit(
        db,
        request,
        principal,
        action="filter.created",
        resource_type="filter",
        resource_id=value.id,
    )
    await db.commit()
    return FilterView.model_validate(value)


@router.post("/preview", response_model=FilterPreviewResult)
async def preview_filter(
    payload: FilterPreviewRequest, db: DB, principal: WorkspacePrincipal
) -> FilterPreviewResult:
    _, rules = await _validated_rules(db, principal.workspace_id, payload.rules)
    limits = await workspace_limits(db, principal.workspace_id)
    if not limits.global_catalog_enabled and payload.catalog_selection.value in {
        "global",
        "combined",
    }:
        raise APIError(403, "GLOBAL_CATALOG_DISABLED", "Global catalog access is disabled.")
    clause = compile_filter(rules, principal.workspace_id)
    scope = catalog_scope_clause(payload.catalog_selection.value, principal.workspace_id)
    base = (
        select(ProxyRoute).outerjoin(ProxyHealth).where(ProxyRoute.active.is_(True), scope, clause)
    )
    count = int(
        (await db.scalar(select(func.count()).select_from(base.order_by(None).subquery()))) or 0
    )
    routes = list(
        (
            await db.scalars(
                base.options(selectinload(ProxyRoute.health))
                .order_by(ProxyHealth.score.desc())
                .limit(payload.sample_size)
            )
        ).all()
    )
    return FilterPreviewResult(count=count, sample=[_route_view(route) for route in routes])


@router.get("/{filter_id}", response_model=FilterView)
async def get_filter(filter_id: UUID, db: DB, principal: WorkspacePrincipal) -> FilterView:
    return FilterView.model_validate(await _tenant_filter(filter_id, db, principal.workspace_id))


@router.patch("/{filter_id}", response_model=FilterView)
async def update_filter(
    filter_id: UUID,
    payload: FilterUpdate,
    request: Request,
    db: DB,
    principal: WorkspacePrincipal,
) -> FilterView:
    value = await _tenant_filter(filter_id, db, principal.workspace_id)
    if payload.name is not None:
        value.name = payload.name.strip()
    if payload.rules is not None:
        value.version, value.rules = await _validated_rules(
            db, principal.workspace_id, payload.rules
        )
    dependent_pools = list(
        (
            await db.scalars(
                select(Pool).where(
                    Pool.workspace_id == principal.workspace_id, Pool.filter_id == value.id
                )
            )
        ).all()
    )
    for pool in dependent_pools:
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
            payload={"reason": "filter_updated"},
        )
    record_audit(
        db,
        request,
        principal,
        action="filter.updated",
        resource_type="filter",
        resource_id=value.id,
    )
    await db.commit()
    return FilterView.model_validate(value)


@router.delete("/{filter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_filter(
    filter_id: UUID, request: Request, db: DB, principal: WorkspacePrincipal
) -> None:
    value = await _tenant_filter(filter_id, db, principal.workspace_id)
    await db.delete(value)
    record_audit(
        db,
        request,
        principal,
        action="filter.deleted",
        resource_type="filter",
        resource_id=value.id,
    )
    await db.commit()
