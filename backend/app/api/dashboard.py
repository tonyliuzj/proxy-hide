from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement

from app.dependencies import DB, WorkspacePrincipal, workspace_limits
from app.domain.filters import catalog_scope_clause
from app.models import (
    CheckJob,
    Endpoint,
    Filter,
    HealthStatus,
    JobStatus,
    Pool,
    ProxyHealth,
    ProxyRoute,
    Source,
    Target,
    TargetKind,
    TrafficRollup,
)
from app.schemas import (
    DashboardSummary,
    JobView,
    Message,
    PasswordChange,
    UsageView,
    WorkspaceLimitsView,
    WorkspaceSettingsUpdate,
    WorkspaceSettingsView,
    WorkspaceSummary,
)
from app.security import hash_password, verify_password
from app.services.audit import record_audit

dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])
settings_router = APIRouter(prefix="/settings", tags=["settings"])


async def _count(db: DB, model: type[Any], *clauses: ColumnElement[bool]) -> int:
    return int((await db.scalar(select(func.count()).select_from(model).where(*clauses))) or 0)


async def _usage(db: DB, workspace_id: UUID) -> UsageView:
    return UsageView(
        private_proxies=await _count(db, ProxyRoute, ProxyRoute.workspace_id == workspace_id),
        sources=await _count(db, Source, Source.workspace_id == workspace_id),
        custom_targets=await _count(
            db,
            Target,
            Target.workspace_id == workspace_id,
            Target.kind == TargetKind.CUSTOM,
        ),
        filters=await _count(db, Filter, Filter.workspace_id == workspace_id),
        pools=await _count(db, Pool, Pool.workspace_id == workspace_id),
        endpoints=await _count(db, Endpoint, Endpoint.workspace_id == workspace_id),
    )


@dashboard_router.get("", response_model=DashboardSummary)
async def dashboard(db: DB, principal: WorkspacePrincipal) -> DashboardSummary:
    workspace_id = principal.workspace_id
    limits = await workspace_limits(db, workspace_id)
    scope_clause = (
        catalog_scope_clause("combined", workspace_id)
        if limits.global_catalog_enabled
        else ProxyRoute.workspace_id == workspace_id
    )
    total = await _count(db, ProxyRoute, ProxyRoute.active.is_(True), scope_clause)
    healthy = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(ProxyRoute)
                .join(ProxyHealth)
                .where(
                    ProxyRoute.active.is_(True),
                    scope_clause,
                    ProxyHealth.status == HealthStatus.HEALTHY,
                )
            )
        )
        or 0
    )
    traffic = await db.execute(
        select(
            func.coalesce(func.sum(TrafficRollup.requests), 0),
            func.coalesce(func.sum(TrafficRollup.successes), 0),
        ).where(
            TrafficRollup.workspace_id == workspace_id,
            TrafficRollup.bucket_start >= datetime.now(UTC) - timedelta(hours=24),
            TrafficRollup.granularity == "hour",
        )
    )
    requests, successes = traffic.one()
    recent_checks = list(
        (
            await db.scalars(
                select(CheckJob)
                .where(CheckJob.workspace_id == workspace_id)
                .order_by(CheckJob.created_at.desc())
                .limit(5)
            )
        ).all()
    )
    return DashboardSummary(
        proxies_total=total,
        proxies_healthy=healthy,
        sources_total=await _count(db, Source, Source.workspace_id == workspace_id),
        pools_total=await _count(db, Pool, Pool.workspace_id == workspace_id),
        pools_ready=await _count(
            db,
            Pool,
            Pool.workspace_id == workspace_id,
            Pool.enabled.is_(True),
            Pool.current_revision.is_not(None),
        ),
        endpoints_total=await _count(db, Endpoint, Endpoint.workspace_id == workspace_id),
        active_jobs=await _count(
            db,
            CheckJob,
            CheckJob.workspace_id == workspace_id,
            CheckJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        ),
        requests_24h=int(requests),
        successful_requests_24h=int(successes),
        recent_checks=[JobView.model_validate(job) for job in recent_checks],
    )


@settings_router.get("", response_model=WorkspaceSettingsView)
async def get_settings_view(db: DB, principal: WorkspacePrincipal) -> WorkspaceSettingsView:
    limits = await workspace_limits(db, principal.workspace_id)
    return WorkspaceSettingsView(
        workspace=WorkspaceSummary.model_validate(principal.workspace),
        limits=WorkspaceLimitsView.model_validate(limits),
        usage=await _usage(db, principal.workspace_id),
    )


@settings_router.patch("", response_model=WorkspaceSettingsView)
async def update_settings_view(
    payload: WorkspaceSettingsUpdate,
    request: Request,
    db: DB,
    principal: WorkspacePrincipal,
) -> WorkspaceSettingsView:
    principal.workspace.name = payload.name.strip()  # type: ignore[union-attr]
    record_audit(
        db,
        request,
        principal,
        action="workspace.settings_updated",
        resource_type="workspace",
        resource_id=principal.workspace_id,
    )
    await db.commit()
    return await get_settings_view(db, principal)


@settings_router.post("/change-password", response_model=Message)
async def change_password(
    payload: PasswordChange, request: Request, db: DB, principal: WorkspacePrincipal
) -> Message:
    if not verify_password(principal.user.password_hash, payload.current_password):
        from app.errors import APIError

        raise APIError(422, "CURRENT_PASSWORD_INVALID", "The current password is incorrect.")
    principal.user.password_hash = hash_password(payload.new_password)
    from app.db import utcnow

    principal.user.password_changed_at = utcnow()
    record_audit(
        db,
        request,
        principal,
        action="user.password_changed",
        resource_type="user",
        resource_id=principal.user.id,
    )
    await db.commit()
    await request.app.state.session_store.revoke_user(principal.user.id)
    return Message(message="Password changed. Sign in again with the new password.")
