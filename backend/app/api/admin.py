from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.filters import _validated_rules
from app.api.inventory import _existing_identity_hashes, _import, _preview, _route_view
from app.config import get_settings
from app.db import utcnow
from app.dependencies import DB, AdminPrincipal, PaginationDep, enforce_quota, paginate
from app.domain.filters import catalog_scope_clause, compile_filter
from app.errors import APIError
from app.models import (
    CatalogSelection,
    Endpoint,
    Filter,
    JobType,
    Pool,
    PoolMember,
    ProxyHealth,
    ProxyRoute,
    ProxyScope,
    Target,
    TargetKind,
    User,
    UserRole,
    Workspace,
    WorkspaceLimit,
    WorkspaceStatus,
)
from app.schemas import (
    AdminWorkspaceConnectionGuideView,
    FilterPreviewRequest,
    FilterPreviewResult,
    JobView,
    Message,
    Page,
    PasswordReplace,
    PoolView,
    ProxyImportPreview,
    ProxyImportRequest,
    ProxyImportResult,
    ProxyView,
    UserView,
    WorkspaceAdminView,
    WorkspaceCreate,
    WorkspaceGlobalPoolCreate,
    WorkspaceLimitsView,
    WorkspaceUpdate,
)
from app.security import hash_password
from app.services.audit import record_audit
from app.services.jobs import create_operation, enqueue_job

router = APIRouter(prefix="/admin", tags=["platform admin"])


async def _admin_workspace(db: DB, workspace_id: UUID) -> Workspace:
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise APIError(404, "WORKSPACE_NOT_FOUND", "The workspace was not found.")
    return workspace


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
    brave = Target(
        workspace_id=workspace.id,
        name="Brave Search",
        kind=TargetKind.BRAVE,
        enabled=True,
        method="GET",
        url="https://search.brave.com/search?q=proxyhide-health-check",
    )
    startpage = Target(
        workspace_id=workspace.id,
        name="Startpage",
        kind=TargetKind.STARTPAGE,
        enabled=True,
        method="GET",
        url="https://www.startpage.com/sp/search?query=proxyhide-health-check",
    )
    duckduckgo = Target(
        workspace_id=workspace.id,
        name="DuckDuckGo",
        kind=TargetKind.DUCKDUCKGO,
        enabled=True,
        method="GET",
        url="https://duckduckgo.com/html/?q=proxyhide-health-check",
    )
    wikipedia = Target(
        workspace_id=workspace.id,
        name="Wikipedia Search",
        kind=TargetKind.WIKIPEDIA,
        enabled=True,
        method="GET",
        url="https://en.wikipedia.org/w/index.php?search=proxyhide-health-check",
    )
    db.add_all([limits, owner, google, bing, brave, startpage, duckduckgo, wikipedia])
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


@router.get(
    "/workspaces/{workspace_id}/connection-guide",
    response_model=AdminWorkspaceConnectionGuideView,
)
async def get_workspace_connection_guide(
    workspace_id: UUID, db: DB, principal: AdminPrincipal
) -> AdminWorkspaceConnectionGuideView:
    workspace = await _admin_workspace(db, workspace_id)
    endpoints = list(
        (
            await db.scalars(
                select(Endpoint)
                .where(Endpoint.workspace_id == workspace_id)
                .order_by(Endpoint.created_at.desc())
            )
        ).all()
    )
    settings = get_settings()
    return AdminWorkspaceConnectionGuideView(
        workspace_name=workspace.name,
        secure_host=settings.public_gateway_tls_host,
        secure_port=settings.public_gateway_tls_port,
        plaintext_host=settings.public_gateway_host,
        plaintext_port=settings.public_gateway_http_port,
        socks_host=settings.public_gateway_host,
        socks_port=settings.public_gateway_socks_port,
        endpoints=endpoints,
    )


@router.get("/workspaces/{workspace_id}/proxies", response_model=Page[ProxyView])
async def list_workspace_proxies(
    workspace_id: UUID, db: DB, principal: AdminPrincipal, pagination: PaginationDep
) -> Page[ProxyView]:
    if await db.get(Workspace, workspace_id) is None:
        raise APIError(404, "WORKSPACE_NOT_FOUND", "The workspace was not found.")
    routes, total = await paginate(
        db,
        select(ProxyRoute)
        .where(
            ProxyRoute.workspace_id == workspace_id,
            ProxyRoute.scope == ProxyScope.PRIVATE,
        )
        .options(selectinload(ProxyRoute.health))
        .order_by(ProxyRoute.created_at.desc()),
        pagination,
    )
    return Page(
        items=[_route_view(route) for route in routes],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post(
    "/workspaces/{workspace_id}/proxies/import/preview",
    response_model=ProxyImportPreview,
)
async def preview_workspace_proxy_import(
    workspace_id: UUID,
    payload: ProxyImportRequest,
    db: DB,
    principal: AdminPrincipal,
) -> ProxyImportPreview:
    if await db.get(Workspace, workspace_id) is None:
        raise APIError(404, "WORKSPACE_NOT_FOUND", "The workspace was not found.")
    existing = await _existing_identity_hashes(db, ProxyScope.PRIVATE, workspace_id)
    return _preview(payload, existing)[0]


@router.post(
    "/workspaces/{workspace_id}/proxies/import",
    response_model=ProxyImportResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_workspace_proxies(
    workspace_id: UUID,
    payload: ProxyImportRequest,
    request: Request,
    db: DB,
    principal: AdminPrincipal,
) -> ProxyImportResult:
    if await db.get(Workspace, workspace_id) is None:
        raise APIError(404, "WORKSPACE_NOT_FOUND", "The workspace was not found.")
    return await _import(
        payload=payload,
        request=request,
        db=db,
        principal=principal,
        scope=ProxyScope.PRIVATE,
        workspace_id=workspace_id,
    )


@router.delete(
    "/workspaces/{workspace_id}/proxies/{proxy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workspace_proxy(
    workspace_id: UUID,
    proxy_id: UUID,
    request: Request,
    db: DB,
    principal: AdminPrincipal,
) -> None:
    route = await db.scalar(
        select(ProxyRoute).where(
            ProxyRoute.id == proxy_id,
            ProxyRoute.workspace_id == workspace_id,
            ProxyRoute.scope == ProxyScope.PRIVATE,
        )
    )
    if route is None:
        raise APIError(404, "PROXY_NOT_FOUND", "The workspace proxy was not found.")
    await db.delete(route)
    record_audit(
        db,
        request,
        principal,
        action="workspace.proxy_deleted",
        resource_type="proxy_route",
        resource_id=proxy_id,
        workspace_id=workspace_id,
    )
    await db.commit()


@router.post(
    "/workspaces/{workspace_id}/proxies/{proxy_id}/check",
    response_model=JobView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def check_workspace_proxy(
    workspace_id: UUID,
    proxy_id: UUID,
    request: Request,
    db: DB,
    principal: AdminPrincipal,
) -> JobView:
    route = await db.scalar(
        select(ProxyRoute).where(
            ProxyRoute.id == proxy_id,
            ProxyRoute.workspace_id == workspace_id,
            ProxyRoute.scope == ProxyScope.PRIVATE,
            ProxyRoute.active.is_(True),
        )
    )
    if route is None:
        raise APIError(404, "PROXY_NOT_FOUND", "The workspace proxy was not found.")
    job = enqueue_job(
        db,
        job_type=JobType.CHECK_PROXY,
        workspace_id=workspace_id,
        entity_id=route.id,
        payload={"reason": "manual"},
    )
    record_audit(
        db,
        request,
        principal,
        action="workspace.proxy_check_requested",
        resource_type="proxy_route",
        resource_id=proxy_id,
        workspace_id=workspace_id,
    )
    await db.commit()
    return JobView.model_validate(job)


@router.get("/workspaces/{workspace_id}/global-pools", response_model=Page[PoolView])
async def list_workspace_global_pools(
    workspace_id: UUID, db: DB, principal: AdminPrincipal, pagination: PaginationDep
) -> Page[PoolView]:
    await _admin_workspace(db, workspace_id)
    pools, total = await paginate(
        db,
        select(Pool)
        .where(
            Pool.workspace_id == workspace_id,
            Pool.catalog_selection == CatalogSelection.GLOBAL,
        )
        .order_by(Pool.created_at.desc()),
        pagination,
    )
    return Page(
        items=[PoolView.model_validate(pool) for pool in pools],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post(
    "/workspaces/{workspace_id}/global-pools/preview",
    response_model=FilterPreviewResult,
)
async def preview_workspace_global_pool(
    workspace_id: UUID,
    payload: FilterPreviewRequest,
    db: DB,
    principal: AdminPrincipal,
) -> FilterPreviewResult:
    await _admin_workspace(db, workspace_id)
    limits = await db.get(WorkspaceLimit, workspace_id)
    if limits is None or not limits.global_catalog_enabled:
        raise APIError(403, "GLOBAL_CATALOG_DISABLED", "Global catalog access is disabled.")
    _, rules = await _validated_rules(db, workspace_id, payload.rules)
    base = (
        select(ProxyRoute)
        .outerjoin(ProxyHealth)
        .where(
            ProxyRoute.active.is_(True),
            catalog_scope_clause("global", workspace_id),
            compile_filter(rules, workspace_id),
        )
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


@router.post(
    "/workspaces/{workspace_id}/global-pools",
    response_model=PoolView,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_global_pool(
    workspace_id: UUID,
    payload: WorkspaceGlobalPoolCreate,
    request: Request,
    db: DB,
    principal: AdminPrincipal,
) -> PoolView:
    await _admin_workspace(db, workspace_id)
    limits = await db.get(WorkspaceLimit, workspace_id)
    if limits is None or not limits.global_catalog_enabled:
        raise APIError(403, "GLOBAL_CATALOG_DISABLED", "Global catalog access is disabled.")
    await enforce_quota(db, workspace_id=workspace_id, model=Filter, limit_field="max_filters")
    await enforce_quota(db, workspace_id=workspace_id, model=Pool, limit_field="max_pools")
    version, rules = await _validated_rules(db, workspace_id, payload.rules)
    filter_row = Filter(
        workspace_id=workspace_id,
        name=f"{payload.name.strip()} global filter",
        version=version,
        rules=rules,
    )
    db.add(filter_row)
    await db.flush()
    pool = Pool(
        workspace_id=workspace_id,
        filter_id=filter_row.id,
        name=payload.name.strip(),
        catalog_selection=CatalogSelection.GLOBAL,
        strategy=payload.strategy,
        enabled=True,
    )
    db.add(pool)
    await db.flush()
    operation = create_operation(
        db, workspace_id=workspace_id, kind="pool_materialize", progress_total=1
    )
    enqueue_job(
        db,
        job_type=JobType.MATERIALIZE_POOL,
        workspace_id=workspace_id,
        entity_id=pool.id,
        operation=operation,
        payload={"reason": "manual", "trigger": "admin_global_pool_created"},
    )
    record_audit(
        db,
        request,
        principal,
        action="workspace.global_pool_created",
        resource_type="pool",
        resource_id=pool.id,
        workspace_id=workspace_id,
    )
    await db.commit()
    return PoolView.model_validate(pool)


@router.get(
    "/workspaces/{workspace_id}/global-pools/{pool_id}/proxies",
    response_model=Page[ProxyView],
)
async def list_workspace_global_pool_proxies(
    workspace_id: UUID,
    pool_id: UUID,
    db: DB,
    principal: AdminPrincipal,
    pagination: PaginationDep,
) -> Page[ProxyView]:
    pool = await db.scalar(
        select(Pool).where(
            Pool.id == pool_id,
            Pool.workspace_id == workspace_id,
            Pool.catalog_selection == CatalogSelection.GLOBAL,
        )
    )
    if pool is None:
        raise APIError(404, "POOL_NOT_FOUND", "The global catalog pool was not found.")
    if pool.current_revision is None:
        return Page(items=[], total=0, page=pagination.page, page_size=pagination.page_size)
    routes, total = await paginate(
        db,
        select(ProxyRoute)
        .join(
            PoolMember,
            (PoolMember.proxy_id == ProxyRoute.id)
            & (PoolMember.pool_id == pool.id)
            & (PoolMember.revision == pool.current_revision),
        )
        .options(selectinload(ProxyRoute.health))
        .order_by(PoolMember.ordinal),
        pagination,
    )
    return Page(
        items=[_route_view(route) for route in routes],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.delete(
    "/workspaces/{workspace_id}/global-pools/{pool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workspace_global_pool(
    workspace_id: UUID,
    pool_id: UUID,
    request: Request,
    db: DB,
    principal: AdminPrincipal,
) -> None:
    pool = await db.scalar(
        select(Pool).where(
            Pool.id == pool_id,
            Pool.workspace_id == workspace_id,
            Pool.catalog_selection == CatalogSelection.GLOBAL,
        )
    )
    if pool is None:
        raise APIError(404, "POOL_NOT_FOUND", "The global catalog pool was not found.")
    endpoint = await db.scalar(select(Endpoint.id).where(Endpoint.pool_id == pool.id))
    if endpoint is not None:
        raise APIError(409, "POOL_IN_USE", "Delete the pool's endpoints before deleting the pool.")
    filter_row = await db.get(Filter, pool.filter_id)
    await db.delete(pool)
    await db.flush()
    if filter_row is not None:
        await db.delete(filter_row)
    record_audit(
        db,
        request,
        principal,
        action="workspace.global_pool_deleted",
        resource_type="pool",
        resource_id=pool_id,
        workspace_id=workspace_id,
    )
    enqueue_job(
        db,
        job_type=JobType.PUBLISH_SNAPSHOT,
        workspace_id=workspace_id,
        payload={"reason": "admin_global_pool_deleted"},
    )
    await db.commit()


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
