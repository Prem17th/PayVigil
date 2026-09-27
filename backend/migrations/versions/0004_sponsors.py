"""Private sponsor receipts; callbacks have no payment authority."""

from alembic import op
import sqlalchemy as sa

revision = "0004_sponsors"
down_revision = "0003_evidence_memory"
branch_labels = None
depends_on = None
S = "beforetransfer"


def upgrade():
    op.drop_constraint("audit_events_subject_type_check", "audit_events", schema=S, type_="check")
    op.create_check_constraint(
        "audit_events_subject_type_check",
        "audit_events",
        "subject_type IN ('supplier','payment','delivery','voice','billing')",
        schema=S,
    )
    op.create_table(
        "sponsor_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("beneficiary_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["supplier_id", "tenant_id"],
            ["beforetransfer.suppliers.id", "beforetransfer.suppliers.tenant_id"],
        ),
        sa.ForeignKeyConstraint(
            ["beneficiary_version_id", "supplier_id", "tenant_id"],
            [
                "beforetransfer.beneficiary_versions.id",
                "beforetransfer.beneficiary_versions.supplier_id",
                "beforetransfer.beneficiary_versions.tenant_id",
            ],
        ),
        sa.UniqueConstraint("supplier_id", "beneficiary_version_id"),
        sa.CheckConstraint("status IN ('PENDING','DELIVERED','UNKNOWN','FAILED','STALE')"),
        sa.CheckConstraint("attempts BETWEEN 1 AND 3"),
        schema=S,
    )
    op.create_table(
        "sponsor_voice_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=False),
        sa.Column("text_digest", sa.String(64), nullable=False),
        sa.Column("voice_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("audio", sa.LargeBinary()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id", "tenant_id"],
            ["beforetransfer.investigations.id", "beforetransfer.investigations.tenant_id"],
        ),
        sa.UniqueConstraint("investigation_id", "text_digest", "voice_id"),
        sa.CheckConstraint("status IN ('PENDING','READY','UNKNOWN')"),
        sa.CheckConstraint("octet_length(audio)<=2000000"),
        schema=S,
    )
    op.create_table(
        "sponsor_billing",
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("beforetransfer.tenants.id"), primary_key=True
        ),
        sa.Column("operation_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("checkout_id", sa.String(160), unique=True),
        sa.Column("checkout_url", sa.String(2048)),
        sa.Column("customer_id", sa.String(160), unique=True),
        sa.Column("subscription_id", sa.String(160), unique=True),
        sa.Column("product_id", sa.String(100), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("reconcile_token", sa.Uuid()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('CHECKOUT_PENDING','UNKNOWN','ACTIVE','CANCELLED','EXPIRED','FAILED')"
        ),
        schema=S,
    )
    op.create_table(
        "sponsor_events",
        sa.Column("provider", sa.String(16), primary_key=True),
        sa.Column("event_id", sa.String(160), primary_key=True),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.Uuid()),
        sa.Column("entity_id", sa.Uuid()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema=S,
    )
    for table in (
        "sponsor_deliveries",
        "sponsor_voice_operations",
        "sponsor_billing",
        "sponsor_events",
    ):
        op.execute(f"ALTER TABLE {S}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {S}.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {S}.{table} FROM PUBLIC")
        # Only the migration owner can execute callback function bodies under this policy.
        # Runtime must not be a member of any table-owner role (checked on every transaction).
        op.execute(
            f"CREATE POLICY receipt_owner ON {S}.{table} TO CURRENT_USER USING (true) WITH CHECK (true)"
        )
        if table != "sponsor_events":
            predicate = f"EXISTS (SELECT 1 FROM {S}.memberships m WHERE m.tenant_id={table}.tenant_id AND m.user_id=NULLIF(current_setting('app.user_id',true),'')::uuid AND m.is_active AND m.role IN ('finance_admin','finance_reviewer'))"
            op.execute(f"GRANT SELECT,INSERT ON {S}.{table} TO beforetransfer_api")
            op.execute(
                f"CREATE POLICY finance_scope ON {S}.{table} TO beforetransfer_api USING ({predicate}) WITH CHECK ({predicate})"
            )
    op.execute(
        f"CREATE POLICY supplier_inbox ON {S}.sponsor_deliveries FOR SELECT TO beforetransfer_api USING (EXISTS (SELECT 1 FROM {S}.supplier_identities i JOIN {S}.memberships m ON m.user_id=i.user_id AND m.tenant_id=i.tenant_id WHERE i.supplier_id=sponsor_deliveries.supplier_id AND i.tenant_id=sponsor_deliveries.tenant_id AND i.user_id=NULLIF(current_setting('app.user_id',true),'')::uuid AND m.is_active AND m.role='supplier'))"
    )
    op.execute(
        f"GRANT UPDATE(status,attempts,last_attempt_at,delivered_at) ON {S}.sponsor_deliveries TO beforetransfer_api"
    )
    op.execute(f"GRANT UPDATE(status,audio) ON {S}.sponsor_voice_operations TO beforetransfer_api")
    op.execute(
        f"GRANT UPDATE(operation_id,status,checkout_id,checkout_url,customer_id,subscription_id,product_id,verified_at,expires_at,reconcile_token) ON {S}.sponsor_billing TO beforetransfer_api"
    )
    op.execute(
        f"CREATE POLICY receipt_owner_read ON {S}.suppliers TO CURRENT_USER USING (true) WITH CHECK (true)"
    )
    op.execute("""CREATE FUNCTION beforetransfer.delivery_callback(eid text,digest text,did uuid,attempt integer,outcome text) RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE d beforetransfer.sponsor_deliveries%ROWTYPE; old beforetransfer.sponsor_events%ROWTYPE; sid uuid; current_version uuid;
        BEGIN
            IF length(eid)>160 OR length(eid)<1 OR length(digest)<>64 OR outcome NOT IN ('DELIVERED','FAILED') OR attempt NOT BETWEEN 1 AND 3 THEN RETURN 'invalid'; END IF;
            SELECT supplier_id INTO sid FROM beforetransfer.sponsor_deliveries WHERE id=did;
            IF sid IS NULL THEN RETURN 'missing'; END IF;
            SELECT current_beneficiary_version_id INTO current_version FROM beforetransfer.suppliers WHERE id=sid FOR UPDATE;
            SELECT * INTO d FROM beforetransfer.sponsor_deliveries WHERE id=did FOR UPDATE;
            INSERT INTO beforetransfer.sponsor_events(provider,event_id,payload_digest,tenant_id,entity_id,status) VALUES ('n8n',eid,digest,d.tenant_id,did,'received') ON CONFLICT DO NOTHING;
            SELECT * INTO old FROM beforetransfer.sponsor_events WHERE provider='n8n' AND event_id=eid FOR UPDATE;
            IF old.payload_digest<>digest OR old.entity_id<>did THEN RETURN 'conflict'; END IF;
            IF old.status='processed' THEN RETURN 'duplicate'; END IF;
            IF d.beneficiary_version_id IS DISTINCT FROM current_version THEN
                UPDATE beforetransfer.sponsor_deliveries SET status='STALE' WHERE id=did;
            ELSIF d.attempts=attempt AND d.status IN ('PENDING','UNKNOWN') THEN
                UPDATE beforetransfer.sponsor_deliveries SET status=outcome,delivered_at=CASE WHEN outcome='DELIVERED' THEN now() ELSE delivered_at END WHERE id=did;
            END IF;
            UPDATE beforetransfer.sponsor_events SET status='processed' WHERE provider='n8n' AND event_id=eid;
            RETURN 'processed';
        END $$""")
    op.execute("""CREATE FUNCTION beforetransfer.billing_event_claim(eid text,digest text,opid uuid,subid text,token uuid) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE b beforetransfer.sponsor_billing%ROWTYPE; e beforetransfer.sponsor_events%ROWTYPE;
        BEGIN
            IF length(eid)>160 OR length(eid)<1 OR length(digest)<>64 THEN RETURN jsonb_build_object('result','invalid'); END IF;
            INSERT INTO beforetransfer.sponsor_events(provider,event_id,payload_digest,status) VALUES ('dodo',eid,digest,'received') ON CONFLICT DO NOTHING;
            SELECT * INTO e FROM beforetransfer.sponsor_events WHERE provider='dodo' AND event_id=eid FOR UPDATE;
            IF e.payload_digest<>digest THEN RETURN jsonb_build_object('result','conflict'); END IF;
            IF e.status IN ('processed','ignored') THEN RETURN jsonb_build_object('result','duplicate'); END IF;
            SELECT * INTO b FROM beforetransfer.sponsor_billing WHERE (opid IS NOT NULL AND operation_id=opid) OR (opid IS NULL AND subid IS NOT NULL AND subscription_id=subid) FOR UPDATE;
            IF b.tenant_id IS NULL OR b.checkout_id IS NULL THEN
                UPDATE beforetransfer.sponsor_events SET status='ignored' WHERE provider='dodo' AND event_id=eid;
                RETURN jsonb_build_object('result','ignored');
            END IF;
            IF (opid IS NOT NULL AND opid<>b.operation_id) OR (subid IS NOT NULL AND b.subscription_id IS NOT NULL AND subid<>b.subscription_id) THEN RETURN jsonb_build_object('result','conflict'); END IF;
            UPDATE beforetransfer.sponsor_billing SET status='UNKNOWN',verified_at=NULL,reconcile_token=token WHERE tenant_id=b.tenant_id;
            UPDATE beforetransfer.sponsor_events SET tenant_id=b.tenant_id,entity_id=b.operation_id WHERE provider='dodo' AND event_id=eid;
            RETURN jsonb_build_object('result','reconcile','operation_id',b.operation_id,'checkout_id',b.checkout_id,'product_id',b.product_id,'customer_id',b.customer_id,'subscription_id',b.subscription_id);
        END $$""")
    op.execute("""CREATE FUNCTION beforetransfer.billing_event_finish(eid text,opid uuid,token uuid,outcome text,cid text,sid text,expiry timestamptz) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE b beforetransfer.sponsor_billing%ROWTYPE;
        BEGIN
            IF outcome NOT IN ('CHECKOUT_PENDING','ACTIVE','CANCELLED','EXPIRED','FAILED') THEN RETURN false; END IF;
            PERFORM 1 FROM beforetransfer.sponsor_events WHERE provider='dodo' AND event_id=eid FOR UPDATE;
            SELECT * INTO b FROM beforetransfer.sponsor_billing WHERE operation_id=opid FOR UPDATE;
            IF b.tenant_id IS NULL OR b.reconcile_token IS DISTINCT FROM token THEN RETURN false; END IF;
            IF NOT EXISTS (SELECT 1 FROM beforetransfer.sponsor_events WHERE provider='dodo' AND event_id=eid AND entity_id=opid AND status='received') THEN RETURN false; END IF;
            IF (b.customer_id IS NOT NULL AND b.customer_id IS DISTINCT FROM cid) OR (b.subscription_id IS NOT NULL AND b.subscription_id IS DISTINCT FROM sid) THEN RETURN false; END IF;
            IF outcome='ACTIVE' AND (cid IS NULL OR sid IS NULL OR expiry IS NULL OR expiry<=now()) THEN RETURN false; END IF;
            UPDATE beforetransfer.sponsor_billing SET status=outcome,customer_id=cid,subscription_id=sid,expires_at=expiry,verified_at=now(),reconcile_token=NULL WHERE tenant_id=b.tenant_id;
            UPDATE beforetransfer.sponsor_events SET status='processed' WHERE provider='dodo' AND event_id=eid;
            RETURN true;
        END $$""")
    signatures = (
        "delivery_callback(text,text,uuid,integer,text)",
        "billing_event_claim(text,text,uuid,text,uuid)",
        "billing_event_finish(text,uuid,uuid,text,text,text,timestamptz)",
    )
    for fn in signatures:
        op.execute(f"REVOKE ALL ON FUNCTION {S}.{fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {S}.{fn} TO beforetransfer_api")
    op.execute("""DO $$ DECLARE r text; f text; BEGIN FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA beforetransfer FROM %I',r);
            FOREACH f IN ARRAY ARRAY['delivery_callback(text,text,uuid,integer,text)','billing_event_claim(text,text,uuid,text,uuid)','billing_event_finish(text,uuid,uuid,text,text,text,timestamptz)'] LOOP
                EXECUTE format('REVOKE ALL ON FUNCTION beforetransfer.%s FROM %I',f,r);
            END LOOP;
        END IF; END LOOP; END $$""")


def downgrade():
    # Existing sponsor audit rows are immutable; downgrade must preserve their valid subject types.
    for fn in (
        "delivery_callback(text,text,uuid,integer,text)",
        "billing_event_claim(text,text,uuid,text,uuid)",
        "billing_event_finish(text,uuid,uuid,text,text,text,timestamptz)",
    ):
        op.execute(f"DROP FUNCTION {S}.{fn}")
    op.execute(f"DROP POLICY receipt_owner_read ON {S}.suppliers")
    for table in (
        "sponsor_events",
        "sponsor_billing",
        "sponsor_voice_operations",
        "sponsor_deliveries",
    ):
        op.drop_table(table, schema=S)
