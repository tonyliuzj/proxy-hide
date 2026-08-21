from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.config import get_settings
from app.db import utcnow
from app.dependencies import DB, CurrentPrincipal
from app.errors import APIError
from app.models import User, Workspace, WorkspaceStatus
from app.schemas import LoginRequest, Message, SessionView, UserView, WorkspaceSummary
from app.security import generate_csrf_token, hash_password, password_needs_rehash, verify_password
from app.sessions import SessionData

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_view(user: User, workspace: Workspace | None, csrf_token: str) -> SessionView:
    return SessionView(
        user=UserView.model_validate(user),
        workspace=WorkspaceSummary.model_validate(workspace) if workspace else None,
        csrf_token=csrf_token,
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


@router.get("/me", response_model=SessionView)
async def me(principal: CurrentPrincipal, response: Response) -> SessionView:
    response.headers["Cache-Control"] = "no-store"
    return _session_view(principal.user, principal.workspace, principal.session.csrf_token)


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
