"""Run the build checks; --postgres provisions fresh disposable loopback test DBs.

Set LOCAL_TEST_ADMIN_URL through a secure environment. Test database/role names
and passwords are generated; this script never accepts remote database targets.
Fresh databases intentionally retain test audit history for diagnosis. Only the
two database names and role names are recorded in the ignored artifact report.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import make_url

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_NAMES = (
    "DATABASE_URL",
    "MIGRATION_DATABASE_URL",
    "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "BREETH_API_KEY",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "N8N_WEBHOOK_URL",
    "N8N_WEBHOOK_TOKEN",
    "N8N_CALLBACK_SECRET",
    "DODO_API_KEY",
    "DODO_WEBHOOK_SECRET",
    "DODO_PRODUCT_ID",
)


def clean_environment() -> dict:
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(
            (
                "SUPABASE_",
                "OPENAI_",
                "BREETH_",
                "ELEVENLABS_",
                "N8N_",
                "DODO_",
                "RENDER_",
                "VITE_",
                "PG",
                "TEST_",
                "SANDBOX_",
                "PAYMENTS_",
                "WORKER_",
            )
        ):
            env.pop(key)
    env.update({name: "" for name in PROVIDER_NAMES})
    env.update(
        APP_ENV="test",
        PGSSLMODE="disable",
        BEFORETRANSFER_DISABLE_DOTENV="1",
        VITE_LOCAL_SANDBOX="false",
        VITE_SUPABASE_URL="",
        VITE_SUPABASE_PUBLISHABLE_KEY="",
        VITE_API_BASE_URL="",
    )
    return env


def run(label: str, command: list, env: dict, cwd=ROOT):
    print(f"CHECK {label}", flush=True)
    result = subprocess.run(command, env=env, cwd=cwd, text=True)
    if result.returncode:
        raise RuntimeError(f"{label} failed")


def provision(env: dict) -> dict:
    # libpq routing variables can override a URI's host without changing its
    # text. Remove them in this operator process as well as child test processes.
    for name in list(os.environ):
        if name.startswith("PG"):
            os.environ.pop(name)
    value = os.environ.get("LOCAL_TEST_ADMIN_URL", "")
    try:
        base = make_url(value)
        if (
            base.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}
            or base.host not in {"localhost", "127.0.0.1", "::1"}
            or set(base.query) - {"sslmode"}
            or base.query.get("sslmode", "disable") != "disable"
        ):
            raise ValueError()
    except Exception:
        raise RuntimeError(
            "LOCAL_TEST_ADMIN_URL must target disposable loopback PostgreSQL without connection overrides."
        ) from None
    base = base.set(
        drivername="postgresql",
        host="127.0.0.1" if base.host == "localhost" else base.host,
        query={"sslmode": "disable"},
    )
    suffix = uuid4().hex[:10]
    names = {"app": f"bt_build_{suffix}_test", "sandbox": f"bt_sandbox_{suffix}_test"}
    roles = {
        key: (f"bt_check_{key}_{suffix}", secrets.token_urlsafe(32))
        for key in ("api", "worker", "sandbox")
    }
    report_path = ROOT / "artifacts/build-checks.json"
    report = json.loads(report_path.read_text())
    report["isolated_test_resources"] = {
        "databases": list(names.values()),
        "roles": [value[0] for value in roles.values()],
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    def url(database, role=None):
        u = base.set(database=names[database])
        if role:
            u = u.set(username=roles[role][0], password=roles[role][1])
        return u.render_as_string(hide_password=False)

    with psycopg.connect(base.render_as_string(hide_password=False), autocommit=True) as connection:
        for database in names.values():
            connection.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database))
            )
        for role, password in roles.values():
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
        for browser_role in ("anon", "authenticated"):
            if not connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (browser_role,)
            ).fetchone():
                connection.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(browser_role))
                )
    # Emulate Supabase's broad defaults in this NEW disposable database so the
    # migrations must revoke them from financial tables and version metadata.
    with psycopg.connect(url("app"), autocommit=True) as connection:
        connection.execute(
            "ALTER DEFAULT PRIVILEGES GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO anon,authenticated"
        )
    migration_env = {**env, "MIGRATION_DATABASE_URL": url("app")}
    run(
        "fresh application migrations",
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        migration_env,
        ROOT / "backend",
    )
    run(
        "fresh independent ledger schema",
        [sys.executable, "-m", "sandbox_service.bootstrap"],
        {
            **env,
            "SANDBOX_MIGRATION_DATABASE_URL": url("sandbox"),
            "SANDBOX_APP_ENV": "test",
            "SANDBOX_PGSSLMODE": "disable",
        },
    )
    with psycopg.connect(base.render_as_string(hide_password=False), autocommit=True) as connection:
        for role, group in (
            ("api", "beforetransfer_api"),
            ("worker", "beforetransfer_worker"),
            ("sandbox", "beforetransfer_sandbox_api"),
        ):
            connection.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(group), sql.Identifier(roles[role][0])
                )
            )
    env.update(
        TEST_ADMIN_DATABASE_URL=url("app"),
        TEST_DATABASE_URL=url("app", "api"),
        TEST_WORKER_DATABASE_URL=url("app", "worker"),
        SANDBOX_TEST_MIGRATION_DATABASE_URL=url("sandbox"),
        SANDBOX_TEST_DATABASE_URL=url("sandbox", "sandbox"),
    )
    return {"databases": list(names.values()), "roles": [value[0] for value in roles.values()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Include real PostgreSQL and HTTP ledger tests (required for release).",
    )
    parser.add_argument("--backend-only", action="store_true")
    args = parser.parse_args()
    env = clean_environment()
    path = ROOT / "artifacts/build-checks.json"
    path.parent.mkdir(exist_ok=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    commit = revision.stdout.strip() if revision.returncode == 0 else None
    path.write_text(
        json.dumps(
            {
                "passed": False,
                "status": "checks_started",
                "commit": commit,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
        + "\n"
    )
    isolated = provision(env) if args.postgres else None
    run("backend controls", [sys.executable, "-m", "pytest", "-q"], env, ROOT / "backend")
    run("release tooling", [sys.executable, "-m", "pytest", "scripts/tests", "-q"], env)
    if args.postgres:
        run(
            "sandbox ledger HTTP and restart",
            [
                sys.executable,
                "-m",
                "pytest",
                "sandbox_service/tests",
                "-q",
                "-o",
                "asyncio_mode=auto",
            ],
            env,
        )
    if not args.backend_only:
        run("frontend boundary checks", ["npm", "test"], env, ROOT / "frontend")
        run("frontend production build", ["npm", "run", "build"], env, ROOT / "frontend")
        run(
            "frontend configuration guards",
            [sys.executable, "scripts/check_frontend_config.py"],
            env,
        )
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "commit": commit,
        "postgres_included": args.postgres,
        "frontend_included": not args.backend_only,
        "isolated_test_resources": isolated,
        "live_providers_verified": False,
    }
    path.write_text(json.dumps(report, indent=2) + "\n")
    print("PASS local build checks. Live provider and hosted checks are separate.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, psycopg.Error, OSError):
        raise SystemExit(
            "Build verification failed. Review the named check; connection details are not printed."
        ) from None
