from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select

from app.config import get_settings
from app.db import utcnow
from app.dependencies import DB, OwnerPrincipal, PaginationDep, paginate
from app.errors import APIError
from app.models import APIToken, User, UserRole
from app.schemas import (
    APITokenCreate,
    APITokenCreated,
    APITokenView,
    MemberCreate,
    MemberUpdate,
    Page,
    SessionRecord,
    UserView,
)
from app.security import digest_api_token, generate_api_token, hash_password
from app.services.audit import record_audit

router = APIRouter(prefix="/access", tags=["workspace access"])


async def _member(db: DB, workspace_id: UUID, user_id: UUID) -> User:
    user = await db.scalar(
        select(User).where(User.id == user_id, User.workspace_id == workspace_id)
    )
    if user is None:
        raise APIError(404, "MEMBER_NOT_FOUND", "The workspace member was not found.")
    return user


async def _ensure_another_owner(db: DB, workspace_id: UUID, user: User) -> None:
    if user.role != UserRole.WORKSPACE_OWNER:
        return
    owners = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.workspace_id == workspace_id,
                    User.role == UserRole.WORKSPACE_OWNER,
                    User.active.is_(True),
                )
            )
        )
        or 0
    )
    if owners <= 1:
        raise APIError(409, "LAST_OWNER", "A workspace must retain at least one active owner.")


@router.get("/members", response_model=Page[UserView])
async def list_members(
    db: DB, principal: OwnerPrincipal, pagination: PaginationDep
) -> Page[UserView]:
    users, total = await paginate(
        db,
        select(User).where(User.workspace_id == principal.workspace_id).order_by(User.created_at),
        pagination,
    )
    return Page(
        items=[UserView.model_validate(user) for user in users],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("/members", response_model=UserView, status_code=status.HTTP_201_CREATED)
async def create_member(
    payload: MemberCreate, request: Request, db: DB, principal: OwnerPrincipal
) -> UserView:
    if await db.scalar(select(User.id).where(User.email == payload.email)):
        raise APIError(409, "EMAIL_EXISTS", "A user with this email already exists.")
    user = User(
        workspace_id=principal.workspace_id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole(payload.role),
        active=True,
        must_change_password=True,
        password_changed_at=utcnow(),
    )
    db.add(user)
    await db.flush()
    record_audit(
        db,
        request,
        principal,
        action="member.created",
        resource_type="user",
        resource_id=user.id,
        details={"email": user.email, "role": user.role.value},
    )
    await db.commit()
    return UserView.model_validate(user)


@router.patch("/members/{user_id}", response_model=UserView)
async def update_member(
    user_id: UUID,
    payload: MemberUpdate,
    request: Request,
    db: DB,
    principal: OwnerPrincipal,
) -> UserView:
    user = await _member(db, principal.workspace_id, user_id)
    if user.id == principal.user.id and payload.active is False:
        raise APIError(409, "SELF_DEACTIVATION", "You cannot deactivate your own account.")
    demoting = payload.role is not None and payload.role != UserRole.WORKSPACE_OWNER.value
    deactivating = payload.active is False
    if demoting or deactivating:
        await _ensure_another_owner(db, principal.workspace_id, user)
    if payload.role is not None:
        user.role = UserRole(payload.role)
    if payload.active is not None:
        user.active = payload.active
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        user.password_changed_at = utcnow()
        user.must_change_password = True
    record_audit(
        db,
        request,
        principal,
        action="member.updated",
        resource_type="user",
        resource_id=user.id,
        details={"role": user.role.value, "active": user.active},
    )
    await db.commit()
    if payload.active is False or payload.password is not None:
        await request.app.state.session_store.revoke_user(user.id)
    return UserView.model_validate(user)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(user_id: UUID, request: Request, db: DB, principal: OwnerPrincipal) -> None:
    user = await _member(db, principal.workspace_id, user_id)
    if user.id == principal.user.id:
        raise APIError(409, "SELF_DELETION", "You cannot delete your own account.")
    await _ensure_another_owner(db, principal.workspace_id, user)
    await request.app.state.session_store.revoke_user(user.id)
    await db.delete(user)
    record_audit(
        db,
        request,
        principal,
        action="member.deleted",
        resource_type="user",
        resource_id=user.id,
        details={"email": user.email},
    )
    await db.commit()


@router.get("/tokens", response_model=Page[APITokenView])
async def list_tokens(
    db: DB, principal: OwnerPrincipal, pagination: PaginationDep
) -> Page[APITokenView]:
    tokens, total = await paginate(
        db,
        select(APIToken)
        .where(APIToken.workspace_id == principal.workspace_id)
        .order_by(APIToken.created_at.desc()),
        pagination,
    )
    return Page(
        items=[APITokenView.model_validate(token) for token in tokens],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("/tokens", response_model=APITokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    payload: APITokenCreate, request: Request, db: DB, principal: OwnerPrincipal
) -> APITokenCreated:
    if payload.expires_at is not None and payload.expires_at <= datetime.now(UTC):
        raise APIError(422, "TOKEN_EXPIRY_INVALID", "Token expiry must be in the future.")
    raw = generate_api_token()
    token = APIToken(
        workspace_id=principal.workspace_id,
        user_id=principal.user.id,
        name=payload.name.strip(),
        token_prefix=raw[:12],
        token_digest=digest_api_token(raw),
        scopes=sorted(set(payload.scopes)),
        expires_at=payload.expires_at,
    )
    db.add(token)
    await db.flush()
    record_audit(
        db,
        request,
        principal,
        action="api_token.created",
        resource_type="api_token",
        resource_id=token.id,
        details={"name": token.name, "scopes": token.scopes},
    )
    await db.commit()
    return APITokenCreated(**APITokenView.model_validate(token).model_dump(), token=raw)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: UUID, request: Request, db: DB, principal: OwnerPrincipal) -> None:
    token = await db.scalar(
        select(APIToken).where(
            APIToken.id == token_id, APIToken.workspace_id == principal.workspace_id
        )
    )
    if token is None:
        raise APIError(404, "TOKEN_NOT_FOUND", "The API token was not found.")
    token.revoked_at = utcnow()
    record_audit(
        db,
        request,
        principal,
        action="api_token.revoked",
        resource_type="api_token",
        resource_id=token.id,
    )
    await db.commit()


@router.get("/sessions", response_model=list[SessionRecord])
async def list_sessions(request: Request, principal: OwnerPrincipal) -> list[SessionRecord]:
    current_token = request.cookies.get(get_settings().session_cookie_name)
    current_id = hashlib.sha256(current_token.encode()).hexdigest() if current_token else None
    sessions = await request.app.state.session_store.list_user(principal.user.id)
    return [
        SessionRecord(
            id=session_id,
            created_at=datetime.fromisoformat(data.created_at),
            current=session_id == current_id,
        )
        for session_id, data in sessions
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: str, request: Request, principal: OwnerPrincipal) -> None:
    if not await request.app.state.session_store.revoke_session(principal.user.id, session_id):
        raise APIError(404, "SESSION_NOT_FOUND", "The session was not found.")
