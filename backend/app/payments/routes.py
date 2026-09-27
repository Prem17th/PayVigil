from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments import domain
from app.core.auth import require_finance, require_supplier
from app.core.database import get_session
from app.payments.schemas import (
    BeneficiaryCreate,
    BeneficiaryDecision,
    PaymentCreate,
    PaymentDecision,
    PaymentRevise,
    PaymentView,
    SupplierCreate,
    SupplierView,
)
from app.core.schemas import Principal


router = APIRouter(prefix="/api")
Session = Annotated[AsyncSession, Depends(get_session)]
Finance = Annotated[Principal, Depends(require_finance)]
SupplierUser = Annotated[Principal, Depends(require_supplier)]


@router.get("/suppliers")
async def suppliers(session: Session, principal: Finance):
    return {"suppliers": await domain.list_suppliers(session, principal)}


@router.post("/suppliers", response_model=SupplierView, status_code=201)
async def create_supplier(body: SupplierCreate, session: Session, principal: Finance):
    return await domain.create_supplier(session, principal, body.name)


@router.post("/suppliers/{supplier_id}/beneficiaries", response_model=SupplierView)
async def add_beneficiary(
    supplier_id: UUID, body: BeneficiaryCreate, session: Session, principal: Finance
):
    return await domain.add_beneficiary(session, principal, supplier_id, body)


@router.post("/suppliers/{supplier_id}/confirmations", response_model=SupplierView)
async def confirm_beneficiary(
    supplier_id: UUID, body: BeneficiaryDecision, session: Session, principal: SupplierUser
):
    return await domain.confirm_beneficiary(
        session, principal, supplier_id, body.beneficiary_version_id
    )


@router.post("/suppliers/{supplier_id}/acceptances", response_model=SupplierView)
async def accept_beneficiary(
    supplier_id: UUID, body: BeneficiaryDecision, session: Session, principal: Finance
):
    return await domain.accept_beneficiary(
        session, principal, supplier_id, body.beneficiary_version_id
    )


@router.get("/supplier/requests")
async def supplier_requests(session: Session, principal: SupplierUser):
    return {"suppliers": await domain.list_suppliers(session, principal)}


@router.get("/payments")
async def payments(session: Session, principal: Finance):
    return {"payments": await domain.list_payments(session, principal)}


@router.get("/payments/{payment_id}", response_model=PaymentView)
async def payment(payment_id: UUID, session: Session, principal: Finance):
    return await domain.get_payment(session, principal, payment_id)


@router.post("/payments", response_model=PaymentView, status_code=201)
async def create_payment(body: PaymentCreate, session: Session, principal: Finance):
    return await domain.create_payment(session, principal, body)


@router.post("/payments/{payment_id}/revisions", response_model=PaymentView)
async def revise_payment(
    payment_id: UUID, body: PaymentRevise, session: Session, principal: Finance
):
    return await domain.revise_payment(session, principal, payment_id, body)


@router.post("/payments/{payment_id}/approvals", response_model=PaymentView)
async def approve_payment(
    payment_id: UUID, body: PaymentDecision, session: Session, principal: Finance
):
    return await domain.approve_payment(session, principal, payment_id, body)


@router.post("/payments/{payment_id}/queue", response_model=PaymentView)
async def queue_payment(
    payment_id: UUID,
    body: PaymentDecision,
    session: Session,
    principal: Finance,
    idempotency_key: Annotated[
        str, Header(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    return await domain.queue_payment(session, principal, payment_id, body, idempotency_key)
