from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Principal
from app.models import AuditEvent


def record_audit(
    db: AsyncSession,
    request: Request,
    principal: Principal,
    *,
    action: str,
    resource_type: str,
    resource_id: UUID | None = None,
    workspace_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        workspace_id=workspace_id if workspace_id is not None else principal.user.workspace_id,
        actor_user_id=principal.user.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:500] or None,
        details=details or {},
    )
    db.add(event)
    return event
