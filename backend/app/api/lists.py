from __future__ import annotations

from datetime import timedelta
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import func, or_, select

from app.config import get_settings
from app.db import utcnow
from app.dependencies import DB, OwnerPrincipal, workspace_limits
from app.errors import APIError
from app.models import (
    Pool,
    PoolListLink,
    PoolMember,
    ProxyHealth,
    ProxyProtocol,
    ProxyRoute,
    ProxyScope,
    Workspace,
    WorkspaceStatus,
)
from app.schemas import PoolListLinkCreate, PoolListLinkCreated, PoolListLinkView
from app.security import KeyRing, digest_api_token, generate_list_token
from app.services.audit import record_audit

MAX_LINKS_PER_POOL = 10
# last_used_at is a convenience for the owner; do not write on every poll.
LAST_USED_RESOLUTION = timedelta(minutes=1)
_SCHEMES = {
    ProxyProtocol.HTTP: "http",
    ProxyProtocol.HTTPS: "https",
    ProxyProtocol.SOCKS4A: "socks4a",
    ProxyProtocol.SOCKS5: "socks5",
}

router = APIRouter(prefix="/pools/{pool_id}/list-links", tags=["pools"])
public_router = APIRouter(prefix="/lists", tags=["lists"])


async def _owned_pool(db: DB, pool_id: UUID, workspace_id: UUID) -> Pool:
    pool = await db.scalar(
        select(Pool).where(Pool.id == pool_id, Pool.workspace_id == workspace_id)
    )
    if pool is None:
        raise APIError(404, "POOL_NOT_FOUND", "The pool was not found.")
    return pool


@router.get("", response_model=list[PoolListLinkView])
async def list_links(pool_id: UUID, db: DB, principal: OwnerPrincipal) -> list[PoolListLinkView]:
    await _owned_pool(db, pool_id, principal.workspace_id)
    links = await db.scalars(
        select(PoolListLink)
        .where(PoolListLink.pool_id == pool_id, PoolListLink.workspace_id == principal.workspace_id)
        .order_by(PoolListLink.created_at.desc())
    )
    return [PoolListLinkView.model_validate(link) for link in links]


@router.post("", response_model=PoolListLinkCreated, status_code=status.HTTP_201_CREATED)
async def create_link(
    pool_id: UUID,
    payload: PoolListLinkCreate,
    request: Request,
    response: Response,
    db: DB,
    principal: OwnerPrincipal,
) -> PoolListLinkCreated:
    await _owned_pool(db, pool_id, principal.workspace_id)
    if payload.include_global:
        limits = await workspace_limits(db, principal.workspace_id)
        if not limits.global_catalog_enabled:
            raise APIError(403, "GLOBAL_CATALOG_DISABLED", "Global catalog access is disabled.")
    existing = await db.scalar(
        select(func.count())
        .select_from(PoolListLink)
        .where(PoolListLink.pool_id == pool_id, PoolListLink.workspace_id == principal.workspace_id)
    )
    if (existing or 0) >= MAX_LINKS_PER_POOL:
        raise APIError(409, "LIST_LINK_LIMIT", "Revoke an existing link before creating another.")
    token = generate_list_token()
    link = PoolListLink(
        workspace_id=principal.workspace_id,
        pool_id=pool_id,
        name=payload.name.strip(),
        token_prefix=token[:16],
        token_digest=digest_api_token(token),
        include_global=payload.include_global,
    )
    db.add(link)
    await db.flush()
    record_audit(
        db,
        request,
        principal,
        action="pool_list_link.created",
        resource_type="pool_list_link",
        resource_id=link.id,
        details={"pool_id": str(pool_id), "include_global": link.include_global},
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return PoolListLinkCreated(
        **PoolListLinkView.model_validate(link).model_dump(),
        url=f"{get_settings().list_base_url}/api/v1/lists/{token}",
    )


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_link(
    pool_id: UUID, link_id: UUID, request: Request, db: DB, principal: OwnerPrincipal
) -> None:
    link = await db.scalar(
        select(PoolListLink).where(
            PoolListLink.id == link_id,
            PoolListLink.pool_id == pool_id,
            PoolListLink.workspace_id == principal.workspace_id,
        )
    )
    if link is None:
        raise APIError(404, "LIST_LINK_NOT_FOUND", "The list link was not found.")
    await db.delete(link)
    record_audit(
        db,
        request,
        principal,
        action="pool_list_link.revoked",
        resource_type="pool_list_link",
        resource_id=link.id,
    )
    await db.commit()


def _authority(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _proxy_url(
    protocol: ProxyProtocol, host: str, port: int, username: str | None, password: str | None
) -> str:
    userinfo = ""
    if username is not None:
        userinfo = quote(username, safe="")
        if password is not None:
            userinfo += ":" + quote(password, safe="")
        userinfo += "@"
    return f"{_SCHEMES[protocol]}://{userinfo}{_authority(host, port)}"


def _hidden(status_code: int = 404) -> PlainTextResponse:
    # One response for unknown, revoked, and suspended so a probe learns nothing.
    return PlainTextResponse("not found\n", status_code=status_code)


@public_router.get("/{token}", response_class=PlainTextResponse)
async def fetch_list(
    token: str,
    db: DB,
    format: Literal["url", "hostport", "json"] = "url",
    protocol: ProxyProtocol | None = None,
) -> Response:
    """Serve the pool's current members to an app that holds the secret link."""
    link = await db.scalar(
        select(PoolListLink).where(PoolListLink.token_digest == digest_api_token(token))
    )
    if link is None:
        return _hidden()
    workspace = await db.get(Workspace, link.workspace_id)
    pool = await db.scalar(
        select(Pool).where(Pool.id == link.pool_id, Pool.workspace_id == link.workspace_id)
    )
    if workspace is None or workspace.status != WorkspaceStatus.ACTIVE or pool is None:
        return _hidden()

    include_global = (
        link.include_global
        and (await workspace_limits(db, link.workspace_id)).global_catalog_enabled
    )
    visible = (
        or_(ProxyRoute.scope == ProxyScope.GLOBAL, ProxyRoute.workspace_id == link.workspace_id)
        if include_global
        else (ProxyRoute.scope == ProxyScope.PRIVATE)
        & (ProxyRoute.workspace_id == link.workspace_id)
    )
    rows: list[tuple[ProxyRoute, ProxyHealth]] = []
    excluded_global = 0
    if pool.enabled and pool.current_revision is not None:
        members = (
            select(ProxyRoute, ProxyHealth)
            .join(PoolMember, PoolMember.proxy_id == ProxyRoute.id)
            .join(ProxyHealth, ProxyHealth.proxy_id == ProxyRoute.id)
            .where(
                PoolMember.pool_id == pool.id,
                PoolMember.revision == pool.current_revision,
                ProxyRoute.active.is_(True),
            )
        )
        statement = members.where(visible).order_by(PoolMember.ordinal)
        if protocol is not None:
            statement = statement.where(ProxyRoute.protocol == protocol)
        rows = [(route, health) for route, health in (await db.execute(statement)).all()]
        if not include_global:
            excluded_global = (
                await db.scalar(
                    select(func.count())
                    .select_from(PoolMember)
                    .join(ProxyRoute, ProxyRoute.id == PoolMember.proxy_id)
                    .where(
                        PoolMember.pool_id == pool.id,
                        PoolMember.revision == pool.current_revision,
                        ProxyRoute.active.is_(True),
                        ProxyRoute.scope == ProxyScope.GLOBAL,
                    )
                )
                or 0
            )

    now = utcnow()
    last_used = link.last_used_at
    if last_used is not None and last_used.tzinfo is None:
        last_used = last_used.replace(tzinfo=now.tzinfo)  # SQLite drops the offset
    if last_used is None or now - last_used >= LAST_USED_RESOLUTION:
        link.last_used_at = now
        await db.commit()

    keyring = KeyRing.from_settings(get_settings())
    entries = []
    for route, health in rows:
        aad = f"proxy-route:{route.id}".encode()
        username = (
            keyring.decrypt_text(route.username_encrypted, associated_data=aad)
            if route.username_encrypted
            else None
        )
        password = (
            keyring.decrypt_text(route.password_encrypted, associated_data=aad)
            if route.password_encrypted
            else None
        )
        entries.append((route, health, username, password))

    headers = {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex",
        "X-Proxy-Count": str(len(entries)),
        "X-Excluded-Global-Count": str(excluded_global),
    }
    if format == "json":
        return JSONResponse(
            [
                {
                    "url": _proxy_url(route.protocol, route.host, route.port, username, password),
                    "protocol": route.protocol.value,
                    "host": route.host,
                    "port": route.port,
                    "username": username,
                    "password": password,
                    "country_code": route.country_code,
                    "latency_ms": health.latency_ewma_ms,
                    "score": health.score,
                }
                for route, health, username, password in entries
            ],
            headers=headers,
        )
    lines = [
        _authority(route.host, route.port)
        if format == "hostport"
        else _proxy_url(route.protocol, route.host, route.port, username, password)
        for route, _health, username, password in entries
    ]
    return PlainTextResponse("".join(f"{line}\n" for line in lines), headers=headers)
