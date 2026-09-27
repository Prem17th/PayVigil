from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class Delivery(Base):
    __tablename__ = "sponsor_deliveries"
    __table_args__ = (
        UniqueConstraint("supplier_id", "beneficiary_version_id"),
        {"schema": "beforetransfer"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("beforetransfer.tenants.id"))
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("beforetransfer.suppliers.id"))
    beneficiary_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("beforetransfer.beneficiary_versions.id")
    )
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VoiceOperation(Base):
    __tablename__ = "sponsor_voice_operations"
    __table_args__ = (
        UniqueConstraint("investigation_id", "text_digest", "voice_id"),
        {"schema": "beforetransfer"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("beforetransfer.tenants.id"))
    investigation_id: Mapped[UUID] = mapped_column(ForeignKey("beforetransfer.investigations.id"))
    text_digest: Mapped[str] = mapped_column(String(64))
    voice_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    audio: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillingAccount(Base):
    __tablename__ = "sponsor_billing"
    __table_args__ = {"schema": "beforetransfer"}
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("beforetransfer.tenants.id"), primary_key=True
    )
    operation_id: Mapped[UUID] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(String(30))
    checkout_id: Mapped[str | None] = mapped_column(String(160), unique=True)
    checkout_url: Mapped[str | None] = mapped_column(String(2048))
    customer_id: Mapped[str | None] = mapped_column(String(160), unique=True)
    subscription_id: Mapped[str | None] = mapped_column(String(160), unique=True)
    product_id: Mapped[str] = mapped_column(String(100))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconcile_token: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SponsorEvent(Base):
    __tablename__ = "sponsor_events"
    __table_args__ = {"schema": "beforetransfer"}
    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[UUID | None] = mapped_column()
    entity_id: Mapped[UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
