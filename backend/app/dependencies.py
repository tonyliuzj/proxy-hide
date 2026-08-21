from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Query, Request
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.errors import APIError
from app.models import User, UserRole, Workspace, WorkspaceLimit, WorkspaceStatus
from app.sessions import SessionData

DB = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True, slots=True)
class Principal:
    user: User
    workspace: Workspace | None
    session: SessionData

    @property
    def workspace_id(self) -> UUID:
        if self.user.workspace_id is None:
            raise APIError(403, "WORKSPACE_REQUIRED", "This action requires a workspace.")
        return self.user.workspace_id


async def current_principal(request: Request, db: DB) -> Principal:
    settings: Settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise APIError(401, "AUTHENTICATION_REQUIRED", "Authentication is required.")
    session = await request.app.state.session_store.get(token)
    if session is None:
        raise APIError(401, "SESSION_EXPIRED", "The session is invalid or expired.")
    user = await db.get(User, session.user_id)
    if user is None or not user.active:
        await request.app.state.session_store.delete(token)
        raise APIError(401, "SESSION_REVOKED", "The session has been revoked.")
    changed_at = user.password_changed_at.isoformat() if user.password_changed_at else None
    if changed_at != session.password_changed_at:
        await request.app.state.session_store.delete(token)
        raise APIError(401, "SESSION_REVOKED", "The session has been revoked.")
    if user.role.value != session.role or user.workspace_id != session.workspace_id:
        await request.app.state.session_store.delete(token)
        raise APIError(401, "SESSION_REVOKED", "The session has been revoked.")
    workspace = None
    if user.workspace_id:
        workspace = await db.get(Workspace, user.workspace_id)
        if workspace is None or workspace.status != WorkspaceStatus.ACTIVE:
            await request.app.state.session_store.delete(token)
            raise APIError(403, "WORKSPACE_SUSPENDED", "The workspace is suspended.")
    return Principal(user=user, workspace=workspace, session=session)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


async def require_workspace(principal: CurrentPrincipal) -> Principal:
    if principal.user.role != UserRole.WORKSPACE_OWNER or principal.workspace is None:
        raise APIError(403, "WORKSPACE_ACCESS_REQUIRED", "Workspace owner access is required.")
    return principal


async def require_admin(principal: CurrentPrincipal) -> Principal:
    if principal.user.role != UserRole.PLATFORM_ADMIN:
        raise APIError(403, "ADMIN_ACCESS_REQUIRED", "Platform administrator access is required.")
    return principal


WorkspacePrincipal = Annotated[Principal, Depends(require_workspace)]
AdminPrincipal = Annotated[Principal, Depends(require_admin)]


@dataclass(frozen=True, slots=True)
class Pagination:
    page: int
    page_size: int
    offset: int


def pagination(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 50,
) -> Pagination:
    size = min(page_size, get_settings().max_page_size)
    return Pagination(page, size, (page - 1) * size)


PaginationDep = Annotated[Pagination, Depends(pagination)]


async def paginate(
    db: AsyncSession, statement: Select[Any], page: Pagination
) -> tuple[list[Any], int]:
    count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
    total = int((await db.scalar(count_statement)) or 0)
    items = list((await db.scalars(statement.offset(page.offset).limit(page.page_size))).all())
    return items, total


async def workspace_limits(db: AsyncSession, workspace_id: UUID) -> WorkspaceLimit:
    limits = await db.get(WorkspaceLimit, workspace_id)
    if limits is None:
        raise APIError(500, "WORKSPACE_LIMITS_MISSING", "Workspace limits are not configured.")
    return limits


async def enforce_quota(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    model: type[Any],
    limit_field: str,
    extra_clause: Any | None = None,
) -> None:
    limits = await workspace_limits(db, workspace_id)
    limit = int(getattr(limits, limit_field))
    statement = select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
    if extra_clause is not None:
        statement = statement.where(extra_clause)
    count = int((await db.scalar(statement)) or 0)
    if count >= limit:
        quota_name = limit_field.removeprefix("max_").replace("_", " ")
        raise APIError(
            409,
            "LIMIT_EXCEEDED",
            f"The workspace limit for {quota_name} has been reached.",
        )
