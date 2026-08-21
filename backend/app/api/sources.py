from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.dependencies import (
    DB,
    AdminPrincipal,
    PaginationDep,
    WorkspacePrincipal,
    enforce_quota,
    paginate,
)
from app.domain.network import DestinationPolicyError, validate_public_http_url
from app.errors import APIError
from app.models import JobType, ProxyScope, Source
from app.schemas import Page, SourceCreate, SourceRunAccepted, SourceUpdate, SourceView
from app.security import KeyRing
from app.services.audit import record_audit
from app.services.jobs import create_operation, enqueue_job

router = APIRouter(prefix="/sources", tags=["sources"])
admin_router = APIRouter(prefix="/admin/sources", tags=["platform admin sources"])


def _view(source: Source) -> SourceView:
    return SourceView(
        id=source.id,
        name=source.name,
        url=source.url,
        default_protocol=source.default_protocol,
        enabled=source.enabled,
        refresh_interval_minutes=source.refresh_interval_minutes,
        has_credentials=source.username_encrypted is not None,
        last_run_at=source.last_run_at,
        last_run_status=source.last_run_status,
        created_at=source.created_at,
    )


async def _validate_url(url: str) -> None:
    try:
        await validate_public_http_url(url)
    except DestinationPolicyError as exc:
        raise APIError(
            422,
            "SOURCE_URL_REJECTED",
            str(exc),
            field_errors=[{"field": "url", "message": str(exc)}],
        ) from exc


@router.get("", response_model=Page[SourceView])
async def list_sources(
    db: DB, principal: WorkspacePrincipal, pagination: PaginationDep
) -> Page[SourceView]:
    sources, total = await paginate(
        db,
        select(Source)
        .where(Source.workspace_id == principal.workspace_id, Source.scope == ProxyScope.PRIVATE)
        .order_by(Source.created_at.desc()),
        pagination,
    )
    return Page(
        items=[_view(source) for source in sources],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("", response_model=SourceView, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreate, request: Request, db: DB, principal: WorkspacePrincipal
) -> SourceView:
    await enforce_quota(
        db,
        workspace_id=principal.workspace_id,
        model=Source,
        limit_field="max_sources",
    )
    url = str(payload.url)
    await _validate_url(url)
    source_id = uuid4()
    aad = f"source:{source_id}".encode()
    keyring = KeyRing.from_settings()
    source = Source(
        id=source_id,
        workspace_id=principal.workspace_id,
        scope=ProxyScope.PRIVATE,
        name=payload.name.strip(),
        url=url,
        username_encrypted=(
            keyring.encrypt_text(payload.username, associated_data=aad)
            if payload.username
            else None
        ),
        password_encrypted=(
            keyring.encrypt_text(payload.password, associated_data=aad)
            if payload.password
            else None
        ),
        default_protocol=payload.default_protocol,
        enabled=payload.enabled,
        refresh_interval_minutes=payload.refresh_interval_minutes,
    )
    db.add(source)
    record_audit(
        db,
        request,
        principal,
        action="source.created",
        resource_type="source",
        resource_id=source.id,
    )
    await db.commit()
    return _view(source)


async def _tenant_source(source_id: UUID, db: DB, workspace_id: UUID) -> Source:
    source = await db.scalar(
        select(Source).where(Source.id == source_id, Source.workspace_id == workspace_id)
    )
    if source is None:
        raise APIError(404, "SOURCE_NOT_FOUND", "The source was not found.")
    return source


@router.get("/{source_id}", response_model=SourceView)
async def get_source(source_id: UUID, db: DB, principal: WorkspacePrincipal) -> SourceView:
    return _view(await _tenant_source(source_id, db, principal.workspace_id))


@router.patch("/{source_id}", response_model=SourceView)
async def update_source(
    source_id: UUID,
    payload: SourceUpdate,
    request: Request,
    db: DB,
    principal: WorkspacePrincipal,
) -> SourceView:
    source = await _tenant_source(source_id, db, principal.workspace_id)
    changes = payload.model_dump(exclude_unset=True)
    if payload.url is not None:
        changes["url"] = str(payload.url)
        await _validate_url(changes["url"])
    aad = f"source:{source.id}".encode()
    keyring = KeyRing.from_settings()
    if changes.pop("clear_credentials", False):
        source.username_encrypted = None
        source.password_encrypted = None
    if "username" in changes:
        username = changes.pop("username")
        source.username_encrypted = (
            keyring.encrypt_text(username, associated_data=aad) if username else None
        )
    if "password" in changes:
        password = changes.pop("password")
        source.password_encrypted = (
            keyring.encrypt_text(password, associated_data=aad) if password else None
        )
    for field, value in changes.items():
        setattr(source, field, value.strip() if field == "name" else value)
    record_audit(
        db,
        request,
        principal,
        action="source.updated",
        resource_type="source",
        resource_id=source.id,
    )
    await db.commit()
    return _view(source)


@router.post(
    "/{source_id}/run", response_model=SourceRunAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def run_source(
    source_id: UUID, request: Request, db: DB, principal: WorkspacePrincipal
) -> SourceRunAccepted:
    source = await _tenant_source(source_id, db, principal.workspace_id)
    operation = create_operation(db, workspace_id=principal.workspace_id, kind="source_refresh")
    await db.flush()
    job = enqueue_job(
        db,
        job_type=JobType.REFRESH_SOURCE,
        workspace_id=principal.workspace_id,
        entity_id=source.id,
        operation=operation,
        payload={"manual": True},
    )
    record_audit(
        db,
        request,
        principal,
        action="source.refresh_requested",
        resource_type="source",
        resource_id=source.id,
    )
    await db.commit()
    return SourceRunAccepted(operation_id=operation.id, job_id=job.id)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: UUID, request: Request, db: DB, principal: WorkspacePrincipal
) -> None:
    source = await _tenant_source(source_id, db, principal.workspace_id)
    await db.delete(source)
    record_audit(
        db,
        request,
        principal,
        action="source.deleted",
        resource_type="source",
        resource_id=source.id,
    )
    await db.commit()


async def _global_source(source_id: UUID, db: DB) -> Source:
    source = await db.scalar(
        select(Source).where(
            Source.id == source_id,
            Source.scope == ProxyScope.GLOBAL,
            Source.workspace_id.is_(None),
        )
    )
    if source is None:
        raise APIError(404, "SOURCE_NOT_FOUND", "The global source was not found.")
    return source


@admin_router.get("", response_model=Page[SourceView])
async def list_global_sources(
    db: DB, principal: AdminPrincipal, pagination: PaginationDep
) -> Page[SourceView]:
    sources, total = await paginate(
        db,
        select(Source)
        .where(Source.scope == ProxyScope.GLOBAL, Source.workspace_id.is_(None))
        .order_by(Source.created_at.desc()),
        pagination,
    )
    return Page(
        items=[_view(source) for source in sources],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@admin_router.post("", response_model=SourceView, status_code=status.HTTP_201_CREATED)
async def create_global_source(
    payload: SourceCreate, request: Request, db: DB, principal: AdminPrincipal
) -> SourceView:
    url = str(payload.url)
    await _validate_url(url)
    source_id = uuid4()
    aad = f"source:{source_id}".encode()
    keyring = KeyRing.from_settings()
    source = Source(
        id=source_id,
        workspace_id=None,
        scope=ProxyScope.GLOBAL,
        name=payload.name.strip(),
        url=url,
        username_encrypted=(
            keyring.encrypt_text(payload.username, associated_data=aad)
            if payload.username
            else None
        ),
        password_encrypted=(
            keyring.encrypt_text(payload.password, associated_data=aad)
            if payload.password
            else None
        ),
        default_protocol=payload.default_protocol,
        enabled=payload.enabled,
        refresh_interval_minutes=payload.refresh_interval_minutes,
    )
    db.add(source)
    record_audit(
        db,
        request,
        principal,
        action="global_source.created",
        resource_type="source",
        resource_id=source.id,
    )
    await db.commit()
    return _view(source)


@admin_router.patch("/{source_id}", response_model=SourceView)
async def update_global_source(
    source_id: UUID,
    payload: SourceUpdate,
    request: Request,
    db: DB,
    principal: AdminPrincipal,
) -> SourceView:
    source = await _global_source(source_id, db)
    changes = payload.model_dump(exclude_unset=True)
    if payload.url is not None:
        changes["url"] = str(payload.url)
        await _validate_url(changes["url"])
    aad = f"source:{source.id}".encode()
    keyring = KeyRing.from_settings()
    if changes.pop("clear_credentials", False):
        source.username_encrypted = None
        source.password_encrypted = None
    if "username" in changes:
        value = changes.pop("username")
        source.username_encrypted = (
            keyring.encrypt_text(value, associated_data=aad) if value else None
        )
    if "password" in changes:
        value = changes.pop("password")
        source.password_encrypted = (
            keyring.encrypt_text(value, associated_data=aad) if value else None
        )
    for field, value in changes.items():
        setattr(source, field, value.strip() if field == "name" else value)
    record_audit(
        db,
        request,
        principal,
        action="global_source.updated",
        resource_type="source",
        resource_id=source.id,
    )
    await db.commit()
    return _view(source)


@admin_router.post(
    "/{source_id}/run",
    response_model=SourceRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_global_source(
    source_id: UUID, request: Request, db: DB, principal: AdminPrincipal
) -> SourceRunAccepted:
    source = await _global_source(source_id, db)
    operation = create_operation(db, workspace_id=None, kind="global_source_refresh")
    job = enqueue_job(
        db,
        job_type=JobType.REFRESH_SOURCE,
        workspace_id=None,
        entity_id=source.id,
        operation=operation,
        payload={"manual": True, "scope": "global"},
    )
    record_audit(
        db,
        request,
        principal,
        action="global_source.refresh_requested",
        resource_type="source",
        resource_id=source.id,
    )
    await db.commit()
    return SourceRunAccepted(operation_id=operation.id, job_id=job.id)


@admin_router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_global_source(
    source_id: UUID, request: Request, db: DB, principal: AdminPrincipal
) -> None:
    source = await _global_source(source_id, db)
    await db.delete(source)
    record_audit(
        db,
        request,
        principal,
        action="global_source.deleted",
        resource_type="source",
        resource_id=source.id,
    )
    await db.commit()
