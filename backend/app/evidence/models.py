from uuid import UUID

from sqlalchemy import String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import APP_SCHEMA, Base
from app.payments.models import DomainRecord


class EvidenceDocument(DomainRecord, Base):
    __tablename__ = "evidence_documents"
    __table_args__ = {"schema": APP_SCHEMA}
    payment_id: Mapped[UUID] = mapped_column(Uuid)
    revision_id: Mapped[UUID] = mapped_column(Uuid)
    filename: Mapped[str] = mapped_column(String(160))
    media_type: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64))
    object_path: Mapped[str] = mapped_column(String(300))
    extracted_text: Mapped[str] = mapped_column(Text)
    pages: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20))
    uploaded_by: Mapped[UUID] = mapped_column(Uuid)


class Investigation(DomainRecord, Base):
    __tablename__ = "investigations"
    __table_args__ = {"schema": APP_SCHEMA}
    payment_id: Mapped[UUID] = mapped_column(Uuid)
    revision_id: Mapped[UUID] = mapped_column(Uuid)
    evidence_digest: Mapped[str] = mapped_column(String(64))
    document_ids: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text, default="")
    findings: Mapped[list] = mapped_column(JSONB, default=list)
    tool_trace: Mapped[list] = mapped_column(JSONB, default=list)
    provider: Mapped[str] = mapped_column(String(30), default="openai")
    created_by: Mapped[UUID] = mapped_column(Uuid)


class InvestigationReview(DomainRecord, Base):
    __tablename__ = "investigation_reviews"
    __table_args__ = {"schema": APP_SCHEMA}
    investigation_id: Mapped[UUID] = mapped_column(Uuid)
    reviewed_by: Mapped[UUID] = mapped_column(Uuid)
    note: Mapped[str] = mapped_column(Text)


class MemoryOperation(DomainRecord, Base):
    __tablename__ = "memory_operations"
    __table_args__ = {"schema": APP_SCHEMA}
    investigation_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20))
    redacted_content: Mapped[str] = mapped_column(Text)
    provenance: Mapped[dict] = mapped_column(JSONB)
    provider_receipt: Mapped[str | None] = mapped_column(String(200))
