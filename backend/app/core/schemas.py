from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    FINANCE_ADMIN = "finance_admin"
    FINANCE_REVIEWER = "finance_reviewer"
    SUPPLIER = "supplier"


class TenantView(BaseModel):
    id: UUID
    name: str


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: UUID
    email: str | None = None
    tenant: TenantView
    role: Role


class Capabilities(BaseModel):
    payments: Literal[True] = True
    investigations: Literal[True] = True


class SetupView(BaseModel):
    auth_configured: bool
    database_configured: bool
    storage_configured: bool
    phase: Literal[9] = 9
    capabilities: Capabilities = Field(default_factory=Capabilities)


class WorkspaceView(BaseModel):
    phase: Literal[9] = 9
    tenant: TenantView
    role: Literal[Role.FINANCE_ADMIN, Role.FINANCE_REVIEWER]
    status: Literal["empty"] = "empty"
    cases: list[object] = Field(default_factory=list)
    capabilities: Capabilities = Field(default_factory=Capabilities)


class SupplierPortalView(BaseModel):
    phase: Literal[9] = 9
    tenant: TenantView
    role: Literal[Role.SUPPLIER] = Role.SUPPLIER
    status: Literal["empty"] = "empty"
    requests: list[object] = Field(default_factory=list)


class StorageChecks(BaseModel):
    bucket_private: Literal[True] = True
    upload: Literal[True] = True
    authenticated_read: Literal[True] = True
    anonymous_read_denied: Literal[True] = True
    deleted: Literal[True] = True


class StorageCheckView(BaseModel):
    phase: Literal[9] = 9
    status: Literal["verified"] = "verified"
    checked_at: datetime
    checks: StorageChecks = Field(default_factory=StorageChecks)
