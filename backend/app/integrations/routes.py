import hashlib
from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_finance, require_supplier
from app.core.database import get_session
from app.core.errors import AppError
from app.payments.domain import transaction
from app.core.providers import get_provider_client
from app.core.schemas import Principal
from app.integrations.models import Delivery
from app.integrations.settings import SponsorSettings, get_sponsor_settings
from app.integrations import domain
from app.integrations import providers as provider

router = APIRouter(prefix="/api")
Session = Annotated[AsyncSession, Depends(get_session)]
Finance = Annotated[Principal, Depends(require_finance)]
SupplierUser = Annotated[Principal, Depends(require_supplier)]
Settings = Annotated[SponsorSettings, Depends(get_sponsor_settings)]
Client = Annotated[httpx.AsyncClient, Depends(get_provider_client)]


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeliveryRequest(Empty):
    beneficiary_version_id: UUID


class DeliveryCallback(Empty):
    event_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_:-]+$")
    delivery_id: UUID
    attempt: int = Field(ge=1, le=3, strict=True)
    status: Literal["DELIVERED", "FAILED"]


@router.get("/suppliers/{supplier_id}/deliveries")
async def deliveries(supplier_id: UUID, session: Session, principal: Finance):
    return await domain.deliveries(session, principal, supplier_id)


@router.post("/suppliers/{supplier_id}/deliveries")
async def request_delivery(
    supplier_id: UUID,
    body: DeliveryRequest,
    session: Session,
    principal: Finance,
    settings: Settings,
    client: Client,
):
    return await domain.request_delivery(
        session, principal, client, settings, supplier_id, body.beneficiary_version_id
    )


@router.post("/deliveries/{delivery_id}/reminders")
async def reminder(
    delivery_id: UUID,
    body: Empty,
    session: Session,
    principal: Finance,
    settings: Settings,
    client: Client,
):
    async with transaction(session, principal):
        row = await session.scalar(
            select(Delivery).where(
                Delivery.id == delivery_id, Delivery.tenant_id == principal.tenant.id
            )
        )
        if row is None:
            raise AppError(404, "delivery_not_found", "The delivery request does not exist.")
        supplier_id, version = row.supplier_id, row.beneficiary_version_id
    return await domain.request_delivery(
        session, principal, client, settings, supplier_id, version, delivery_id
    )


@router.get("/supplier/inbox")
async def inbox(session: Session, principal: SupplierUser):
    return await domain.deliveries(session, principal)


async def bounded_body(request):
    raw = await request.body()
    if len(raw) > 65536:
        raise AppError(413, "callback_too_large", "The callback body exceeds its limit.")
    return raw


@router.post("/integrations/n8n/callback")
async def n8n_callback(request: Request, session: Session, settings: Settings):
    raw = await bounded_body(request)
    value = provider.verify_n8n(
        raw,
        request.headers,
        settings.n8n_callback_secret.get_secret_value(),
        settings.n8n_callback_auth_mode,
    )
    try:
        body = DeliveryCallback.model_validate(value)
    except ValidationError:
        raise AppError(
            422, "invalid_callback_body", "The delivery callback body is invalid."
        ) from None
    return await domain.delivery_callback(session, body, hashlib.sha256(raw).hexdigest())


@router.post("/investigations/{investigation_id}/audio")
async def audio(
    investigation_id: UUID,
    body: Empty,
    session: Session,
    principal: Finance,
    settings: Settings,
    client: Client,
):
    content = await domain.audio(session, principal, client, settings, investigation_id)
    return Response(
        content,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/billing")
async def billing(session: Session, principal: Finance, settings: Settings):
    return await domain.billing_status(session, principal, settings)


@router.post("/billing/checkout")
async def checkout(
    body: Empty, session: Session, principal: Finance, settings: Settings, client: Client
):
    return await domain.checkout(session, principal, client, settings)


@router.post("/billing/reconcile")
async def reconcile(
    body: Empty, session: Session, principal: Finance, settings: Settings, client: Client
):
    return await domain.reconcile(session, principal, client, settings)


@router.post("/integrations/dodo/webhook")
async def webhook(request: Request, session: Session, settings: Settings, client: Client):
    raw = await bounded_body(request)
    eid, body = provider.verify_dodo(
        raw, request.headers, settings.dodo_webhook_secret.get_secret_value()
    )
    return await domain.billing_webhook(
        session, client, settings, eid, body, hashlib.sha256(raw).hexdigest()
    )


@router.get("/payments/{payment_id}/report")
async def report(
    payment_id: UUID, session: Session, principal: Finance, settings: Settings, response: Response
):
    response.headers["Content-Disposition"] = f'attachment; filename="payvigil-{payment_id}.json"'
    response.headers["Cache-Control"] = "no-store"
    return await domain.report(session, principal, settings, payment_id)
