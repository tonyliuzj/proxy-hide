from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class GatewayEvent:
    endpoint_id: str
    workspace_id: str
    pool_id: str
    route_id: str | None
    outcome: str
    latency_ms: float
    bytes_up: int = 0
    bytes_down: int = 0
    occurred_at: float = 0.0

    def payload(self) -> dict[str, str]:
        data = asdict(self)
        if not data["occurred_at"]:
            data["occurred_at"] = time.time()
        return {key: str(value) for key, value in data.items() if value is not None}


class StreamWriter(Protocol):
    async def xadd(self, stream: str, fields: dict[str, str], **kwargs: Any) -> Any: ...


class TelemetryBuffer:
    def __init__(self, *, maxsize: int = 10_000) -> None:
        self.queue: asyncio.Queue[GatewayEvent] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0
        self._stopped = asyncio.Event()

    def emit(self, event: GatewayEvent) -> bool:
        try:
            self.queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self.dropped += 1
            return False

    async def run(self, redis: StreamWriter, *, stream: str = "proxyhide:gateway:events") -> None:
        while not self._stopped.is_set():
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                await redis.xadd(stream, event.payload(), maxlen=100_000, approximate=True)
            except (OSError, TimeoutError):
                self.dropped += 1
            finally:
                self.queue.task_done()

    def stop(self) -> None:
        self._stopped.set()
