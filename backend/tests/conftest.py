from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.sessions import SessionData


class MemorySessionStore:
    def __init__(self) -> None:
        self.values: dict[str, SessionData] = {}
        self.counter = 0

    async def create(self, data: SessionData) -> str:
        self.counter += 1
        token = f"test-session-{self.counter}"
        self.values[token] = data
        return token

    async def get(self, token: str) -> SessionData | None:
        return self.values.get(token)

    async def delete(self, token: str) -> None:
        self.values.pop(token, None)

    async def revoke_user(self, user_id: UUID) -> None:
        self.values = {
            token: data for token, data in self.values.items() if data.user_id != user_id
        }

    async def revoke_workspace(self, workspace_id: UUID) -> None:
        self.values = {
            token: data for token, data in self.values.items() if data.workspace_id != workspace_id
        }


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async def override_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.state.session_store = MemorySessionStore()
    app.state.redis = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as value:
        yield value
    app.dependency_overrides.clear()
