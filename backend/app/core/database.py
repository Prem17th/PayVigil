import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import URL, make_url, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.models import Membership, Tenant


DATABASE_OPERATION_TIMEOUT_SECONDS = 8


def database_url(settings: Settings, *, migration: bool = False) -> URL:
    raw = (
        settings.migration_database_url.get_secret_value()
        if migration
        else settings.database_url.get_secret_value()
    ).strip()
    if not raw:
        raise AppError(503, "database_not_configured", "Database configuration is required.")
    try:
        url = make_url(raw)
        if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError("unsupported database")
        url = url.set(drivername="postgresql+psycopg")
        sslmode = str(url.query.get("sslmode", settings.pgsslmode))
        if settings.app_env != "test" and sslmode != "verify-full":
            raise ValueError("Authenticated TLS required")
        query = dict(url.query)
        query["sslmode"] = sslmode
        if sslmode in {"verify-ca", "verify-full"}:
            query.setdefault("sslrootcert", settings.pgsslrootcert)
        query.setdefault("connect_timeout", "5")
        return url.set(query=query)
    except (ValueError, TypeError, SQLAlchemyError):
        raise AppError(
            503, "database_configuration_invalid", "Database configuration is invalid."
        ) from None


def get_engine(request: Request, settings: Settings = Depends(get_settings)) -> AsyncEngine:
    # No engine, connection, or migration is created at import/startup.
    if getattr(request.app.state, "database_engine", None) is None:
        request.app.state.database_engine = create_async_engine(
            database_url(settings),
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=2,
            pool_timeout=5,
            hide_parameters=True,
            echo=False,
            connect_args={"prepare_threshold": None},
        )
    return request.app.state.database_engine


async def get_session(engine: AsyncEngine = Depends(get_engine)) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


_ROLE_CHECK = text("""
SELECT r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb, r.rolreplication,
       EXISTS (SELECT 1 FROM pg_catalog.pg_roles allowed
               WHERE allowed.rolname = :required_role
                 AND pg_has_role(current_user, allowed.oid, 'member')) AS permitted,
       EXISTS (SELECT 1 FROM pg_catalog.pg_class c
               JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'beforetransfer'
                 AND pg_has_role(current_user, c.relowner, 'member')) AS owns_tables,
       EXISTS (SELECT 1 FROM pg_catalog.pg_roles privileged
               WHERE (privileged.rolsuper OR privileged.rolbypassrls
                      OR privileged.rolcreaterole OR privileged.rolcreatedb OR privileged.rolreplication)
                 AND pg_has_role(current_user, privileged.oid, 'member')) AS inherits_privilege
FROM pg_catalog.pg_roles r WHERE r.rolname = current_user
""")


async def assert_restricted_role(
    session: AsyncSession, required_role: str = "beforetransfer_api"
) -> None:
    if required_role not in {"beforetransfer_api", "beforetransfer_worker"}:
        raise AppError(503, "database_role_unsafe", "A restricted database role is required.")
    row = (await session.execute(_ROLE_CHECK, {"required_role": required_role})).mappings().one()
    if (
        any(
            row[name]
            for name in (
                "rolsuper",
                "rolbypassrls",
                "rolcreaterole",
                "rolcreatedb",
                "rolreplication",
                "owns_tables",
                "inherits_privilege",
            )
        )
        or not row["permitted"]
    ):
        raise AppError(
            503, "database_role_unsafe", "The API requires its restricted database role."
        )


async def lookup_membership(
    session: AsyncSession, user_id: UUID
) -> tuple[Membership, Tenant] | None:
    try:
        async with asyncio.timeout(DATABASE_OPERATION_TIMEOUT_SECONDS), session.begin():
            await assert_restricted_role(session)
            # Transaction-local value cannot bleed into a pooled connection.
            await session.execute(
                text("SELECT set_config('app.user_id', :user_id, true)"),
                {"user_id": str(user_id)},
            )
            result = await session.execute(
                select(Membership, Tenant)
                .join(Tenant, Membership.tenant_id == Tenant.id)
                .where(Membership.user_id == user_id, Membership.is_active.is_(True))
            )
            return result.one_or_none()
    except (SQLAlchemyError, TimeoutError):
        raise AppError(
            503, "database_unavailable", "Membership verification is unavailable."
        ) from None


async def verify_database(session: AsyncSession) -> None:
    from app.evidence.models import EvidenceDocument, Investigation, MemoryOperation
    from app.payments.models import PaymentApproval
    from app.integrations.models import BillingAccount, Delivery, VoiceOperation

    try:
        async with asyncio.timeout(DATABASE_OPERATION_TIMEOUT_SECONDS), session.begin():
            await assert_restricted_role(session)
            # Checks table access and migration presence with RLS still applied.
            await session.execute(select(Membership.id).limit(1))
            for column in (
                PaymentApproval.evidence_digest,
                EvidenceDocument.id,
                Investigation.id,
                MemoryOperation.id,
                BillingAccount.tenant_id,
                Delivery.id,
                VoiceOperation.id,
            ):
                await session.execute(select(column).limit(1))
    except (SQLAlchemyError, TimeoutError):
        raise AppError(
            503, "database_unavailable", "Database readiness could not be verified."
        ) from None
