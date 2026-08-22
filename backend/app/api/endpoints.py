from __future__ import annotations

import ipaddress
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.db import utcnow
from app.dependencies import DB, PaginationDep, WorkspacePrincipal, enforce_quota, paginate
from app.errors import APIError
from app.models import Endpoint, JobType, Pool
from app.schemas import (
    ConnectionGuideView,
    EndpointCreate,
    EndpointCreated,
    EndpointUpdate,
    EndpointView,
    Page,
)
from app.security import digest_endpoint_secret, generate_endpoint_secret
from app.services.audit import record_audit
from app.services.jobs import enqueue_job

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


@router.get("/connection-guide", response_model=ConnectionGuideView)
async def connection_guide(principal: WorkspacePrincipal) -> ConnectionGuideView:
    settings = get_settings()
    return ConnectionGuideView(
        secure_host=settings.public_gateway_tls_host,
        secure_port=settings.public_gateway_tls_port,
        plaintext_host=settings.public_gateway_host,
        plaintext_port=settings.public_gateway_http_port,
        socks_host=settings.public_gateway_host,
        socks_port=settings.public_gateway_socks_port,
    )


def _normalize_allowlist(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise APIError(
                422,
                "ALLOWLIST_INVALID",
                f"{value!r} is not a valid IP address or CIDR network.",
            ) from exc
        if network.is_unspecified or network.is_multicast:
            raise APIError(422, "ALLOWLIST_INVALID", f"{value!r} is not an allowed network.")
        normalized.append(network.with_prefixlen)
    return sorted(set(normalized))


async def _tenant_pool(pool_id: UUID, db: DB, workspace_id: UUID) -> Pool:
    pool = await db.scalar(
        select(Pool).where(Pool.id == pool_id, Pool.workspace_id == workspace_id)
    )
    if pool is None:
        raise APIError(422, "POOL_NOT_FOUND", "The selected pool was not found.")
    return pool


async def _tenant_endpoint(endpoint_id: UUID, db: DB, workspace_id: UUID) -> Endpoint:
    endpoint = await db.scalar(
        select(Endpoint).where(Endpoint.id == endpoint_id, Endpoint.workspace_id == workspace_id)
    )
    if endpoint is None:
        raise APIError(404, "ENDPOINT_NOT_FOUND", "The endpoint was not found.")
    return endpoint


def _created_view(endpoint: Endpoint, secret: str) -> EndpointCreated:
    settings = get_settings()
    username = quote(endpoint.username, safe="")
    encoded_secret = quote(secret, safe="")
    return EndpointCreated(
        **EndpointView.model_validate(endpoint).model_dump(),
        secret=secret,
        plaintext_url=(
            f"http://{username}:{encoded_secret}@{settings.public_gateway_host}:"
            f"{settings.public_gateway_http_port}"
        ),
        secure_url=(
            f"https://{username}:{encoded_secret}@{settings.public_gateway_tls_host}:"
            f"{settings.public_gateway_tls_port}"
        ),
    )


def _enqueue_snapshot(db: DB, workspace_id: UUID, reason: str) -> None:
    enqueue_job(
        db,
        job_type=JobType.PUBLISH_SNAPSHOT,
        workspace_id=workspace_id,
        payload={"reason": reason},
    )


@router.get("", response_model=Page[EndpointView])
async def list_endpoints(
    db: DB, principal: WorkspacePrincipal, pagination: PaginationDep
) -> Page[EndpointView]:
    endpoints, total = await paginate(
        db,
        select(Endpoint)
        .where(Endpoint.workspace_id == principal.workspace_id)
        .order_by(Endpoint.created_at.desc()),
        pagination,
    )
    return Page(
        items=[EndpointView.model_validate(endpoint) for endpoint in endpoints],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("", response_model=EndpointCreated, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    payload: EndpointCreate,
    request: Request,
    response: Response,
    db: DB,
    principal: WorkspacePrincipal,
) -> EndpointCreated:
    await enforce_quota(
        db,
        workspace_id=principal.workspace_id,
        model=Endpoint,
        limit_field="max_endpoints",
    )
    await _tenant_pool(payload.pool_id, db, principal.workspace_id)
    secret = generate_endpoint_secret()
    endpoint = Endpoint(
        workspace_id=principal.workspace_id,
        name=payload.name.strip(),
        pool_id=payload.pool_id,
        username=payload.username,
        secret_digest=digest_endpoint_secret(secret),
        enabled=payload.enabled,
        ip_allowlist=_normalize_allowlist(payload.ip_allowlist),
        secret_rotated_at=utcnow(),
    )
    db.add(endpoint)
    await db.flush()
    _enqueue_snapshot(db, principal.workspace_id, "endpoint_created")
    record_audit(
        db,
        request,
        principal,
        action="endpoint.created",
        resource_type="endpoint",
        resource_id=endpoint.id,
        details={"username": endpoint.username},
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return _created_view(endpoint, secret)


@router.get("/{endpoint_id}", response_model=EndpointView)
async def get_endpoint(endpoint_id: UUID, db: DB, principal: WorkspacePrincipal) -> EndpointView:
    return EndpointView.model_validate(
        await _tenant_endpoint(endpoint_id, db, principal.workspace_id)
    )


@router.patch("/{endpoint_id}", response_model=EndpointView)
async def update_endpoint(
    endpoint_id: UUID,
    payload: EndpointUpdate,
    request: Request,
    db: DB,
    principal: WorkspacePrincipal,
) -> EndpointView:
    endpoint = await _tenant_endpoint(endpoint_id, db, principal.workspace_id)
    changes = payload.model_dump(exclude_unset=True)
    if payload.pool_id is not None:
        await _tenant_pool(payload.pool_id, db, principal.workspace_id)
    if payload.ip_allowlist is not None:
        changes["ip_allowlist"] = _normalize_allowlist(payload.ip_allowlist)
    for field, value in changes.items():
        setattr(endpoint, field, value.strip() if field == "name" else value)
    _enqueue_snapshot(db, principal.workspace_id, "endpoint_updated")
    record_audit(
        db,
        request,
        principal,
        action="endpoint.updated",
        resource_type="endpoint",
        resource_id=endpoint.id,
    )
    await db.commit()
    return EndpointView.model_validate(endpoint)


@router.post("/{endpoint_id}/regenerate-secret", response_model=EndpointCreated)
async def regenerate_secret(
    endpoint_id: UUID,
    request: Request,
    response: Response,
    db: DB,
    principal: WorkspacePrincipal,
) -> EndpointCreated:
    endpoint = await _tenant_endpoint(endpoint_id, db, principal.workspace_id)
    secret = generate_endpoint_secret()
    endpoint.secret_digest = digest_endpoint_secret(secret)
    endpoint.secret_rotated_at = utcnow()
    _enqueue_snapshot(db, principal.workspace_id, "endpoint_secret_rotated")
    record_audit(
        db,
        request,
        principal,
        action="endpoint.secret_rotated",
        resource_type="endpoint",
        resource_id=endpoint.id,
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return _created_view(endpoint, secret)


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    endpoint_id: UUID, request: Request, db: DB, principal: WorkspacePrincipal
) -> None:
    endpoint = await _tenant_endpoint(endpoint_id, db, principal.workspace_id)
    await db.delete(endpoint)
    _enqueue_snapshot(db, principal.workspace_id, "endpoint_deleted")
    record_audit(
        db,
        request,
        principal,
        action="endpoint.deleted",
        resource_type="endpoint",
        resource_id=endpoint.id,
    )
    await db.commit()
