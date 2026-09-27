"""Deterministic authority checks and transactional outbox operations."""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import assert_restricted_role
from app.core.errors import AppError
from app.payments.models import (
    AuditEvent,
    BeneficiaryAcceptance,
    BeneficiaryVersion,
    Execution,
    Payment,
    PaymentApproval,
    PaymentRevision,
    Supplier,
    SupplierConfirmation,
    SupplierIdentity,
)
from app.payments.schemas import (
    AcceptanceView,
    ApprovalView,
    AuditView,
    BeneficiaryCreate,
    BeneficiaryView,
    ConfirmationView,
    ExecutionView,
    PaymentCreate,
    PaymentDecision,
    PaymentRevise,
    PaymentView,
    RevisionView,
    SupplierView,
)
from app.core.schemas import Principal, Role


LOCKED_PAYMENT_STATES = {"QUEUED", "SUBMITTING", "UNKNOWN", "SUCCEEDED", "FAILED"}
ACTIVE_EXECUTION_STATES = {"QUEUED", "SUBMITTING", "UNKNOWN"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)


@asynccontextmanager
async def transaction(session: AsyncSession, principal: Principal | None = None):
    try:
        async with asyncio.timeout(8), session.begin():
            await assert_restricted_role(
                session, "beforetransfer_api" if principal else "beforetransfer_worker"
            )
            if principal:
                await session.execute(
                    text("SELECT set_config('app.user_id',:user,true)"),
                    {"user": str(principal.user_id)},
                )
            yield
    except IntegrityError:
        raise conflict(
            "record_conflict", "An existing record or concurrent change prevents this action."
        ) from None
    except (SQLAlchemyError, TimeoutError):
        raise AppError(
            503,
            "database_unavailable",
            "The operation could not be verified. Reload before retrying.",
        ) from None


def audit(
    session: AsyncSession,
    tenant_id: UUID,
    subject_type: str,
    subject_id: UUID,
    action: str,
    actor: UUID | None,
    **details,
):
    session.add(
        AuditEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            subject_type=subject_type,
            subject_id=subject_id,
            action=action,
            actor_user_id=actor,
            details=details,
        )
    )


async def audit_view(
    session: AsyncSession, tenant_id: UUID, kind: str, subject_id: UUID
) -> list[AuditView]:
    rows = (
        await session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.subject_type == kind,
                AuditEvent.subject_id == subject_id,
            )
            .order_by(AuditEvent.created_at, AuditEvent.id)
            .limit(100)
        )
    ).all()
    return [
        AuditView(
            id=r.id,
            action=r.action,
            actor_user_id=r.actor_user_id,
            created_at=r.created_at,
            details=r.details,
        )
        for r in rows
    ]


async def supplier_row(
    session: AsyncSession, supplier_id: UUID, tenant_id: UUID, *, lock=False
) -> Supplier:
    query = select(Supplier).where(Supplier.id == supplier_id, Supplier.tenant_id == tenant_id)
    if lock:
        query = query.with_for_update()
    row = await session.scalar(query)
    if row is None:
        raise AppError(404, "supplier_not_found", "The supplier is not available.")
    return row


async def payment_rows(session: AsyncSession, payment_id: UUID, tenant_id: UUID, *, lock=False):
    payment = await session.scalar(
        select(Payment).where(Payment.id == payment_id, Payment.tenant_id == tenant_id)
    )
    if payment is None:
        raise AppError(404, "payment_not_found", "The payment is not available.")
    supplier = await supplier_row(session, payment.supplier_id, tenant_id, lock=lock)
    if lock:
        payment = await session.scalar(
            select(Payment)
            .where(Payment.id == payment_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    revision = await session.get(PaymentRevision, payment.current_revision_id)
    if revision is None:
        raise conflict("revision_missing", "The payment has no valid revision.")
    return supplier, payment, revision


async def beneficiary_decisions(session: AsyncSession, version_id: UUID):
    confirmation = await session.scalar(
        select(SupplierConfirmation).where(
            SupplierConfirmation.beneficiary_version_id == version_id
        )
    )
    acceptance = await session.scalar(
        select(BeneficiaryAcceptance).where(
            BeneficiaryAcceptance.beneficiary_version_id == version_id
        )
    )
    return confirmation, acceptance


async def supplier_view(
    session: AsyncSession, supplier: Supplier, principal: Principal
) -> SupplierView:
    beneficiary = None
    holds, actions = [], []
    finance = principal.role in {Role.FINANCE_ADMIN, Role.FINANCE_REVIEWER}
    busy = False
    if finance:
        busy = bool(
            await session.scalar(
                select(Payment.id)
                .where(
                    Payment.supplier_id == supplier.id, Payment.state.in_(ACTIVE_EXECUTION_STATES)
                )
                .limit(1)
            )
        )
        if not busy:
            actions.append("add_beneficiary")
        else:
            holds.append("An active or uncertain execution locks destination changes.")
    if supplier.current_beneficiary_version_id:
        version = await session.get(BeneficiaryVersion, supplier.current_beneficiary_version_id)
        confirmation, acceptance = await beneficiary_decisions(session, version.id)
        beneficiary = BeneficiaryView(
            id=version.id,
            version=version.version,
            beneficiary_name=version.beneficiary_name,
            sandbox_account_id=version.sandbox_account_id,
            created_at=version.created_at,
            confirmation=ConfirmationView(id=confirmation.id, confirmed_at=confirmation.created_at)
            if confirmation
            else None,
            acceptance=AcceptanceView(id=acceptance.id, accepted_at=acceptance.created_at)
            if acceptance
            else None,
        )
        if not confirmation:
            holds.append("Assigned supplier confirmation is required.")
            if not finance:
                actions.append("confirm")
        if not acceptance:
            holds.append("Finance acceptance of this destination version is required.")
            if finance and confirmation:
                actions.append("accept")
    else:
        holds.append("A synthetic beneficiary destination is required.")
    return SupplierView(
        id=supplier.id,
        name=supplier.name,
        current_beneficiary=beneficiary,
        allowed_actions=actions,
        hold_reasons=holds,
        audit_events=await audit_view(session, supplier.tenant_id, "supplier", supplier.id),
    )


def approval_body(
    payment: Payment, revision: PaymentRevision, beneficiary: BeneficiaryVersion
) -> dict:
    return {
        "payment_id": str(payment.id),
        "revision_id": str(revision.id),
        "tenant_id": str(payment.tenant_id),
        "supplier_id": str(payment.supplier_id),
        "beneficiary_version_id": str(beneficiary.id),
        "invoice_reference": payment.invoice_reference,
        "amount_minor": revision.amount_minor,
        "currency": revision.currency,
        "beneficiary_name": beneficiary.beneficiary_name,
        "sandbox_account_id": beneficiary.sandbox_account_id,
        "simulation": revision.simulation,
    }


def digest_body(body: dict) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def sandbox_body(
    payment: Payment, revision: PaymentRevision, beneficiary: BeneficiaryVersion
) -> dict:
    body = approval_body(payment, revision, beneficiary)
    # The approval digest also binds the supplier and beneficiary version; the
    # independent sandbox contract carries the immutable destination snapshot.
    body.pop("supplier_id")
    body.pop("beneficiary_version_id")
    return {**body, "digest": revision.digest}


async def prerequisite_holds(
    session: AsyncSession, supplier: Supplier, revision: PaymentRevision
) -> list[str]:
    holds = []
    if supplier.current_beneficiary_version_id != revision.beneficiary_version_id:
        holds.append(
            "Destination changed. Create a new payment revision and obtain fresh approval."
        )
    confirmation, acceptance = await beneficiary_decisions(session, revision.beneficiary_version_id)
    if not confirmation:
        holds.append("Supplier confirmation of this destination version is required.")
    if not acceptance:
        holds.append("Finance acceptance of this destination version is required.")
    from app.evidence.domain import evidence_holds

    payment = await session.get(Payment, revision.payment_id)
    holds.extend(await evidence_holds(session, payment, revision.id))
    return holds


async def latest_approval(session: AsyncSession, payment: Payment, revision: PaymentRevision):
    from app.evidence.domain import evidence_state

    evidence_digest, _ = await evidence_state(session, payment.id)
    return await session.scalar(
        select(PaymentApproval)
        .where(
            PaymentApproval.payment_id == payment.id,
            PaymentApproval.revision_id == revision.id,
            PaymentApproval.digest == revision.digest,
            PaymentApproval.expires_at > func.clock_timestamp(),
            PaymentApproval.evidence_digest == evidence_digest,
        )
        .order_by(PaymentApproval.created_at.desc())
        .limit(1)
    )


async def payment_view(
    session: AsyncSession, supplier: Supplier, payment: Payment, revision: PaymentRevision
) -> PaymentView:
    beneficiary = await session.get(BeneficiaryVersion, revision.beneficiary_version_id)
    execution = await session.scalar(select(Execution).where(Execution.payment_id == payment.id))
    holds = await prerequisite_holds(session, supplier, revision)
    approval = await latest_approval(session, payment, revision) if not holds else None
    actions = []
    if payment.state not in LOCKED_PAYMENT_STATES:
        actions.append("revise")
        if not holds:
            actions.append("approve")
            if approval:
                actions.append("queue")
            else:
                holds.append("A current, unexpired approval of this exact revision is required.")
    elif payment.state == "UNKNOWN":
        holds.append(
            "Execution outcome is unknown. Readback reconciliation is required; a replacement is blocked."
        )
    elif payment.state in {"QUEUED", "SUBMITTING"}:
        holds.append("Execution is in progress. Changes and replacement requests are blocked.")
    elif payment.state == "FAILED":
        holds.append("This execution is terminally rejected and will not be retried automatically.")
    state = payment.state
    if state == "APPROVED" and not approval:
        state = "DRAFT"
    return PaymentView(
        id=payment.id,
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        invoice_reference=payment.invoice_reference,
        state=state,
        current_revision=RevisionView(
            id=revision.id,
            version=revision.version,
            amount_minor=revision.amount_minor,
            currency=revision.currency,
            beneficiary_version_id=beneficiary.id,
            beneficiary_name=beneficiary.beneficiary_name,
            sandbox_account_id=beneficiary.sandbox_account_id,
            simulation=revision.simulation,
            digest=revision.digest,
            created_at=revision.created_at,
        ),
        approval=ApprovalView(
            id=approval.id,
            revision_id=approval.revision_id,
            digest=approval.digest,
            approved_at=approval.created_at,
            expires_at=approval.expires_at,
        )
        if approval
        else None,
        execution=ExecutionView(
            id=execution.id,
            state=execution.state,
            transfer_id=execution.transfer_id,
            queued_at=execution.created_at,
            updated_at=execution.updated_at,
        )
        if execution
        else None,
        allowed_actions=actions,
        hold_reasons=holds,
        audit_events=await audit_view(session, payment.tenant_id, "payment", payment.id),
    )


async def list_suppliers(session: AsyncSession, principal: Principal) -> list[SupplierView]:
    async with transaction(session, principal):
        query = (
            select(Supplier)
            .where(Supplier.tenant_id == principal.tenant.id)
            .order_by(Supplier.created_at)
            .limit(100)
        )
        if principal.role == Role.SUPPLIER:
            query = query.join(SupplierIdentity, SupplierIdentity.supplier_id == Supplier.id).where(
                SupplierIdentity.user_id == principal.user_id
            )
        return [
            await supplier_view(session, supplier, principal)
            for supplier in (await session.scalars(query)).all()
        ]


async def create_supplier(session: AsyncSession, principal: Principal, name: str) -> SupplierView:
    async with transaction(session, principal):
        supplier = Supplier(id=uuid4(), tenant_id=principal.tenant.id, name=name)
        session.add(supplier)
        await session.flush()
        audit(
            session,
            supplier.tenant_id,
            "supplier",
            supplier.id,
            "supplier_created",
            principal.user_id,
        )
        await session.flush()
        return await supplier_view(session, supplier, principal)


async def add_beneficiary(
    session: AsyncSession, principal: Principal, supplier_id: UUID, body: BeneficiaryCreate
) -> SupplierView:
    async with transaction(session, principal):
        supplier = await supplier_row(session, supplier_id, principal.tenant.id, lock=True)
        if supplier.current_beneficiary_version_id != body.expected_version_id:
            raise conflict(
                "stale_beneficiary", "The destination changed. Reload before creating a version."
            )
        if await session.scalar(
            select(Payment.id)
            .where(Payment.supplier_id == supplier.id, Payment.state.in_(ACTIVE_EXECUTION_STATES))
            .limit(1)
        ):
            raise conflict(
                "execution_in_progress",
                "An active or uncertain execution prevents destination changes.",
            )
        previous = (
            await session.get(BeneficiaryVersion, supplier.current_beneficiary_version_id)
            if supplier.current_beneficiary_version_id
            else None
        )
        version = BeneficiaryVersion(
            id=uuid4(),
            tenant_id=supplier.tenant_id,
            supplier_id=supplier.id,
            version=previous.version + 1 if previous else 1,
            beneficiary_name=body.beneficiary_name,
            sandbox_account_id=body.sandbox_account_id,
            created_by=principal.user_id,
        )
        session.add(version)
        await session.flush()
        supplier.current_beneficiary_version_id = version.id
        audit(
            session,
            supplier.tenant_id,
            "supplier",
            supplier.id,
            "beneficiary_version_created",
            principal.user_id,
            beneficiary_version_id=str(version.id),
            version=version.version,
        )
        await session.flush()
        return await supplier_view(session, supplier, principal)


async def confirm_beneficiary(
    session: AsyncSession, principal: Principal, supplier_id: UUID, version_id: UUID
) -> SupplierView:
    async with transaction(session, principal):
        supplier = await supplier_row(session, supplier_id, principal.tenant.id, lock=True)
        assigned = await session.scalar(
            select(SupplierIdentity.id).where(
                SupplierIdentity.supplier_id == supplier.id,
                SupplierIdentity.user_id == principal.user_id,
            )
        )
        if not assigned:
            raise AppError(
                403,
                "supplier_assignment_required",
                "This identity is not assigned to the supplier.",
            )
        if supplier.current_beneficiary_version_id != version_id:
            raise conflict(
                "stale_beneficiary", "Only the current destination version can be confirmed."
            )
        confirmation, _ = await beneficiary_decisions(session, version_id)
        if not confirmation:
            session.add(
                SupplierConfirmation(
                    id=uuid4(),
                    tenant_id=supplier.tenant_id,
                    supplier_id=supplier.id,
                    beneficiary_version_id=version_id,
                    confirmed_by=principal.user_id,
                )
            )
            audit(
                session,
                supplier.tenant_id,
                "supplier",
                supplier.id,
                "supplier_confirmed",
                principal.user_id,
                beneficiary_version_id=str(version_id),
                notice="Confirmation is not proof of bank-account ownership.",
            )
            await session.flush()
        return await supplier_view(session, supplier, principal)


async def accept_beneficiary(
    session: AsyncSession, principal: Principal, supplier_id: UUID, version_id: UUID
) -> SupplierView:
    async with transaction(session, principal):
        supplier = await supplier_row(session, supplier_id, principal.tenant.id, lock=True)
        if supplier.current_beneficiary_version_id != version_id:
            raise conflict(
                "stale_beneficiary", "Only the current destination version can be accepted."
            )
        confirmation, acceptance = await beneficiary_decisions(session, version_id)
        if not confirmation:
            raise conflict(
                "confirmation_required",
                "Assigned supplier confirmation is required before finance acceptance.",
            )
        if not acceptance:
            session.add(
                BeneficiaryAcceptance(
                    id=uuid4(),
                    tenant_id=supplier.tenant_id,
                    supplier_id=supplier.id,
                    beneficiary_version_id=version_id,
                    accepted_by=principal.user_id,
                )
            )
            audit(
                session,
                supplier.tenant_id,
                "supplier",
                supplier.id,
                "finance_accepted",
                principal.user_id,
                beneficiary_version_id=str(version_id),
            )
            await session.flush()
        return await supplier_view(session, supplier, principal)


async def make_revision(
    session: AsyncSession,
    principal: Principal,
    supplier: Supplier,
    payment: Payment,
    amount_minor: int,
    simulation: str,
    version: int,
):
    if supplier.current_beneficiary_version_id is None:
        raise conflict("beneficiary_required", "A synthetic supplier destination is required.")
    beneficiary = await session.get(BeneficiaryVersion, supplier.current_beneficiary_version_id)
    revision = PaymentRevision(
        id=uuid4(),
        tenant_id=payment.tenant_id,
        payment_id=payment.id,
        beneficiary_version_id=beneficiary.id,
        version=version,
        amount_minor=amount_minor,
        currency="INR",
        simulation=simulation,
        created_by=principal.user_id,
    )
    revision.digest = digest_body(approval_body(payment, revision, beneficiary))
    session.add(revision)
    await session.flush()
    payment.current_revision_id = revision.id
    payment.state = "DRAFT"
    payment.updated_at = now()
    audit(
        session,
        payment.tenant_id,
        "payment",
        payment.id,
        "payment_revision_created",
        principal.user_id,
        revision_id=str(revision.id),
        version=version,
        digest=revision.digest,
    )
    await session.flush()
    return revision


async def create_payment(
    session: AsyncSession, principal: Principal, body: PaymentCreate
) -> PaymentView:
    async with transaction(session, principal):
        supplier = await supplier_row(session, body.supplier_id, principal.tenant.id, lock=True)
        if await session.scalar(
            select(Payment.id).where(
                Payment.tenant_id == principal.tenant.id,
                Payment.supplier_id == supplier.id,
                Payment.invoice_reference == body.invoice_reference,
            )
        ):
            raise conflict(
                "invoice_exists",
                "This supplier invoice already has a payment intent. Open the existing payment.",
            )
        payment = Payment(
            id=uuid4(),
            tenant_id=principal.tenant.id,
            supplier_id=supplier.id,
            invoice_reference=body.invoice_reference,
            state="DRAFT",
        )
        session.add(payment)
        await session.flush()
        revision = await make_revision(
            session, principal, supplier, payment, body.amount_minor, body.simulation, 1
        )
        return await payment_view(session, supplier, payment, revision)


async def get_payment(session: AsyncSession, principal: Principal, payment_id: UUID) -> PaymentView:
    async with transaction(session, principal):
        return await payment_view(
            session, *(await payment_rows(session, payment_id, principal.tenant.id))
        )


async def list_payments(session: AsyncSession, principal: Principal) -> list[PaymentView]:
    async with transaction(session, principal):
        payments = (
            await session.scalars(
                select(Payment)
                .where(Payment.tenant_id == principal.tenant.id)
                .order_by(Payment.created_at.desc())
                .limit(100)
            )
        ).all()
        result = []
        for payment in payments:
            supplier = await session.get(Supplier, payment.supplier_id)
            revision = await session.get(PaymentRevision, payment.current_revision_id)
            result.append(await payment_view(session, supplier, payment, revision))
        return result


async def revise_payment(
    session: AsyncSession, principal: Principal, payment_id: UUID, body: PaymentRevise
) -> PaymentView:
    async with transaction(session, principal):
        supplier, payment, revision = await payment_rows(
            session, payment_id, principal.tenant.id, lock=True
        )
        if payment.state in LOCKED_PAYMENT_STATES:
            raise conflict("payment_locked", "An executing or terminal payment cannot be revised.")
        if revision.id != body.expected_revision_id:
            raise conflict("stale_revision", "The payment changed. Review its current revision.")
        revision = await make_revision(
            session,
            principal,
            supplier,
            payment,
            body.amount_minor,
            body.simulation,
            revision.version + 1,
        )
        return await payment_view(session, supplier, payment, revision)


async def assert_exact_authority(
    session: AsyncSession,
    supplier: Supplier,
    payment: Payment,
    revision: PaymentRevision,
    body: PaymentDecision,
):
    if body.revision_id != revision.id or body.digest != revision.digest:
        raise conflict(
            "stale_revision", "The reviewed revision and digest must match the current payment."
        )
    beneficiary = await session.get(BeneficiaryVersion, revision.beneficiary_version_id)
    if revision.digest != digest_body(approval_body(payment, revision, beneficiary)):
        raise conflict("digest_mismatch", "The immutable payment binding could not be verified.")
    holds = await prerequisite_holds(session, supplier, revision)
    if any("evidence" in hold.lower() or "investigation" in hold.lower() for hold in holds):
        raise conflict(
            "evidence_review_required",
            "A completed, human-reviewed investigation of the current evidence snapshot is required.",
        )
    if holds:
        raise conflict(
            "beneficiary_not_accepted",
            "The current destination requires supplier confirmation and finance acceptance.",
        )
    return beneficiary


async def approve_payment(
    session: AsyncSession, principal: Principal, payment_id: UUID, body: PaymentDecision
) -> PaymentView:
    async with transaction(session, principal):
        supplier, payment, revision = await payment_rows(
            session, payment_id, principal.tenant.id, lock=True
        )
        if payment.state in LOCKED_PAYMENT_STATES:
            raise conflict(
                "payment_locked", "An executing or terminal payment cannot receive a new approval."
            )
        await assert_exact_authority(session, supplier, payment, revision, body)
        if not await latest_approval(session, payment, revision):
            timestamp = await session.scalar(select(func.clock_timestamp()))
            from app.evidence.domain import evidence_state

            evidence_digest, _ = await evidence_state(session, payment.id)
            approval = PaymentApproval(
                id=uuid4(),
                tenant_id=payment.tenant_id,
                payment_id=payment.id,
                revision_id=revision.id,
                digest=revision.digest,
                approved_by=principal.user_id,
                evidence_digest=evidence_digest,
                created_at=timestamp,
                expires_at=timestamp
                + timedelta(seconds=get_settings().payment_approval_ttl_seconds),
            )
            session.add(approval)
            audit(
                session,
                payment.tenant_id,
                "payment",
                payment.id,
                "payment_approved",
                principal.user_id,
                revision_id=str(revision.id),
                digest=revision.digest,
                expires_at=approval.expires_at.isoformat(),
            )
        payment.state, payment.updated_at = "APPROVED", now()
        await session.flush()
        return await payment_view(session, supplier, payment, revision)


async def queue_payment(
    session: AsyncSession,
    principal: Principal,
    payment_id: UUID,
    body: PaymentDecision,
    request_key: str,
) -> PaymentView:
    async with transaction(session, principal):
        supplier, payment, revision = await payment_rows(
            session, payment_id, principal.tenant.id, lock=True
        )
        existing = await session.scalar(select(Execution).where(Execution.payment_id == payment.id))
        key_owner = await session.scalar(
            select(Execution).where(
                Execution.tenant_id == payment.tenant_id, Execution.request_key == request_key
            )
        )
        if key_owner and (
            key_owner.payment_id != payment.id or key_owner.revision_id != body.revision_id
        ):
            raise conflict(
                "idempotency_conflict",
                "This idempotency key is already bound to another payment revision.",
            )
        if existing:
            if (
                existing.revision_id != body.revision_id
                or existing.body.get("digest") != body.digest
            ):
                raise conflict(
                    "execution_exists", "An execution is already bound to another revision."
                )
            return await payment_view(session, supplier, payment, revision)
        if payment.state in LOCKED_PAYMENT_STATES:
            raise conflict("payment_locked", "This payment cannot be queued.")
        beneficiary = await assert_exact_authority(session, supplier, payment, revision, body)
        approval = await latest_approval(session, payment, revision)
        if not approval:
            raise conflict("approval_required", "An exact, unexpired payment approval is required.")
        execution = Execution(
            id=uuid4(),
            tenant_id=payment.tenant_id,
            payment_id=payment.id,
            revision_id=revision.id,
            approval_id=approval.id,
            request_key=request_key,
            body=sandbox_body(payment, revision, beneficiary),
            state="QUEUED",
        )
        session.add(execution)
        payment.state, payment.updated_at = "QUEUED", now()
        audit(
            session,
            payment.tenant_id,
            "payment",
            payment.id,
            "execution_queued",
            principal.user_id,
            execution_id=str(execution.id),
            revision_id=str(revision.id),
            digest=revision.digest,
        )
        await session.flush()
        return await payment_view(session, supplier, payment, revision)


async def locked_execution(session: AsyncSession, execution_id: UUID, *, skip_locked=False):
    seed = (
        await session.execute(
            select(Execution.payment_id, Execution.tenant_id, Payment.supplier_id)
            .join(Payment, Payment.id == Execution.payment_id)
            .where(Execution.id == execution_id)
        )
    ).one_or_none()
    if seed is None:
        return None
    supplier = await session.scalar(
        select(Supplier)
        .where(Supplier.id == seed.supplier_id)
        .with_for_update(skip_locked=skip_locked)
    )
    if supplier is None:
        return None
    payment = await session.scalar(
        select(Payment)
        .where(Payment.id == seed.payment_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )
    if payment is None:
        return None
    execution = await session.scalar(
        select(Execution)
        .where(Execution.id == execution_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )
    return (supplier, payment, execution) if execution else None


def claim_view(execution: Execution) -> dict:
    return {
        "execution_id": str(execution.id),
        "lease_token": str(execution.lease_token),
        "body": dict(execution.body),
        "state": execution.state,
    }


async def claim_execution(session: AsyncSession, worker_id: str) -> dict | None:
    """Commit a leased claim before HTTP. A claimed transfer is never reposted."""
    async with transaction(session):
        candidates = (
            await session.scalars(
                select(Execution.id)
                .where(Execution.state == "QUEUED")
                .order_by(Execution.created_at)
                .limit(25)
            )
        ).all()
        for execution_id in candidates:
            rows = await locked_execution(session, execution_id, skip_locked=True)
            if not rows:
                continue
            supplier, payment, execution = rows
            if execution.state != "QUEUED" or payment.state != "QUEUED":
                continue
            revision = await session.get(PaymentRevision, execution.revision_id)
            approval = await session.get(PaymentApproval, execution.approval_id)
            timestamp = await session.scalar(select(func.clock_timestamp()))
            try:
                if payment.current_revision_id != revision.id:
                    raise conflict("stale_revision", "The queued revision is no longer current.")
                beneficiary = await assert_exact_authority(
                    session,
                    supplier,
                    payment,
                    revision,
                    PaymentDecision(
                        revision_id=revision.id, digest=execution.body.get("digest", "")
                    ),
                )
                from app.evidence.domain import evidence_state

                evidence_digest, _ = await evidence_state(session, payment.id)
                if (
                    approval.expires_at <= timestamp
                    or approval.revision_id != revision.id
                    or approval.digest != revision.digest
                    or approval.evidence_digest != evidence_digest
                    or execution.body != sandbox_body(payment, revision, beneficiary)
                ):
                    raise conflict("approval_expired", "The queued authority is no longer valid.")
            except AppError as error:
                execution.state = payment.state = "FAILED"
                execution.updated_at = payment.updated_at = timestamp
                audit(
                    session,
                    payment.tenant_id,
                    "payment",
                    payment.id,
                    "dispatch_blocked",
                    None,
                    reason=error.code,
                )
                await session.flush()
                continue
            execution.state = payment.state = "SUBMITTING"
            execution.lease_token = uuid4()
            execution.worker_id = worker_id[:100]
            execution.lease_until = timestamp + timedelta(
                seconds=get_settings().payment_worker_lease_seconds
            )
            execution.updated_at = payment.updated_at = timestamp
            audit(
                session,
                payment.tenant_id,
                "payment",
                payment.id,
                "execution_submitting",
                None,
                execution_id=str(execution.id),
                revision_id=str(revision.id),
            )
            await session.flush()
            return claim_view(execution)
    return None


async def claim_reconciliation(session: AsyncSession, worker_id: str) -> dict | None:
    """Recover expired claims by GET only, including a crash before the POST."""
    async with transaction(session):
        timestamp = await session.scalar(select(func.clock_timestamp()))
        candidates = (
            await session.scalars(
                select(Execution.id)
                .where(
                    or_(
                        and_(Execution.state == "SUBMITTING", Execution.lease_until <= timestamp),
                        and_(
                            Execution.state == "UNKNOWN",
                            Execution.next_attempt_at <= timestamp,
                            or_(
                                Execution.lease_until.is_(None), Execution.lease_until <= timestamp
                            ),
                        ),
                    )
                )
                .order_by(Execution.next_attempt_at)
                .limit(25)
            )
        ).all()
        for execution_id in candidates:
            rows = await locked_execution(session, execution_id, skip_locked=True)
            if not rows:
                continue
            _, payment, execution = rows
            if execution.state not in {"SUBMITTING", "UNKNOWN"}:
                continue
            if execution.lease_until and execution.lease_until > timestamp:
                continue
            if execution.state == "SUBMITTING":
                execution.state = payment.state = "UNKNOWN"
                audit(
                    session,
                    payment.tenant_id,
                    "payment",
                    payment.id,
                    "execution_unknown",
                    None,
                    execution_id=str(execution.id),
                    reason="worker_lease_expired",
                )
            execution.lease_token = uuid4()
            execution.worker_id = worker_id[:100]
            execution.lease_until = timestamp + timedelta(
                seconds=get_settings().payment_worker_lease_seconds
            )
            execution.next_attempt_at = timestamp + timedelta(
                seconds=get_settings().payment_reconcile_interval_seconds
            )
            execution.updated_at = payment.updated_at = timestamp
            await session.flush()
            return claim_view(execution)
    return None


def readback_matches(execution: Execution, readback: dict | None) -> bool:
    if not isinstance(readback, dict):
        return False
    if readback.get("idempotency_key") != str(execution.id) or readback.get("status") not in {
        "SUCCEEDED",
        "FAILED",
    }:
        return False
    transfer_id = readback.get("transfer_id")
    if not isinstance(transfer_id, str) or not 1 <= len(transfer_id) <= 100:
        return False
    return all(
        type(readback.get(key)) is type(value) and readback[key] == value
        for key, value in execution.body.items()
    )


async def finish_execution(
    session: AsyncSession,
    execution_id: UUID,
    lease_token: UUID,
    readback: dict | None,
    *,
    uncertain: bool = True,
) -> None:
    """Only independently verified, exact readback can establish a terminal result."""
    async with transaction(session):
        rows = await locked_execution(session, execution_id)
        if rows is None:
            return
        _, payment, execution = rows
        if execution.state not in {"SUBMITTING", "UNKNOWN"} or execution.lease_token != lease_token:
            return  # A newer lease owns reconciliation; ignore a late old worker.
        timestamp = await session.scalar(select(func.clock_timestamp()))
        was_unknown = execution.state == "UNKNOWN"
        if uncertain or not readback_matches(execution, readback):
            execution.state = payment.state = "UNKNOWN"
            execution.next_attempt_at = timestamp + timedelta(
                seconds=get_settings().payment_reconcile_interval_seconds
            )
            if not was_unknown:
                audit(
                    session,
                    payment.tenant_id,
                    "payment",
                    payment.id,
                    "execution_unknown",
                    None,
                    execution_id=str(execution.id),
                    reason="independent_readback_unavailable_or_conflicting",
                )
        else:
            execution.state = payment.state = readback["status"]
            execution.transfer_id = readback["transfer_id"]
            audit(
                session,
                payment.tenant_id,
                "payment",
                payment.id,
                "execution_succeeded" if readback["status"] == "SUCCEEDED" else "execution_failed",
                None,
                execution_id=str(execution.id),
                transfer_id=execution.transfer_id,
                verified_by="independent_readback",
            )
        execution.lease_token = execution.lease_until = None
        execution.updated_at = payment.updated_at = timestamp
        await session.flush()
