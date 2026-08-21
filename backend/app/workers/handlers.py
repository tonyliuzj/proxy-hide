from __future__ import annotations

import asyncio
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.proxies import parse_proxy_text
from app.domain.scoring import update_health
from app.gateway.models import ProxyProtocol as GatewayProxyProtocol
from app.gateway.models import UpstreamRoute
from app.models import (
    CatalogSelection,
    CheckAttempt,
    CheckJob,
    HealthStatus,
    JobStatus,
    JobType,
    Pool,
    ProxyHealth,
    ProxyRoute,
    ProxyScope,
    Source,
    SourceMembership,
    SourceRun,
    Target,
    TargetHealth,
    TargetKind,
    WorkspaceLimit,
)
from app.security import KeyRing, digest_proxy_identity
from app.services.jobs import enqueue_job

from .checks import CheckSpec, ProxyCheckRunner, bing_check_spec, google_check_spec
from .feeds import PublicFeedFetcher
from .geoip import GeoIPResolver
from .jobs import JobEnvelope
from .materializer import PoolMaterializer, SnapshotPublisher
from .scheduler import general_check_interval


class WorkerHandlers:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: Settings,
        keyring: KeyRing,
        check_runner: ProxyCheckRunner,
        feed_fetcher: PublicFeedFetcher,
        materializer: PoolMaterializer,
        snapshot_publisher: SnapshotPublisher,
        geoip_resolver: GeoIPResolver | None = None,
    ) -> None:
        self.sessions = sessions
        self.settings = settings
        self.keyring = keyring
        self.check_runner = check_runner
        self.feed_fetcher = feed_fetcher
        self.materializer = materializer
        self.snapshot_publisher = snapshot_publisher
        self.geoip_resolver = geoip_resolver or GeoIPResolver(settings.geoip_database_path)

    def mapping(self) -> dict[str, Any]:
        return {
            JobType.CHECK_PROXY.value: self.check_proxy,
            JobType.CHECK_TARGET.value: self.check_target,
            JobType.REFRESH_SOURCE.value: self.refresh_source,
            JobType.MATERIALIZE_POOL.value: self.materialize_pool,
            JobType.PUBLISH_SNAPSHOT.value: self.publish_snapshot,
            JobType.RETENTION.value: self.retention,
        }

    async def check_proxy(self, envelope: JobEnvelope) -> None:
        if envelope.entity_id is None:
            raise ValueError("check_proxy job has no proxy ID")
        proxy_id = UUID(envelope.entity_id)
        async with self.sessions() as session:
            route = await session.get(ProxyRoute, proxy_id)
            if route is None or not route.active:
                return
            upstream = self._upstream(route)
        result = await self.check_runner.check(
            upstream,
            CheckSpec(url=_nonce_url(self.settings.general_probe_url), capture_exit_ip=True),
        )
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            route = await session.get(ProxyRoute, proxy_id, with_for_update=True)
            if route is None:
                return
            health = await session.get(ProxyHealth, proxy_id, with_for_update=True)
            if health is None:
                health = ProxyHealth(proxy_id=proxy_id)
                session.add(health)
            update = update_health(
                prior_success_ewma=(health.success_ewma if health.valid_checks else None),
                prior_latency_ewma_ms=health.latency_ewma_ms,
                prior_valid_checks=health.valid_checks,
                succeeded=result.success,
                latency_ms=result.latency_ms if result.success else None,
            )
            health.success_ewma = update.success_ewma
            health.latency_ewma_ms = update.latency_ewma_ms
            health.score = update.score
            health.status = update.status
            health.valid_checks = update.valid_checks
            health.consecutive_failures = 0 if result.success else health.consecutive_failures + 1
            health.last_checked_at = now
            health.next_check_at = now + general_check_interval(update.status)
            health.last_error_code = result.error_code.value if result.error_code else None
            health.last_error_message = result.error_message
            if result.exit_ip:
                route.exit_ip = result.exit_ip
                location = self.geoip_resolver.lookup(result.exit_ip)
                if location is not None:
                    route.country_code = location.country_code
                    route.asn = location.asn
            session.add(
                CheckAttempt(
                    workspace_id=route.workspace_id,
                    job_id=UUID(envelope.job_id),
                    proxy_id=route.id,
                    success=result.success,
                    latency_ms=result.latency_ms,
                    error_code=result.error_code.value if result.error_code else None,
                    error_message=result.error_message,
                    checked_at=now,
                )
            )
            await self._enqueue_dependent_pools(session, route)

    async def check_target(self, envelope: JobEnvelope) -> None:
        if envelope.entity_id is None or envelope.workspace_id is None:
            raise ValueError("check_target job requires target and workspace IDs")
        target_id = UUID(envelope.entity_id)
        workspace_id = UUID(envelope.workspace_id)
        async with self.sessions() as session:
            target = await session.scalar(
                select(Target).where(Target.id == target_id, Target.workspace_id == workspace_id)
            )
            limits = await session.get(WorkspaceLimit, workspace_id)
            if target is None or not target.enabled or limits is None:
                return
            spec = self._target_spec(target)
            scope = (
                or_(
                    ProxyRoute.scope == ProxyScope.GLOBAL,
                    (ProxyRoute.scope == ProxyScope.PRIVATE)
                    & (ProxyRoute.workspace_id == workspace_id),
                )
                if limits.global_catalog_enabled
                else (ProxyRoute.scope == ProxyScope.PRIVATE)
                & (ProxyRoute.workspace_id == workspace_id)
            )
            routes = (
                await session.scalars(
                    select(ProxyRoute)
                    .join(ProxyHealth, ProxyHealth.proxy_id == ProxyRoute.id)
                    .where(
                        ProxyRoute.active.is_(True),
                        scope,
                        ProxyHealth.status.in_((HealthStatus.HEALTHY, HealthStatus.DEGRADED)),
                        ProxyHealth.last_checked_at >= datetime.now(UTC) - timedelta(minutes=30),
                    )
                    .order_by(ProxyRoute.id)
                )
            ).all()
            upstreams = [(route.id, self._upstream(route)) for route in routes]
            concurrency = max(1, limits.max_concurrent_checks)

        semaphore = asyncio.Semaphore(concurrency)

        async def run_one(route_id: UUID, upstream: UpstreamRoute) -> tuple[UUID, Any]:
            async with semaphore:
                return route_id, await self.check_runner.check(upstream, spec)

        results = await asyncio.gather(*(run_one(route_id, route) for route_id, route in upstreams))
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            for route_id, result in results:
                health = await session.get(
                    TargetHealth, (workspace_id, target_id, route_id), with_for_update=True
                )
                if health is None:
                    health = TargetHealth(
                        workspace_id=workspace_id,
                        target_id=target_id,
                        proxy_id=route_id,
                        availability=result.availability,
                        checked_at=now,
                    )
                    session.add(health)
                health.availability = result.availability
                health.latency_ms = result.latency_ms
                health.checked_at = now
                health.error_code = result.error_code.value if result.error_code else None
                session.add(
                    CheckAttempt(
                        workspace_id=workspace_id,
                        job_id=UUID(envelope.job_id),
                        proxy_id=route_id,
                        target_id=target_id,
                        success=result.success,
                        latency_ms=result.latency_ms,
                        error_code=result.error_code.value if result.error_code else None,
                        error_message=result.error_message,
                        availability=result.availability,
                        checked_at=now,
                    )
                )
            job = await session.get(CheckJob, UUID(envelope.job_id))
            if job is not None:
                job.progress_total = len(results)
                job.progress_current = len(results)
            if results:
                await self._enqueue_workspace_pools(session, workspace_id, "target_health_changed")

    async def refresh_source(self, envelope: JobEnvelope) -> None:
        if envelope.entity_id is None:
            raise ValueError("refresh_source job has no source ID")
        source_id = UUID(envelope.entity_id)
        run_id = uuid4()
        async with self.sessions() as session, session.begin():
            source = await session.get(Source, source_id)
            if source is None or not source.enabled:
                return
            session.add(
                SourceRun(
                    id=run_id,
                    source_id=source.id,
                    workspace_id=source.workspace_id,
                    status=JobStatus.RUNNING,
                    complete_snapshot=False,
                )
            )
            url = source.url
            default_protocol = source.default_protocol
            workspace_id = source.workspace_id
            scope = source.scope
            aad = f"source:{source.id}".encode()
            username = (
                self.keyring.decrypt_text(source.username_encrypted, associated_data=aad)
                if source.username_encrypted
                else None
            )
            password = (
                self.keyring.decrypt_text(source.password_encrypted, associated_data=aad)
                if source.password_encrypted
                else None
            )
        try:
            response = await self.feed_fetcher.fetch(url, username=username, password=password)
            parsed = parse_proxy_text(response.text(), default_protocol)
            await self._commit_source_snapshot(
                source_id,
                run_id,
                workspace_id,
                scope,
                parsed,
            )
        except Exception as exc:
            async with self.sessions() as session, session.begin():
                run = await session.get(SourceRun, run_id, with_for_update=True)
                source = await session.get(Source, source_id, with_for_update=True)
                if run is not None:
                    run.status = JobStatus.FAILED
                    run.error = {"code": "source_refresh_failed", "message": str(exc)[:500]}
                    run.finished_at = datetime.now(UTC)
                if source is not None:
                    source.last_run_at = datetime.now(UTC)
                    source.last_run_status = "failed"
            raise

    async def _commit_source_snapshot(
        self,
        source_id: UUID,
        run_id: UUID,
        workspace_id: UUID | None,
        scope: ProxyScope,
        parsed: Any,
    ) -> None:
        now = datetime.now(UTC)
        complete = not parsed.invalid
        async with self.sessions() as session, session.begin():
            source = await session.get(Source, source_id, with_for_update=True)
            run = await session.get(SourceRun, run_id, with_for_update=True)
            if source is None or run is None:
                return
            existing_routes = (
                await session.scalars(
                    select(ProxyRoute).where(
                        ProxyRoute.scope == scope,
                        ProxyRoute.workspace_id == workspace_id,
                    )
                )
            ).all()
            by_identity = {route.identity_hash: route for route in existing_routes}
            if workspace_id is not None:
                limits = await session.get(WorkspaceLimit, workspace_id)
                incoming_new = sum(
                    digest_proxy_identity(proxy.identity_hash, self.settings) not in by_identity
                    for proxy in parsed.valid
                )
                if (
                    limits is None
                    or len(existing_routes) + incoming_new > limits.max_private_proxies
                ):
                    raise ValueError("source refresh would exceed the private proxy limit")
            memberships = (
                await session.scalars(
                    select(SourceMembership).where(SourceMembership.source_id == source_id)
                )
            ).all()
            by_proxy = {membership.proxy_id: membership for membership in memberships}
            seen: set[UUID] = set()
            added = 0
            for proxy in parsed.valid:
                identity = digest_proxy_identity(proxy.identity_hash, self.settings)
                route = by_identity.get(identity)
                if route is None:
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
                            self.keyring.encrypt_text(proxy.username, associated_data=aad)
                            if proxy.username
                            else None
                        ),
                        password_encrypted=(
                            self.keyring.encrypt_text(proxy.password, associated_data=aad)
                            if proxy.password
                            else None
                        ),
                        identity_hash=identity,
                        manual=False,
                        active=True,
                    )
                    session.add(route)
                    session.add(ProxyHealth(proxy_id=route_id))
                    by_identity[identity] = route
                    added += 1
                    enqueue_job(
                        session,
                        job_type=JobType.CHECK_PROXY,
                        workspace_id=workspace_id,
                        entity_id=route.id,
                        payload={"reason": "source_discovery"},
                    )
                elif not route.active:
                    route.active = True
                    enqueue_job(
                        session,
                        job_type=JobType.CHECK_PROXY,
                        workspace_id=workspace_id,
                        entity_id=route.id,
                        payload={"reason": "source_reactivated"},
                    )
                membership = by_proxy.get(route.id)
                if membership is None:
                    membership = SourceMembership(source_id=source_id, proxy_id=route.id)
                    session.add(membership)
                    by_proxy[route.id] = membership
                membership.active = True
                membership.absent_complete_runs = 0
                membership.last_seen_at = now
                seen.add(route.id)

            deactivated = 0
            if complete:
                for membership in memberships:
                    if membership.proxy_id in seen:
                        continue
                    membership.absent_complete_runs += 1
                    if membership.absent_complete_runs >= 2 and membership.active:
                        membership.active = False
                        deactivated += 1
                await session.flush()
                affected = [item.proxy_id for item in memberships if not item.active]
                for proxy_id in affected:
                    route = await session.get(ProxyRoute, proxy_id)
                    if route is None or route.manual:
                        continue
                    active_count = await session.scalar(
                        select(func.count())
                        .select_from(SourceMembership)
                        .where(
                            SourceMembership.proxy_id == proxy_id,
                            SourceMembership.active.is_(True),
                        )
                    )
                    if not active_count:
                        route.active = False

            source.last_run_at = now
            source.last_run_status = "succeeded" if complete else "partial"
            run.status = JobStatus.SUCCEEDED
            run.complete_snapshot = complete
            run.parsed_count = len(parsed.valid)
            run.invalid_count = len(parsed.invalid)
            run.added_count = added
            run.deactivated_count = deactivated
            run.finished_at = now
            if workspace_id is not None:
                await self._enqueue_workspace_pools(session, workspace_id, "source_changed")
            else:
                pools = (
                    await session.scalars(
                        select(Pool).where(
                            Pool.enabled.is_(True),
                            Pool.catalog_selection.in_(
                                (CatalogSelection.GLOBAL, CatalogSelection.COMBINED)
                            ),
                        )
                    )
                ).all()
                await self._enqueue_pools(session, list(pools), "source_changed")

    async def materialize_pool(self, envelope: JobEnvelope) -> None:
        if envelope.entity_id is None:
            raise ValueError("materialize_pool job has no pool ID")
        await self.materializer.materialize(UUID(envelope.entity_id))
        await self.snapshot_publisher.publish()

    async def publish_snapshot(self, envelope: JobEnvelope) -> None:
        await self.snapshot_publisher.publish()

    async def retention(self, envelope: JobEnvelope) -> None:
        from .repositories import SQLAlchemyScheduleRepository

        await SQLAlchemyScheduleRepository(self.sessions).run_retention()

    def _upstream(self, route: ProxyRoute) -> UpstreamRoute:
        aad = f"proxy-route:{route.id}".encode()
        return UpstreamRoute(
            id=str(route.id),
            protocol=GatewayProxyProtocol(route.protocol.value),
            host=route.host,
            port=route.port,
            username=(
                self.keyring.decrypt_text(route.username_encrypted, associated_data=aad)
                if route.username_encrypted
                else None
            ),
            password=(
                self.keyring.decrypt_text(route.password_encrypted, associated_data=aad)
                if route.password_encrypted
                else None
            ),
            score=0,
            latency_ms=None,
        )

    def _target_spec(self, target: Target) -> CheckSpec:
        if target.kind is TargetKind.GOOGLE:
            return google_check_spec()
        if target.kind is TargetKind.BING:
            return bing_check_spec()
        if not target.url:
            raise ValueError("custom target has no URL")
        aad = f"target:{target.id}".encode()
        secret_headers = (
            self.keyring.decrypt_json(target.secret_headers_encrypted, associated_data=aad)
            if target.secret_headers_encrypted
            else {}
        )
        headers = {**target.headers, **secret_headers}
        body = (
            self.keyring.decrypt(target.body_encrypted, associated_data=aad)
            if target.body_encrypted
            else b""
        )
        return CheckSpec(
            url=target.url,
            method=target.method,
            headers=tuple((str(key), str(value)) for key, value in headers.items()),
            body=body,
            status_ranges=tuple((int(item[0]), int(item[1])) for item in target.status_ranges),
            required_patterns=tuple(target.required_patterns),
            forbidden_patterns=tuple(target.forbidden_patterns),
        )

    async def _enqueue_dependent_pools(self, session: AsyncSession, route: ProxyRoute) -> None:
        if route.scope is ProxyScope.GLOBAL:
            pools = (
                await session.scalars(
                    select(Pool).where(
                        Pool.enabled.is_(True),
                        Pool.catalog_selection.in_(
                            (CatalogSelection.GLOBAL, CatalogSelection.COMBINED)
                        ),
                    )
                )
            ).all()
        else:
            pools = (
                await session.scalars(
                    select(Pool).where(
                        Pool.workspace_id == route.workspace_id,
                        Pool.enabled.is_(True),
                        Pool.catalog_selection.in_(
                            (CatalogSelection.PRIVATE, CatalogSelection.COMBINED)
                        ),
                    )
                )
            ).all()
        await self._enqueue_pools(session, pools, "proxy_health_changed")

    async def _enqueue_workspace_pools(
        self, session: AsyncSession, workspace_id: UUID, reason: str
    ) -> None:
        pools = (
            await session.scalars(
                select(Pool).where(Pool.workspace_id == workspace_id, Pool.enabled.is_(True))
            )
        ).all()
        await self._enqueue_pools(session, pools, reason)

    @staticmethod
    async def _enqueue_pools(session: AsyncSession, pools: Sequence[Pool], reason: str) -> None:
        if not pools:
            return
        pool_ids = [pool.id for pool in pools]
        active = set(
            (
                await session.scalars(
                    select(CheckJob.entity_id).where(
                        CheckJob.type == JobType.MATERIALIZE_POOL,
                        CheckJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
                        CheckJob.entity_id.in_(pool_ids),
                    )
                )
            ).all()
        )
        for pool in pools:
            if pool.id not in active:
                enqueue_job(
                    session,
                    job_type=JobType.MATERIALIZE_POOL,
                    workspace_id=pool.workspace_id,
                    entity_id=pool.id,
                    payload={"reason": reason},
                )


def _nonce_url(url: str) -> str:
    parsed = urlsplit(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("nonce", secrets.token_urlsafe(12)))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
