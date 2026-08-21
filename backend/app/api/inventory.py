from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Request, UploadFile, status
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.dependencies import (
    DB,
    AdminPrincipal,
    PaginationDep,
    WorkspacePrincipal,
    paginate,
    workspace_limits,
)
from app.domain.filters import catalog_scope_clause
from app.domain.proxies import ParsedProxy, parse_proxy_text
from app.errors import APIError
from app.models import (
    HealthStatus,
    JobType,
    OperationStatus,
    ProxyHealth,
    ProxyProtocol,
    ProxyRoute,
    ProxyScope,
)
from app.schemas import (
    JobView,
    Page,
    ProxyImportPreview,
    ProxyImportRequest,
    ProxyImportResult,
    ProxyInvalidRow,
    ProxyPreviewRow,
    ProxyView,
)
from app.security import KeyRing, digest_proxy_identity
from app.services.audit import record_audit
from app.services.jobs import create_operation, enqueue_job

router = APIRouter(prefix="/proxies", tags=["proxies"])
admin_router = APIRouter(prefix="/admin/proxies", tags=["platform admin proxies"])
_MAX_UPLOAD_BYTES = 20_000_000


def _route_view(route: ProxyRoute) -> ProxyView:
    health = route.health
    private = route.scope == ProxyScope.PRIVATE
    return ProxyView(
        id=route.id,
        scope=route.scope.value,
        protocol=route.protocol,
        host=route.host if private else None,
        port=route.port if private else None,
        credentials="***:***" if private and route.username_encrypted is not None else None,
        country_code=route.country_code,
        asn=route.asn,
        active=route.active,
        health=health.status if health else HealthStatus.UNKNOWN,
        score=health.score if health else 0,
        latency_ms=health.latency_ewma_ms if health else None,
        success_rate=round((health.success_ewma if health else 0) * 100, 2),
    )


async def _existing_identity_hashes(
    db: DB, scope: ProxyScope, workspace_id: UUID | None
) -> set[str]:
    clause = ProxyRoute.scope == scope
    clause = and_(clause, ProxyRoute.workspace_id == workspace_id)
    return set((await db.scalars(select(ProxyRoute.identity_hash).where(clause))).all())


def _preview(
    payload: ProxyImportRequest, existing: set[str]
) -> tuple[ProxyImportPreview, tuple[ParsedProxy, ...]]:
    parsed = parse_proxy_text(payload.text, payload.default_protocol)
    valid: list[ParsedProxy] = []
    duplicates = list(parsed.duplicate_lines)
    rows: list[ProxyPreviewRow] = []
    for index, proxy in enumerate(parsed.valid, start=1):
        stored_hash = digest_proxy_identity(proxy.identity_hash)
        if stored_hash in existing:
            duplicates.append(index)
            continue
        valid.append(proxy)
        rows.append(
            ProxyPreviewRow(
                protocol=proxy.protocol,
                host=proxy.host,
                port=proxy.port,
                username="***" if proxy.username is not None else None,
                identity_hash=stored_hash,
            )
        )
    preview = ProxyImportPreview(
        valid=rows,
        invalid=[
            ProxyInvalidRow(line=item.line, value=item.value, error=item.error)
            for item in parsed.invalid
        ],
        duplicate_lines=duplicates,
        valid_count=len(rows),
        invalid_count=len(parsed.invalid),
        duplicate_count=len(duplicates),
    )
    return preview, tuple(valid)


async def _read_upload(upload: UploadFile) -> str:
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(64 * 1024):
        size += len(chunk)
        if size > _MAX_UPLOAD_BYTES:
            raise APIError(413, "IMPORT_TOO_LARGE", "Proxy files are limited to 20 MB.")
        chunks.append(chunk)
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise APIError(
            422, "IMPORT_ENCODING_INVALID", "Proxy files must be UTF-8 encoded."
        ) from exc


async def _import(
    *,
    payload: ProxyImportRequest,
    request: Request,
    db: DB,
    principal: WorkspacePrincipal | AdminPrincipal,
    scope: ProxyScope,
    workspace_id: UUID | None,
) -> ProxyImportResult:
    existing = await _existing_identity_hashes(db, scope, workspace_id)
    preview, proxies = _preview(payload, existing)
    if scope == ProxyScope.PRIVATE:
        limits = await workspace_limits(db, workspace_id)  # type: ignore[arg-type]
        current = len(existing)
        if current + len(proxies) > limits.max_private_proxies:
            raise APIError(409, "LIMIT_EXCEEDED", "The private proxy limit would be exceeded.")
    operation = create_operation(
        db, workspace_id=workspace_id, kind="proxy_import_and_initial_check"
    )
    await db.flush()
    keyring = KeyRing.from_settings()
    for proxy in proxies:
        route_id = uuid4()
        aad = f"proxy-route:{route_id}".encode()
        route = ProxyRoute(
            id=route_id,
            workspace_id=workspace_id,
            scope=scope,
            protocol=proxy.protocol,
            host=proxy.host,
            port=proxy.port,
            username_encrypted=(
                keyring.encrypt_text(proxy.username, associated_data=aad)
                if proxy.username
                else None
            ),
            password_encrypted=(
                keyring.encrypt_text(proxy.password, associated_data=aad)
                if proxy.password
                else None
            ),
            identity_hash=digest_proxy_identity(proxy.identity_hash),
            active=True,
        )
        db.add(route)
        db.add(ProxyHealth(proxy_id=route.id))
        enqueue_job(
            db,
            job_type=JobType.CHECK_PROXY,
            workspace_id=workspace_id,
            entity_id=route.id,
            operation=operation,
            payload={"reason": "initial_import"},
        )
    operation.progress_total = len(proxies)
    operation.status = OperationStatus.SUCCEEDED if not proxies else OperationStatus.PENDING
    record_audit(
        db,
        request,
        principal,
        action="proxy.imported",
        resource_type="proxy_route",
        workspace_id=workspace_id,
        details={
            "scope": scope.value,
            "imported": len(proxies),
            "duplicates": preview.duplicate_count,
            "invalid": preview.invalid_count,
        },
    )
    await db.commit()
    return ProxyImportResult(
        imported=len(proxies),
        duplicates=preview.duplicate_count,
        invalid=preview.invalid_count,
        operation_id=operation.id,
    )


@router.post("/import/preview", response_model=ProxyImportPreview)
async def preview_private_import(
    payload: ProxyImportRequest, db: DB, principal: WorkspacePrincipal
) -> ProxyImportPreview:
    existing = await _existing_identity_hashes(db, ProxyScope.PRIVATE, principal.workspace_id)
    return _preview(payload, existing)[0]


@router.post("/import/file/preview", response_model=ProxyImportPreview)
async def preview_private_file_import(
    db: DB,
    principal: WorkspacePrincipal,
    file: UploadFile = File(...),
    default_protocol: ProxyProtocol = Form(ProxyProtocol.HTTP),
) -> ProxyImportPreview:
    payload = ProxyImportRequest(text=await _read_upload(file), default_protocol=default_protocol)
    existing = await _existing_identity_hashes(db, ProxyScope.PRIVATE, principal.workspace_id)
    return _preview(payload, existing)[0]


@router.post("/import", response_model=ProxyImportResult, status_code=status.HTTP_202_ACCEPTED)
async def import_private_proxies(
    payload: ProxyImportRequest, request: Request, db: DB, principal: WorkspacePrincipal
) -> ProxyImportResult:
    return await _import(
        payload=payload,
        request=request,
        db=db,
        principal=principal,
        scope=ProxyScope.PRIVATE,
        workspace_id=principal.workspace_id,
    )


@router.post("/import/file", response_model=ProxyImportResult, status_code=status.HTTP_202_ACCEPTED)
async def import_private_proxy_file(
    request: Request,
    db: DB,
    principal: WorkspacePrincipal,
    file: UploadFile = File(...),
    default_protocol: ProxyProtocol = Form(ProxyProtocol.HTTP),
) -> ProxyImportResult:
    payload = ProxyImportRequest(text=await _read_upload(file), default_protocol=default_protocol)
    return await _import(
        payload=payload,
        request=request,
        db=db,
        principal=principal,
        scope=ProxyScope.PRIVATE,
        workspace_id=principal.workspace_id,
    )


@router.get("", response_model=Page[ProxyView])
async def list_proxies(
    db: DB,
    principal: WorkspacePrincipal,
    pagination: PaginationDep,
    scope: ProxyScope | None = None,
    protocol: ProxyProtocol | None = None,
    health: HealthStatus | None = None,
    country: str | None = Query(default=None, min_length=2, max_length=2),
) -> Page[ProxyView]:
    limits = await workspace_limits(db, principal.workspace_id)
    visibility = ProxyRoute.workspace_id == principal.workspace_id
    if limits.global_catalog_enabled:
        visibility = catalog_scope_clause("combined", principal.workspace_id)
    statement = (
        select(ProxyRoute)
        .where(visibility, ProxyRoute.active.is_(True))
        .outerjoin(ProxyHealth)
        .options(selectinload(ProxyRoute.health))
        .order_by(ProxyRoute.created_at.desc())
    )
    if scope:
        statement = statement.where(ProxyRoute.scope == scope)
    if protocol:
        statement = statement.where(ProxyRoute.protocol == protocol)
    if health:
        statement = statement.where(ProxyHealth.status == health)
    if country:
        statement = statement.where(ProxyRoute.country_code == country.upper())
    routes, total = await paginate(db, statement, pagination)
    return Page(
        items=[_route_view(route) for route in routes],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{proxy_id}", response_model=ProxyView)
async def get_proxy(proxy_id: UUID, db: DB, principal: WorkspacePrincipal) -> ProxyView:
    limits = await workspace_limits(db, principal.workspace_id)
    visibility = ProxyRoute.workspace_id == principal.workspace_id
    if limits.global_catalog_enabled:
        visibility = catalog_scope_clause("combined", principal.workspace_id)
    route = await db.scalar(
        select(ProxyRoute)
        .where(ProxyRoute.id == proxy_id, visibility)
        .options(selectinload(ProxyRoute.health))
    )
    if route is None:
        raise APIError(404, "PROXY_NOT_FOUND", "The proxy was not found.")
    return _route_view(route)


@router.post("/{proxy_id}/check", response_model=JobView, status_code=status.HTTP_202_ACCEPTED)
async def check_proxy(
    proxy_id: UUID, request: Request, db: DB, principal: WorkspacePrincipal
) -> JobView:
    limits = await workspace_limits(db, principal.workspace_id)
    visibility = ProxyRoute.workspace_id == principal.workspace_id
    if limits.global_catalog_enabled:
        visibility = catalog_scope_clause("combined", principal.workspace_id)
    route = await db.scalar(
        select(ProxyRoute).where(
            ProxyRoute.id == proxy_id,
            ProxyRoute.active.is_(True),
            visibility,
        )
    )
    if route is None:
        raise APIError(404, "PROXY_NOT_FOUND", "The proxy was not found.")
    job = enqueue_job(
        db,
        job_type=JobType.CHECK_PROXY,
        workspace_id=principal.workspace_id,
        entity_id=route.id,
        payload={"reason": "manual"},
    )
    record_audit(
        db,
        request,
        principal,
        action="proxy.check_requested",
        resource_type="proxy_route",
        resource_id=route.id,
    )
    await db.commit()
    return JobView.model_validate(job)


@router.delete("/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_private_proxy(
    proxy_id: UUID, request: Request, db: DB, principal: WorkspacePrincipal
) -> None:
    route = await db.scalar(
        select(ProxyRoute).where(
            ProxyRoute.id == proxy_id,
            ProxyRoute.workspace_id == principal.workspace_id,
            ProxyRoute.scope == ProxyScope.PRIVATE,
        )
    )
    if route is None:
        raise APIError(404, "PROXY_NOT_FOUND", "The private proxy was not found.")
    await db.delete(route)
    record_audit(
        db,
        request,
        principal,
        action="proxy.deleted",
        resource_type="proxy_route",
        resource_id=proxy_id,
    )
    await db.commit()


@admin_router.post("/import/preview", response_model=ProxyImportPreview)
async def preview_global_import(
    payload: ProxyImportRequest, db: DB, principal: AdminPrincipal
) -> ProxyImportPreview:
    existing = await _existing_identity_hashes(db, ProxyScope.GLOBAL, None)
    return _preview(payload, existing)[0]


@admin_router.post("/import/file/preview", response_model=ProxyImportPreview)
async def preview_global_file_import(
    db: DB,
    principal: AdminPrincipal,
    file: UploadFile = File(...),
    default_protocol: ProxyProtocol = Form(ProxyProtocol.HTTP),
) -> ProxyImportPreview:
    payload = ProxyImportRequest(text=await _read_upload(file), default_protocol=default_protocol)
    existing = await _existing_identity_hashes(db, ProxyScope.GLOBAL, None)
    return _preview(payload, existing)[0]


@admin_router.post(
    "/import", response_model=ProxyImportResult, status_code=status.HTTP_202_ACCEPTED
)
async def import_global_proxies(
    payload: ProxyImportRequest, request: Request, db: DB, principal: AdminPrincipal
) -> ProxyImportResult:
    return await _import(
        payload=payload,
        request=request,
        db=db,
        principal=principal,
        scope=ProxyScope.GLOBAL,
        workspace_id=None,
    )


@admin_router.post(
    "/import/file", response_model=ProxyImportResult, status_code=status.HTTP_202_ACCEPTED
)
async def import_global_proxy_file(
    request: Request,
    db: DB,
    principal: AdminPrincipal,
    file: UploadFile = File(...),
    default_protocol: ProxyProtocol = Form(ProxyProtocol.HTTP),
) -> ProxyImportResult:
    payload = ProxyImportRequest(text=await _read_upload(file), default_protocol=default_protocol)
    return await _import(
        payload=payload,
        request=request,
        db=db,
        principal=principal,
        scope=ProxyScope.GLOBAL,
        workspace_id=None,
    )


@admin_router.get("", response_model=Page[ProxyView])
async def list_global_proxies(
    db: DB, principal: AdminPrincipal, pagination: PaginationDep
) -> Page[ProxyView]:
    statement = (
        select(ProxyRoute)
        .where(ProxyRoute.scope == ProxyScope.GLOBAL)
        .options(selectinload(ProxyRoute.health))
        .order_by(ProxyRoute.created_at.desc())
    )
    routes, total = await paginate(db, statement, pagination)
    # Admins can inspect addresses while credentials remain redacted.
    items = []
    for route in routes:
        view = _route_view(route).model_copy(
            update={
                "host": route.host,
                "port": route.port,
                "credentials": "***:***" if route.username_encrypted else None,
            }
        )
        items.append(view)
    return Page(items=items, total=total, page=pagination.page, page_size=pagination.page_size)
