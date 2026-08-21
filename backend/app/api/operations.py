from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.dependencies import DB, PaginationDep, WorkspacePrincipal, paginate
from app.errors import APIError
from app.models import Operation
from app.schemas import OperationView, Page

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("", response_model=Page[OperationView])
async def list_operations(
    db: DB, principal: WorkspacePrincipal, pagination: PaginationDep
) -> Page[OperationView]:
    operations, total = await paginate(
        db,
        select(Operation)
        .where(Operation.workspace_id == principal.workspace_id)
        .order_by(Operation.created_at.desc()),
        pagination,
    )
    return Page(
        items=[OperationView.model_validate(operation) for operation in operations],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{operation_id}", response_model=OperationView)
async def get_operation(operation_id: UUID, db: DB, principal: WorkspacePrincipal) -> OperationView:
    operation = await db.scalar(
        select(Operation).where(
            Operation.id == operation_id,
            Operation.workspace_id == principal.workspace_id,
        )
    )
    if operation is None:
        raise APIError(404, "OPERATION_NOT_FOUND", "The operation was not found.")
    return OperationView.model_validate(operation)
