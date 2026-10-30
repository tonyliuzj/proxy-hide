from __future__ import annotations

import ipaddress
import secrets
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


def _require_open_access_allowlist(allowlist: list[str]) -> None:
    """An open port trusts the client address alone, so the allowlist must mean something."""
    if not allowlist:
        raise APIError(
            422,
            "OPEN_ACCESS_NEEDS_ALLOWLIST",
            "A port without credentials needs a client IP allowlist, for example 192.168.0.0/16.",
        )
    if any(ipaddress.ip_network(value).prefixlen == 0 for value in allowlist):
        raise APIError(
            422,
            "OPEN_ACCESS_TOO_BROAD",
            "A port without credentials cannot allow every address. Narrow the allowlist "
            "or require credentials.",
        )


async def _allocate_port(db: DB, requested: int | None) -> int:
    window = get_settings().listener_port_range
    if window is None:
        raise APIError(422, "DEDICATED_PORTS_DISABLED", "Dedicated endpoint ports are disabled.")
    low, high = window
    taken = set(
        (
            await db.scalars(select(Endpoint.listen_port).where(Endpoint.listen_port.is_not(None)))
        ).all()
    )
    if requested is not None:
        if not low <= requested <= high:
            raise APIError(422, "PORT_OUT_OF_RANGE", f"Choose a port between {low} and {high}.")
        if requested in taken:
            raise APIError(409, "PORT_IN_USE", f"Port {requested} is already used.")
        return requested
    free = next((port for port in range(low, high + 1) if port not in taken), None)
    if free is None:
        raise APIError(409, "NO_FREE_PORTS", "Every dedicated port is already in use.")
    return free


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


def _created_view(endpoint: Endpoint, secret: str | None) -> EndpointCreated:
    settings = get_settings()
    fields = EndpointView.model_validate(endpoint).model_dump(exclude={"proxy_address"})
    if secret is None:
        return EndpointCreated(**fields)
    username = quote(endpoint.username, safe="")
    encoded_secret = quote(secret, safe="")
    return EndpointCreated(
        **fields,
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
    allowlist = _normalize_allowlist(payload.ip_allowlist)
    dedicated = payload.dedicated_port or payload.listen_port is not None
    open_access = not payload.require_auth
    if open_access:
        if not dedicated:
            raise APIError(
                422,
                "OPEN_ACCESS_NEEDS_PORT",
                "Access without credentials needs a dedicated port.",
            )
        _require_open_access_allowlist(allowlist)
    elif payload.username is None:
        raise APIError(422, "USERNAME_REQUIRED", "A username is required when using credentials.")
    listen_port = await _allocate_port(db, payload.listen_port) if dedicated else None
    # An open endpoint is never issued a secret; the stored digest is of a value no one holds.
    secret = None if open_access else generate_endpoint_secret()
    endpoint = Endpoint(
        workspace_id=principal.workspace_id,
        name=payload.name.strip(),
        pool_id=payload.pool_id,
        username=payload.username or f"open-{secrets.token_hex(4)}",
        secret_digest=digest_endpoint_secret(secret or generate_endpoint_secret()),
        enabled=payload.enabled,
        ip_allowlist=allowlist,
        secret_rotated_at=None if open_access else utcnow(),
        listen_port=listen_port,
        require_auth=payload.require_auth,
        strategy=payload.strategy,
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
        details={"username": endpoint.username, "listen_port": endpoint.listen_port},
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
    require_auth = changes.get("require_auth", endpoint.require_auth)
    if "require_auth" in changes and require_auth is None:
        raise APIError(422, "REQUIRE_AUTH_INVALID", "require_auth must be true or false.")
    if not require_auth:
        if endpoint.listen_port is None:
            raise APIError(
                422,
                "OPEN_ACCESS_NEEDS_PORT",
                "Access without credentials needs a dedicated port.",
            )
        _require_open_access_allowlist(changes.get("ip_allowlist", endpoint.ip_allowlist))
    elif endpoint.secret_rotated_at is None:
        raise APIError(
            422,
            "SECRET_NOT_ISSUED",
            "Regenerate the secret before requiring credentials on this endpoint.",
        )
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
