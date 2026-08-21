from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.filters import catalog_scope_clause, compile_filter
from app.gateway.snapshots import EncryptedSnapshotCodec
from app.models import (
    Endpoint,
    Filter,
    HealthStatus,
    Pool,
    PoolMember,
    PoolRevision,
    ProxyHealth,
    ProxyRoute,
    Workspace,
    WorkspaceLimit,
)
from app.security import KeyRing


class PoolMaterializer:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def materialize(self, pool_id: UUID) -> int:
        async with self.sessions() as session, session.begin():
            pool = await session.scalar(select(Pool).where(Pool.id == pool_id).with_for_update())
            if pool is None:
                raise ValueError("pool does not exist")
            filter_row = await session.scalar(
                select(Filter).where(
                    Filter.id == pool.filter_id,
                    Filter.workspace_id == pool.workspace_id,
                )
            )
            if filter_row is None:
                raise ValueError("pool filter does not exist")
            condition = compile_filter(filter_row.rules, pool.workspace_id)
            scope = catalog_scope_clause(pool.catalog_selection.value, pool.workspace_id)
            candidates = (
                await session.execute(
                    select(ProxyRoute, ProxyHealth)
                    .join(ProxyHealth, ProxyHealth.proxy_id == ProxyRoute.id)
                    .where(
                        ProxyRoute.active.is_(True),
                        ProxyHealth.status.in_((HealthStatus.HEALTHY, HealthStatus.DEGRADED)),
                        ProxyHealth.last_checked_at >= datetime.now(UTC) - timedelta(minutes=30),
                        scope,
                        condition,
                    )
                    .order_by(ProxyHealth.latency_ewma_ms.asc().nullslast(), ProxyRoute.id)
                )
            ).all()
            revision_number = (pool.current_revision or 0) + 1
            session.add(
                PoolRevision(
                    workspace_id=pool.workspace_id,
                    pool_id=pool.id,
                    revision=revision_number,
                    member_count=len(candidates),
                    rule_snapshot=filter_row.rules,
                )
            )
            for ordinal, (route, health) in enumerate(candidates):
                session.add(
                    PoolMember(
                        pool_id=pool.id,
                        revision=revision_number,
                        proxy_id=route.id,
                        weight=max(health.score, 1.0) ** 2,
                        ordinal=ordinal,
                    )
                )
            pool.current_revision = revision_number
            pool.materialized_at = datetime.now(UTC)
            return revision_number


class SnapshotPublisher:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        redis: Any,
        keyring: KeyRing,
        *,
        snapshot_key: str = "proxyhide:gateway:snapshot",
        reload_channel: str = "proxyhide:gateway:reload",
        ttl_seconds: int | None = None,
    ) -> None:
        self.sessions = sessions
        self.redis = redis
        self.keyring = keyring
        self.codec = EncryptedSnapshotCodec(keyring)
        self.snapshot_key = snapshot_key
        self.reload_channel = reload_channel
        self.ttl_seconds = ttl_seconds

    async def publish(self) -> int:
        payload = await self.build()
        version = int(payload["version"])
        encrypted = self.codec.encode(payload)
        pipeline = self.redis.pipeline(transaction=True)
        if self.ttl_seconds is None:
            pipeline.set(self.snapshot_key, encrypted)
        else:
            pipeline.set(self.snapshot_key, encrypted, ex=self.ttl_seconds)
        pipeline.publish(self.reload_channel, str(version))
        await pipeline.execute()
        return version

    async def build(self) -> dict[str, Any]:
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(Endpoint, Workspace, WorkspaceLimit, Pool)
                    .join(Workspace, Workspace.id == Endpoint.workspace_id)
                    .join(WorkspaceLimit, WorkspaceLimit.workspace_id == Workspace.id)
                    .join(Pool, Pool.id == Endpoint.pool_id)
                    .order_by(Endpoint.username)
                )
            ).all()
            endpoints: dict[str, Any] = {}
            pools: dict[str, Any] = {}
            for endpoint, workspace, limits, pool in rows:
                endpoints[endpoint.username] = {
                    "id": str(endpoint.id),
                    "workspace_id": str(endpoint.workspace_id),
                    "username": endpoint.username,
                    "secret_digest": endpoint.secret_digest,
                    "pool_id": str(endpoint.pool_id),
                    "enabled": endpoint.enabled,
                    "workspace_status": workspace.status.value,
                    "ip_allowlist": endpoint.ip_allowlist,
                    "destination_ports": limits.destination_ports,
                    "requests_per_minute": limits.requests_per_minute,
                    "max_connections": limits.max_gateway_connections,
                }
                pool_key = str(pool.id)
                if pool_key not in pools:
                    pools[pool_key] = await self._pool_payload(session, pool)
            return {
                "version": time.time_ns(),
                "generated_at": datetime.now(UTC).isoformat(),
                "endpoints": endpoints,
                "pools": pools,
            }

    async def _pool_payload(self, session: AsyncSession, pool: Pool) -> dict[str, Any]:
        if not pool.enabled or pool.current_revision is None:
            return {
                "id": str(pool.id),
                "revision": 0,
                "strategy": pool.strategy.value,
                "routes": [],
            }
        rows = (
            await session.execute(
                select(PoolMember, ProxyRoute, ProxyHealth)
                .join(ProxyRoute, ProxyRoute.id == PoolMember.proxy_id)
                .join(ProxyHealth, ProxyHealth.proxy_id == ProxyRoute.id)
                .where(
                    PoolMember.pool_id == pool.id,
                    PoolMember.revision == pool.current_revision,
                    ProxyRoute.active.is_(True),
                )
                .order_by(PoolMember.ordinal)
            )
        ).all()
        routes = []
        for _member, route, health in rows:
            aad = f"proxy-route:{route.id}".encode()
            routes.append(
                {
                    "id": str(route.id),
                    "protocol": route.protocol.value,
                    "host": route.host,
                    "port": route.port,
                    "username": (
                        self.keyring.decrypt_text(route.username_encrypted, associated_data=aad)
                        if route.username_encrypted
                        else None
                    ),
                    "password": (
                        self.keyring.decrypt_text(route.password_encrypted, associated_data=aad)
                        if route.password_encrypted
                        else None
                    ),
                    "score": health.score,
                    "latency_ms": health.latency_ewma_ms,
                }
            )
        return {
            "id": str(pool.id),
            "revision": pool.current_revision,
            "strategy": pool.strategy.value,
            "routes": routes,
        }
