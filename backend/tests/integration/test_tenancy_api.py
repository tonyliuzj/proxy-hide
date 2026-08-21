from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    CheckJob,
    Filter,
    JobType,
    Operation,
    Pool,
    PoolStrategy,
    ProxyHealth,
    ProxyProtocol,
    ProxyRoute,
    ProxyScope,
    User,
    UserRole,
    Workspace,
    WorkspaceLimit,
)
from app.security import hash_password
from app.workers.jobs import JobEnvelope
from app.workers.repositories import SQLAlchemyJobRepository

SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class SeededTenancyData:
    workspace_one_id: UUID
    pool_id: UUID
    own_proxy_id: UUID
    other_proxy_id: UUID
    global_proxy_id: UUID


async def _seed(session_factory: SessionFactory) -> SeededTenancyData:
    async with session_factory() as db:
        one = Workspace(name="One", slug="one")
        two = Workspace(name="Two", slug="two")
        db.add_all([one, two])
        await db.flush()
        db.add_all([WorkspaceLimit(workspace_id=one.id), WorkspaceLimit(workspace_id=two.id)])
        db.add_all(
            [
                User(
                    workspace_id=one.id,
                    email="one@example.com",
                    password_hash=hash_password("workspace one password"),
                    role=UserRole.WORKSPACE_OWNER,
                ),
                User(
                    workspace_id=two.id,
                    email="two@example.com",
                    password_hash=hash_password("workspace two password"),
                    role=UserRole.WORKSPACE_OWNER,
                ),
            ]
        )
        own = ProxyRoute(
            workspace_id=one.id,
            scope=ProxyScope.PRIVATE,
            protocol=ProxyProtocol.HTTP,
            host="one.example",
            port=80,
            identity_hash="one",
        )
        other = ProxyRoute(
            workspace_id=two.id,
            scope=ProxyScope.PRIVATE,
            protocol=ProxyProtocol.HTTP,
            host="two.example",
            port=80,
            identity_hash="two",
        )
        global_route = ProxyRoute(
            scope=ProxyScope.GLOBAL,
            protocol=ProxyProtocol.HTTP,
            host="global.example",
            port=80,
            identity_hash="global",
        )
        db.add_all([own, other, global_route])
        await db.flush()
        db.add_all(
            [
                ProxyHealth(proxy_id=own.id),
                ProxyHealth(proxy_id=other.id),
                ProxyHealth(proxy_id=global_route.id),
            ]
        )
        rules = {
            "version": 1,
            "root": {
                "op": "all",
                "rules": [
                    {"op": "predicate", "field": "health", "operator": "eq", "value": "healthy"}
                ],
            },
        }
        filter_value = Filter(workspace_id=one.id, name="healthy", rules=rules)
        db.add(filter_value)
        await db.flush()
        pool = Pool(
            workspace_id=one.id,
            filter_id=filter_value.id,
            name="main",
            strategy=PoolStrategy.WEIGHTED_HEALTH,
        )
        db.add(pool)
        await db.commit()
        return SeededTenancyData(
            workspace_one_id=one.id,
            pool_id=pool.id,
            own_proxy_id=own.id,
            other_proxy_id=other.id,
            global_proxy_id=global_route.id,
        )


async def _login(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "one@example.com", "password": "workspace one password"},
    )
    assert response.status_code == 200, response.text
    csrf_token = response.json()["csrf_token"]
    assert isinstance(csrf_token, str)
    return csrf_token


async def test_workspace_inventory_is_isolated_and_global_rows_are_masked(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    await _seed(session_factory)
    await _login(client)
    response = await client.get("/api/v1/proxies")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 2
    private = next(item for item in payload["items"] if item["scope"] == "private")
    global_route = next(item for item in payload["items"] if item["scope"] == "global")
    assert private["host"] == "one.example"
    assert global_route["host"] is None
    assert "two.example" not in response.text


async def test_endpoint_secret_is_returned_once_and_csrf_is_enforced(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    seeded = await _seed(session_factory)
    csrf = await _login(client)
    request = {
        "name": "Main endpoint",
        "pool_id": str(seeded.pool_id),
        "username": "workspace-one",
        "ip_allowlist": [],
    }
    rejected = await client.post("/api/v1/endpoints", json=request)
    assert rejected.status_code == 403
    created = await client.post("/api/v1/endpoints", json=request, headers={"X-CSRF-Token": csrf})
    assert created.status_code == 201, created.text
    assert created.json()["secret"]
    assert created.headers["cache-control"] == "no-store"
    listed = await client.get("/api/v1/endpoints")
    assert listed.status_code == 200
    assert "secret" not in listed.json()["items"][0]


async def test_pool_materialization_operation_tracks_its_single_job(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    seeded = await _seed(session_factory)
    csrf = await _login(client)

    response = await client.post(
        f"/api/v1/pools/{seeded.pool_id}/materialize",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["progress_current"] == 0
    assert payload["progress_total"] == 1
    operation_id = UUID(payload["id"])
    async with session_factory() as db:
        job = await db.scalar(
            select(CheckJob).where(
                CheckJob.workspace_id == seeded.workspace_one_id,
                CheckJob.entity_id == seeded.pool_id,
                CheckJob.type == JobType.MATERIALIZE_POOL,
            )
        )
        assert job is not None
        assert job.payload["operation_id"] == str(operation_id)

    envelope = JobEnvelope(
        job_id=str(job.id),
        type=JobType.MATERIALIZE_POOL.value,
        workspace_id=str(seeded.workspace_one_id),
        entity_id=str(seeded.pool_id),
    )
    repository = SQLAlchemyJobRepository(session_factory)
    assert await repository.claim(envelope)
    await repository.succeed(envelope)

    async with session_factory() as db:
        operation = await db.get(Operation, operation_id)
        assert operation is not None
        assert operation.status.value == "succeeded"
        assert operation.progress_current == 1
        assert operation.progress_total == 1


async def test_manual_check_allows_own_private_proxy(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    seeded = await _seed(session_factory)
    csrf = await _login(client)

    response = await client.post(
        f"/api/v1/proxies/{seeded.own_proxy_id}/check",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["type"] == "check_proxy"
    assert payload["status"] == "queued"
    assert payload["entity_id"] == str(seeded.own_proxy_id)
    async with session_factory() as db:
        job = await db.get(CheckJob, UUID(payload["id"]))
        assert job is not None
        assert job.workspace_id == seeded.workspace_one_id
        assert job.payload == {"reason": "manual"}


async def test_manual_check_allows_global_proxy_when_catalog_is_enabled(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    seeded = await _seed(session_factory)
    csrf = await _login(client)

    response = await client.post(
        f"/api/v1/proxies/{seeded.global_proxy_id}/check",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["entity_id"] == str(seeded.global_proxy_id)
    async with session_factory() as db:
        job = await db.get(CheckJob, UUID(payload["id"]))
        assert job is not None
        assert job.workspace_id == seeded.workspace_one_id
        assert job.payload == {"reason": "manual"}


async def test_manual_check_hides_cross_tenant_private_proxy(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    seeded = await _seed(session_factory)
    csrf = await _login(client)

    response = await client.post(
        f"/api/v1/proxies/{seeded.other_proxy_id}/check",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "PROXY_NOT_FOUND"


async def test_manual_check_hides_global_proxy_when_catalog_is_disabled(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    seeded = await _seed(session_factory)
    async with session_factory() as db:
        limits = await db.get(WorkspaceLimit, seeded.workspace_one_id)
        assert limits is not None
        limits.global_catalog_enabled = False
        await db.commit()
    csrf = await _login(client)

    response = await client.post(
        f"/api/v1/proxies/{seeded.global_proxy_id}/check",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "PROXY_NOT_FOUND"
