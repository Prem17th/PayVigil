"""Private workspace membership foundation; no financial domain tables."""

from alembic import op
import sqlalchemy as sa

revision = "0001_phase2_memberships"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA beforetransfer")
    op.execute("REVOKE ALL ON SCHEMA beforetransfer FROM PUBLIC")
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'beforetransfer_api') THEN
            CREATE ROLE beforetransfer_api NOLOGIN NOSUPERUSER NOBYPASSRLS;
        ELSIF EXISTS (
            SELECT 1 FROM pg_roles r WHERE r.rolname = 'beforetransfer_api'
            AND (r.rolcanlogin OR r.rolsuper OR r.rolbypassrls OR r.rolcreaterole
                 OR r.rolcreatedb OR r.rolreplication
                 OR EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member = r.oid))
        ) THEN
            RAISE EXCEPTION 'Existing beforetransfer_api role is not a restricted group';
        END IF;
    END $$""")
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="beforetransfer",
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_memberships_user_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["beforetransfer.tenants.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "role IN ('finance_admin', 'finance_reviewer', 'supplier')",
            name="membership_role_allowed",
        ),
        schema="beforetransfer",
    )
    for table in ("tenants", "memberships"):
        op.execute(f"ALTER TABLE beforetransfer.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE beforetransfer.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON beforetransfer.{table} FROM PUBLIC")
    # Supabase's browser roles may not exist in ordinary PostgreSQL.
    op.execute("""DO $$ DECLARE browser_role text; BEGIN
        FOREACH browser_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = browser_role) THEN
                EXECUTE format('REVOKE ALL ON SCHEMA beforetransfer FROM %I', browser_role);
                EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA beforetransfer FROM %I', browser_role);
            END IF;
        END LOOP;
    END $$""")
    op.execute("GRANT USAGE ON SCHEMA beforetransfer TO beforetransfer_api")
    op.execute(
        "GRANT SELECT ON beforetransfer.tenants, beforetransfer.memberships TO beforetransfer_api"
    )
    op.execute("""CREATE POLICY membership_self ON beforetransfer.memberships
        FOR SELECT TO beforetransfer_api USING (
            is_active AND user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )""")
    op.execute("""CREATE POLICY tenant_for_member ON beforetransfer.tenants
        FOR SELECT TO beforetransfer_api USING (
            EXISTS (SELECT 1 FROM beforetransfer.memberships m
                WHERE m.tenant_id = tenants.id AND m.is_active
                  AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
        )""")


def downgrade():
    op.drop_table("memberships", schema="beforetransfer")
    op.drop_table("tenants", schema="beforetransfer")
    op.execute("DROP SCHEMA beforetransfer")
    # The cluster role can be shared by another deployment; never drop it here.
