from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.dependencies import DB, WorkspacePrincipal
from app.models import TrafficRollup
from app.schemas import TrafficPoint, TrafficSummary

router = APIRouter(prefix="/traffic", tags=["traffic"])


@router.get("", response_model=TrafficSummary)
async def traffic_summary(
    db: DB,
    principal: WorkspacePrincipal,
    start: datetime | None = None,
    end: datetime | None = None,
    endpoint_id: UUID | None = None,
    pool_id: UUID | None = None,
    granularity: str = Query(default="hour", pattern="^(minute|hour)$"),
) -> TrafficSummary:
    now = datetime.now(UTC)
    end = end or now
    start = start or end - timedelta(hours=24)
    if start >= end or end - start > timedelta(days=366):
        from app.errors import APIError

        raise APIError(422, "TRAFFIC_RANGE_INVALID", "Select a range up to 366 days.")
    statement = (
        select(TrafficRollup)
        .where(
            TrafficRollup.workspace_id == principal.workspace_id,
            TrafficRollup.bucket_start >= start,
            TrafficRollup.bucket_start < end,
            TrafficRollup.granularity == granularity,
        )
        .order_by(TrafficRollup.bucket_start)
    )
    if endpoint_id:
        statement = statement.where(TrafficRollup.endpoint_id == endpoint_id)
    if pool_id:
        statement = statement.where(TrafficRollup.pool_id == pool_id)
    values = list((await db.scalars(statement)).all())
    points = [
        TrafficPoint(
            bucket_start=value.bucket_start,
            requests=value.requests,
            successes=value.successes,
            failures=value.failures,
            bytes_up=value.bytes_up,
            bytes_down=value.bytes_down,
            average_latency_ms=(value.latency_sum_ms / value.requests if value.requests else None),
        )
        for value in values
    ]
    requests = sum(value.requests for value in values)
    latency = sum(value.latency_sum_ms for value in values)
    return TrafficSummary(
        requests=requests,
        successes=sum(value.successes for value in values),
        failures=sum(value.failures for value in values),
        bytes_up=sum(value.bytes_up for value in values),
        bytes_down=sum(value.bytes_down for value in values),
        average_latency_ms=latency / requests if requests else None,
        points=points,
    )
