"""Payment authority records; every destination is explicitly synthetic."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import APP_SCHEMA, Base


class DomainRecord:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Supplier(DomainRecord, Base):
    __tablename__ = "suppliers"
    __table_args__ = {"schema": APP_SCHEMA}
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    current_beneficiary_version_id: Mapped[UUID | None] = mapped_column(Uuid)


class SupplierIdentity(DomainRecord, Base):
    __tablename__ = "supplier_identities"
    __table_args__ = {"schema": APP_SCHEMA}
    supplier_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class BeneficiaryVersion(DomainRecord, Base):
    __tablename__ = "beneficiary_versions"
    __table_args__ = {"schema": APP_SCHEMA}
    supplier_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    beneficiary_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sandbox_account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class SupplierConfirmation(DomainRecord, Base):
    __tablename__ = "supplier_confirmations"
    __table_args__ = {"schema": APP_SCHEMA}
    supplier_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    beneficiary_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    confirmed_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class BeneficiaryAcceptance(DomainRecord, Base):
    __tablename__ = "beneficiary_acceptances"
    __table_args__ = {"schema": APP_SCHEMA}
    supplier_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    beneficiary_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    accepted_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class Payment(DomainRecord, Base):
    __tablename__ = "payments"
    __table_args__ = {"schema": APP_SCHEMA}
    supplier_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    invoice_reference: Mapped[str] = mapped_column(String(80), nullable=False)
    current_revision_id: Mapped[UUID | None] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PaymentRevision(DomainRecord, Base):
    __tablename__ = "payment_revisions"
    __table_args__ = {"schema": APP_SCHEMA}
    payment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    beneficiary_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    simulation: Mapped[str] = mapped_column(String(20), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class PaymentApproval(DomainRecord, Base):
    __tablename__ = "payment_approvals"
    __table_args__ = {"schema": APP_SCHEMA}
    payment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    )


class Execution(DomainRecord, Base):
    """Transactional outbox; ID is the stable sandbox idempotency key."""

    __tablename__ = "executions"
    __table_args__ = {"schema": APP_SCHEMA}
    payment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    approval_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    request_key: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED")
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    transfer_id: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditEvent(DomainRecord, Base):
    __tablename__ = "audit_events"
    __table_args__ = {"schema": APP_SCHEMA}
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
