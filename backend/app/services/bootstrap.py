from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


# Signed-bigint-safe ASCII key "PHADMBST"; advisory lock keys must be unique per subsystem.
_ADMIN_BOOTSTRAP_LOCK_ID = 0x504841444D425354


async def acquire_admin_bootstrap_lock(db: AsyncSession) -> None:
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        await db.execute(select(func.pg_advisory_xact_lock(_ADMIN_BOOTSTRAP_LOCK_ID)))
