from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.domain.filters import (
    FilterValidationError,
    catalog_scope_clause,
    compile_filter,
    validate_filter,
)
from app.models import ProxyHealth, ProxyProtocol, ProxyRoute, ProxyScope, Workspace


def test_nested_filter_validates_and_compiles() -> None:
    workspace_id = uuid4()
    payload = {
        "version": 1,
        "root": {
            "op": "all",
            "rules": [
                {"op": "predicate", "field": "country", "operator": "eq", "value": "GB"},
                {
                    "op": "any",
                    "rules": [
                        {"op": "predicate", "field": "score", "operator": "gte", "value": 85},
                        {
                            "op": "predicate",
                            "field": "target_availability",
                            "operator": "eq",
                            "target_id": str(uuid4()),
                            "value": "available",
                        },
                    ],
                },
            ],
        },
    }
    assert validate_filter(payload).version == 1
    statement = (
        select(ProxyRoute).outerjoin(ProxyHealth).where(compile_filter(payload, workspace_id))
    )
    sql = str(statement)
    assert "proxy_routes.country_code" in sql
    assert "EXISTS" in sql


def test_filter_rejects_unknown_fields_and_bad_target_ids() -> None:
    with pytest.raises(FilterValidationError) as captured:
        validate_filter(
            {
                "op": "all",
                "rules": [
                    {"op": "predicate", "field": "secret", "operator": "eq", "value": 1},
                    {
                        "op": "predicate",
                        "field": "target_availability",
                        "operator": "eq",
                        "target_id": "wrong",
                        "value": "available",
                    },
                ],
            }
        )
    assert len(captured.value.errors) == 2


@pytest.mark.asyncio
async def test_combined_catalog_prefers_matching_private_route(session_factory) -> None:
    workspace = Workspace(name="One", slug="one")
    async with session_factory() as db:
        db.add(workspace)
        await db.flush()
        global_shadowed = ProxyRoute(
            scope=ProxyScope.GLOBAL,
            protocol=ProxyProtocol.HTTP,
            host="global.example",
            port=80,
            identity_hash="same",
        )
        global_unique = ProxyRoute(
            scope=ProxyScope.GLOBAL,
            protocol=ProxyProtocol.HTTP,
            host="unique.example",
            port=80,
            identity_hash="unique",
        )
        private = ProxyRoute(
            workspace_id=workspace.id,
            scope=ProxyScope.PRIVATE,
            protocol=ProxyProtocol.HTTP,
            host="private.example",
            port=80,
            identity_hash="same",
        )
        db.add_all([global_shadowed, global_unique, private])
        await db.commit()
        routes = list(
            (
                await db.scalars(
                    select(ProxyRoute).where(
                        catalog_scope_clause("combined", workspace.id),
                        ProxyRoute.active.is_(True),
                    )
                )
            ).all()
        )
    assert {route.host for route in routes} == {"private.example", "unique.example"}
