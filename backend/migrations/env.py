import os

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import Settings
from app.core.database import database_url
from app.core.models import Base
from app.payments import models as payment_models  # noqa: F401 - register migration metadata
from app.evidence import models as evidence_models  # noqa: F401 - register migration metadata


target_metadata = Base.metadata
settings = (
    Settings(_env_file=None) if os.getenv("BEFORETRANSFER_DISABLE_DOTENV") == "1" else Settings()
)
VERSION_SCHEMA = "beforetransfer_migrations"


def protect_migration_metadata():
    # A separate schema exists before Alembic creates its version table. Browser
    # roles must not inherit legacy Supabase public/default table grants.
    context.execute(f"CREATE SCHEMA IF NOT EXISTS {VERSION_SCHEMA}")
    context.execute(f"REVOKE ALL ON SCHEMA {VERSION_SCHEMA} FROM PUBLIC")
    context.execute("""DO $$ DECLARE browser_role text; BEGIN
        IF to_regclass('beforetransfer_migrations.alembic_version') IS NOT NULL THEN
            ALTER TABLE beforetransfer_migrations.alembic_version ENABLE ROW LEVEL SECURITY;
            REVOKE ALL ON beforetransfer_migrations.alembic_version FROM PUBLIC;
        END IF;
        FOREACH browser_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = browser_role) THEN
                EXECUTE format('REVOKE ALL ON SCHEMA beforetransfer_migrations FROM %I', browser_role);
                IF to_regclass('beforetransfer_migrations.alembic_version') IS NOT NULL THEN
                    EXECUTE format('REVOKE ALL ON beforetransfer_migrations.alembic_version FROM %I', browser_role);
                END IF;
            END IF;
        END LOOP;
    END $$""")


def run_protected_migrations():
    with context.begin_transaction():
        protect_migration_metadata()
        context.run_migrations()
        protect_migration_metadata()


def run_migrations_offline():
    # Offline SQL generation deliberately needs no connection or credentials.
    context.configure(
        dialect_name="postgresql",
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        version_table_schema=VERSION_SCHEMA,
    )
    run_protected_migrations()


def run_migrations_online():
    engine = create_engine(
        database_url(settings, migration=True),
        poolclass=pool.NullPool,
        hide_parameters=True,
        connect_args={"prepare_threshold": None},
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=VERSION_SCHEMA,
        )
        run_protected_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
