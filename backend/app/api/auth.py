from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.db import utcnow
from app.dependencies import DB, CurrentPrincipal
from app.errors import APIError
from app.models import AuditEvent, User, UserRole, Workspace, WorkspaceStatus
from app.schemas import (
    LoginRequest,
    Message,
    SessionView,
    SetupRequest,
    SetupStatus,
    UserView,
    WorkspaceSummary,
)
from app.security import generate_csrf_token, hash_password, password_needs_rehash, verify_password
from app.services.bootstrap import acquire_admin_bootstrap_lock
from app.sessions import SessionData

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_view(user: User, workspace: Workspace | None, csrf_token: str) -> SessionView:
    return SessionView(
        user=UserView.model_validate(user),
        workspace=WorkspaceSummary.model_validate(workspace) if workspace else None,
        csrf_token=csrf_token,
        must_change_password=user.must_change_password,
    )


def _set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


async def _start_session(
    request: Request,
    response: Response,
    user: User,
    workspace: Workspace | None,
) -> SessionView:
    csrf_token = generate_csrf_token()
    session = SessionData.create(
        user_id=user.id,
        role=user.role.value,
        workspace_id=user.workspace_id,
        csrf_token=csrf_token,
        password_changed_at=user.password_changed_at,
    )
    token = await request.app.state.session_store.create(session)
    _set_session_cookies(response, token, csrf_token)
    return _session_view(user, workspace, csrf_token)


@router.get("/setup/status", response_model=SetupStatus)
async def setup_status(response: Response, db: DB) -> SetupStatus:
    user_exists = (await db.scalar(select(User.id).limit(1))) is not None
    response.headers["Cache-Control"] = "no-store"
    return SetupStatus(setup_required=not user_exists)


@router.post(
    "/setup",
    response_model=SessionView,
    status_code=status.HTTP_201_CREATED,
)
async def setup(
    payload: SetupRequest,
    request: Request,
    response: Response,
    db: DB,
) -> SessionView:
    await acquire_admin_bootstrap_lock(db)
    if (await db.scalar(select(User.id).limit(1))) is not None:
        raise APIError(
            409,
            "SETUP_ALREADY_COMPLETED",
            "Initial setup has already been completed.",
            headers={"Cache-Control": "no-store"},
        )

    now = utcnow()
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        password_changed_at=now,
        last_login_at=now,
        role=UserRole.PLATFORM_ADMIN,
        active=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        AuditEvent(
            workspace_id=None,
            actor_user_id=user.id,
            action="platform_admin.bootstrapped",
            resource_type="user",
            resource_id=user.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:500] or None,
            details={"email": user.email},
        )
    )
    await db.commit()
    return await _start_session(request, response, user, None)


@router.post("/login", response_model=SessionView)
async def login(payload: LoginRequest, request: Request, response: Response, db: DB) -> SessionView:
    user = await db.scalar(select(User).where(User.email == payload.email))
    # Password verification is deliberately folded into the same response to prevent enumeration.
    if user is None or not user.active or not verify_password(user.password_hash, payload.password):
        raise APIError(401, "INVALID_CREDENTIALS", "The email or password is incorrect.")
    workspace = await db.get(Workspace, user.workspace_id) if user.workspace_id else None
    if workspace is not None and workspace.status != WorkspaceStatus.ACTIVE:
        raise APIError(403, "WORKSPACE_SUSPENDED", "The workspace is suspended.")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    user.last_login_at = utcnow()
    await db.commit()
    return await _start_session(request, response, user, workspace)


@router.get("/me", response_model=SessionView)
async def me(principal: CurrentPrincipal, response: Response) -> SessionView:
    response.headers["Cache-Control"] = "no-store"
    return _session_view(
        principal.user,
        principal.workspace,
        principal.session.csrf_token if principal.session else "",
    )


@router.post("/logout", response_model=Message)
async def logout(request: Request, response: Response, principal: CurrentPrincipal) -> Message:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await request.app.state.session_store.delete(token)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    response.headers["Cache-Control"] = "no-store"
    return Message(message="Signed out.")
