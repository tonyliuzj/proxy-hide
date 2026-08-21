from __future__ import annotations

import asyncio

import typer
from sqlalchemy import select

from app.db import SessionLocal, dispose_engine, utcnow
from app.models import User, UserRole
from app.security import hash_password
from app.services.bootstrap import acquire_admin_bootstrap_lock

cli = typer.Typer(help="Proxy Hide administrative commands.")


@cli.callback()
def main() -> None:
    """Run operator-only Proxy Hide administration commands."""


async def _bootstrap_admin(email: str, password: str) -> None:
    normalized_email = email.strip().lower()
    async with SessionLocal() as db:
        await acquire_admin_bootstrap_lock(db)
        existing = await db.scalar(select(User).where(User.email == normalized_email))
        if existing is not None:
            if existing.role != UserRole.PLATFORM_ADMIN:
                raise typer.BadParameter("email belongs to a workspace owner")
            existing.password_hash = hash_password(password)
            existing.password_changed_at = utcnow()
            existing.active = True
            action = "updated"
        else:
            db.add(
                User(
                    email=normalized_email,
                    password_hash=hash_password(password),
                    password_changed_at=utcnow(),
                    role=UserRole.PLATFORM_ADMIN,
                    active=True,
                )
            )
            action = "created"
        await db.commit()
    typer.echo(f"Platform administrator {action}: {normalized_email}")


async def _bootstrap_admin_command(email: str, password: str) -> None:
    try:
        await _bootstrap_admin(email, password)
    finally:
        await dispose_engine()


@cli.command("bootstrap-admin")
def bootstrap_admin(
    email: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    """Create the first administrator or replace an existing administrator password."""
    asyncio.run(_bootstrap_admin_command(email, password))


if __name__ == "__main__":
    cli()
