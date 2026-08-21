from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.dependencies import DB, PaginationDep, WorkspacePrincipal, paginate
from app.models import AuditEvent
from app.schemas import AuditEventView, Page

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditEventView])
async def list_audit_events(
    db: DB, principal: WorkspacePrincipal, pagination: PaginationDep
) -> Page[AuditEventView]:
    events, total = await paginate(
        db,
        select(AuditEvent)
        .where(AuditEvent.workspace_id == principal.workspace_id)
        .order_by(AuditEvent.created_at.desc()),
        pagination,
    )
    return Page(
        items=[AuditEventView.model_validate(event) for event in events],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
