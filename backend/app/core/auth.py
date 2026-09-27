from dataclasses import dataclass
from uuid import UUID

import httpx
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_session, lookup_membership
from app.core.errors import AppError
from app.core.providers import get_provider_client
from app.core.schemas import Principal, Role, TenantView


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class VerifiedIdentity:
    user_id: UUID
    email: str | None


async def get_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
    client: httpx.AsyncClient = Depends(get_provider_client),
) -> VerifiedIdentity:
    if not settings.auth_configured:
        raise AppError(503, "auth_not_configured", "Authentication is not configured.")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "authentication_required", "A valid signed-in session is required.")
    token = credentials.credentials
    if len(token) > 16384 or any(c.isspace() for c in token):
        raise AppError(401, "invalid_session", "The signed-in session is invalid or expired.")
    try:
        response = await client.get(
            f"{settings.provider_url}/auth/v1/user",
            headers={
                "apikey": settings.supabase_publishable_key.get_secret_value(),
                "Authorization": f"Bearer {token}",
            },
        )
    except httpx.HTTPError:
        raise AppError(
            503, "auth_unavailable", "Session verification is temporarily unavailable."
        ) from None
    if response.status_code in {400, 401, 403}:
        raise AppError(401, "invalid_session", "The signed-in session is invalid or expired.")
    if response.status_code != 200:
        raise AppError(503, "auth_unavailable", "Session verification is temporarily unavailable.")
    try:
        body = response.json()
        identity = VerifiedIdentity(
            user_id=UUID(body["id"]),
            email=body.get("email") if isinstance(body.get("email"), str) else None,
        )
        if body.get("is_anonymous") is True:
            raise ValueError("anonymous identity")
    except (ValueError, TypeError, KeyError, AttributeError):
        raise AppError(
            401, "invalid_session", "The signed-in session could not be verified."
        ) from None
    # Never decode JWT locally or trust user_metadata/app_metadata for app roles.
    return identity


async def get_principal(
    identity: VerifiedIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    membership = await lookup_membership(session, identity.user_id)
    if membership is None:
        raise AppError(403, "membership_required", "An active workspace membership is required.")
    member, tenant = membership
    try:
        role = Role(member.role)
    except ValueError:
        raise AppError(
            403, "membership_invalid", "The workspace membership cannot authorize access."
        ) from None
    return Principal(
        user_id=identity.user_id,
        email=identity.email,
        tenant=TenantView(id=tenant.id, name=tenant.name),
        role=role,
    )


async def require_finance(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role not in {Role.FINANCE_ADMIN, Role.FINANCE_REVIEWER}:
        raise AppError(403, "finance_access_required", "This action requires a finance role.")
    return principal


async def require_supplier(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != Role.SUPPLIER:
        raise AppError(403, "supplier_access_required", "This portal requires a supplier role.")
    return principal
