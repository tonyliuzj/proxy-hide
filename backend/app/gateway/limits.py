from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from .errors import PoolUnavailable
from .models import EndpointSnapshot


class SlidingWindowRateLimiter:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, workspace_id: str, limit: int, *, period: float = 60.0) -> bool:
        now = self._clock()
        async with self._lock:
            requests = self._requests[workspace_id]
            while requests and requests[0] <= now - period:
                requests.popleft()
            if len(requests) >= limit:
                return False
            requests.append(now)
            return True


class ConnectionLimiter:
    def __init__(self, *, global_limit: int = 10_000, per_ip_limit: int = 500) -> None:
        self.global_limit = global_limit
        self.per_ip_limit = per_ip_limit
        self._global = 0
        self._by_ip: dict[str, int] = defaultdict(int)
        self._by_workspace: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, client_ip: str, endpoint: EndpointSnapshot) -> AsyncIterator[None]:
        async with self._lock:
            if (
                self._global >= self.global_limit
                or self._by_ip[client_ip] >= self.per_ip_limit
                or self._by_workspace[endpoint.workspace_id] >= endpoint.max_connections
            ):
                raise PoolUnavailable("connection limit exceeded")
            self._global += 1
            self._by_ip[client_ip] += 1
            self._by_workspace[endpoint.workspace_id] += 1
        try:
            yield
        finally:
            async with self._lock:
                self._global -= 1
                self._by_ip[client_ip] -= 1
                self._by_workspace[endpoint.workspace_id] -= 1
