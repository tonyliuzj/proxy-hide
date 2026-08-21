from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.db import utcnow
from app.dependencies import DB, AdminPrincipal, PaginationDep, paginate
from app.errors import APIError
from app.models import (
    JobType,
    Target,
    TargetKind,
    User,
    UserRole,
    Workspace,
    WorkspaceLimit,
    WorkspaceStatus,
)
from app.schemas import (
    Message,
    Page,
    PasswordReplace,
    UserView,
    WorkspaceAdminView,
    WorkspaceCreate,
    WorkspaceLimitsView,
    WorkspaceUpdate,
)
from app.security import hash_password
from app.services.audit import record_audit
from app.services.jobs import enqueue_job

router = APIRouter(prefix="/admin", tags=["platform admin"])


async def _workspace_view(db: DB, workspace: Workspace) -> WorkspaceAdminView:
    owner = await db.scalar(
        select(User).where(
            User.workspace_id == workspace.id,
            User.role == UserRole.WORKSPACE_OWNER,
        )
    )
    limits = await db.get(WorkspaceLimit, workspace.id)
    if owner is None or limits is None:
        raise APIError(500, "WORKSPACE_INCOMPLETE", "The workspace record is incomplete.")
    return WorkspaceAdminView(
        **{
            "id": workspace.id,
            "name": workspace.name,
            "slug": workspace.slug,
            "status": workspace.status,
            "created_at": workspace.created_at,
        },
        owner=UserView.model_validate(owner),
        limits=WorkspaceLimitsView.model_validate(limits),
    )


@router.get("/workspaces", response_model=Page[WorkspaceAdminView])
async def list_workspaces(
    db: DB, principal: AdminPrincipal, pagination: PaginationDep
) -> Page[WorkspaceAdminView]:
    workspaces, total = await paginate(
        db, select(Workspace).order_by(Workspace.created_at.desc()), pagination
    )
    return Page(
        items=[await _workspace_view(db, workspace) for workspace in workspaces],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("/workspaces", response_model=WorkspaceAdminView, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate, request: Request, db: DB, principal: AdminPrincipal
) -> WorkspaceAdminView:
    workspace = Workspace(
        name=payload.name.strip(), slug=payload.slug, status=WorkspaceStatus.ACTIVE
    )
    db.add(workspace)
    await db.flush()
    limits = WorkspaceLimit(workspace=workspace, **payload.limits.model_dump())
    owner = User(
        workspace_id=workspace.id,
        email=payload.owner_email,
        password_hash=hash_password(payload.owner_password),
        role=UserRole.WORKSPACE_OWNER,
        active=True,
        password_changed_at=utcnow(),
    )
    google = Target(
        workspace_id=workspace.id,
        name="Google",
        kind=TargetKind.GOOGLE,
        enabled=True,
        method="GET",
        url="https://www.google.com/search?q=proxyhide-health-check",
    )
    bing = Target(
        workspace_id=workspace.id,
        name="Bing",
        kind=TargetKind.BING,
        enabled=True,
        method="GET",
        url="https://www.bing.com/search?q=proxyhide-health-check",
    )
    db.add_all([limits, owner, google, bing])
    await db.flush()
    record_audit(
        db,
        request,
        principal,
        action="workspace.created",
        resource_type="workspace",
        resource_id=workspace.id,
        workspace_id=workspace.id,
        details={"owner_email": owner.email, "slug": workspace.slug},
    )
    await db.commit()
    return await _workspace_view(db, workspace)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceAdminView)
async def get_workspace(
    workspace_id: UUID, db: DB, principal: AdminPrincipal
) -> WorkspaceAdminView:
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise APIError(404, "WORKSPACE_NOT_FOUND", "The workspace was not found.")
    return await _workspace_view(db, workspace)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceAdminView)
async def update_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    request: Request,
    db: DB,
    principal: AdminPrincipal,
) -> WorkspaceAdminView:
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise APIError(404, "WORKSPACE_NOT_FOUND", "The workspace was not found.")
    previous_status = workspace.status
    if payload.name is not None:
        workspace.name = payload.name.strip()
    if payload.status is not None:
        workspace.status = payload.status
        workspace.suspended_at = utcnow() if payload.status == WorkspaceStatus.SUSPENDED else None
    if payload.limits is not None:
        limits = await db.get(WorkspaceLimit, workspace.id)
        if limits is None:
            raise APIError(500, "WORKSPACE_LIMITS_MISSING", "Workspace limits are missing.")
        for field, value in payload.limits.model_dump().items():
            setattr(limits, field, value)
    record_audit(
        db,
        request,
        principal,
        action="workspace.updated",
        resource_type="workspace",
        resource_id=workspace.id,
        workspace_id=workspace.id,
        details={"status": workspace.status.value},
    )
    enqueue_job(
        db,
        job_type=JobType.PUBLISH_SNAPSHOT,
        workspace_id=workspace.id,
        payload={"reason": "workspace_updated"},
    )
    await db.commit()
    if previous_status != workspace.status and workspace.status == WorkspaceStatus.SUSPENDED:
        await request.app.state.session_store.revoke_workspace(workspace.id)
    return await _workspace_view(db, workspace)


@router.post("/workspaces/{workspace_id}/replace-password", response_model=Message)
async def replace_owner_password(
    workspace_id: UUID,
    payload: PasswordReplace,
    request: Request,
    db: DB,
    principal: AdminPrincipal,
) -> Message:
    owner = await db.scalar(
        select(User).where(
            User.workspace_id == workspace_id,
            User.role == UserRole.WORKSPACE_OWNER,
        )
    )
    if owner is None:
        raise APIError(404, "WORKSPACE_OWNER_NOT_FOUND", "The workspace owner was not found.")
    owner.password_hash = hash_password(payload.password)
    owner.password_changed_at = utcnow()
    record_audit(
        db,
        request,
        principal,
        action="workspace.owner_password_replaced",
        resource_type="user",
        resource_id=owner.id,
        workspace_id=workspace_id,
    )
    await db.commit()
    await request.app.state.session_store.revoke_user(owner.id)
    return Message(message="The owner password was replaced and active sessions were revoked.")
