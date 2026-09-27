"""Private evidence snapshots, reviewed investigations and advisory memory receipts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_evidence_memory"
down_revision = "0002_payment_authority"
branch_labels = None
depends_on = None
SCHEMA = "beforetransfer"
EMPTY_DIGEST = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


def base():
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


def payment_ref():
    return sa.ForeignKeyConstraint(
        ["revision_id", "payment_id", "tenant_id"],
        [
            "beforetransfer.payment_revisions.id",
            "beforetransfer.payment_revisions.payment_id",
            "beforetransfer.payment_revisions.tenant_id",
        ],
    )


def upgrade():
    op.add_column(
        "payment_approvals",
        sa.Column("evidence_digest", sa.String(64), nullable=False, server_default=EMPTY_DIGEST),
        schema=SCHEMA,
    )
    op.create_table(
        "evidence_documents",
        *base(),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(160), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("object_path", sa.String(300), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("pages", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        payment_ref(),
        sa.UniqueConstraint("payment_id", "revision_id", "sha256"),
        sa.CheckConstraint("status IN ('uploading','ready','failed','unknown')"),
        schema=SCHEMA,
    )
    op.create_table(
        "investigations",
        *base(),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_digest", sa.String(64), nullable=False),
        sa.Column("document_ids", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("findings", postgresql.JSONB(), nullable=False),
        sa.Column("tool_trace", postgresql.JSONB(), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        payment_ref(),
        sa.UniqueConstraint("payment_id", "revision_id", "evidence_digest"),
        sa.CheckConstraint("status IN ('running','completed','failed','unknown')"),
        schema=SCHEMA,
    )
    op.create_index(
        "one_active_investigation",
        "investigations",
        ["payment_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status='running'"),
    )
    op.create_table(
        "investigation_reviews",
        *base(),
        sa.Column("investigation_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["investigation_id", "tenant_id"],
            ["beforetransfer.investigations.id", "beforetransfer.investigations.tenant_id"],
        ),
        sa.UniqueConstraint("investigation_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "memory_operations",
        *base(),
        sa.Column("investigation_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("redacted_content", sa.Text(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("provider_receipt", sa.String(200)),
        sa.ForeignKeyConstraint(
            ["investigation_id", "tenant_id"],
            ["beforetransfer.investigations.id", "beforetransfer.investigations.tenant_id"],
        ),
        sa.UniqueConstraint("investigation_id"),
        sa.CheckConstraint("status IN ('pending','written','failed','unknown')"),
        schema=SCHEMA,
    )
    for table in (
        "evidence_documents",
        "investigations",
        "investigation_reviews",
        "memory_operations",
    ):
        op.execute(f"ALTER TABLE beforetransfer.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE beforetransfer.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON beforetransfer.{table} FROM PUBLIC")
        op.execute(f"GRANT SELECT,INSERT ON beforetransfer.{table} TO beforetransfer_api")
        op.execute(f"GRANT SELECT ON beforetransfer.{table} TO beforetransfer_worker")
        finance = f"EXISTS (SELECT 1 FROM beforetransfer.memberships m WHERE m.tenant_id={table}.tenant_id AND m.user_id=NULLIF(current_setting('app.user_id',true),'')::uuid AND m.is_active AND m.role IN ('finance_admin','finance_reviewer'))"
        op.execute(
            f"CREATE POLICY finance_scope ON beforetransfer.{table} TO beforetransfer_api USING ({finance}) WITH CHECK ({finance})"
        )
        op.execute(
            f"CREATE POLICY worker_read ON beforetransfer.{table} FOR SELECT TO beforetransfer_worker USING (true)"
        )
    op.execute("GRANT UPDATE(status) ON beforetransfer.evidence_documents TO beforetransfer_api")
    op.execute(
        "GRANT UPDATE(status,summary,findings,tool_trace) ON beforetransfer.investigations TO beforetransfer_api"
    )
    op.execute(
        "GRANT UPDATE(status,provider_receipt) ON beforetransfer.memory_operations TO beforetransfer_api"
    )
    op.execute(
        "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON beforetransfer.investigation_reviews FOR EACH ROW EXECUTE FUNCTION beforetransfer.reject_history_change()"
    )
    op.execute("""CREATE FUNCTION beforetransfer.protect_evidence_operation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Evidence history cannot be deleted'; END IF;
        IF TG_TABLE_NAME='evidence_documents' THEN
            IF (to_jsonb(NEW)-'status') IS DISTINCT FROM (to_jsonb(OLD)-'status') OR OLD.status IN ('ready','failed') THEN
                RAISE EXCEPTION 'Document history is immutable'; END IF;
        ELSIF TG_TABLE_NAME='investigations' THEN
            IF (to_jsonb(NEW)-ARRAY['status','summary','findings','tool_trace']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','summary','findings','tool_trace']) OR OLD.status<>'running' THEN
                RAISE EXCEPTION 'Investigation history is immutable'; END IF;
        ELSE
            IF (to_jsonb(NEW)-ARRAY['status','provider_receipt']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','provider_receipt']) OR OLD.status<>'pending' THEN
                RAISE EXCEPTION 'Memory receipt is immutable'; END IF;
        END IF;
        RETURN NEW; END $$""")
    for table in ("evidence_documents", "investigations", "memory_operations"):
        op.execute(
            f"CREATE TRIGGER immutable_operation BEFORE UPDATE OR DELETE ON beforetransfer.{table} FOR EACH ROW EXECUTE FUNCTION beforetransfer.protect_evidence_operation()"
        )
    op.execute("REVOKE ALL ON FUNCTION beforetransfer.protect_evidence_operation() FROM PUBLIC")
    op.execute("""DO $$ DECLARE r text; BEGIN FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA beforetransfer FROM %I',r);
        END IF; END LOOP; END $$""")


def downgrade():
    for table in (
        "memory_operations",
        "investigation_reviews",
        "investigations",
        "evidence_documents",
    ):
        op.drop_table(table, schema=SCHEMA)
    op.execute("DROP FUNCTION beforetransfer.protect_evidence_operation()")
    op.drop_column("payment_approvals", "evidence_digest", schema=SCHEMA)
