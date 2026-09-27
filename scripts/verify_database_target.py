"""Read-only hosted PostgreSQL preflight; never runs migrations or logs a DSN."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import certifi
import psycopg
from sqlalchemy import make_url

from render_release import ReleaseError, environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/hosted-database-preflight.json")
    )
    args = parser.parse_args()
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read-only hosted database identity, TLS and privilege preflight",
        "passed": False,
    }
    try:
        env = environment(args.env_file)
        url = make_url(env.get("MIGRATION_DATABASE_URL", ""))
        if (
            url.drivername not in {"postgresql", "postgresql+psycopg", "postgres"}
            or not url.host
            or url.database != args.expected_database
            or set(url.query) - {"sslmode", "sslrootcert", "connect_timeout"}
            or url.query.get("sslmode", "verify-full") != "verify-full"
        ):
            raise ReleaseError(
                "The expected database and a fully verified TLS URL are required; connection overrides are rejected."
            )
        # Use a known CA bundle on macOS without weakening certificate/hostname
        # verification or persisting a machine-specific path in release secrets.
        roots = url.query.get("sslrootcert", env.get("PGSSLROOTCERT", "system"))
        roots = certifi.where() if roots == "system" else roots
        url = url.set(
            drivername="postgresql", query={"sslmode": "verify-full", "sslrootcert": roots}
        )
        for name in list(os.environ):
            if name.startswith("PG"):
                os.environ.pop(name)
        with psycopg.connect(
            url.render_as_string(hide_password=False),
            connect_timeout=8,
            options="-c default_transaction_read_only=on -c statement_timeout=8000",
        ) as connection:

            def row(query, names):
                return dict(zip(names, connection.execute(query).fetchone()))

            report["identity"] = row(
                "SELECT current_database(),current_user,current_setting('server_version')",
                ("database", "user", "postgres_version"),
            )
            report["role"] = row(
                "SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication FROM pg_roles WHERE rolname=current_user",
                ("superuser", "bypass_rls", "create_role", "create_database", "replication"),
            )
            report["tls"] = row(
                "SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()",
                ("encrypted", "protocol"),
            )
            report["schema_tables"] = [
                dict(zip(("schema", "table_count"), values))
                for values in connection.execute(
                    "SELECT schemaname,count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') GROUP BY schemaname ORDER BY schemaname"
                )
            ]
            report["passed"] = (
                report["identity"]["database"] == args.expected_database
                and report["tls"]["encrypted"]
            )
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        if isinstance(exc, ReleaseError):
            report["error"] = str(exc)
        # Connection errors can contain DSNs; do not include their raw messages.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
