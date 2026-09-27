"""Sponsor operations are receipts and advisory features, never payment authority."""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import assert_restricted_role
from app.core.errors import AppError
from app.payments.domain import (
    audit,
    conflict,
    now,
    payment_rows,
    payment_view,
    supplier_row,
    supplier_view,
    transaction,
)
from app.payments.models import SupplierConfirmation, SupplierIdentity
from app.integrations.models import BillingAccount, Delivery, VoiceOperation
from app.integrations import providers as provider


def delivery_view(row, *, current_version=None):
    return dict(
        id=str(row.id),
        supplier_id=str(row.supplier_id),
        beneficiary_version_id=str(row.beneficiary_version_id),
        status="STALE"
        if current_version is not None and row.beneficiary_version_id != current_version
        else row.status,
        created_at=row.created_at,
        delivered_at=row.delivered_at,
        attempts=row.attempts,
    )


async def deliveries(session, principal, supplier_id=None):
    async with transaction(session, principal):
        query = select(Delivery).where(Delivery.tenant_id == principal.tenant.id)
        if supplier_id:
            await supplier_row(session, supplier_id, principal.tenant.id)
            query = query.where(Delivery.supplier_id == supplier_id)
        else:
            query = query.where(Delivery.status.in_(["DELIVERED", "STALE"]))
        rows = (await session.scalars(query.order_by(Delivery.created_at.desc()).limit(100))).all()
        result = []
        for row in rows:
            supplier = await supplier_row(session, row.supplier_id, principal.tenant.id)
            result.append(
                delivery_view(row, current_version=supplier.current_beneficiary_version_id)
            )
        return {"deliveries": result}


async def request_delivery(
    session, principal, client, settings, supplier_id, version_id=None, delivery_id=None
):
    if not settings.n8n_configured:
        raise AppError(503, "n8n_not_configured", "n8n delivery is not configured.")
    async with transaction(session, principal):
        supplier = await supplier_row(session, supplier_id, principal.tenant.id, lock=True)
        version_id = version_id or supplier.current_beneficiary_version_id
        if not version_id or version_id != supplier.current_beneficiary_version_id:
            raise conflict(
                "stale_beneficiary",
                "Reload the current supplier version before requesting confirmation.",
            )
        confirmation = await session.scalar(
            select(SupplierConfirmation.id).where(
                SupplierConfirmation.beneficiary_version_id == version_id
            )
        )
        if confirmation:
            raise conflict(
                "already_confirmed", "The current beneficiary version is already confirmed."
            )
        assigned = await session.scalar(
            select(SupplierIdentity.id).where(SupplierIdentity.supplier_id == supplier.id)
        )
        if not assigned:
            raise conflict(
                "supplier_unassigned", "Assign an authenticated supplier identity before delivery."
            )
        row = await session.scalar(
            select(Delivery)
            .where(
                Delivery.supplier_id == supplier.id, Delivery.beneficiary_version_id == version_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if delivery_id:
            if row is None or row.id != delivery_id or row.status != "DELIVERED":
                raise conflict(
                    "reminder_unavailable",
                    "Only a delivered current request can receive a reminder.",
                )
            if row.attempts >= 3 or now() - row.last_attempt_at < timedelta(seconds=60):
                raise AppError(
                    429,
                    "reminder_limited",
                    "Wait at least 60 seconds between requests; at most three attempts are allowed.",
                )
            row.attempts += 1
            row.status = "PENDING"
            row.last_attempt_at = now()
        elif row:
            if row.status != "FAILED":
                # A receipt survives timeouts; never blindly repeat uncertain sends.
                return delivery_view(row, current_version=version_id)
            if row.attempts >= 3 or now() - row.last_attempt_at < timedelta(seconds=60):
                raise AppError(
                    429,
                    "reminder_limited",
                    "Wait at least 60 seconds between requests; at most three attempts are allowed.",
                )
            row.attempts += 1
            row.status = "PENDING"
            row.last_attempt_at = now()
        else:
            row = Delivery(
                id=uuid4(),
                tenant_id=principal.tenant.id,
                supplier_id=supplier.id,
                beneficiary_version_id=version_id,
                status="PENDING",
                attempts=1,
                last_attempt_at=now(),
            )
            session.add(row)
        audit(
            session,
            principal.tenant.id,
            "delivery",
            row.id,
            "delivery_requested",
            principal.user_id,
            attempt=row.attempts,
        )
        await session.flush()
        did, attempt = row.id, row.attempts
    try:
        await provider.deliver(client, settings, did, attempt)
    except AppError:
        async with transaction(session, principal):
            row = await session.scalar(
                select(Delivery)
                .where(Delivery.id == did)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row.status == "PENDING" and row.attempts == attempt:
                row.status = "UNKNOWN"
        raise
    async with transaction(session, principal):
        row = await session.scalar(
            select(Delivery).where(Delivery.id == did).execution_options(populate_existing=True)
        )
        return delivery_view(row)


@asynccontextmanager
async def callback_transaction(session):
    try:
        async with asyncio.timeout(8), session.begin():
            await assert_restricted_role(session)
            yield
    except (SQLAlchemyError, TimeoutError):
        raise AppError(
            503, "callback_unavailable", "The callback receipt could not be committed."
        ) from None


async def delivery_callback(session, body, digest):
    async with callback_transaction(session):
        result = await session.scalar(
            text("SELECT beforetransfer.delivery_callback(:eid,:digest,:did,:attempt,:outcome)"),
            {
                "eid": body.event_id,
                "digest": digest,
                "did": body.delivery_id,
                "attempt": body.attempt,
                "outcome": body.status,
            },
        )
        if result == "conflict":
            raise conflict(
                "callback_conflict", "The callback event does not match its stored receipt."
            )
        if result in {"missing", "invalid"}:
            raise AppError(404, "delivery_not_found", "The delivery request does not exist.")
        return {"status": result}


def billing_view(row, settings):
    current = now()
    entitled = bool(
        settings.billing_configured
        and row
        and row.status == "ACTIVE"
        and row.expires_at
        and row.expires_at > current
        and row.verified_at
        and current - row.verified_at < timedelta(minutes=5)
    )
    status = "UNCONFIGURED" if not settings.billing_configured else row.status if row else "NONE"
    if status == "ACTIVE" and not entitled:
        status = "EXPIRED" if row.expires_at and row.expires_at <= current else "UNKNOWN"
    return {
        "mode": "test",
        "configured": bool(settings.billing_configured),
        "entitled": entitled,
        "status": status,
        "expires_at": row.expires_at if row else None,
    }


async def billing_status(session, principal, settings):
    async with transaction(session, principal):
        row = await session.get(BillingAccount, principal.tenant.id)
        return billing_view(row, settings)


def configured_billing(settings):
    if not settings.billing_configured:
        raise AppError(503, "billing_not_configured", "Dodo test billing is not configured.")


async def checkout(session, principal, client, settings):
    configured_billing(settings)
    async with transaction(session, principal):
        # Serializes creation when no billing row exists yet, scoped to server-authenticated tenant.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant,0))"),
            {"tenant": str(principal.tenant.id)},
        )
        row = await session.scalar(
            select(BillingAccount)
            .where(BillingAccount.tenant_id == principal.tenant.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row and row.status == "CHECKOUT_PENDING" and row.checkout_url:
            return {"checkout_url": row.checkout_url, "checkout_id": row.checkout_id}
        if row and row.status not in {"CANCELLED", "EXPIRED", "FAILED"}:
            raise conflict(
                "checkout_pending",
                "Reconcile the existing billing operation before starting another checkout.",
            )
        operation = uuid4()
        if row is None:
            row = BillingAccount(
                tenant_id=principal.tenant.id,
                operation_id=operation,
                status="UNKNOWN",
                product_id=settings.dodo_product_id,
            )
            session.add(row)
        else:
            row.operation_id = operation
            row.status = "UNKNOWN"
            row.product_id = settings.dodo_product_id
            row.checkout_id = row.checkout_url = row.customer_id = row.subscription_id = None
            row.verified_at = row.expires_at = row.reconcile_token = None
        audit(
            session,
            principal.tenant.id,
            "billing",
            operation,
            "checkout_requested",
            principal.user_id,
        )
    result = await provider.create_checkout(client, settings, operation)
    async with transaction(session, principal):
        row = await session.scalar(
            select(BillingAccount)
            .where(BillingAccount.tenant_id == principal.tenant.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row.operation_id != operation:
            raise conflict(
                "billing_changed", "The billing operation changed while checkout was created."
            )
        row.checkout_id = result["checkout_id"]
        row.checkout_url = result["checkout_url"]
        row.status = "CHECKOUT_PENDING"
    return result


def billing_context(row):
    return {
        key: getattr(row, key)
        for key in ("checkout_id", "product_id", "customer_id", "subscription_id")
    }


def apply_billing(row, result):
    # Previously bound identity is never cleared by an incomplete provider response.
    for key in ("customer_id", "subscription_id"):
        if getattr(row, key) is not None and result[key] != getattr(row, key):
            raise conflict(
                "billing_identity_changed", "The provider billing identity could not be matched."
            )
    row.status = result["status"]
    row.customer_id = result["customer_id"]
    row.subscription_id = result["subscription_id"]
    row.expires_at = datetime.fromisoformat(result["expires_at"]) if result["expires_at"] else None
    row.verified_at = now()
    row.reconcile_token = None


async def reconcile(session, principal, client, settings):
    configured_billing(settings)
    async with transaction(session, principal):
        row = await session.scalar(
            select(BillingAccount)
            .where(BillingAccount.tenant_id == principal.tenant.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not row or not row.checkout_id:
            raise conflict(
                "checkout_unknown",
                "No stored checkout can be reconciled. A lost checkout creation requires operator investigation.",
            )
        token = uuid4()
        operation = row.operation_id
        context = billing_context(row)
        row.reconcile_token = token
        row.status = "UNKNOWN"
        row.verified_at = None
    result = await provider.reconcile_billing(client, settings, context)
    async with transaction(session, principal):
        row = await session.scalar(
            select(BillingAccount)
            .where(BillingAccount.tenant_id == principal.tenant.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row.operation_id == operation and row.reconcile_token == token:
            apply_billing(row, result)
        return billing_view(row, settings)


async def billing_webhook(session, client, settings, event_id, body, digest):
    configured_billing(settings)
    data = body.get("data", {})
    if not isinstance(data, dict):
        raise AppError(422, "invalid_webhook_body", "The webhook body is invalid.")
    metadata = data.get("metadata", {})
    try:
        operation = (
            UUID(metadata["beforetransfer_operation"])
            if isinstance(metadata, dict) and metadata.get("beforetransfer_operation")
            else None
        )
        subscription = data.get("subscription_id")
        if subscription is not None:
            provider.identifier(subscription)
    except (ValueError, TypeError, KeyError):
        raise AppError(
            422, "invalid_webhook_body", "The webhook routing reference is invalid."
        ) from None
    token = uuid4()
    async with callback_transaction(session):
        context = await session.scalar(
            text("SELECT beforetransfer.billing_event_claim(:eid,:digest,:opid,:subid,:token)"),
            {
                "eid": event_id,
                "digest": digest,
                "opid": operation,
                "subid": subscription,
                "token": token,
            },
        )
    if context["result"] == "conflict":
        raise conflict("webhook_conflict", "The webhook event does not match its stored receipt.")
    if context["result"] != "reconcile":
        return {"status": context["result"]}
    result = await provider.reconcile_billing(client, settings, context)
    async with callback_transaction(session):
        committed = await session.scalar(
            text(
                "SELECT beforetransfer.billing_event_finish(:eid,:opid,:token,:outcome,:cid,:sid,:expiry)"
            ),
            {
                "eid": event_id,
                "opid": UUID(context["operation_id"]),
                "token": token,
                "outcome": result["status"],
                "cid": result["customer_id"],
                "sid": result["subscription_id"],
                "expiry": datetime.fromisoformat(result["expires_at"])
                if result["expires_at"]
                else None,
            },
        )
    return {"status": "processed" if committed else "superseded"}


async def audio(session, principal, client, settings, investigation_id):
    from app.evidence.domain import require_reviewed_investigation
    from app.evidence.providers import safe_review_summary
    from app.integrations.voice import generate_audio

    if not settings.voice_configured:
        raise AppError(503, "voice_not_configured", "ElevenLabs voice is not configured.")
    async with transaction(session, principal):
        investigation = await require_reviewed_investigation(session, principal, investigation_id)
        summary = safe_review_summary(investigation)
        digest = hashlib.sha256(summary.encode()).hexdigest()
        row = await session.scalar(
            select(VoiceOperation).where(
                VoiceOperation.investigation_id == investigation.id,
                VoiceOperation.text_digest == digest,
                VoiceOperation.voice_id == settings.elevenlabs_voice_id,
            )
        )
        if row:
            if row.status == "READY":
                return row.audio
            raise conflict(
                "voice_pending",
                "The existing audio request is pending or uncertain; no automatic retry is allowed.",
            )
        operation = uuid4()
        session.add(
            VoiceOperation(
                id=operation,
                tenant_id=principal.tenant.id,
                investigation_id=investigation.id,
                text_digest=digest,
                voice_id=settings.elevenlabs_voice_id,
                status="PENDING",
            )
        )
        audit(
            session, principal.tenant.id, "voice", operation, "voice_requested", principal.user_id
        )
    try:
        content = await generate_audio(client, settings, summary)
    except AppError:
        async with transaction(session, principal):
            row = await session.get(VoiceOperation, operation)
            row.status = "UNKNOWN"
        raise
    async with transaction(session, principal):
        # Preserve the current evidence/review gate even if evidence changed during synthesis.
        await require_reviewed_investigation(session, principal, investigation_id)
        row = await session.get(VoiceOperation, operation)
        row.status = "READY"
        row.audio = content
    return content


async def report(session, principal, settings, payment_id):
    from app.evidence.models import EvidenceDocument, Investigation
    from app.evidence.domain import serialize_investigation

    async with transaction(session, principal):
        row = await session.get(BillingAccount, principal.tenant.id)
        if not billing_view(row, settings)["entitled"]:
            raise AppError(
                403,
                "report_entitlement_required",
                "A recently verified active test subscription is required for report export.",
            )
        supplier, payment, revision = await payment_rows(session, payment_id, principal.tenant.id)
        docs = (
            await session.scalars(
                select(EvidenceDocument)
                .where(EvidenceDocument.payment_id == payment_id)
                .order_by(EvidenceDocument.created_at)
            )
        ).all()
        investigations = (
            await session.scalars(
                select(Investigation)
                .where(Investigation.payment_id == payment_id)
                .order_by(Investigation.created_at)
            )
        ).all()
        return {
            "payment": (await payment_view(session, supplier, payment, revision)).model_dump(
                mode="json"
            ),
            "supplier": (await supplier_view(session, supplier, principal)).model_dump(mode="json"),
            "evidence": [
                dict(
                    id=str(d.id),
                    revision_id=str(d.revision_id),
                    filename=d.filename,
                    media_type=d.media_type,
                    sha256=d.sha256,
                    extraction_status=d.status,
                    created_at=d.created_at.isoformat(),
                )
                for d in docs
            ],
            "investigations": [await serialize_investigation(session, i) for i in investigations],
            "generated_at": now().isoformat(),
            "advisory": True,
            "mode": "test",
        }
