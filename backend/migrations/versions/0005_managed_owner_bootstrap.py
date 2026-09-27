"""Permit narrow identity bootstrap by a managed, non-bypass migration owner."""

from alembic import op


revision = "0005_managed_owner_bootstrap"
down_revision = "0004_sponsors"
branch_labels = None
depends_on = None


def upgrade():
    # Managed PostgreSQL owners can own/alter tables without SUPERUSER or
    # BYPASSRLS. FORCE RLS therefore requires explicit bootstrap policies.
    # Bind policies to the actual table owner, never a public/runtime group.
    op.execute("""DO $bootstrap_policies$
    DECLARE table_name text; owner_name name := current_user; actual_owner oid;
    BEGIN
        FOREACH table_name IN ARRAY ARRAY['tenants','memberships','supplier_identities'] LOOP
            SELECT c.relowner INTO actual_owner FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='beforetransfer' AND c.relname=table_name AND c.relkind='r';
            IF actual_owner IS DISTINCT FROM (SELECT oid FROM pg_catalog.pg_roles WHERE rolname=owner_name) THEN
                RAISE EXCEPTION 'Bootstrap migration must run as the existing application table owner';
            END IF;
            EXECUTE format(
                'CREATE POLICY managed_owner_bootstrap_select ON beforetransfer.%I FOR SELECT TO %I USING (current_user = %L)',
                table_name, owner_name, owner_name);
            EXECUTE format(
                'CREATE POLICY managed_owner_bootstrap_insert ON beforetransfer.%I FOR INSERT TO %I WITH CHECK (current_user = %L)',
                table_name, owner_name, owner_name);
        END LOOP;
    END $bootstrap_policies$""")


def downgrade():
    for table in ("supplier_identities", "memberships", "tenants"):
        op.execute(f"DROP POLICY managed_owner_bootstrap_insert ON beforetransfer.{table}")
        op.execute(f"DROP POLICY managed_owner_bootstrap_select ON beforetransfer.{table}")
