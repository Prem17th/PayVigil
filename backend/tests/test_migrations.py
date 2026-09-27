from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_migration_generates_postgres_schema_and_fail_closed_rls():
    output = StringIO()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"), output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE SCHEMA beforetransfer" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY membership_self" in sql
    assert "current_setting('app.user_id', true)" in sql
    assert "UNIQUE (user_id)" in sql
    assert "GRANT SELECT ON beforetransfer.tenants" in sql
    assert "auth.users" not in sql
    assert "CREATE TABLE beforetransfer_migrations.alembic_version" in sql
    assert "REVOKE ALL ON SCHEMA beforetransfer_migrations FROM PUBLIC" in sql
    assert "ALTER TABLE beforetransfer_migrations.alembic_version ENABLE ROW LEVEL SECURITY" in sql
    assert "CREATE TABLE alembic_version" not in sql
    assert "CREATE POLICY managed_owner_bootstrap_select" in sql
    assert "CREATE POLICY managed_owner_bootstrap_insert" in sql
    assert "Bootstrap migration must run as the existing application table owner" in sql
