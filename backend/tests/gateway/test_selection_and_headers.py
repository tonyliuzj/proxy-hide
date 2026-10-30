from __future__ import annotations

import random

import pytest

from app.gateway.errors import BadRequest
from app.gateway.headers import sanitized_request_headers
from app.gateway.models import PoolSnapshot, PoolStrategy, ProxyProtocol, UpstreamRoute
from app.gateway.selection import CandidateSelector, QuarantineRegistry


def routes() -> tuple[UpstreamRoute, ...]:
    return (
        UpstreamRoute("slow", ProxyProtocol.HTTP, "one.example", 80, score=40, latency_ms=500),
        UpstreamRoute("fast", ProxyProtocol.HTTP, "two.example", 80, score=90, latency_ms=100),
        UpstreamRoute("unknown", ProxyProtocol.HTTP, "three.example", 80, score=50),
    )


@pytest.mark.asyncio
async def test_lowest_latency_and_round_robin_are_deterministic() -> None:
    selector = CandidateSelector(rng=random.Random(1))
    lowest = PoolSnapshot("pool", 1, PoolStrategy.LOWEST_LATENCY, routes())
    assert [item.id for item in await selector.select(lowest)] == ["fast", "slow", "unknown"]

    rotating = PoolSnapshot("round", 1, PoolStrategy.ROUND_ROBIN, routes())
    assert (await selector.select(rotating, limit=1))[0].id == "slow"
    assert (await selector.select(rotating, limit=1))[0].id == "fast"


@pytest.mark.asyncio
async def test_quarantine_removes_failed_routes_until_cooldown() -> None:
    quarantine = QuarantineRegistry(cooldown_seconds=60)
    selector = CandidateSelector(quarantine, rng=random.Random(2))
    pool = PoolSnapshot("pool", 1, PoolStrategy.LOWEST_LATENCY, routes())
    quarantine.fail("fast")

    selected = await selector.select(pool)
    assert "fast" not in {item.id for item in selected}


def test_request_header_sanitization_preserves_origin_auth_and_strips_hops() -> None:
    headers = sanitized_request_headers(
        [
            (b"Host", b"example.test"),
            (b"Authorization", b"Bearer origin"),
            (b"Proxy-Authorization", b"Basic client-secret"),
            (b"Connection", b"x-remove"),
            (b"X-Remove", b"secret"),
            (b"X-Keep", b"yes"),
        ],
        authority="example.test",
    )
    normalized = {key.lower(): value for key, value in headers}
    assert normalized[b"authorization"] == b"Bearer origin"
    assert normalized[b"x-keep"] == b"yes"
    assert b"proxy-authorization" not in normalized
    assert b"x-remove" not in normalized


def test_request_smuggling_headers_are_rejected() -> None:
    with pytest.raises(BadRequest):
        sanitized_request_headers(
            [(b"Host", b"example"), (b"Transfer-Encoding", b"chunked"), (b"Content-Length", b"3")],
            authority="example",
        )


@pytest.mark.asyncio
async def test_sticky_stays_on_one_route_until_it_is_quarantined() -> None:
    quarantine = QuarantineRegistry(cooldown_seconds=60)
    selector = CandidateSelector(quarantine, rng=random.Random(3))
    pool = PoolSnapshot("pool", 1, PoolStrategy.STICKY, routes())

    first = (await selector.select(pool, limit=1))[0].id
    assert first == "slow"  # first route in pool order
    assert [(await selector.select(pool, limit=1))[0].id for _ in range(5)] == [first] * 5

    quarantine.fail(first)
    moved = (await selector.select(pool, limit=1))[0].id
    assert moved != first
    quarantine.succeed(first)  # recovery does not win the pin back
    assert (await selector.select(pool, limit=1))[0].id == moved


@pytest.mark.asyncio
async def test_sticky_offers_fallbacks_for_the_same_request() -> None:
    selector = CandidateSelector(rng=random.Random(4))
    pool = PoolSnapshot("pool", 1, PoolStrategy.STICKY, routes())
    selected = await selector.select(pool, limit=3)
    assert [item.id for item in selected] == ["slow", "fast", "unknown"]


@pytest.mark.asyncio
async def test_endpoint_strategy_overrides_the_pool_and_keeps_separate_state() -> None:
    selector = CandidateSelector(rng=random.Random(5))
    pool = PoolSnapshot("pool", 1, PoolStrategy.RANDOM, routes())

    fastest = await selector.select(pool, limit=1, strategy=PoolStrategy.LOWEST_LATENCY)
    assert fastest[0].id == "fast"

    kwargs = {"limit": 1, "strategy": PoolStrategy.ROUND_ROBIN}
    a = [(await selector.select(pool, scope="pool:a", **kwargs))[0].id for _ in range(2)]  # type: ignore[arg-type]
    b = [(await selector.select(pool, scope="pool:b", **kwargs))[0].id for _ in range(2)]  # type: ignore[arg-type]
    assert a == b == ["slow", "fast"]
