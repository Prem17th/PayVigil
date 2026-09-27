from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.payments.schemas import StrictBody


class EvidenceUpload(StrictBody):
    revision_id: UUID
    filename: str = Field(min_length=1, max_length=160)
    media_type: Literal["text/plain", "application/pdf"]
    content_base64: str = Field(min_length=1, max_length=2_800_000)

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value) or "/" in value or "\\" in value:
            raise ValueError("A display filename without path or control characters is required")
        return value


class InvestigationCreate(StrictBody):
    revision_id: UUID


class InvestigationReviewBody(StrictBody):
    acknowledged: Literal[True]
    note: str = Field(min_length=1, max_length=2000)


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=36, max_length=36)
    quote: str = Field(min_length=1, max_length=500)
    page: int = Field(strict=True, ge=1, le=20)


FindingCode = Literal[
    "beneficiary_mismatch",
    "amount_mismatch",
    "invoice_mismatch",
    "currency_mismatch",
    "prompt_injection",
    "missing_fields",
    "conflicting_evidence",
    "no_discrepancy",
    "manual_verification_required",
]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["info", "warning", "critical"]
    code: FindingCode
    explanation: str = Field(min_length=1, max_length=1500)
    citations: list[Citation] = Field(min_length=1, max_length=6)


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=3000)
    findings: list[Finding] = Field(min_length=1, max_length=20)
