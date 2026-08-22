from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class OutboxItem:
    id: str
    topic: str
    payload: dict[str, Any]


class OutboxRepository(Protocol):
    async def claim_batch(self, limit: int) -> list[OutboxItem]: ...

    async def mark_published(self, item_id: str) -> None: ...

    async def mark_failed(self, item_id: str, error: str) -> None: ...


class OutboxDispatcher:
    """At-least-once database outbox publisher; consumers deduplicate by job_id."""

    def __init__(
        self,
        redis: Any,
        repository: OutboxRepository,
        *,
        jobs_stream: str = "proxyhide:jobs",
        priority_jobs_stream: str = "proxyhide:jobs:priority",
        batch_size: int = 100,
        idle_seconds: float = 1.0,
    ) -> None:
        self.redis = redis
        self.repository = repository
        self.jobs_stream = jobs_stream
        self.priority_jobs_stream = priority_jobs_stream
        self.batch_size = batch_size
        self.idle_seconds = idle_seconds
        self._stopped = asyncio.Event()

    async def dispatch_once(self) -> int:
        items = await self.repository.claim_batch(self.batch_size)
        published = 0
        for item in items:
            try:
                fields = {
                    str(key): "" if value is None else str(value)
                    for key, value in item.payload.items()
                }
                stream = (
                    self.priority_jobs_stream if item.topic == "jobs_priority" else self.jobs_stream
                )
                await self.redis.xadd(stream, fields)
                await self.repository.mark_published(item.id)
                published += 1
            except Exception as exc:
                await self.repository.mark_failed(item.id, f"{type(exc).__name__}: {exc}"[:500])
        return published

    async def run(self) -> None:
        while not self._stopped.is_set():
            count = await self.dispatch_once()
            if count:
                continue
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.idle_seconds)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stopped.set()
