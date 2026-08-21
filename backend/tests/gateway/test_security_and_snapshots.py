from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.gateway.errors import BadRequest, DestinationDenied, PoolUnavailable
from app.gateway.models import GatewaySnapshot
from app.gateway.security import PublicResolver, is_public_address, parse_connect_authority
from app.gateway.snapshots import EncryptedSnapshotCodec, RedisSnapshotLoader, SnapshotStore
from app.security import KeyRing


def snapshot_payload(secret_digest: str = "a" * 64) -> dict[str, object]:
    return {
        "version": 7,
        "generated_at": datetime.now(UTC).isoformat(),
        "endpoints": {
            "edge": {
                "id": "endpoint-1",
                "workspace_id": "workspace-1",
                "pool_id": "pool-1",
                "secret_digest": secret_digest,
                "workspace_status": "active",
                "destination_ports": [80, 443],
                "max_gateway_connections": 12,
            }
        },
        "pools": {
            "pool-1": {
                "revision": 3,
                "strategy": "weighted_health",
                "routes": [
                    {
                        "id": "route-1",
                        "protocol": "http",
                        "host": "proxy.example",
                        "port": 8080,
                        "username": "private-user",
                        "password": "private-password",
                        "score": 90,
                    }
                ],
            }
        },
    }


def test_encrypted_snapshot_envelope_hides_credentials_and_authenticates() -> None:
    codec = EncryptedSnapshotCodec(KeyRing("test", {"test": b"k" * 32}))
    payload = snapshot_payload()
    encoded = codec.encode(payload)

    assert b"private-user" not in encoded
    assert b"private-password" not in encoded
    envelope = json.loads(encoded)
    assert envelope["schema_version"] == 1
    assert codec.decode(encoded) == payload

    envelope["ciphertext"] = envelope["ciphertext"][:-2] + "AA"
    with pytest.raises(ValueError):
        codec.decode(json.dumps(envelope).encode())


@pytest.mark.asyncio
async def test_snapshot_store_fails_closed_after_redis_outage_window() -> None:
    now = 10.0
    store = SnapshotStore(stale_after=60, clock=lambda: now)
    await store.install(GatewaySnapshot.from_dict(snapshot_payload()))
    assert store.current().version == 7

    store.mark_redis_unavailable()
    now = 69.9
    assert store.current().version == 7
    now = 70.1
    with pytest.raises(PoolUnavailable):
        store.current()


class FakePubSub:
    def __init__(self) -> None:
        self.channel: str | None = None
        self.subscribed = asyncio.Event()
        self.messages: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.channel = channel
        self.subscribed.set()

    async def get_message(self, **kwargs: Any) -> dict[str, str] | None:
        timeout = float(kwargs["timeout"])
        try:
            return await asyncio.wait_for(self.messages.get(), timeout=timeout)
        except TimeoutError:
            return None

    async def aclose(self) -> None:
        self.closed = True


class FakeSnapshotRedis:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.pubsub_instance = FakePubSub()
        self.get_calls: asyncio.Queue[None] = asyncio.Queue()

    async def get(self, key: str) -> bytes:
        assert key == "snapshot"
        await self.get_calls.put(None)
        return self.payload

    def pubsub(self) -> FakePubSub:
        return self.pubsub_instance


@pytest.mark.asyncio
async def test_snapshot_loader_refreshes_immediately_on_reload_notification() -> None:
    codec = EncryptedSnapshotCodec(KeyRing("test", {"test": b"k" * 32}))
    redis = FakeSnapshotRedis(codec.encode(snapshot_payload()))
    store = SnapshotStore()
    loader = RedisSnapshotLoader(
        redis,
        store,
        codec,
        snapshot_key="snapshot",
        reload_channel="reload",
        poll_interval=1,
    )
    task = asyncio.create_task(loader.run())
    try:
        await asyncio.wait_for(redis.pubsub_instance.subscribed.wait(), timeout=1)
        await asyncio.wait_for(redis.get_calls.get(), timeout=1)
        await asyncio.wait_for(redis.get_calls.get(), timeout=1)
        assert redis.pubsub_instance.channel == "reload"
        assert store.version == 7

        updated = snapshot_payload()
        updated["version"] = 8
        redis.payload = codec.encode(updated)
        await redis.pubsub_instance.messages.put({"type": "message", "data": "8"})
        await asyncio.wait_for(redis.get_calls.get(), timeout=1)
        assert store.version == 8
    finally:
        loader.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.parametrize(
    "value,expected",
    [
        ("8.8.8.8", True),
        ("2606:4700:4700::1111", True),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("169.254.169.254", False),
        ("::1", False),
        ("2001:db8::1", False),
    ],
)
def test_public_address_policy(value: str, expected: bool) -> None:
    assert is_public_address(value) is expected


@pytest.mark.asyncio
async def test_public_resolver_rejects_local_literal() -> None:
    with pytest.raises(DestinationDenied):
        await PublicResolver().resolve("127.0.0.1", 80)


def test_connect_authority_parses_ipv6_and_rejects_userinfo() -> None:
    assert parse_connect_authority("[2606:4700:4700::1111]:443") == (
        "2606:4700:4700::1111",
        443,
    )
    with pytest.raises(BadRequest):
        parse_connect_authority("user@example.com:443")
