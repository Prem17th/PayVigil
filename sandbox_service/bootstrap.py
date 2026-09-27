"""Explicit sandbox schema bootstrap. Never invoked by the API process."""

from sqlalchemy import create_engine, text

from .config import database_url, get_settings
from .ledger import metadata


def bootstrap() -> None:
    engine = create_engine(database_url(get_settings(), migration=True), hide_parameters=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'beforetransfer_sandbox_api') THEN
                    CREATE ROLE beforetransfer_sandbox_api NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
                ELSIF EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname = 'beforetransfer_sandbox_api'
                    AND (r.rolcanlogin OR r.rolsuper OR r.rolbypassrls OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication
                         OR EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member = r.oid))) THEN
                    RAISE EXCEPTION 'Sandbox API group must be restricted';
                END IF;
            END $$""")
            )
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS sandbox_ledger"))
            connection.execute(text("REVOKE ALL ON SCHEMA sandbox_ledger FROM PUBLIC"))
            metadata.create_all(connection)
            for table in ("transfers", "debits"):
                connection.execute(
                    text(f"ALTER TABLE sandbox_ledger.{table} ENABLE ROW LEVEL SECURITY")
                )
                connection.execute(
                    text(f"ALTER TABLE sandbox_ledger.{table} FORCE ROW LEVEL SECURITY")
                )
                connection.execute(text(f"REVOKE ALL ON sandbox_ledger.{table} FROM PUBLIC"))
                connection.execute(
                    text(f"DROP POLICY IF EXISTS sandbox_runtime ON sandbox_ledger.{table}")
                )
                connection.execute(
                    text(
                        f"CREATE POLICY sandbox_runtime ON sandbox_ledger.{table} TO beforetransfer_sandbox_api USING (true) WITH CHECK (true)"
                    )
                )
            connection.execute(
                text("""DO $$ DECLARE browser_role text; BEGIN
                FOREACH browser_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = browser_role) THEN
                        EXECUTE format('REVOKE ALL ON SCHEMA sandbox_ledger FROM %I', browser_role);
                        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA sandbox_ledger FROM %I', browser_role);
                    END IF;
                END LOOP;
            END $$""")
            )
            connection.execute(
                text("GRANT USAGE ON SCHEMA sandbox_ledger TO beforetransfer_sandbox_api")
            )
            connection.execute(
                text(
                    "GRANT SELECT, INSERT ON sandbox_ledger.transfers, sandbox_ledger.debits TO beforetransfer_sandbox_api"
                )
            )
        print(
            "Synthetic sandbox schema ready. Provision its separate restricted LOGIN role before API start."
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    bootstrap()
