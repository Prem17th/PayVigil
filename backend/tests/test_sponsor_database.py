"""Real isolated PostgreSQL tests for sponsor receipts and authority separation."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.payments import domain as payments
from app.integrations import domain
from app.core.errors import AppError
from app.payments.models import PaymentApproval, SupplierConfirmation
from app.payments.schemas import BeneficiaryCreate
from app.integrations.models import BillingAccount, Delivery, SponsorEvent
from test_payment_domain import payment_db as payment_db
from test_payment_domain import call, prepare_payment
from test_sponsor_providers import settings


async def sponsor(db, fn, *args, actor=None):
    async with db.api() as session:
        return await fn(session, actor or db.finance, *args)


async def callback(db, delivery_id, *, attempt=1, status="DELIVERED", eid=None, digest="a" * 64):
    body = SimpleNamespace(
        delivery_id=UUID(str(delivery_id)),
        attempt=attempt,
        status=status,
        event_id=eid or str(delivery_id) + ":" + str(attempt),
    )
    async with db.api() as session:
        return await domain.delivery_callback(session, body, digest)


async def test_delivery_callback_replay_tenant_and_payment_authority(payment_db, monkeypatch):
    db = payment_db
    payment = await prepare_payment(db, accepted=False)
    calls = []

    async def deliver(*args):
        calls.append(args[2])

    monkeypatch.setattr(domain.provider, "deliver", deliver)

    async def create():
        return await sponsor(
            db,
            domain.request_delivery,
            None,
            settings(),
            db.supplier_id,
            payment.current_revision.beneficiary_version_id,
        )

    receipts = await asyncio.gather(*(create() for _ in range(5)))
    assert len(calls) == 1 and len({r["id"] for r in receipts}) == 1
    did = receipts[0]["id"]
    assert (await callback(db, did))["status"] == "processed"
    assert (await callback(db, did))["status"] == "duplicate"
    with pytest.raises(AppError, match="callback_conflict"):
        await callback(db, did, digest="b" * 64)
    inbox = await sponsor(db, domain.deliveries, actor=db.supplier)
    assert [r["id"] for r in inbox["deliveries"]] == [did]
    assert (await sponsor(db, domain.deliveries, actor=db.outsider))["deliveries"] == []
    async with db.admin() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SupplierConfirmation)
                .where(SupplierConfirmation.supplier_id == db.supplier_id)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PaymentApproval)
                .where(PaymentApproval.payment_id == payment.id)
            )
            == 0
        )
    with pytest.raises(AppError, match="reminder_limited"):
        await sponsor(
            db,
            domain.request_delivery,
            None,
            settings(),
            db.supplier_id,
            payment.current_revision.beneficiary_version_id,
            UUID(did),
        )
    await call(
        db,
        payments.add_beneficiary,
        db.supplier_id,
        BeneficiaryCreate(
            expected_version_id=payment.current_revision.beneficiary_version_id,
            beneficiary_name="Synthetic changed",
            sandbox_account_id="SIM-NEW-001",
        ),
    )
    await callback(db, did, eid=str(uuid4()), digest="c" * 64)
    assert (await sponsor(db, domain.deliveries, actor=db.supplier))["deliveries"][0][
        "status"
    ] == "STALE"


async def test_delivery_callback_wins_race_with_lost_provider_response(payment_db, monkeypatch):
    db = payment_db
    payment = await prepare_payment(db, accepted=False)

    async def uncertain(client, config, did, attempt):
        await callback(db, did, attempt=attempt)
        raise AppError(503, "n8n_unavailable", "Synthetic lost response")

    monkeypatch.setattr(domain.provider, "deliver", uncertain)
    with pytest.raises(AppError):
        await sponsor(
            db,
            domain.request_delivery,
            None,
            settings(),
            db.supplier_id,
            payment.current_revision.beneficiary_version_id,
        )
    rows = await sponsor(db, domain.deliveries, db.supplier_id)
    assert rows["deliveries"][0]["status"] == "DELIVERED"


async def seed_billing(db):
    operation = uuid4()
    async with db.admin() as session, session.begin():
        session.add(
            BillingAccount(
                tenant_id=db.tenant_id,
                operation_id=operation,
                status="CHECKOUT_PENDING",
                checkout_id="cks_" + operation.hex,
                checkout_url="https://test.checkout.dodopayments.com/test",
                product_id="pdt_test",
            )
        )
    return operation


def outcome(status="ACTIVE"):
    return {
        "status": status,
        "customer_id": "cus_" + str(uuid4()).replace("-", ""),
        "subscription_id": "sub_" + str(uuid4()).replace("-", ""),
        "expires_at": (domain.now() + timedelta(days=1)).isoformat()
        if status == "ACTIVE"
        else None,
    }


async def test_reconcile_fence_prevents_stale_active_overwriting_cancellation(
    payment_db, monkeypatch
):
    db = payment_db
    await seed_billing(db)
    entered = asyncio.Event()
    release = asyncio.Event()
    count = 0
    active = outcome()
    cancelled = {**active, "status": "CANCELLED", "expires_at": None}

    async def readback(*args):
        nonlocal count
        count += 1
        if count == 1:
            entered.set()
            await release.wait()
            return active
        return cancelled

    monkeypatch.setattr(domain.provider, "reconcile_billing", readback)
    first = asyncio.create_task(sponsor(db, domain.reconcile, None, settings()))
    await entered.wait()
    newer = await sponsor(db, domain.reconcile, None, settings())
    assert newer["status"] == "CANCELLED"
    release.set()
    older = await first
    assert older["status"] == "CANCELLED" and not older["entitled"]
    assert (await sponsor(db, domain.billing_status, settings()))["status"] == "CANCELLED"


async def test_signed_event_payload_is_hint_not_entitlement_and_replay_is_once(
    payment_db, monkeypatch
):
    db = payment_db
    operation = await seed_billing(db)
    reads = []
    cancelled = outcome("CANCELLED")

    async def provider(*args):
        reads.append(args[-1])
        return cancelled

    monkeypatch.setattr(domain.provider, "reconcile_billing", provider)
    event_id = "msg_" + uuid4().hex
    body = {
        "type": "subscription.active",
        "data": {"status": "active", "metadata": {"beforetransfer_operation": str(operation)}},
    }

    async def webhook(digest="a" * 64):
        async with db.api() as session:
            return await domain.billing_webhook(session, None, settings(), event_id, body, digest)

    assert (await webhook())["status"] == "processed"
    assert (await webhook())["status"] == "duplicate"
    assert len(reads) == 1 and reads[0]["product_id"] == "pdt_test"
    assert (await sponsor(db, domain.billing_status, settings()))["status"] == "CANCELLED"
    with pytest.raises(AppError, match="webhook_conflict"):
        await webhook("b" * 64)
    async with db.admin() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SponsorEvent)
                .where(SponsorEvent.provider == "dodo", SponsorEvent.event_id == event_id)
            )
            == 1
        )
    assert (await sponsor(db, domain.billing_status, settings(), actor=db.outsider))[
        "status"
    ] == "NONE"


async def test_unknown_checkout_never_blindly_repeats_and_report_fails_closed(
    payment_db, monkeypatch
):
    db = payment_db
    calls = []

    async def uncertain(*args):
        calls.append(args[-1])
        raise AppError(503, "billing_unavailable", "Synthetic lost response")

    monkeypatch.setattr(domain.provider, "create_checkout", uncertain)
    with pytest.raises(AppError):
        await sponsor(db, domain.checkout, None, settings())
    with pytest.raises(AppError, match="checkout_pending"):
        await sponsor(db, domain.checkout, None, settings())
    assert len(calls) == 1
    with pytest.raises(AppError, match="report_entitlement_required"):
        await sponsor(db, domain.report, settings(), uuid4())


async def test_entitlement_expires_and_callback_tables_are_not_browser_writable(payment_db):
    db = payment_db
    await seed_billing(db)
    async with db.admin() as session, session.begin():
        row = await session.get(BillingAccount, db.tenant_id)
        row.status = "ACTIVE"
        row.expires_at = domain.now() + timedelta(days=1)
        row.verified_at = domain.now() - timedelta(minutes=6)
    view = await sponsor(db, domain.billing_status, settings())
    assert not view["entitled"] and view["status"] == "UNKNOWN"
    async with db.api() as session:
        with pytest.raises(DBAPIError):
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO beforetransfer.sponsor_events(provider,event_id,payload_digest,status) VALUES ('dodo','forged','x','processed')"
                    )
                )
    async with db.admin() as session:
        for role in ["anon", "authenticated"]:
            exists = await session.scalar(
                text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:r)"), {"r": role}
            )
            if exists:
                assert not await session.scalar(
                    text(
                        "SELECT has_function_privilege(:r,'beforetransfer.delivery_callback(text,text,uuid,integer,text)','EXECUTE')"
                    ),
                    {"r": role},
                )


async def test_voice_requires_current_review_and_caches_only_safe_template(payment_db, monkeypatch):
    from app.evidence.models import Investigation
    from app.evidence.domain import review_investigation
    from app.payments.schemas import PaymentRevise
    from app.integrations.settings import SponsorSettings

    db = payment_db
    payment = await prepare_payment(db, accepted=False)
    iid = uuid4()
    async with db.admin() as session, session.begin():
        session.add(
            Investigation(
                id=iid,
                tenant_id=db.tenant_id,
                payment_id=payment.id,
                revision_id=payment.current_revision.id,
                evidence_digest="4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
                document_ids=[],
                status="completed",
                summary="Private Name secret@private.invalid SIM-ACCOUNT-123456",
                findings=[
                    {
                        "code": "manual_verification_required",
                        "severity": "warning",
                        "explanation": "Private Name",
                        "citations": [],
                    }
                ],
                tool_trace=[],
                provider="synthetic-test",
                created_by=db.finance.user_id,
            )
        )
    config = SponsorSettings(
        _env_file=None, elevenlabs_api_key="synthetic-key", elevenlabs_voice_id="stock_test"
    )
    texts = []

    async def voice(client, settings, summary):
        texts.append(summary)
        return b"ID3synthetic-audio"

    monkeypatch.setattr("app.integrations.voice.generate_audio", voice)
    with pytest.raises(AppError, match="investigation_review_required"):
        await sponsor(db, domain.audio, None, config, iid)
    assert not texts
    await sponsor(db, review_investigation, iid, "Reviewed synthetic findings")
    first = await sponsor(db, domain.audio, None, config, iid)
    assert first == await sponsor(db, domain.audio, None, config, iid)
    assert (
        len(texts) == 1
        and "Private Name" not in texts[0]
        and "secret@" not in texts[0]
        and "SIM-" not in texts[0]
    )
    await call(
        db,
        payments.revise_payment,
        payment.id,
        PaymentRevise(
            expected_revision_id=payment.current_revision.id,
            amount_minor=20000,
            simulation="success",
        ),
    )
    with pytest.raises(AppError, match="stale_investigation"):
        await sponsor(db, domain.audio, None, config, iid)
    assert len(texts) == 1


async def test_reminder_attempt_budget_and_old_callback_cannot_override_new_attempt(
    payment_db, monkeypatch
):
    db = payment_db
    payment = await prepare_payment(db, accepted=False)

    async def sent(*args):
        pass

    monkeypatch.setattr(domain.provider, "deliver", sent)
    row = await sponsor(
        db,
        domain.request_delivery,
        None,
        settings(),
        db.supplier_id,
        payment.current_revision.beneficiary_version_id,
    )
    did = UUID(row["id"])
    await callback(db, did)
    for attempt in (2, 3):
        async with db.admin() as session, session.begin():
            saved = await session.get(Delivery, did)
            saved.last_attempt_at = domain.now() - timedelta(seconds=61)
        row = await sponsor(
            db,
            domain.request_delivery,
            None,
            settings(),
            db.supplier_id,
            payment.current_revision.beneficiary_version_id,
            did,
        )
        assert row["attempts"] == attempt and row["status"] == "PENDING"
        await callback(
            db,
            did,
            attempt=attempt - 1,
            eid=str(uuid4()),
            status="FAILED",
            digest=str(attempt) * 64,
        )
        assert (await sponsor(db, domain.deliveries, db.supplier_id))["deliveries"][0][
            "status"
        ] == "PENDING"
        await callback(db, did, attempt=attempt)
    with pytest.raises(AppError, match="reminder_limited"):
        await sponsor(
            db,
            domain.request_delivery,
            None,
            settings(),
            db.supplier_id,
            payment.current_revision.beneficiary_version_id,
            did,
        )


async def test_explicit_known_failed_delivery_retry_keeps_receipt_and_budget(
    payment_db, monkeypatch
):
    db = payment_db
    payment = await prepare_payment(db, accepted=False)
    calls = []

    async def send(client, config, did, attempt):
        calls.append((did, attempt))

    monkeypatch.setattr(domain.provider, "deliver", send)
    args = (None, settings(), db.supplier_id, payment.current_revision.beneficiary_version_id)
    initial = await sponsor(db, domain.request_delivery, *args)
    did = UUID(initial["id"])
    await callback(db, did, status="FAILED")
    with pytest.raises(AppError, match="reminder_limited"):
        await sponsor(db, domain.request_delivery, *args)
    assert len(calls) == 1
    async with db.admin() as session, session.begin():
        row = await session.get(Delivery, did)
        row.last_attempt_at = domain.now() - timedelta(seconds=61)
    retried = await sponsor(db, domain.request_delivery, *args)
    assert (
        retried["id"] == initial["id"]
        and retried["attempts"] == 2
        and retried["status"] == "PENDING"
    )
    assert calls == [(did, 1), (did, 2)]
    assert (await sponsor(db, domain.request_delivery, *args))["attempts"] == 2
    assert len(calls) == 2
