from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


def _text(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


@dataclass(frozen=True, slots=True)
class JobEnvelope:
    job_id: str
    type: str
    workspace_id: str | None
    entity_id: str | None
    attempt: int = 0

    @classmethod
    def from_fields(cls, fields: Mapping[object, object]) -> JobEnvelope:
        normalized = {_text(key): _text(value) for key, value in fields.items()}
        job_id = normalized.get("job_id")
        job_type = normalized.get("type")
        if not job_id or not job_type:
            raise ValueError("job stream entry requires job_id and type")
        try:
            attempt = int(normalized.get("attempt") or 0)
        except ValueError as exc:
            raise ValueError("job attempt must be numeric") from exc
        return cls(
            job_id=job_id,
            type=job_type,
            workspace_id=normalized.get("workspace_id") or None,
            entity_id=normalized.get("entity_id") or None,
            attempt=max(0, attempt),
        )

    def fields(self, *, attempt: int | None = None) -> dict[str, str]:
        return {
            "job_id": self.job_id,
            "type": self.type,
            "workspace_id": self.workspace_id or "",
            "entity_id": self.entity_id or "",
            "attempt": str(self.attempt if attempt is None else attempt),
        }


class JobRepository(Protocol):
    async def claim(self, job: JobEnvelope) -> bool:
        """Atomically transition QUEUED to RUNNING; false means already handled."""

    async def succeed(self, job: JobEnvelope) -> None: ...

    async def fail(self, job: JobEnvelope, error: str, *, terminal: bool) -> None: ...


JobHandler = Callable[[JobEnvelope], Awaitable[None]]


class RedisStreamWorker:
    def __init__(
        self,
        redis: Any,
        repository: JobRepository,
        handlers: Mapping[str, JobHandler],
        *,
        stream: str = "proxyhide:jobs",
        group: str = "workers",
        consumer: str = "worker-1",
        dead_letter_stream: str = "proxyhide:jobs:dead",
        max_attempts: int = 5,
        block_ms: int = 5_000,
        reclaim_idle_ms: int = 60_000,
    ) -> None:
        self.redis = redis
        self.repository = repository
        self.handlers = dict(handlers)
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.dead_letter_stream = dead_letter_stream
        self.max_attempts = max(1, max_attempts)
        self.block_ms = block_ms
        self.reclaim_idle_ms = reclaim_idle_ms
        self._stopped = asyncio.Event()
        self._reclaim_cursor = "0-0"

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def run(self) -> None:
        await self.ensure_group()
        while not self._stopped.is_set():
            await self.reclaim_once()
            entries = await self.redis.xreadgroup(
                self.group,
                self.consumer,
                {self.stream: ">"},
                count=10,
                block=self.block_ms,
            )
            for _, messages in entries or ():
                for message_id, fields in messages:
                    await self.process(message_id, fields)

    async def process(self, message_id: str | bytes, fields: Mapping[object, object]) -> None:
        try:
            job = JobEnvelope.from_fields(fields)
        except ValueError as exc:
            await self._dead_letter_raw(message_id, fields, str(exc))
            return
        claimed = await self.repository.claim(job)
        if not claimed:
            await self.redis.xack(self.stream, self.group, message_id)
            return
        handler = self.handlers.get(job.type)
        if handler is None:
            await self._fail(message_id, job, f"unsupported job type: {job.type}")
            return
        try:
            await handler(job)
            await self.repository.succeed(job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail(message_id, job, f"{type(exc).__name__}: {exc}")
            return
        # The database commit in succeed happens before acknowledgement.
        await self.redis.xack(self.stream, self.group, message_id)

    async def _fail(self, message_id: str | bytes, job: JobEnvelope, error: str) -> None:
        next_attempt = job.attempt + 1
        terminal = next_attempt >= self.max_attempts
        await self.repository.fail(job, error[:500], terminal=terminal)
        target = self.dead_letter_stream if terminal else self.stream
        fields = job.fields(attempt=next_attempt)
        fields["error"] = error[:500]
        await self._publish_and_ack(message_id, target, fields)

    async def _dead_letter_raw(
        self,
        message_id: str | bytes,
        fields: Mapping[object, object],
        error: str,
    ) -> None:
        normalized = {str(_text(key)): str(_text(value) or "") for key, value in fields.items()}
        normalized["error"] = error[:500]
        await self._publish_and_ack(message_id, self.dead_letter_stream, normalized)

    async def _publish_and_ack(
        self,
        message_id: str | bytes,
        target_stream: str,
        fields: Mapping[str, str],
    ) -> None:
        pipeline_factory = getattr(self.redis, "pipeline", None)
        if pipeline_factory is None:
            await self.redis.xadd(target_stream, dict(fields))
            await self.redis.xack(self.stream, self.group, message_id)
            return
        pipeline = pipeline_factory(transaction=True)
        result = pipeline.xadd(target_stream, dict(fields))
        if inspect.isawaitable(result):
            await result
        result = pipeline.xack(self.stream, self.group, message_id)
        if inspect.isawaitable(result):
            await result
        await pipeline.execute()

    async def reclaim_once(self) -> int:
        xautoclaim = getattr(self.redis, "xautoclaim", None)
        if xautoclaim is None:
            return 0
        try:
            result = await xautoclaim(
                self.stream,
                self.group,
                self.consumer,
                min_idle_time=self.reclaim_idle_ms,
                start_id=self._reclaim_cursor,
                count=10,
            )
        except Exception as exc:
            if "NOGROUP" in str(exc):
                return 0
            raise
        if not result:
            return 0
        self._reclaim_cursor = _text(result[0]) or "0-0"
        messages = result[1] if len(result) > 1 else ()
        for message_id, fields in messages:
            await self.process(message_id, fields)
        return len(messages)

    def stop(self) -> None:
        self._stopped.set()
