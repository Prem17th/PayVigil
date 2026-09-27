"""Real PostgreSQL authority/concurrency tests, confined to guarded local DBs.

History is intentionally append-only. Synthetic rows remain in the disposable
*_test database; remove the whole isolated database after the test run.
"""

import asyncio
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.payments import domain
from app.core.auth import get_identity, VerifiedIdentity
from app.core.config import Settings
from app.core.database import database_url, get_session
from app.core.errors import AppError
from app.core.models import Membership, Tenant
from app.payments.models import (
    AuditEvent,
    Execution,
    Payment,
    Supplier,
    SupplierIdentity,
)
from app.payments.schemas import BeneficiaryCreate, PaymentCreate, PaymentDecision, PaymentRevise
from app.core.schemas import Principal, Role, TenantView
from test_postgres import isolated_test_urls


@pytest_asyncio.fixture
async def payment_db():
    values = [
        os.getenv(name)
        for name in ("TEST_DATABASE_URL", "TEST_ADMIN_DATABASE_URL", "TEST_WORKER_DATABASE_URL")
    ]
    if not all(values):
        pytest.skip("Explicit isolated API, admin, and worker PostgreSQL URLs required")
    api_url, admin_url, worker_url = values
    isolated_test_urls(api_url, admin_url)
    isolated_test_urls(worker_url, admin_url)
    engines = [
        create_async_engine(
            database_url(
                Settings(_env_file=None, app_env="test", database_url=value, pgsslmode="disable")
            )
        )
        for value in values
    ]
    api, admin, worker = [async_sessionmaker(engine, expire_on_commit=False) for engine in engines]
    tenant_id, other_tenant, finance_id, supplier_user, other_finance = [uuid4() for _ in range(5)]
    supplier_id, unassigned_supplier = uuid4(), uuid4()
    async with admin() as session, session.begin():
        session.add_all(
            [
                Tenant(id=tenant_id, name="Synthetic payment test"),
                Tenant(id=other_tenant, name="Other isolated tenant"),
            ]
        )
        await session.flush()
        session.add_all(
            [
                Membership(
                    id=uuid4(), user_id=finance_id, tenant_id=tenant_id, role="finance_admin"
                ),
                Membership(id=uuid4(), user_id=supplier_user, tenant_id=tenant_id, role="supplier"),
                Membership(
                    id=uuid4(), user_id=other_finance, tenant_id=other_tenant, role="finance_admin"
                ),
                Supplier(id=supplier_id, tenant_id=tenant_id, name="Synthetic assigned supplier"),
                Supplier(
                    id=unassigned_supplier,
                    tenant_id=tenant_id,
                    name="Synthetic unassigned supplier",
                ),
            ]
        )
        await session.flush()
        session.add(
            SupplierIdentity(
                id=uuid4(), tenant_id=tenant_id, supplier_id=supplier_id, user_id=supplier_user
            )
        )

    def principal(user, tenant, role):
        return Principal(
            user_id=user, email=None, tenant=TenantView(id=tenant, name="Test"), role=role
        )

    db = SimpleNamespace(
        api=api,
        admin=admin,
        worker=worker,
        tenant_id=tenant_id,
        finance=principal(finance_id, tenant_id, Role.FINANCE_ADMIN),
        supplier=principal(supplier_user, tenant_id, Role.SUPPLIER),
        outsider=principal(other_finance, other_tenant, Role.FINANCE_ADMIN),
        supplier_id=supplier_id,
        unassigned_supplier=unassigned_supplier,
    )
    # The production worker intentionally claims globally. End each test's
    # queued fixtures through its real claim/finish transactions so a later
    # test cannot accidentally consume a previous test's outbox item.
    try:
        yield db
    finally:
        for _ in range(100):
            claimed = await claim(db)
            if claimed is None:
                break
            await finish(db, claimed, readback(claimed, status="FAILED"), uncertain=False)
        for engine in engines:
            await engine.dispose()


async def call(db, function, *args, actor=None):
    async with db.api() as session:
        return await function(session, actor or db.finance, *args)


async def prepare_payment(db, *, accepted=True, approved=False, invoice="INV-001"):
    supplier = await call(
        db,
        domain.add_beneficiary,
        db.supplier_id,
        BeneficiaryCreate(
            beneficiary_name="Synthetic supplier",
            sandbox_account_id="SIM-SUPPLIER-001",
            expected_version_id=None,
        ),
    )
    version = supplier.current_beneficiary.id
    if accepted:
        await call(db, domain.confirm_beneficiary, db.supplier_id, version, actor=db.supplier)
        await call(db, domain.accept_beneficiary, db.supplier_id, version)
    payment = await call(
        db,
        domain.create_payment,
        PaymentCreate(
            supplier_id=db.supplier_id,
            invoice_reference=invoice,
            amount_minor=10001,
            currency="INR",
            simulation="success",
        ),
    )
    if approved:
        payment = await call(db, domain.approve_payment, payment.id, decision(payment))
    return payment


def decision(payment):
    return PaymentDecision(
        revision_id=payment.current_revision.id, digest=payment.current_revision.digest
    )


async def queue(db, payment):
    return await call(db, domain.queue_payment, payment.id, decision(payment), str(uuid4()))


async def claim(db):
    async with db.worker() as session:
        return await domain.claim_execution(session, "test-worker")


async def finish(db, claimed, result=None, uncertain=True):
    async with db.worker() as session:
        await domain.finish_execution(
            session,
            UUID(claimed["execution_id"]),
            UUID(claimed["lease_token"]),
            result,
            uncertain=uncertain,
        )


def readback(claimed, **changes):
    return {
        **claimed["body"],
        "idempotency_key": claimed["execution_id"],
        "transfer_id": str(uuid4()),
        "status": "SUCCEEDED",
        **changes,
    }


async def test_supplier_mapping_confirmation_and_acceptance_are_separate(payment_db):
    db = payment_db
    payment = await prepare_payment(db, accepted=False)
    with pytest.raises(AppError, match="beneficiary_not_accepted"):
        await call(db, domain.approve_payment, payment.id, decision(payment))
    with pytest.raises(AppError, match="confirmation_required"):
        await call(
            db,
            domain.accept_beneficiary,
            db.supplier_id,
            payment.current_revision.beneficiary_version_id,
        )
    with pytest.raises(AppError) as denied:
        await call(
            db,
            domain.confirm_beneficiary,
            db.unassigned_supplier,
            payment.current_revision.beneficiary_version_id,
            actor=db.supplier,
        )
    assert denied.value.status in {403, 404}
    await call(
        db,
        domain.confirm_beneficiary,
        db.supplier_id,
        payment.current_revision.beneficiary_version_id,
        actor=db.supplier,
    )
    with pytest.raises(AppError, match="beneficiary_not_accepted"):
        await call(db, domain.approve_payment, payment.id, decision(payment))
    await call(
        db,
        domain.accept_beneficiary,
        db.supplier_id,
        payment.current_revision.beneficiary_version_id,
    )
    approved = await call(db, domain.approve_payment, payment.id, decision(payment))
    assert approved.approval and approved.state == "APPROVED"
    assert approved.approval.digest == payment.current_revision.digest


async def test_stale_revision_and_destination_invalidate_approval(payment_db):
    db = payment_db
    payment = await prepare_payment(db, approved=True)
    revised = await call(
        db,
        domain.revise_payment,
        payment.id,
        PaymentRevise(
            expected_revision_id=payment.current_revision.id,
            amount_minor=20000,
            simulation="decline",
        ),
    )
    assert (
        revised.approval is None
        and revised.current_revision.digest != payment.current_revision.digest
    )
    with pytest.raises(AppError, match="stale_revision"):
        await call(db, domain.queue_payment, payment.id, decision(payment), str(uuid4()))
    revised = await call(db, domain.approve_payment, payment.id, decision(revised))
    await call(
        db,
        domain.add_beneficiary,
        db.supplier_id,
        BeneficiaryCreate(
            expected_version_id=revised.current_revision.beneficiary_version_id,
            beneficiary_name="New synthetic version",
            sandbox_account_id="SIM-SUPPLIER-002",
        ),
    )
    with pytest.raises(AppError, match="beneficiary_not_accepted"):
        await call(db, domain.queue_payment, payment.id, decision(revised), str(uuid4()))
    displayed = await call(db, domain.get_payment, payment.id)
    assert displayed.approval is None and "queue" not in displayed.allowed_actions


async def test_concurrent_queue_is_one_atomic_execution_and_invoice_is_unique(payment_db):
    db = payment_db
    payment = await prepare_payment(db, approved=True, invoice="  inv-001  ")
    results = await asyncio.gather(*(queue(db, payment) for _ in range(8)))
    assert len({row.execution.id for row in results}) == 1
    async with db.admin() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Execution)
                .where(Execution.payment_id == payment.id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.subject_id == payment.id, AuditEvent.action == "execution_queued")
            )
            == 1
        )
    with pytest.raises(AppError, match="invoice_exists"):
        await call(
            db,
            domain.create_payment,
            PaymentCreate(
                supplier_id=db.supplier_id,
                invoice_reference="INV-001",
                amount_minor=999,
                simulation="success",
            ),
        )


async def test_queue_and_revision_race_never_dispatches_unapproved_revision(payment_db):
    db = payment_db
    payment = await prepare_payment(db, approved=True)
    results = await asyncio.gather(
        queue(db, payment),
        call(
            db,
            domain.revise_payment,
            payment.id,
            PaymentRevise(
                expected_revision_id=payment.current_revision.id,
                amount_minor=50000,
                simulation="success",
            ),
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, AppError) for result in results) == 1
    displayed = await call(db, domain.get_payment, payment.id)
    if displayed.execution:
        assert displayed.current_revision.id == payment.current_revision.id
        assert displayed.current_revision.amount_minor == 10001
    else:
        assert displayed.approval is None and displayed.state == "DRAFT"


async def test_unknown_blocks_replacement_and_conflicting_readback_cannot_succeed(
    payment_db, monkeypatch
):
    db = payment_db
    monkeypatch.setattr(
        domain,
        "get_settings",
        lambda: SimpleNamespace(
            payment_approval_ttl_seconds=600,
            payment_worker_lease_seconds=60,
            payment_reconcile_interval_seconds=0,
        ),
    )
    payment = await prepare_payment(db, approved=True)
    queued = await queue(db, payment)
    claimed = await claim(db)
    assert claimed["execution_id"] == str(queued.execution.id)
    await finish(db, claimed)  # Lost response / no independent readback.
    unknown = await call(db, domain.get_payment, payment.id)
    assert unknown.state == "UNKNOWN" and not unknown.allowed_actions
    with pytest.raises(AppError, match="payment_locked"):
        await call(
            db,
            domain.revise_payment,
            payment.id,
            PaymentRevise(
                expected_revision_id=payment.current_revision.id,
                amount_minor=5,
                simulation="success",
            ),
        )
    with pytest.raises(AppError, match="execution_in_progress"):
        await call(
            db,
            domain.add_beneficiary,
            db.supplier_id,
            BeneficiaryCreate(
                expected_version_id=payment.current_revision.beneficiary_version_id,
                beneficiary_name="Replacement",
                sandbox_account_id="SIM-REPLACEMENT",
            ),
        )
    assert (await queue(db, payment)).execution.id == queued.execution.id
    assert await claim(db) is None  # No POST retry for UNKNOWN.
    async with db.worker() as session:
        reconciliation = await domain.claim_reconciliation(session, "second-worker")
    await finish(db, reconciliation, readback(reconciliation, amount_minor=1), uncertain=False)
    assert (await call(db, domain.get_payment, payment.id)).state == "UNKNOWN"
    async with db.worker() as session:
        reconciliation = await domain.claim_reconciliation(session, "third-worker")
    # A stale worker lease cannot overwrite the current claim.
    await finish(db, claimed, readback(claimed), uncertain=False)
    assert (await call(db, domain.get_payment, payment.id)).state == "UNKNOWN"
    await finish(db, reconciliation, readback(reconciliation), uncertain=False)
    assert (await call(db, domain.get_payment, payment.id)).state == "SUCCEEDED"


async def test_expiry_rechecked_before_queue_and_before_dispatch(payment_db, monkeypatch):
    db = payment_db
    monkeypatch.setattr(
        domain,
        "get_settings",
        lambda: SimpleNamespace(
            payment_approval_ttl_seconds=0.15,
            payment_worker_lease_seconds=60,
            payment_reconcile_interval_seconds=3,
        ),
    )
    payment = await prepare_payment(db, approved=True)
    await asyncio.sleep(0.17)
    with pytest.raises(AppError, match="approval_required"):
        await queue(db, payment)
    payment = await call(db, domain.approve_payment, payment.id, decision(payment))
    await queue(db, payment)
    await asyncio.sleep(0.17)
    assert await claim(db) is None
    displayed = await call(db, domain.get_payment, payment.id)
    assert displayed.state == "FAILED" and displayed.execution.transfer_id is None
    assert any(event.action == "dispatch_blocked" for event in displayed.audit_events)


async def test_history_rls_and_worker_authority_are_enforced_by_database(payment_db):
    db = payment_db
    payment = await prepare_payment(db, approved=True)
    for query in (
        "UPDATE beforetransfer.payment_revisions SET amount_minor=1 WHERE id=:id",
        "DELETE FROM beforetransfer.payment_revisions WHERE id=:id",
    ):
        with pytest.raises(DBAPIError):
            async with db.admin() as session, session.begin():
                await session.execute(text(query), {"id": payment.current_revision.id})
    with pytest.raises(DBAPIError):
        async with db.worker() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE beforetransfer.payment_approvals SET expires_at=clock_timestamp()+interval '1 day' WHERE payment_id=:id"
                ),
                {"id": payment.id},
            )
    with pytest.raises(AppError) as denied:
        await call(db, domain.get_payment, payment.id, actor=db.outsider)
    assert denied.value.status == 404
    async with db.api() as session, domain.transaction(session, db.supplier):
        assert (await session.scalars(select(Payment))).all() == []
        assert (await session.scalars(select(SupplierIdentity.supplier_id))).all() == [
            db.supplier_id
        ]


async def test_http_supplier_cannot_approve_or_cross_assignment(payment_db, app):
    db = payment_db
    payment = await prepare_payment(db, approved=True)

    async def session_dependency():
        async with db.api() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_identity] = lambda: VerifiedIdentity(db.supplier.user_id, None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/payments/{payment.id}/approvals", json=decision(payment).model_dump(mode="json")
        )
        assert response.status_code == 403
        requests = await client.get("/api/supplier/requests")
        assert requests.status_code == 200
        assert [row["id"] for row in requests.json()["suppliers"]] == [str(db.supplier_id)]
        app.dependency_overrides[get_identity] = lambda: VerifiedIdentity(db.finance.user_id, None)
        response = await client.post(
            f"/api/payments/{payment.id}/queue",
            json={"revision_id": str(uuid4()), "digest": "0" * 64},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 409 and response.json()["error"]["code"] == "stale_revision"


@pytest.mark.parametrize("amount", [True, 1.2, "100", 0, -1, 1_000_000_000_001])
def test_payment_amount_is_positive_integer_paise(amount):
    with pytest.raises(ValidationError):
        PaymentCreate(supplier_id=uuid4(), invoice_reference="INV-1", amount_minor=amount)


def test_real_account_and_ambiguous_invoice_are_rejected():
    with pytest.raises(ValidationError):
        BeneficiaryCreate(
            beneficiary_name="Supplier", sandbox_account_id="123456789012", expected_version_id=None
        )
    with pytest.raises(ValidationError):
        PaymentCreate(supplier_id=uuid4(), invoice_reference="../💸", amount_minor=1)
