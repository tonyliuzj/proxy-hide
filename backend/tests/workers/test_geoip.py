from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    CheckAttempt,
    CheckJob,
    JobType,
    ProxyHealth,
    ProxyProtocol,
    ProxyRoute,
    ProxyScope,
    TargetAvailability,
)
from app.security import KeyRing
from app.workers.checks import CheckResult
from app.workers.geoip import GeoIPResolver, GeoIPResult
from app.workers.handlers import WorkerHandlers
from app.workers.jobs import JobEnvelope


class FakeReader:
    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record
        self.closed = False

    def get(self, address: str) -> dict[str, Any]:
        assert address == "203.0.113.42"
        return self.record

    def close(self) -> None:
        self.closed = True


def test_geoip_extracts_country_and_asn(monkeypatch, tmp_path: Path) -> None:
    reader = FakeReader(
        {"country": {"iso_code": "gb"}, "autonomous_system_number": 64500}
    )
    monkeypatch.setattr("maxminddb.open_database", lambda _path: reader)
    resolver = GeoIPResolver(str(tmp_path / "GeoIP.mmdb"))

    assert resolver.lookup("203.0.113.42") is not None
    result = resolver.lookup("203.0.113.42")
    assert result is not None
    assert result.country_code == "GB"
    assert result.asn == 64500

    resolver.close()
    assert reader.closed


def test_geoip_missing_database_is_optional(tmp_path: Path) -> None:
    resolver = GeoIPResolver(str(tmp_path / "missing.mmdb"))

    assert resolver.lookup("203.0.113.42") is None
    assert resolver.lookup("not-an-ip") is None


class SuccessfulRunner:
    async def check(self, *_args: Any, **_kwargs: Any) -> CheckResult:
        return CheckResult(
            success=True,
            latency_ms=125.0,
            status_code=200,
            availability=TargetAvailability.AVAILABLE,
            exit_ip="8.8.8.8",
        )


class FixedResolver:
    def lookup(self, address: str) -> GeoIPResult:
        assert address == "8.8.8.8"
        return GeoIPResult(country_code="US", asn=15169)


async def test_proxy_check_commits_exit_location(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = uuid4()
    async with session_factory() as db, db.begin():
        route = ProxyRoute(
            scope=ProxyScope.GLOBAL,
            protocol=ProxyProtocol.HTTP,
            host="proxy.example",
            port=8080,
            identity_hash="geoip-test-route",
        )
        db.add(route)
        await db.flush()
        route_id = route.id
        db.add(ProxyHealth(proxy_id=route_id))
        db.add(
            CheckJob(
                id=job_id,
                type=JobType.CHECK_PROXY,
                entity_id=route_id,
                deduplication_key="geoip-test-job",
            )
        )

    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite://")
    handler = WorkerHandlers(
        session_factory,
        settings,
        KeyRing.from_settings(settings),
        cast(Any, SuccessfulRunner()),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, FixedResolver()),
    )
    await handler.check_proxy(
        JobEnvelope(
            job_id=str(job_id),
            type=JobType.CHECK_PROXY.value,
            workspace_id=None,
            entity_id=str(route_id),
        )
    )

    async with session_factory() as db:
        saved_route = await db.get(ProxyRoute, route_id)
        saved_health = await db.get(ProxyHealth, route_id)
        attempts = (await db.scalars(CheckAttempt.__table__.select())).all()
        assert saved_route is not None
        assert saved_route.exit_ip == "8.8.8.8"
        assert saved_route.country_code == "US"
        assert saved_route.asn == 15169
        assert saved_health is not None
        assert saved_health.valid_checks == 1
        assert len(attempts) == 1
