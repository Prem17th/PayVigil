import re
import unicodedata
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


Simulation = Literal["success", "decline", "lost_response"]
PaymentState = Literal[
    "DRAFT", "APPROVED", "QUEUED", "SUBMITTING", "UNKNOWN", "SUCCEEDED", "FAILED"
]


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SupplierCreate(StrictBody):
    name: str = Field(min_length=1, max_length=160)


class BeneficiaryCreate(StrictBody):
    beneficiary_name: str = Field(min_length=1, max_length=160)
    sandbox_account_id: str = Field(pattern=r"^SIM-[A-Z0-9-]{3,64}$")
    expected_version_id: UUID | None

    @field_validator("beneficiary_name")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Beneficiary names cannot contain control characters.")
        return value


class BeneficiaryDecision(StrictBody):
    beneficiary_version_id: UUID


class PaymentCreate(StrictBody):
    supplier_id: UUID
    invoice_reference: str = Field(min_length=1, max_length=80)
    amount_minor: int = Field(strict=True, gt=0, le=1_000_000_000_000)
    currency: Literal["INR"] = "INR"
    simulation: Simulation = "success"

    @field_validator("invoice_reference")
    @classmethod
    def canonical_invoice(cls, value: str) -> str:
        value = " ".join(unicodedata.normalize("NFKC", value).upper().split())
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9 /_.-]{0,79}", value):
            raise ValueError(
                "Use a letter or number followed by letters, numbers, spaces, /, _, ., or -."
            )
        return value


class PaymentRevise(StrictBody):
    expected_revision_id: UUID
    amount_minor: int = Field(strict=True, gt=0, le=1_000_000_000_000)
    simulation: Simulation


class PaymentDecision(StrictBody):
    revision_id: UUID
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class AuditView(BaseModel):
    id: UUID
    action: str
    actor_user_id: UUID | None
    created_at: datetime
    details: dict


class ConfirmationView(BaseModel):
    id: UUID
    confirmed_at: datetime


class AcceptanceView(BaseModel):
    id: UUID
    accepted_at: datetime


class BeneficiaryView(BaseModel):
    id: UUID
    version: int
    beneficiary_name: str
    sandbox_account_id: str
    created_at: datetime
    confirmation: ConfirmationView | None
    acceptance: AcceptanceView | None


class SupplierView(BaseModel):
    id: UUID
    name: str
    current_beneficiary: BeneficiaryView | None
    allowed_actions: list[Literal["add_beneficiary", "confirm", "accept"]]
    hold_reasons: list[str]
    audit_events: list[AuditView]


class RevisionView(BaseModel):
    id: UUID
    version: int
    amount_minor: int
    currency: Literal["INR"]
    beneficiary_version_id: UUID
    beneficiary_name: str
    sandbox_account_id: str
    simulation: Simulation
    digest: str
    created_at: datetime


class ApprovalView(BaseModel):
    id: UUID
    revision_id: UUID
    digest: str
    approved_at: datetime
    expires_at: datetime


class ExecutionView(BaseModel):
    id: UUID
    state: PaymentState
    transfer_id: str | None
    queued_at: datetime
    updated_at: datetime


class PaymentView(BaseModel):
    id: UUID
    supplier_id: UUID
    supplier_name: str
    invoice_reference: str
    state: PaymentState
    current_revision: RevisionView
    approval: ApprovalView | None
    execution: ExecutionView | None
    allowed_actions: list[Literal["revise", "approve", "queue"]]
    hold_reasons: list[str]
    audit_events: list[AuditView]
