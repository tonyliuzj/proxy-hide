from __future__ import annotations

import asyncio
import math
import random
import time
from collections import defaultdict

from .models import PoolSnapshot, PoolStrategy, UpstreamRoute


class QuarantineRegistry:
    def __init__(self, *, cooldown_seconds: float = 60.0, failure_threshold: int = 1) -> None:
        self.cooldown_seconds = cooldown_seconds
        self.failure_threshold = max(1, failure_threshold)
        self._failures: dict[str, int] = defaultdict(int)
        self._until: dict[str, float] = {}

    def available(self, route_id: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        until = self._until.get(route_id, 0.0)
        if until <= current:
            self._until.pop(route_id, None)
            return True
        return False

    def fail(self, route_id: str, *, now: float | None = None) -> None:
        self._failures[route_id] += 1
        if self._failures[route_id] >= self.failure_threshold:
            current = time.monotonic() if now is None else now
            self._until[route_id] = current + self.cooldown_seconds
            self._failures[route_id] = 0

    def succeed(self, route_id: str) -> None:
        self._failures.pop(route_id, None)
        self._until.pop(route_id, None)


class CandidateSelector:
    def __init__(
        self, quarantine: QuarantineRegistry | None = None, *, rng: random.Random | None = None
    ) -> None:
        self.quarantine = quarantine or QuarantineRegistry()
        self._rng = rng or random.SystemRandom()
        self._round_robin: dict[str, int] = defaultdict(int)
        self._sticky: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def select(
        self,
        pool: PoolSnapshot,
        *,
        limit: int = 3,
        strategy: PoolStrategy | None = None,
        scope: str | None = None,
    ) -> tuple[UpstreamRoute, ...]:
        """Order candidate routes for one connection attempt.

        ``strategy`` overrides the pool's rotation mode. ``scope`` keys the round-robin
        and sticky state so endpoints sharing a pool do not disturb each other.
        """
        routes = [route for route in pool.routes if self.quarantine.available(route.id)]
        if not routes:
            return ()
        count = min(max(1, limit), len(routes))
        mode = strategy or pool.strategy
        state_key = scope or pool.id
        if mode is PoolStrategy.RANDOM:
            return tuple(self._rng.sample(routes, count))
        if mode is PoolStrategy.STICKY:
            return await self._sticky_choice(state_key, routes, count)
        if mode is PoolStrategy.LOWEST_LATENCY:
            return tuple(
                sorted(
                    routes,
                    key=lambda route: (
                        math.inf if route.latency_ms is None else route.latency_ms,
                        -route.score,
                        route.id,
                    ),
                )[:count]
            )
        if mode is PoolStrategy.WEIGHTED_HEALTH:
            return tuple(self._weighted_without_replacement(routes, count))
        async with self._lock:
            start = self._round_robin[state_key] % len(routes)
            self._round_robin[state_key] = (start + 1) % len(routes)
        ordered = routes[start:] + routes[:start]
        return tuple(ordered[:count])

    async def _sticky_choice(
        self, state_key: str, routes: list[UpstreamRoute], count: int
    ) -> tuple[UpstreamRoute, ...]:
        """Stay on one route until it is quarantined or leaves the pool, then re-pin.

        A route that recovers does not win the pin back; "no rotation" means the
        exit address only changes when the current one stops working.
        """
        async with self._lock:
            pinned = self._sticky.get(state_key)
            current = next((route for route in routes if route.id == pinned), None)
            if current is None:
                current = routes[0]
                self._sticky[state_key] = current.id
        fallbacks = [route for route in routes if route.id != current.id]
        return (current, *fallbacks[: count - 1])

    def _weighted_without_replacement(
        self, routes: list[UpstreamRoute], count: int
    ) -> list[UpstreamRoute]:
        remaining = list(routes)
        selected: list[UpstreamRoute] = []
        for _ in range(count):
            weights = [max(route.score, 1.0) ** 2 for route in remaining]
            total = sum(weights)
            point = self._rng.random() * total
            cumulative = 0.0
            index = len(remaining) - 1
            for candidate_index, weight in enumerate(weights):
                cumulative += weight
                if point <= cumulative:
                    index = candidate_index
                    break
            selected.append(remaining.pop(index))
        return selected
