from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.db import utcnow
from app.dependencies import DB, OwnerPrincipal, PaginationDep, WorkspacePrincipal, paginate
from app.domain.network import DestinationPolicyError, validate_public_http_url
from app.errors import APIError
from app.models import Alert, AlertStatus, Webhook, WebhookDelivery
from app.schemas import (
    AlertUpdate,
    AlertView,
    Page,
    WebhookCreate,
    WebhookCreated,
    WebhookDeliveryView,
    WebhookUpdate,
    WebhookView,
)
from app.security import KeyRing
from app.services.audit import record_audit

router = APIRouter(tags=["alerts and webhooks"])


@router.get("/alerts", response_model=Page[AlertView])
async def list_alerts(
    db: DB, principal: WorkspacePrincipal, pagination: PaginationDep
) -> Page[AlertView]:
    items, total = await paginate(
        db,
        select(Alert)
        .where(Alert.workspace_id == principal.workspace_id)
        .order_by(Alert.created_at.desc()),
        pagination,
    )
    return Page(
        items=[AlertView.model_validate(item) for item in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.patch("/alerts/{alert_id}", response_model=AlertView)
async def update_alert(
    alert_id: UUID,
    payload: AlertUpdate,
    request: Request,
    db: DB,
    principal: WorkspacePrincipal,
) -> AlertView:
    alert = await db.scalar(
        select(Alert).where(Alert.id == alert_id, Alert.workspace_id == principal.workspace_id)
    )
    if alert is None:
        raise APIError(404, "ALERT_NOT_FOUND", "The alert was not found.")
    alert.status = AlertStatus(payload.status)
    if alert.status is AlertStatus.ACKNOWLEDGED:
        alert.acknowledged_by = principal.user.id
        alert.acknowledged_at = utcnow()
    else:
        alert.resolved_at = utcnow()
    record_audit(
        db,
        request,
        principal,
        action=f"alert.{alert.status.value}",
        resource_type="alert",
        resource_id=alert.id,
    )
    await db.commit()
    return AlertView.model_validate(alert)


async def _safe_url(value: object) -> str:
    url = str(value)
    try:
        await validate_public_http_url(url)
    except DestinationPolicyError as exc:
        raise APIError(422, "WEBHOOK_URL_REJECTED", str(exc)) from exc
    return url


async def _webhook(db: DB, workspace_id: UUID, webhook_id: UUID) -> Webhook:
    item = await db.scalar(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.workspace_id == workspace_id)
    )
    if item is None:
        raise APIError(404, "WEBHOOK_NOT_FOUND", "The webhook was not found.")
    return item


@router.get("/webhooks", response_model=Page[WebhookView])
async def list_webhooks(
    db: DB, principal: OwnerPrincipal, pagination: PaginationDep
) -> Page[WebhookView]:
    items, total = await paginate(
        db,
        select(Webhook)
        .where(Webhook.workspace_id == principal.workspace_id)
        .order_by(Webhook.created_at.desc()),
        pagination,
    )
    return Page(
        items=[WebhookView.model_validate(item) for item in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("/webhooks", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate,
    request: Request,
    response: Response,
    db: DB,
    principal: OwnerPrincipal,
) -> WebhookCreated:
    secret = secrets.token_urlsafe(32)
    item = Webhook(
        workspace_id=principal.workspace_id,
        name=payload.name.strip(),
        url=await _safe_url(payload.url),
        events=sorted(set(payload.events)),
        enabled=payload.enabled,
        secret_encrypted=KeyRing.from_settings().encrypt_text(secret),
    )
    db.add(item)
    await db.flush()
    record_audit(
        db,
        request,
        principal,
        action="webhook.created",
        resource_type="webhook",
        resource_id=item.id,
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return WebhookCreated(**WebhookView.model_validate(item).model_dump(), secret=secret)


@router.patch("/webhooks/{webhook_id}", response_model=WebhookView)
async def update_webhook(
    webhook_id: UUID,
    payload: WebhookUpdate,
    request: Request,
    db: DB,
    principal: OwnerPrincipal,
) -> WebhookView:
    item = await _webhook(db, principal.workspace_id, webhook_id)
    changes = payload.model_dump(exclude_unset=True, exclude={"rotate_secret", "url"})
    for field, value in changes.items():
        setattr(item, field, value.strip() if field == "name" and value else value)
    if payload.url is not None:
        item.url = await _safe_url(payload.url)
    if payload.rotate_secret:
        item.secret_encrypted = KeyRing.from_settings().encrypt_text(secrets.token_urlsafe(32))
    record_audit(
        db,
        request,
        principal,
        action="webhook.updated",
        resource_type="webhook",
        resource_id=item.id,
    )
    await db.commit()
    return WebhookView.model_validate(item)


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: UUID, request: Request, db: DB, principal: OwnerPrincipal
) -> None:
    item = await _webhook(db, principal.workspace_id, webhook_id)
    await db.delete(item)
    record_audit(
        db,
        request,
        principal,
        action="webhook.deleted",
        resource_type="webhook",
        resource_id=item.id,
    )
    await db.commit()


@router.get("/webhooks/{webhook_id}/deliveries", response_model=Page[WebhookDeliveryView])
async def list_deliveries(
    webhook_id: UUID,
    db: DB,
    principal: OwnerPrincipal,
    pagination: PaginationDep,
) -> Page[WebhookDeliveryView]:
    await _webhook(db, principal.workspace_id, webhook_id)
    items, total = await paginate(
        db,
        select(WebhookDelivery)
        .where(
            WebhookDelivery.webhook_id == webhook_id,
            WebhookDelivery.workspace_id == principal.workspace_id,
        )
        .order_by(WebhookDelivery.created_at.desc()),
        pagination,
    )
    return Page(
        items=[WebhookDeliveryView.model_validate(item) for item in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
