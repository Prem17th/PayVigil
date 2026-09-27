"""Opt-in real PostgreSQL verification; provider mocks are not used here.

Run against a migrated isolated loopback database ending in _test, never a
production project. The owner-role test briefly grants and revokes that role.
TEST_DATABASE_URL: restricted API role. TEST_ADMIN_DATABASE_URL: fixture owner.
"""

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.database import assert_restricted_role, database_url, lookup_membership
from app.core.errors import AppError


pytestmark = pytest.mark.postgres


def isolated_test_urls(runtime_url: str, admin_url: str) -> None:
    """Reject remote destinations and libpq query overrides before any writes."""
    try:
        urls = [make_url(value) for value in (runtime_url, admin_url)]
        for url in urls:
            if (
                url.drivername not in {"postgresql", "postgresql+psycopg", "postgres"}
                or url.host not in {"localhost", "127.0.0.1", "::1"}
                or not url.database
                or not url.database.endswith("_test")
                or set(url.query) - {"sslmode"}
                or url.query.get("sslmode", "disable") != "disable"
            ):
                raise ValueError
        if (
            (urls[0].host, urls[0].port, urls[0].database)
            != (urls[1].host, urls[1].port, urls[1].database)
            or not urls[0].username
            or not urls[1].username
            or urls[0].username == urls[1].username
        ):
            raise ValueError
    except Exception:
        raise ValueError(
            "PostgreSQL tests require distinct roles on the same explicit loopback *_test database, without connection overrides."
        ) from None


@pytest_asyncio.fixture
async def database_fixture():
    runtime_url = os.getenv("TEST_DATABASE_URL")
    admin_url = os.getenv("TEST_ADMIN_DATABASE_URL")
    if not runtime_url or not admin_url:
        pytest.skip("Explicit isolated PostgreSQL test URLs are required")
    isolated_test_urls(runtime_url, admin_url)
    runtime = create_async_engine(
        database_url(
            Settings(_env_file=None, app_env="test", database_url=runtime_url, pgsslmode="disable")
        )
    )
    admin = create_async_engine(
        database_url(
            Settings(_env_file=None, app_env="test", database_url=admin_url, pgsslmode="disable")
        )
    )
    tenant_a, tenant_b, user_a, user_b = (uuid4() for _ in range(4))
    async with admin.begin() as connection:
        for tenant, user in ((tenant_a, user_a), (tenant_b, user_b)):
            await connection.execute(
                text(
                    "INSERT INTO beforetransfer.tenants(id,name) VALUES (:id,'Isolated test tenant')"
                ),
                {"id": tenant},
            )
            await connection.execute(
                text(
                    "INSERT INTO beforetransfer.memberships(id,user_id,tenant_id,role) VALUES (:id,:user,:tenant,'finance_reviewer')"
                ),
                {"id": uuid4(), "user": user, "tenant": tenant},
            )
    try:
        yield runtime, admin, tenant_a, tenant_b, user_a, user_b
    finally:
        async with admin.begin() as connection:
            await connection.execute(
                text("DELETE FROM beforetransfer.memberships WHERE tenant_id IN (:a,:b)"),
                {"a": tenant_a, "b": tenant_b},
            )
            await connection.execute(
                text("DELETE FROM beforetransfer.tenants WHERE id IN (:a,:b)"),
                {"a": tenant_a, "b": tenant_b},
            )
        await runtime.dispose()
        await admin.dispose()


async def test_real_membership_lookup_and_context_reset(database_fixture):
    runtime, _, tenant_a, _, user_a, _ = database_fixture
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    async with sessions() as session:
        membership = await lookup_membership(session, user_a)
        assert membership is not None and membership[1].id == tenant_a
        assert (
            await session.execute(text("SELECT count(*) FROM beforetransfer.memberships"))
        ).scalar_one() == 0


async def test_real_rls_prevents_cross_tenant_reads(database_fixture):
    runtime, _, tenant_a, tenant_b, user_a, _ = database_fixture
    async with runtime.begin() as connection:
        await connection.execute(
            text("SELECT set_config('app.user_id', :user, true)"), {"user": str(user_a)}
        )
        tenants = (
            (await connection.execute(text("SELECT id FROM beforetransfer.tenants")))
            .scalars()
            .all()
        )
        assert tenants == [tenant_a]
        assert tenant_b not in tenants


async def test_real_api_role_cannot_change_memberships(database_fixture):
    runtime, _, _, _, user_a, _ = database_fixture
    with pytest.raises(DBAPIError):
        async with runtime.begin() as connection:
            await connection.execute(
                text("SELECT set_config('app.user_id', :user, true)"), {"user": str(user_a)}
            )
            await connection.execute(
                text(
                    "UPDATE beforetransfer.memberships SET role='finance_admin' WHERE user_id=:user"
                ),
                {"user": user_a},
            )


async def test_privileged_database_connection_is_rejected(database_fixture):
    _, admin, *_ = database_fixture
    async with async_sessionmaker(admin)() as session:
        with pytest.raises(AppError, match="database_role_unsafe"):
            await assert_restricted_role(session)


async def test_blocked_database_query_times_out_and_rolls_back(database_fixture, monkeypatch):
    runtime, admin, _, _, user_a, _ = database_fixture
    monkeypatch.setattr("app.core.database.DATABASE_OPERATION_TIMEOUT_SECONDS", 0.05)
    async with async_sessionmaker(runtime)() as session:
        async with admin.begin() as connection:
            await connection.execute(
                text("LOCK TABLE beforetransfer.memberships IN ACCESS EXCLUSIVE MODE")
            )
            with pytest.raises(AppError, match="database_unavailable"):
                await lookup_membership(session, user_a)
        assert not session.in_transaction()
        # The cancelled transaction must not leave an authenticated context.
        assert (
            await session.execute(text("SELECT count(*) FROM beforetransfer.memberships"))
        ).scalar_one() == 0


async def test_inherited_owner_membership_is_rejected(database_fixture):
    runtime, admin, *_ = database_fixture
    async with runtime.connect() as connection:
        runtime_role = (await connection.execute(text("SELECT current_user"))).scalar_one()
    async with admin.connect() as connection:
        owner_role = (await connection.execute(text("SELECT current_user"))).scalar_one()
    quote = admin.dialect.identifier_preparer.quote
    async with admin.begin() as connection:
        await connection.execute(text(f"GRANT {quote(owner_role)} TO {quote(runtime_role)}"))
    try:
        async with async_sessionmaker(runtime)() as session:
            with pytest.raises(AppError, match="database_role_unsafe"):
                await assert_restricted_role(session)
    finally:
        async with admin.begin() as connection:
            await connection.execute(text(f"REVOKE {quote(owner_role)} FROM {quote(runtime_role)}"))


@pytest.mark.parametrize(
    "runtime_url",
    [
        "postgresql://api@db.example.com/app_test",
        "postgresql://api@127.0.0.1/app",
        "postgresql://api@127.0.0.1/app_test?host=db.example.com",
        "postgresql://api@127.0.0.1/app_test?service=production",
        "postgresql://api@127.0.0.1/app_test?sslmode=require",
        "postgresql://api@127.0.0.1/other_test",
        "postgresql://admin@127.0.0.1/app_test",
    ],
)
def test_database_fixture_refuses_unsafe_targets(runtime_url):
    with pytest.raises(ValueError, match="loopback"):
        isolated_test_urls(runtime_url, "postgresql://admin@127.0.0.1/app_test")


async def test_migration_metadata_is_private_despite_browser_default_grants(database_fixture):
    _, admin, *_ = database_fixture
    async with admin.connect() as connection:
        assert (
            await connection.execute(text("SELECT to_regclass('public.alembic_version')"))
        ).scalar_one() is None
        assert (
            await connection.execute(
                text(
                    "SELECT relrowsecurity FROM pg_class WHERE oid='beforetransfer_migrations.alembic_version'::regclass"
                )
            )
        ).scalar_one() is True
        for role in ("anon", "authenticated"):
            exists = (
                await connection.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:role)"),
                    {"role": role},
                )
            ).scalar_one()
            if not exists:
                pytest.fail(
                    "Create isolated browser roles and global default grants before migration to exercise this test"
                )
            defaults = (
                (
                    await connection.execute(
                        text("""
                SELECT e.privilege_type FROM pg_default_acl d
                CROSS JOIN LATERAL aclexplode(d.defaclacl) e
                WHERE d.defaclrole=(SELECT oid FROM pg_roles WHERE rolname=current_user)
                  AND d.defaclnamespace=0 AND d.defaclobjtype='r'
                  AND e.grantee=(SELECT oid FROM pg_roles WHERE rolname=:role)
            """),
                        {"role": role},
                    )
                )
                .scalars()
                .all()
            )
            assert set(defaults) >= {"SELECT", "INSERT", "UPDATE", "DELETE"}
            # Test preparation must grant these globally before migration, like
            # existing Supabase projects. The migration revokes table access.
            for schema in ("beforetransfer", "beforetransfer_migrations"):
                assert (
                    await connection.execute(
                        text("SELECT has_schema_privilege(:role,:schema,'USAGE')"),
                        {"role": role, "schema": schema},
                    )
                ).scalar_one() is False
            for table in (
                "beforetransfer.tenants",
                "beforetransfer.memberships",
                "beforetransfer_migrations.alembic_version",
            ):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert (
                        await connection.execute(
                            text("SELECT has_table_privilege(:role,:table,:privilege)"),
                            {"role": role, "table": table, "privilege": privilege},
                        )
                    ).scalar_one() is False
