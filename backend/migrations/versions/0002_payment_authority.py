"""Immutable payment authority and a restricted transactional execution outbox."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_payment_authority"
down_revision = "0001_phase2_memberships"
branch_labels = None
depends_on = None
SCHEMA = "beforetransfer"


def base_columns():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("beforetransfer.tenants.id"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("id", "tenant_id"),
    ]


def ref(local, table, remote=("id", "tenant_id")):
    return sa.ForeignKeyConstraint(local, [f"beforetransfer.{table}.{column}" for column in remote])


def upgrade():
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='beforetransfer_worker') THEN
            CREATE ROLE beforetransfer_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
        ELSIF EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname='beforetransfer_worker'
            AND (r.rolcanlogin OR r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication
                 OR EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid))) THEN
            RAISE EXCEPTION 'Existing beforetransfer_worker role is not a restricted group';
        END IF;
    END $$""")
    op.create_table(
        "suppliers",
        *base_columns(),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("current_beneficiary_version_id", sa.Uuid()),
        schema=SCHEMA,
    )
    op.create_table(
        "supplier_identities",
        *base_columns(),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        ref(["supplier_id", "tenant_id"], "suppliers"),
        sa.UniqueConstraint("supplier_id", "user_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "beneficiary_versions",
        *base_columns(),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("beneficiary_name", sa.String(160), nullable=False),
        sa.Column("sandbox_account_id", sa.String(80), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        ref(["supplier_id", "tenant_id"], "suppliers"),
        sa.UniqueConstraint("supplier_id", "version"),
        sa.UniqueConstraint("id", "supplier_id", "tenant_id"),
        sa.CheckConstraint("version > 0"),
        sa.CheckConstraint("sandbox_account_id ~ '^SIM-[A-Z0-9-]{3,64}$'"),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "supplier_current_version",
        "suppliers",
        "beneficiary_versions",
        ["current_beneficiary_version_id", "id", "tenant_id"],
        ["id", "supplier_id", "tenant_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        deferrable=True,
        initially="DEFERRED",
    )
    for table, actor in (
        ("supplier_confirmations", "confirmed_by"),
        ("beneficiary_acceptances", "accepted_by"),
    ):
        op.create_table(
            table,
            *base_columns(),
            sa.Column("supplier_id", sa.Uuid(), nullable=False),
            sa.Column("beneficiary_version_id", sa.Uuid(), nullable=False),
            sa.Column(actor, sa.Uuid(), nullable=False),
            ref(
                ["beneficiary_version_id", "supplier_id", "tenant_id"],
                "beneficiary_versions",
                ("id", "supplier_id", "tenant_id"),
            ),
            sa.UniqueConstraint("beneficiary_version_id"),
            schema=SCHEMA,
        )
    op.create_table(
        "payments",
        *base_columns(),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_reference", sa.String(80), nullable=False),
        sa.Column("current_revision_id", sa.Uuid()),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        ref(["supplier_id", "tenant_id"], "suppliers"),
        sa.UniqueConstraint(
            "tenant_id", "supplier_id", "invoice_reference", name="unique_supplier_invoice"
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT','APPROVED','QUEUED','SUBMITTING','UNKNOWN','SUCCEEDED','FAILED')"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "payment_revisions",
        *base_columns(),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("beneficiary_version_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("simulation", sa.String(20), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        ref(["payment_id", "tenant_id"], "payments"),
        ref(["beneficiary_version_id", "tenant_id"], "beneficiary_versions"),
        sa.UniqueConstraint("payment_id", "version"),
        sa.UniqueConstraint("id", "payment_id", "tenant_id"),
        sa.CheckConstraint("amount_minor > 0 AND amount_minor <= 1000000000000"),
        sa.CheckConstraint("currency='INR'"),
        sa.CheckConstraint("version > 0"),
        sa.CheckConstraint("simulation IN ('success','decline','lost_response')"),
        sa.CheckConstraint("digest ~ '^[a-f0-9]{64}$'"),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "payment_current_revision",
        "payments",
        "payment_revisions",
        ["current_revision_id", "id", "tenant_id"],
        ["id", "payment_id", "tenant_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "payment_approvals",
        *base_columns(),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        ref(
            ["revision_id", "payment_id", "tenant_id"],
            "payment_revisions",
            ("id", "payment_id", "tenant_id"),
        ),
        sa.UniqueConstraint("id", "payment_id", "tenant_id"),
        sa.CheckConstraint("expires_at > created_at"),
        schema=SCHEMA,
    )
    op.create_table(
        "executions",
        *base_columns(),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(100), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("worker_id", sa.String(100)),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("transfer_id", sa.String(100)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        ref(
            ["revision_id", "payment_id", "tenant_id"],
            "payment_revisions",
            ("id", "payment_id", "tenant_id"),
        ),
        ref(
            ["approval_id", "payment_id", "tenant_id"],
            "payment_approvals",
            ("id", "payment_id", "tenant_id"),
        ),
        sa.UniqueConstraint("payment_id"),
        sa.UniqueConstraint("tenant_id", "request_key"),
        sa.CheckConstraint("state IN ('QUEUED','SUBMITTING','UNKNOWN','SUCCEEDED','FAILED')"),
        schema=SCHEMA,
    )
    op.create_index("executions_pending", "executions", ["state", "next_attempt_at"], schema=SCHEMA)
    op.create_table(
        "audit_events",
        *base_columns(),
        sa.Column("subject_type", sa.String(20), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("subject_type IN ('supplier','payment')"),
        schema=SCHEMA,
    )
    op.create_index(
        "audit_subject",
        "audit_events",
        ["tenant_id", "subject_type", "subject_id", "created_at"],
        schema=SCHEMA,
    )

    tables = (
        "suppliers",
        "supplier_identities",
        "beneficiary_versions",
        "supplier_confirmations",
        "beneficiary_acceptances",
        "payments",
        "payment_revisions",
        "payment_approvals",
        "executions",
        "audit_events",
    )
    for table in tables:
        op.execute(f"ALTER TABLE beforetransfer.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE beforetransfer.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"REVOKE ALL ON beforetransfer.{table} FROM PUBLIC, beforetransfer_api, beforetransfer_worker"
        )
    op.execute("""DO $$ DECLARE browser_role text; BEGIN
        FOREACH browser_role IN ARRAY ARRAY['anon','authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=browser_role) THEN
                EXECUTE format('REVOKE ALL ON SCHEMA beforetransfer FROM %I',browser_role);
                EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA beforetransfer FROM %I',browser_role);
            END IF;
        END LOOP;
    END $$""")
    op.execute("GRANT USAGE ON SCHEMA beforetransfer TO beforetransfer_worker")
    op.execute(
        "GRANT SELECT ON "
        + ",".join(f"beforetransfer.{t}" for t in tables)
        + " TO beforetransfer_api"
    )
    op.execute(
        "GRANT INSERT ON "
        + ",".join(f"beforetransfer.{t}" for t in tables if t != "supplier_identities")
        + " TO beforetransfer_api"
    )
    op.execute(
        "GRANT UPDATE (current_beneficiary_version_id) ON beforetransfer.suppliers TO beforetransfer_api"
    )
    op.execute(
        "GRANT UPDATE (current_revision_id,state,updated_at) ON beforetransfer.payments TO beforetransfer_api"
    )
    worker_tables = tuple(t for t in tables if t != "supplier_identities")
    op.execute(
        "GRANT SELECT ON "
        + ",".join(f"beforetransfer.{t}" for t in worker_tables)
        + " TO beforetransfer_worker"
    )
    op.execute(
        "GRANT UPDATE (state,updated_at) ON beforetransfer.payments TO beforetransfer_worker"
    )
    op.execute(
        "GRANT UPDATE (state,lease_token,lease_until,worker_id,next_attempt_at,transfer_id,updated_at) ON beforetransfer.executions TO beforetransfer_worker"
    )
    op.execute("GRANT INSERT ON beforetransfer.audit_events TO beforetransfer_worker")
    # SELECT FOR UPDATE needs an UPDATE privilege, but the worker cannot change
    # this column's value (the immutable-key trigger below rejects that).
    op.execute("GRANT UPDATE (id) ON beforetransfer.suppliers TO beforetransfer_worker")
    user = "NULLIF(current_setting('app.user_id',true),'')::uuid"
    for table in tables:
        finance = f"EXISTS (SELECT 1 FROM beforetransfer.memberships m WHERE m.tenant_id={table}.tenant_id AND m.user_id={user} AND m.is_active AND m.role IN ('finance_admin','finance_reviewer'))"
        op.execute(
            f"CREATE POLICY finance_scope ON beforetransfer.{table} TO beforetransfer_api USING ({finance}) WITH CHECK ({finance})"
        )
        if table in worker_tables:
            op.execute(
                f"CREATE POLICY worker_scope ON beforetransfer.{table} TO beforetransfer_worker USING (true) WITH CHECK (true)"
            )

    def assigned(supplier):
        return f"EXISTS (SELECT 1 FROM beforetransfer.supplier_identities si WHERE si.supplier_id={supplier} AND si.user_id={user})"

    op.execute(
        f"CREATE POLICY supplier_assignment_self ON beforetransfer.supplier_identities FOR SELECT TO beforetransfer_api USING (user_id={user} AND EXISTS (SELECT 1 FROM beforetransfer.memberships m WHERE m.user_id={user} AND m.tenant_id=supplier_identities.tenant_id AND m.is_active AND m.role='supplier'))"
    )
    for table, supplier in (
        ("suppliers", "suppliers.id"),
        ("beneficiary_versions", "beneficiary_versions.supplier_id"),
        ("supplier_confirmations", "supplier_confirmations.supplier_id"),
        ("beneficiary_acceptances", "beneficiary_acceptances.supplier_id"),
    ):
        op.execute(
            f"CREATE POLICY assigned_supplier_read ON beforetransfer.{table} FOR SELECT TO beforetransfer_api USING ({assigned(supplier)})"
        )
    op.execute(
        f"CREATE POLICY assigned_supplier_confirm ON beforetransfer.supplier_confirmations FOR INSERT TO beforetransfer_api WITH CHECK (confirmed_by={user} AND {assigned('supplier_confirmations.supplier_id')})"
    )
    op.execute(
        f"CREATE POLICY assigned_supplier_audit_read ON beforetransfer.audit_events FOR SELECT TO beforetransfer_api USING (subject_type='supplier' AND {assigned('audit_events.subject_id')})"
    )
    op.execute(
        f"CREATE POLICY assigned_supplier_audit_insert ON beforetransfer.audit_events FOR INSERT TO beforetransfer_api WITH CHECK (subject_type='supplier' AND actor_user_id={user} AND {assigned('audit_events.subject_id')})"
    )
    # Supplier confirmations must lock the supplier, without gaining the ability
    # to mutate its destination. RLS permits the no-op lock; column grants and
    # the trigger still prevent mutation of identity fields.
    op.execute("GRANT UPDATE (id) ON beforetransfer.suppliers TO beforetransfer_api")
    op.execute(
        f"CREATE POLICY assigned_supplier_lock ON beforetransfer.suppliers FOR UPDATE TO beforetransfer_api USING ({assigned('suppliers.id')}) WITH CHECK ({assigned('suppliers.id')})"
    )
    op.execute("""CREATE FUNCTION beforetransfer.reject_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Immutable history cannot be changed'; END $$""")
    for table in (
        "beneficiary_versions",
        "supplier_confirmations",
        "beneficiary_acceptances",
        "payment_revisions",
        "payment_approvals",
        "audit_events",
    ):
        op.execute(
            f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON beforetransfer.{table} FOR EACH ROW EXECUTE FUNCTION beforetransfer.reject_history_change()"
        )
    op.execute("""CREATE FUNCTION beforetransfer.protect_supplier_key() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF (NEW.id,NEW.tenant_id,NEW.name,NEW.created_at) IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.name,OLD.created_at) THEN
            RAISE EXCEPTION 'Supplier identity is immutable'; END IF;
        IF NEW.current_beneficiary_version_id IS DISTINCT FROM OLD.current_beneficiary_version_id
           AND NOT EXISTS (SELECT 1 FROM beforetransfer.memberships m WHERE m.user_id=NULLIF(current_setting('app.user_id',true),'')::uuid
               AND m.tenant_id=OLD.tenant_id AND m.is_active AND m.role IN ('finance_admin','finance_reviewer')) THEN
            RAISE EXCEPTION 'Finance authority required'; END IF;
        RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER supplier_key BEFORE UPDATE ON beforetransfer.suppliers FOR EACH ROW EXECUTE FUNCTION beforetransfer.protect_supplier_key()"
    )
    op.execute("""CREATE FUNCTION beforetransfer.protect_payment_key() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF (NEW.id,NEW.tenant_id,NEW.supplier_id,NEW.invoice_reference,NEW.created_at) IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.supplier_id,OLD.invoice_reference,OLD.created_at) THEN
            RAISE EXCEPTION 'Payment identity is immutable'; END IF;
        IF OLD.state IN ('QUEUED','SUBMITTING','UNKNOWN','SUCCEEDED','FAILED') AND NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id THEN
            RAISE EXCEPTION 'Executing or terminal payment revision is immutable'; END IF;
        IF OLD.state IN ('SUCCEEDED','FAILED') AND NEW.state IS DISTINCT FROM OLD.state THEN
            RAISE EXCEPTION 'Terminal payment state is immutable'; END IF;
        IF NEW.state IN ('SUBMITTING','UNKNOWN','SUCCEEDED','FAILED') AND NEW.state IS DISTINCT FROM OLD.state
           AND NOT pg_has_role(current_user,'beforetransfer_worker','member') THEN
            RAISE EXCEPTION 'Worker authority required'; END IF;
        RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER payment_key BEFORE UPDATE ON beforetransfer.payments FOR EACH ROW EXECUTE FUNCTION beforetransfer.protect_payment_key()"
    )
    op.execute("""CREATE FUNCTION beforetransfer.protect_execution_key() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF (NEW.id,NEW.tenant_id,NEW.payment_id,NEW.revision_id,NEW.approval_id,NEW.request_key,NEW.body,NEW.created_at)
           IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.payment_id,OLD.revision_id,OLD.approval_id,OLD.request_key,OLD.body,OLD.created_at) THEN
            RAISE EXCEPTION 'Execution binding is immutable'; END IF;
        IF OLD.state IN ('SUCCEEDED','FAILED') AND NEW.state IS DISTINCT FROM OLD.state THEN
            RAISE EXCEPTION 'Terminal execution is immutable'; END IF;
        RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER execution_key BEFORE UPDATE ON beforetransfer.executions FOR EACH ROW EXECUTE FUNCTION beforetransfer.protect_execution_key()"
    )
    for function in (
        "reject_history_change",
        "protect_supplier_key",
        "protect_payment_key",
        "protect_execution_key",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION beforetransfer.{function}() FROM PUBLIC")


def downgrade():
    op.drop_constraint("supplier_current_version", "suppliers", schema=SCHEMA, type_="foreignkey")
    op.drop_constraint("payment_current_revision", "payments", schema=SCHEMA, type_="foreignkey")
    for table in (
        "audit_events",
        "executions",
        "payment_approvals",
        "payment_revisions",
        "payments",
        "beneficiary_acceptances",
        "supplier_confirmations",
        "beneficiary_versions",
        "supplier_identities",
        "suppliers",
    ):
        op.drop_table(table, schema=SCHEMA)
    for function in (
        "reject_history_change",
        "protect_supplier_key",
        "protect_payment_key",
        "protect_execution_key",
    ):
        op.execute(f"DROP FUNCTION beforetransfer.{function}()")
