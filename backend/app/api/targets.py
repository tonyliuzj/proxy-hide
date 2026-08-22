from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID, uuid4

import re2
from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.dependencies import (
    DB,
    PaginationDep,
    WorkspacePrincipal,
    enforce_quota,
    paginate,
    workspace_limits,
)
from app.domain.network import DestinationPolicyError, validate_public_http_url
from app.errors import APIError
from app.models import JobType, Target, TargetKind
from app.schemas import (
    Page,
    TargetCheckAccepted,
    TargetCreate,
    TargetUpdate,
    TargetView,
)
from app.security import KeyRing
from app.services.audit import record_audit
from app.services.jobs import create_operation, enqueue_job

router = APIRouter(prefix="/targets", tags=["targets"])

_BUILTIN_URLS = {
    TargetKind.GOOGLE: "https://www.google.com/search?q=proxyhide-health-check",
    TargetKind.BING: "https://www.bing.com/search?q=proxyhide-health-check",
    TargetKind.BRAVE: "https://search.brave.com/search?q=proxyhide-health-check",
    TargetKind.STARTPAGE: "https://www.startpage.com/sp/search?query=proxyhide-health-check",
    TargetKind.DUCKDUCKGO: "https://duckduckgo.com/html/?q=proxyhide-health-check",
    TargetKind.WIKIPEDIA: "https://en.wikipedia.org/w/index.php?search=proxyhide-health-check",
}
_PROHIBITED_HEADERS = {
    "connection",
    "content-length",
    "host",
    "proxy-authorization",
    "proxy-connection",
    "transfer-encoding",
    "upgrade",
}


def _validate_headers(headers: dict[str, str]) -> None:
    if len(headers) > 50:
        raise APIError(422, "TARGET_HEADERS_INVALID", "At most 50 target headers are allowed.")
    for name, value in headers.items():
        if name.lower() in _PROHIBITED_HEADERS or "\r" in name or "\n" in name:
            raise APIError(422, "TARGET_HEADERS_INVALID", f"Header {name!r} is not allowed.")
        if "\r" in value or "\n" in value or len(value.encode()) > 8192:
            raise APIError(422, "TARGET_HEADERS_INVALID", f"Header {name!r} has an invalid value.")


def _validate_patterns(patterns: list[str]) -> None:
    for pattern in patterns:
        if len(pattern.encode()) > 1024:
            raise APIError(422, "TARGET_PATTERN_INVALID", "Target patterns are limited to 1 KiB.")
        try:
            re2.compile(pattern)
        except re2.error as exc:
            raise APIError(422, "TARGET_PATTERN_INVALID", f"Invalid RE2 expression: {exc}") from exc


async def _validate_custom_target(payload: TargetCreate, allowed_ports: list[int]) -> str:
    if payload.kind != TargetKind.CUSTOM:
        return _BUILTIN_URLS[payload.kind]
    if payload.url is None:
        raise APIError(422, "TARGET_URL_REQUIRED", "A custom target URL is required.")
    url = str(payload.url)
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in allowed_ports:
        raise APIError(
            422, "TARGET_PORT_REJECTED", "The target port is not allowed for this workspace."
        )
    try:
        await validate_public_http_url(url)
    except DestinationPolicyError as exc:
        raise APIError(422, "TARGET_URL_REJECTED", str(exc)) from exc
    return url


def _view(target: Target) -> TargetView:
    return TargetView(
        id=target.id,
        name=target.name,
        kind=target.kind,
        enabled=target.enabled,
        method=target.method,
        url=target.url,
        headers=target.headers,
        has_secret_headers=target.secret_headers_encrypted is not None,
        has_body=target.body_encrypted is not None,
        status_ranges=target.status_ranges,
        required_literals=target.required_literals,
        forbidden_literals=target.forbidden_literals,
        required_patterns=target.required_patterns,
        forbidden_patterns=target.forbidden_patterns,
        created_at=target.created_at,
    )


@router.get("", response_model=Page[TargetView])
async def list_targets(
    db: DB, principal: WorkspacePrincipal, pagination: PaginationDep
) -> Page[TargetView]:
    targets, total = await paginate(
        db,
        select(Target)
        .where(Target.workspace_id == principal.workspace_id)
        .order_by(Target.created_at.desc()),
        pagination,
    )
    return Page(
        items=[_view(target) for target in targets],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("", response_model=TargetView, status_code=status.HTTP_201_CREATED)
async def create_target(
    payload: TargetCreate, request: Request, db: DB, principal: WorkspacePrincipal
) -> TargetView:
    if payload.kind == TargetKind.CUSTOM:
        await enforce_quota(
            db,
            workspace_id=principal.workspace_id,
            model=Target,
            limit_field="max_custom_targets",
            extra_clause=Target.kind == TargetKind.CUSTOM,
        )
    elif await db.scalar(
        select(Target.id).where(
            Target.workspace_id == principal.workspace_id, Target.kind == payload.kind
        )
    ):
        raise APIError(409, "TARGET_EXISTS", f"The {payload.kind.value} target already exists.")
    limits = await workspace_limits(db, principal.workspace_id)
    url = await _validate_custom_target(payload, limits.destination_ports)
    _validate_headers(payload.headers)
    _validate_headers(payload.secret_headers)
    _validate_patterns(payload.required_patterns + payload.forbidden_patterns)
    if any(
        len(value.encode()) > 4096
        for value in payload.required_literals + payload.forbidden_literals
    ):
        raise APIError(422, "TARGET_LITERAL_INVALID", "Target literals are limited to 4 KiB.")
    target_id = uuid4()
    aad = f"target:{target_id}".encode()
    keyring = KeyRing.from_settings()
    target = Target(
        id=target_id,
        workspace_id=principal.workspace_id,
        name=payload.name.strip(),
        kind=payload.kind,
        enabled=payload.enabled,
        method=payload.method,
        url=url,
        headers=payload.headers,
        secret_headers_encrypted=(
            keyring.encrypt_json(payload.secret_headers, associated_data=aad)
            if payload.secret_headers
            else None
        ),
        body_encrypted=(
            keyring.encrypt_text(payload.body, associated_data=aad) if payload.body else None
        ),
        status_ranges=[list(value) for value in payload.status_ranges],
        required_literals=payload.required_literals,
        forbidden_literals=payload.forbidden_literals,
        required_patterns=payload.required_patterns,
        forbidden_patterns=payload.forbidden_patterns,
    )
    db.add(target)
    record_audit(
        db,
        request,
        principal,
        action="target.created",
        resource_type="target",
        resource_id=target.id,
    )
    await db.commit()
    return _view(target)


async def _tenant_target(target_id: UUID, db: DB, workspace_id: UUID) -> Target:
    target = await db.scalar(
        select(Target).where(Target.id == target_id, Target.workspace_id == workspace_id)
    )
    if target is None:
        raise APIError(404, "TARGET_NOT_FOUND", "The target was not found.")
    return target


@router.get("/{target_id}", response_model=TargetView)
async def get_target(target_id: UUID, db: DB, principal: WorkspacePrincipal) -> TargetView:
    return _view(await _tenant_target(target_id, db, principal.workspace_id))


@router.patch("/{target_id}", response_model=TargetView)
async def update_target(
    target_id: UUID,
    payload: TargetUpdate,
    request: Request,
    db: DB,
    principal: WorkspacePrincipal,
) -> TargetView:
    target = await _tenant_target(target_id, db, principal.workspace_id)
    changes = payload.model_dump(exclude_unset=True)
    if target.kind != TargetKind.CUSTOM and any(
        field in changes for field in ("method", "url", "headers", "secret_headers", "body")
    ):
        raise APIError(
            422, "BUILTIN_TARGET_IMMUTABLE", "Built-in target request settings are fixed."
        )
    if payload.url is not None:
        url = str(payload.url)
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        limits = await workspace_limits(db, principal.workspace_id)
        if port not in limits.destination_ports:
            raise APIError(
                422,
                "TARGET_PORT_REJECTED",
                "The target port is not allowed for this workspace.",
            )
        try:
            await validate_public_http_url(url)
        except DestinationPolicyError as exc:
            raise APIError(422, "TARGET_URL_REJECTED", str(exc)) from exc
        changes["url"] = url
    if payload.headers is not None:
        _validate_headers(payload.headers)
    patterns = (payload.required_patterns or []) + (payload.forbidden_patterns or [])
    _validate_patterns(patterns)
    literals = (payload.required_literals or []) + (payload.forbidden_literals or [])
    if any(len(value.encode()) > 4096 for value in literals):
        raise APIError(422, "TARGET_LITERAL_INVALID", "Target literals are limited to 4 KiB.")
    aad = f"target:{target.id}".encode()
    keyring = KeyRing.from_settings()
    if changes.pop("clear_secret_headers", False):
        target.secret_headers_encrypted = None
    if "secret_headers" in changes:
        secret_headers = changes.pop("secret_headers")
        _validate_headers(secret_headers)
        target.secret_headers_encrypted = (
            keyring.encrypt_json(secret_headers, associated_data=aad) if secret_headers else None
        )
    if changes.pop("clear_body", False):
        target.body_encrypted = None
    if "body" in changes:
        body = changes.pop("body")
        target.body_encrypted = keyring.encrypt_text(body, associated_data=aad) if body else None
    if "status_ranges" in changes and changes["status_ranges"] is not None:
        changes["status_ranges"] = [list(value) for value in changes["status_ranges"]]
    for field, value in changes.items():
        setattr(target, field, value.strip() if field == "name" else value)
    record_audit(
        db,
        request,
        principal,
        action="target.updated",
        resource_type="target",
        resource_id=target.id,
    )
    await db.commit()
    return _view(target)


@router.post(
    "/{target_id}/check", response_model=TargetCheckAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def check_target(
    target_id: UUID, request: Request, db: DB, principal: WorkspacePrincipal
) -> TargetCheckAccepted:
    target = await _tenant_target(target_id, db, principal.workspace_id)
    operation = create_operation(db, workspace_id=principal.workspace_id, kind="target_check")
    await db.flush()
    job = enqueue_job(
        db,
        job_type=JobType.CHECK_TARGET,
        workspace_id=principal.workspace_id,
        entity_id=target.id,
        operation=operation,
        payload={"manual": True},
    )
    record_audit(
        db,
        request,
        principal,
        action="target.check_requested",
        resource_type="target",
        resource_id=target.id,
    )
    await db.commit()
    return TargetCheckAccepted(operation_id=operation.id, job_id=job.id)


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: UUID, request: Request, db: DB, principal: WorkspacePrincipal
) -> None:
    target = await _tenant_target(target_id, db, principal.workspace_id)
    await db.delete(target)
    record_audit(
        db,
        request,
        principal,
        action="target.deleted",
        resource_type="target",
        resource_id=target.id,
    )
    await db.commit()
