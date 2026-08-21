from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import json
import time
from collections.abc import Callable
from typing import Any, Protocol

from redis.exceptions import RedisError

from app.security import KeyRing

from .errors import PoolUnavailable
from .models import EndpointSnapshot, GatewaySnapshot, PoolSnapshot


class AsyncRedisLike(Protocol):
    async def get(self, key: str) -> bytes | str | None: ...

    def pubsub(self) -> Any: ...


SNAPSHOT_AAD = b"proxyhide:gateway:snapshot:v1"


class EncryptedSnapshotCodec:
    """Authenticated snapshot envelope safe to persist in Redis/AOF."""

    def __init__(self, keyring: KeyRing) -> None:
        self.keyring = keyring

    def encode(self, snapshot: dict[str, Any]) -> bytes:
        encrypted = self.keyring.encrypt_json(snapshot, associated_data=SNAPSHOT_AAD)
        envelope = {
            "schema_version": 1,
            "key_id": self.keyring.primary_key_id,
            "ciphertext": base64.b64encode(encrypted).decode("ascii"),
        }
        return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def decode(self, payload: bytes | str) -> dict[str, Any]:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        envelope = json.loads(payload)
        if not isinstance(envelope, dict) or envelope.get("schema_version") != 1:
            raise ValueError("unsupported gateway snapshot envelope")
        encoded = envelope.get("ciphertext")
        if not isinstance(encoded, str):
            raise ValueError("gateway snapshot ciphertext is missing")
        encrypted = base64.b64decode(encoded, validate=True)
        result = self.keyring.decrypt_json(encrypted, associated_data=SNAPSHOT_AAD)
        if not isinstance(result, dict):
            raise ValueError("decrypted gateway snapshot must be an object")
        return result


class SnapshotStore:
    """Atomic, versioned last-known-good snapshot with a bounded outage window."""

    def __init__(
        self, *, stale_after: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.stale_after = stale_after
        self._clock = clock
        self._snapshot = GatewaySnapshot.empty()
        self._last_refresh: float | None = None
        self._redis_available = False
        self._lock = asyncio.Lock()

    @property
    def version(self) -> int:
        return self._snapshot.version

    @property
    def ready(self) -> bool:
        return self._last_refresh is not None and not self.stale

    @property
    def stale(self) -> bool:
        if self._last_refresh is None:
            return True
        return not self._redis_available and self._clock() - self._last_refresh > self.stale_after

    async def install(self, snapshot: GatewaySnapshot) -> bool:
        async with self._lock:
            if snapshot.version < self._snapshot.version:
                return False
            if snapshot.version == self._snapshot.version and self._last_refresh is not None:
                self._last_refresh = self._clock()
                self._redis_available = True
                return False
            self._snapshot = snapshot
            self._last_refresh = self._clock()
            self._redis_available = True
            return True

    def mark_redis_unavailable(self) -> None:
        self._redis_available = False

    def endpoint_and_pool(
        self, username: str
    ) -> tuple[EndpointSnapshot | None, PoolSnapshot | None]:
        if self.stale:
            raise PoolUnavailable("gateway snapshot is unavailable or stale")
        endpoint = self._snapshot.endpoints.get(username)
        pool = self._snapshot.pools.get(endpoint.pool_id) if endpoint else None
        return endpoint, pool

    def current(self) -> GatewaySnapshot:
        if self.stale:
            raise PoolUnavailable("gateway snapshot is unavailable or stale")
        return self._snapshot


class RedisSnapshotLoader:
    def __init__(
        self,
        redis: AsyncRedisLike,
        store: SnapshotStore,
        codec: EncryptedSnapshotCodec,
        *,
        snapshot_key: str = "proxyhide:gateway:snapshot",
        reload_channel: str = "proxyhide:gateway:reload",
        poll_interval: float = 15.0,
    ) -> None:
        self.redis = redis
        self.store = store
        self.codec = codec
        self.snapshot_key = snapshot_key
        self.reload_channel = reload_channel
        self.poll_interval = poll_interval
        self._stopped = asyncio.Event()

    async def refresh(self) -> bool:
        try:
            payload = await self.redis.get(self.snapshot_key)
            if not payload:
                self.store.mark_redis_unavailable()
                return False
            snapshot = GatewaySnapshot.from_dict(
                self.codec.decode(payload), loaded_monotonic=time.monotonic()
            )
            return await self.store.install(snapshot)
        except (OSError, TimeoutError, RedisError, ValueError, TypeError):
            self.store.mark_redis_unavailable()
            return False

    async def run(self) -> None:
        """Refresh on notifications, with polling as the loss-tolerant fallback."""
        await self.refresh()
        while not self._stopped.is_set():
            try:
                await self._subscribe_and_poll()
            except (OSError, TimeoutError, RedisError):
                self.store.mark_redis_unavailable()
            if self._stopped.is_set():
                break
            await self.refresh()
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=min(1.0, self.poll_interval)
                )
            except TimeoutError:
                pass

    async def _subscribe_and_poll(self) -> None:
        pubsub = self.redis.pubsub()
        try:
            await pubsub.subscribe(self.reload_channel)
            # Close the fetch/subscribe race before waiting for notifications.
            await self.refresh()
            while not self._stopped.is_set():
                await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=self.poll_interval,
                )
                if not self._stopped.is_set():
                    await self.refresh()
        finally:
            close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
            if close is not None:
                with contextlib.suppress(OSError, RedisError):
                    result = close()
                    if inspect.isawaitable(result):
                        await result

    def stop(self) -> None:
        self._stopped.set()
