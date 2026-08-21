from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.security import generate_session_token


@dataclass(frozen=True, slots=True)
class SessionData:
    user_id: UUID
    role: str
    workspace_id: UUID | None
    csrf_token: str
    password_changed_at: str | None
    created_at: str

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        role: str,
        workspace_id: UUID | None,
        csrf_token: str,
        password_changed_at: datetime | None,
    ) -> SessionData:
        return cls(
            user_id=user_id,
            role=role,
            workspace_id=workspace_id,
            csrf_token=csrf_token,
            password_changed_at=(password_changed_at.isoformat() if password_changed_at else None),
            created_at=datetime.now(UTC).isoformat(),
        )


class SessionStore:
    def __init__(self, redis: Redis, settings: Settings | None = None) -> None:
        self.redis = redis
        self.settings = settings or get_settings()

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _key(self, token: str) -> str:
        return f"proxyhide:session:{self._digest(token)}"

    async def create(self, data: SessionData) -> str:
        token = generate_session_token()
        key = self._key(token)
        serialized = asdict(data)
        serialized["user_id"] = str(data.user_id)
        serialized["workspace_id"] = str(data.workspace_id) if data.workspace_id else None
        ttl = self.settings.session_ttl_seconds
        async with self.redis.pipeline(transaction=True) as pipeline:
            pipeline.set(key, json.dumps(serialized, separators=(",", ":")), ex=ttl)
            pipeline.sadd(f"proxyhide:user-sessions:{data.user_id}", key)
            pipeline.expire(f"proxyhide:user-sessions:{data.user_id}", ttl)
            if data.workspace_id:
                pipeline.sadd(f"proxyhide:workspace-sessions:{data.workspace_id}", key)
                pipeline.expire(f"proxyhide:workspace-sessions:{data.workspace_id}", ttl)
            await pipeline.execute()
        return token

    async def get(self, token: str) -> SessionData | None:
        raw = await self.redis.get(self._key(token))
        if not raw:
            return None
        try:
            value = json.loads(raw)
            data = SessionData(
                user_id=UUID(value["user_id"]),
                role=value["role"],
                workspace_id=UUID(value["workspace_id"]) if value["workspace_id"] else None,
                csrf_token=value["csrf_token"],
                password_changed_at=value.get("password_changed_at"),
                created_at=value["created_at"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            await self.redis.delete(self._key(token))
            return None
        await self.redis.expire(self._key(token), self.settings.session_ttl_seconds)
        return data

    async def delete(self, token: str) -> None:
        key = self._key(token)
        raw = await self.redis.get(key)
        if raw:
            try:
                value = json.loads(raw)
                async with self.redis.pipeline(transaction=True) as pipeline:
                    pipeline.delete(key)
                    pipeline.srem(f"proxyhide:user-sessions:{value['user_id']}", key)
                    if value.get("workspace_id"):
                        pipeline.srem(f"proxyhide:workspace-sessions:{value['workspace_id']}", key)
                    await pipeline.execute()
                return
            except (KeyError, TypeError, json.JSONDecodeError):
                pass
        await self.redis.delete(key)

    async def revoke_user(self, user_id: UUID) -> None:
        set_key = f"proxyhide:user-sessions:{user_id}"
        keys = await self.redis.smembers(set_key)  # type: ignore[misc]
        if keys:
            await self.redis.delete(*keys)
        await self.redis.delete(set_key)

    async def revoke_workspace(self, workspace_id: UUID) -> None:
        set_key = f"proxyhide:workspace-sessions:{workspace_id}"
        keys = await self.redis.smembers(set_key)  # type: ignore[misc]
        if keys:
            await self.redis.delete(*keys)
        await self.redis.delete(set_key)
