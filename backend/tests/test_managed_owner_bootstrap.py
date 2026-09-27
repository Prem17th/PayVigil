"""Managed-owner compatibility using only a new disposable loopback database.

The fixture never reads deployment credentials. It requires the existing
TEST_ADMIN_DATABASE_URL guard and generates all database names and role secrets.
"""

import os
import secrets
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.database import assert_restricted_role, database_url, lookup_membership
from app.core.errors import AppError
from app.core.models import Tenant
from app.payments.domain import create_supplier, list_suppliers, transaction
from app.core.schemas import Principal, Role, TenantView


pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def managed_database():
    raw = os.getenv("TEST_ADMIN_DATABASE_URL")
    if not raw:
        pytest.skip("Explicit isolated PostgreSQL test admin URL is required")
    base = make_url(raw)
    if (
        base.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}
        or base.host not in {"127.0.0.1", "localhost", "::1"}
        or not base.database
        or not base.database.endswith("_test")
        or set(base.query) - {"sslmode"}
        or base.query.get("sslmode", "disable") != "disable"
    ):
        pytest.fail(
            "Managed-owner tests require an explicit loopback *_test admin database without routing overrides"
        )
    suffix = uuid4().hex[:10]
    database = f"bt_owner_{suffix}_test"
    roles = {kind: f"bt_owner_{kind}_{suffix}" for kind in ("migration", "api", "worker")}
    passwords = {kind: secrets.token_urlsafe(32) for kind in roles}
    base = base.set(drivername="postgresql", query={"sslmode": "disable"})
    urls = {
        kind: base.set(database=database, username=role, password=passwords[kind]).render_as_string(
            hide_password=False
        )
        for kind, role in roles.items()
    }
    created_roles = []
    created_database = False
    tenant_a, tenant_b, finance, supplier_user, other_finance = (uuid4() for _ in range(5))
    # libpq environment variables must not override the guarded loopback URI.
    with pytest.MonkeyPatch.context() as environment:
        for name in list(os.environ):
            if name.startswith("PG"):
                environment.delenv(name, raising=False)
        try:
            with psycopg.connect(
                base.render_as_string(hide_password=False), autocommit=True
            ) as admin:
                for kind, role in roles.items():
                    attributes = (
                        "CREATEDB CREATEROLE" if kind == "migration" else "NOCREATEDB NOCREATEROLE"
                    )
                    admin.execute(
                        sql.SQL(
                            "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOREPLICATION "
                            + attributes
                            + " PASSWORD {}"
                        ).format(sql.Identifier(role), sql.Literal(passwords[kind]))
                    )
                    created_roles.append(role)
                admin.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0").format(
                        sql.Identifier(database), sql.Identifier(roles["migration"])
                    )
                )
                created_database = True
            environment.setenv("APP_ENV", "test")
            environment.setenv("PGSSLMODE", "disable")
            environment.setenv("BEFORETRANSFER_DISABLE_DOTENV", "1")
            environment.setenv("MIGRATION_DATABASE_URL", urls["migration"])
            config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
            command.upgrade(config, "0004_sponsors")
            with psycopg.connect(urls["migration"], autocommit=True) as owner:
                flags = owner.execute(
                    "SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"
                ).fetchone()
                assert flags == (False, False, True, True)
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    owner.execute(
                        "INSERT INTO beforetransfer.tenants(id,name) VALUES (%s,'Before policy')",
                        (uuid4(),),
                    )
            command.upgrade(config, "head")
            command.upgrade(config, "head")  # Re-running migrations must be harmless.
            with psycopg.connect(urls["migration"]) as owner:
                for tenant, name in (
                    (tenant_a, "Managed tenant A"),
                    (tenant_b, "Managed tenant B"),
                ):
                    owner.execute(
                        "INSERT INTO beforetransfer.tenants(id,name) VALUES (%s,%s)", (tenant, name)
                    )
                for user, tenant, role in (
                    (finance, tenant_a, "finance_admin"),
                    (supplier_user, tenant_a, "supplier"),
                    (other_finance, tenant_b, "finance_admin"),
                ):
                    owner.execute(
                        "INSERT INTO beforetransfer.memberships(id,user_id,tenant_id,role) VALUES (%s,%s,%s,%s)",
                        (uuid4(), user, tenant, role),
                    )
            with psycopg.connect(
                base.render_as_string(hide_password=False), autocommit=True
            ) as admin:
                for kind, group in (
                    ("api", "beforetransfer_api"),
                    ("worker", "beforetransfer_worker"),
                ):
                    admin.execute(
                        sql.SQL("GRANT {} TO {}").format(
                            sql.Identifier(group), sql.Identifier(roles[kind])
                        )
                    )
            yield SimpleNamespace(
                urls=urls,
                base=base,
                roles=roles,
                tenant_a=tenant_a,
                tenant_b=tenant_b,
                finance=finance,
                supplier_user=supplier_user,
            )
        finally:
            with psycopg.connect(
                base.render_as_string(hide_password=False), autocommit=True
            ) as admin:
                if created_database:
                    admin.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
                    )
                for role in reversed(created_roles):
                    admin.execute(
                        sql.SQL("DROP ROLE {}{}").format(
                            sql.SQL("IF EXISTS "), sql.Identifier(role)
                        )
                    )


def engine(url):
    return create_async_engine(
        database_url(
            Settings(_env_file=None, app_env="test", database_url=url, pgsslmode="disable")
        )
    )


async def test_managed_owner_bootstraps_membership_and_supplier_assignment(managed_database):
    db = managed_database
    api = engine(db.urls["api"])
    try:
        finance = Principal(
            user_id=db.finance,
            tenant=TenantView(id=db.tenant_a, name="Managed tenant A"),
            role=Role.FINANCE_ADMIN,
        )
        supplier_principal = Principal(
            user_id=db.supplier_user, tenant=finance.tenant, role=Role.SUPPLIER
        )
        sessions = async_sessionmaker(api, expire_on_commit=False)
        async with sessions() as session:
            membership = await lookup_membership(session, db.finance)
            assert membership[1].id == db.tenant_a
            supplier = await create_supplier(session, finance, "Managed-owner synthetic supplier")
        # Same checked bootstrap join as the operator documentation; owner has
        # neither SUPERUSER nor BYPASSRLS and does not disable FORCE RLS.
        with psycopg.connect(db.urls["migration"]) as owner:
            inserted = owner.execute(
                """INSERT INTO beforetransfer.supplier_identities(id,tenant_id,supplier_id,user_id)
                SELECT %s,s.tenant_id,s.id,m.user_id FROM beforetransfer.suppliers s
                JOIN beforetransfer.memberships m ON m.tenant_id=s.tenant_id
                WHERE s.id=%s AND s.tenant_id=%s AND m.user_id=%s AND m.role='supplier' AND m.is_active
                RETURNING supplier_id""",
                (uuid4(), supplier.id, db.tenant_a, db.supplier_user),
            ).fetchone()
            assert inserted == (supplier.id,)
        async with sessions() as session:
            assigned = await list_suppliers(session, supplier_principal)
            assert [row.id for row in assigned] == [supplier.id]
            async with transaction(session, finance):
                assert (await session.scalars(select(Tenant.id))).all() == [db.tenant_a]
    finally:
        await api.dispose()


def test_managed_owner_bootstrap_policies_are_narrow(managed_database):
    db = managed_database
    with psycopg.connect(db.urls["migration"], autocommit=True) as owner:
        policies = owner.execute("""SELECT tablename,cmd,roles::text[] FROM pg_policies
            WHERE schemaname='beforetransfer' AND policyname LIKE 'managed_owner_bootstrap_%'
            ORDER BY tablename,cmd""").fetchall()
        assert len(policies) == 6
        assert {row[0] for row in policies} == {"tenants", "memberships", "supplier_identities"}
        assert {row[1] for row in policies} == {"SELECT", "INSERT"}
        assert all(row[2] == [db.roles["migration"]] for row in policies)
        assert (
            owner.execute(
                "UPDATE beforetransfer.memberships SET role='finance_admin' WHERE user_id=%s",
                (db.supplier_user,),
            ).rowcount
            == 0
        )
        assert (
            owner.execute("DELETE FROM beforetransfer.tenants WHERE id=%s", (db.tenant_b,)).rowcount
            == 0
        )
        assert owner.execute(
            "SELECT role FROM beforetransfer.memberships WHERE user_id=%s", (db.supplier_user,)
        ).fetchone() == ("supplier",)
        assert (
            owner.execute("""SELECT bool_and(relrowsecurity AND relforcerowsecurity) FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='beforetransfer' AND c.relkind='r'""").fetchone()
            == (True,)
        )
        for role in (db.roles["api"], db.roles["worker"]):
            for table in ("tenants", "memberships", "supplier_identities"):
                assert owner.execute(
                    "SELECT has_table_privilege(%s,%s,'INSERT')", (role, f"beforetransfer.{table}")
                ).fetchone() == (False,)
    for kind in ("api", "worker"):
        with psycopg.connect(db.urls[kind], autocommit=True) as runtime:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                runtime.execute(
                    "INSERT INTO beforetransfer.tenants(id,name) VALUES (%s,'Must be denied')",
                    (uuid4(),),
                )


async def test_migration_owner_and_owner_membership_remain_rejected_at_runtime(managed_database):
    db = managed_database
    for kind in ("migration", "api", "worker"):
        connection = engine(db.urls[kind])
        try:
            async with async_sessionmaker(connection)() as session:
                if kind == "migration":
                    with pytest.raises(AppError, match="database_role_unsafe"):
                        await assert_restricted_role(session)
                else:
                    await assert_restricted_role(
                        session, "beforetransfer_api" if kind == "api" else "beforetransfer_worker"
                    )
        finally:
            await connection.dispose()
    with psycopg.connect(db.base.render_as_string(hide_password=False), autocommit=True) as admin:
        admin.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(db.roles["migration"]), sql.Identifier(db.roles["api"])
            )
        )
    connection = engine(db.urls["api"])
    try:
        async with async_sessionmaker(connection)() as session:
            with pytest.raises(AppError, match="database_role_unsafe"):
                await assert_restricted_role(session)
    finally:
        await connection.dispose()
        with psycopg.connect(
            db.base.render_as_string(hide_password=False), autocommit=True
        ) as admin:
            admin.execute(
                sql.SQL("REVOKE {} FROM {}").format(
                    sql.Identifier(db.roles["migration"]), sql.Identifier(db.roles["api"])
                )
            )
