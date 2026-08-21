from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.workers.jobs import JobEnvelope, RedisStreamWorker


class Repository:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.claimed = True

    async def claim(self, job: JobEnvelope) -> bool:
        self.events.append("claim")
        return self.claimed

    async def succeed(self, job: JobEnvelope) -> None:
        self.events.append("succeed")

    async def fail(self, job: JobEnvelope, error: str, *, terminal: bool) -> None:
        self.events.append(f"fail:{terminal}")


class Redis:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.events: list[str] = []
        self.added: list[tuple[str, dict[str, str]]] = []

    async def xack(self, stream: str, group: str, message_id: object) -> None:
        assert self.repository.events[-1] in {"succeed", "claim", "fail:False", "fail:True"}
        self.events.append("ack")

    async def xadd(self, stream: str, fields: Mapping[str, str]) -> None:
        self.added.append((stream, dict(fields)))


@pytest.mark.asyncio
async def test_worker_acknowledges_only_after_database_success() -> None:
    repository = Repository()
    redis = Redis(repository)

    async def handler(job: JobEnvelope) -> None:
        repository.events.append("handler")

    worker = RedisStreamWorker(redis, repository, {"check_proxy": handler})
    await worker.process("1-0", {"job_id": "job", "type": "check_proxy", "attempt": "0"})

    assert repository.events == ["claim", "handler", "succeed"]
    assert redis.events == ["ack"]


@pytest.mark.asyncio
async def test_worker_requeues_then_dead_letters_terminal_failure() -> None:
    repository = Repository()
    redis = Redis(repository)

    async def failing(job: JobEnvelope) -> None:
        raise RuntimeError("broken")

    worker = RedisStreamWorker(redis, repository, {"check_proxy": failing}, max_attempts=2)
    await worker.process("1-0", {"job_id": "job", "type": "check_proxy", "attempt": "0"})
    await worker.process("2-0", {"job_id": "job", "type": "check_proxy", "attempt": "1"})

    assert [item[0] for item in redis.added] == ["proxyhide:jobs", "proxyhide:jobs:dead"]
    assert repository.events == ["claim", "fail:False", "claim", "fail:True"]
    assert redis.events == ["ack", "ack"]
