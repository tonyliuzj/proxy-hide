from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Query, Request
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.errors import APIError
from app.models import APIToken, User, UserRole, Workspace, WorkspaceLimit, WorkspaceStatus
from app.security import digest_api_token
from app.sessions import SessionData

DB = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True, slots=True)
class Principal:
    user: User
    workspace: Workspace | None
    session: SessionData | None
    token_scopes: frozenset[str] = frozenset()

    @property
    def via_api_token(self) -> bool:
        return self.session is None

    @property
    def workspace_id(self) -> UUID:
        if self.user.workspace_id is None:
            raise APIError(403, "WORKSPACE_REQUIRED", "This action requires a workspace.")
        return self.user.workspace_id


async def current_principal(request: Request, db: DB) -> Principal:
    settings: Settings = get_settings()
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        raw_token = authorization[7:].strip()
        api_token = await db.scalar(
            select(APIToken).where(
                APIToken.token_digest == digest_api_token(raw_token),
                APIToken.revoked_at.is_(None),
            )
        )
        now = datetime.now(UTC)
        if api_token is None or (api_token.expires_at is not None and api_token.expires_at <= now):
            raise APIError(401, "INVALID_API_TOKEN", "The API token is invalid or expired.")
        user = await db.get(User, api_token.user_id)
        workspace = await db.get(Workspace, api_token.workspace_id)
        if user is None or not user.active or workspace is None:
            raise APIError(401, "API_TOKEN_REVOKED", "The API token is no longer active.")
        if workspace.status != WorkspaceStatus.ACTIVE:
            raise APIError(403, "WORKSPACE_SUSPENDED", "The workspace is suspended.")
        api_token.last_used_at = now
        api_token.last_used_ip = request.client.host if request.client else None
        await db.commit()
        return Principal(
            user=user,
            workspace=workspace,
            session=None,
            token_scopes=frozenset(api_token.scopes),
        )
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


async def require_workspace(request: Request, principal: CurrentPrincipal) -> Principal:
    if (
        principal.user.role
        not in {
            UserRole.WORKSPACE_OWNER,
            UserRole.WORKSPACE_OPERATOR,
            UserRole.WORKSPACE_VIEWER,
        }
        or principal.workspace is None
    ):
        raise APIError(403, "WORKSPACE_ACCESS_REQUIRED", "Workspace owner access is required.")
    safe = request.method in {"GET", "HEAD", "OPTIONS"}
    password_route = request.url.path.endswith("/change-password") or (
        request.url.path.endswith("/settings") and safe
    )
    if principal.user.must_change_password and not password_route:
        raise APIError(403, "PASSWORD_CHANGE_REQUIRED", "Change the initial password to continue.")
    if principal.user.role == UserRole.WORKSPACE_VIEWER and not safe:
        raise APIError(403, "READ_ONLY_ROLE", "The viewer role cannot modify workspace resources.")
    if principal.via_api_token:
        required = "read" if safe else "write"
        if required not in principal.token_scopes and "admin" not in principal.token_scopes:
            raise APIError(
                403, "TOKEN_SCOPE_REQUIRED", f"The API token requires the {required} scope."
            )
    return principal


async def require_owner(request: Request, principal: CurrentPrincipal) -> Principal:
    if principal.user.role != UserRole.WORKSPACE_OWNER or principal.workspace is None:
        raise APIError(403, "OWNER_ACCESS_REQUIRED", "Workspace owner access is required.")
    if principal.user.must_change_password and not request.url.path.endswith("/change-password"):
        raise APIError(403, "PASSWORD_CHANGE_REQUIRED", "Change the initial password to continue.")
    if principal.via_api_token and "admin" not in principal.token_scopes:
        raise APIError(403, "TOKEN_SCOPE_REQUIRED", "The API token requires the admin scope.")
    return principal


async def require_admin(principal: CurrentPrincipal) -> Principal:
    if principal.user.role != UserRole.PLATFORM_ADMIN:
        raise APIError(403, "ADMIN_ACCESS_REQUIRED", "Platform administrator access is required.")
    return principal


WorkspacePrincipal = Annotated[Principal, Depends(require_workspace)]
OwnerPrincipal = Annotated[Principal, Depends(require_owner)]
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
