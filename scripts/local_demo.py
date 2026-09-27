"""Provision and run the explicitly synthetic local review environment.

Usage: python scripts/local_demo.py setup|start
Setup requires LOCAL_TEST_ADMIN_URL for a disposable loopback PostgreSQL server.
No provider credentials, cloud resources, real bank accounts, or real funds.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import psycopg
from psycopg import sql
from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / ".local" / "demo"
PYTHON = ROOT / ".venv" / "bin" / "python"
STATE = DEMO / "runtime.json"
IDENTITY = DEMO / "identities.json"
FRONTEND_ENV = ROOT / "frontend" / ".env.development.local"
APP_DATABASE = "beforetransfer_demo_test"
LEDGER_DATABASE = "beforetransfer_sandbox_demo_test"


def save_private(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(value, output, indent=2)
        output.write("\n")
    path.chmod(0o600)


def require_loopback(value: str):
    url = make_url(value)
    if url.host not in {"127.0.0.1", "localhost", "::1"} or url.drivername not in {
        "postgresql",
        "postgresql+psycopg",
        "postgres",
    }:
        raise RuntimeError("A disposable loopback PostgreSQL admin URL is required.")
    if any(key not in {"sslmode", "connect_timeout"} for key in url.query):
        raise RuntimeError("Unsupported connection override in local test URL.")
    return url.set(
        drivername="postgresql",
        host="127.0.0.1" if url.host == "localhost" else url.host,
        query={"sslmode": "disable"},
    )


def initial_state(admin_url: str) -> dict:
    base = require_loopback(admin_url)
    roles = {
        key: {"name": f"bt_demo_{key}", "password": secrets.token_urlsafe(32)}
        for key in ("api", "worker", "sandbox")
    }

    def database_url(role, database):
        return base.set(
            username=roles[role]["name"], password=roles[role]["password"], database=database
        ).render_as_string(hide_password=False)

    return {
        "roles": roles,
        "admin_url": base.render_as_string(hide_password=False),
        "app_admin_url": base.set(database=APP_DATABASE).render_as_string(hide_password=False),
        "ledger_admin_url": base.set(database=LEDGER_DATABASE).render_as_string(
            hide_password=False
        ),
        "database_url": database_url("api", APP_DATABASE),
        "worker_database_url": database_url("worker", APP_DATABASE),
        "sandbox_database_url": database_url("sandbox", LEDGER_DATABASE),
        "sandbox_api_key": secrets.token_urlsafe(40),
        "tenant_id": str(uuid4()),
        "other_tenant_id": str(uuid4()),
        "supplier_id": str(uuid4()),
    }


def initial_identities() -> dict:
    actors = {}
    for actor in ("finance", "supplier", "outsider", "unassigned"):
        actors[actor] = {
            "user_id": str(uuid4()),
            "email": f"{actor}@beforetransfer.test",
            "refresh_token": secrets.token_urlsafe(40),
        }
    return {
        "signing_secret": secrets.token_urlsafe(48),
        "publishable_key": "sb_publishable_" + secrets.token_urlsafe(32),
        "storage_key": "sb_secret_" + secrets.token_urlsafe(40),
        "identity_origin": "http://127.0.0.1:54330",
        "frontend_origin": "http://127.0.0.1:5176",
        "actors": actors,
    }


def environment(state: dict, identities: dict) -> dict[str, str]:
    env = dict(os.environ)
    # The explicit fixture process never inherits real integration credentials.
    for key in list(env):
        if key.startswith(
            ("SUPABASE_", "OPENAI_", "BREETH_", "ELEVENLABS_", "DODO_", "N8N_", "RENDER_", "PG")
        ):
            env.pop(key)
    env.update(
        {
            "BEFORETRANSFER_DISABLE_DOTENV": "1",
            "OPENAI_API_KEY": "",
            "OPENAI_MODEL": "",
            "BREETH_API_KEY": "",
            "ELEVENLABS_API_KEY": "",
            "ELEVENLABS_VOICE_ID": "",
            "N8N_WEBHOOK_URL": "",
            "N8N_WEBHOOK_TOKEN": "",
            "N8N_CALLBACK_SECRET": "",
            "DODO_API_KEY": "",
            "DODO_WEBHOOK_SECRET": "",
            "DODO_PRODUCT_ID": "",
            "APP_ENV": "test",
            "DATABASE_URL": state["database_url"],
            "WORKER_DATABASE_URL": state["worker_database_url"],
            "PGSSLMODE": "disable",
            "SUPABASE_URL": identities["identity_origin"],
            "SUPABASE_PUBLISHABLE_KEY": identities["publishable_key"],
            "SUPABASE_SECRET_KEY": identities["storage_key"],
            "SUPABASE_STORAGE_BUCKET": "beforetransfer-evidence",
            "CORS_ORIGINS": identities["frontend_origin"],
            "LOCAL_DEMO_IDENTITY_FILE": str(IDENTITY),
            "PAYMENTS_SANDBOX_URL": "http://127.0.0.1:8001",
            "PAYMENTS_SANDBOX_API_KEY": state["sandbox_api_key"],
            "SANDBOX_APP_ENV": "test",
            "SANDBOX_DATABASE_URL": state["sandbox_database_url"],
            "SANDBOX_API_KEY": state["sandbox_api_key"],
            "SANDBOX_PGSSLMODE": "disable",
            "SANDBOX_LOST_RESPONSE_DELAY_SECONDS": "10",
            "SANDBOX_VISIBILITY_DELAY_SECONDS": "15",
        }
    )
    env.pop("MIGRATION_DATABASE_URL", None)
    env.pop("SANDBOX_MIGRATION_DATABASE_URL", None)
    return env


def checked(command: list[str], env: dict, cwd=ROOT) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode:
        # Migration errors can contain connection context. Keep diagnostics private.
        log = DEMO / "setup-error.log"
        log.write_text(result.stdout + result.stderr)
        log.chmod(0o600)
        raise RuntimeError(f"Local setup failed. Private diagnostics: {log}")


def setup() -> None:
    for name in list(os.environ):
        if name.startswith("PG"):
            os.environ.pop(name)
    admin_url = os.environ.get("LOCAL_TEST_ADMIN_URL", "")
    if not admin_url:
        raise RuntimeError(
            "Set LOCAL_TEST_ADMIN_URL in the environment; never use a production database."
        )
    require_loopback(admin_url)
    state = json.loads(STATE.read_text()) if STATE.exists() else initial_state(admin_url)
    if require_loopback(admin_url) != require_loopback(state["admin_url"]):
        raise RuntimeError("Existing local state belongs to a different test instance.")
    identities = json.loads(IDENTITY.read_text()) if IDENTITY.exists() else initial_identities()
    save_private(STATE, state)
    save_private(IDENTITY, identities)
    with psycopg.connect(state["admin_url"], autocommit=True) as connection:
        for database in (APP_DATABASE, LEDGER_DATABASE):
            if not connection.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
            ).fetchone():
                connection.execute(
                    sql.SQL("CREATE DATABASE {} WITH TEMPLATE template0").format(
                        sql.Identifier(database)
                    )
                )
        for role in state["roles"].values():
            exists = connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (role["name"],)
            ).fetchone()
            if not exists:
                connection.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(role["name"]), sql.Literal(role["password"]))
                )
    env = environment(state, identities)
    checked(
        [str(PYTHON), "-m", "alembic", "upgrade", "head"],
        {**env, "MIGRATION_DATABASE_URL": state["app_admin_url"]},
        ROOT / "backend",
    )
    checked(
        [str(PYTHON), "-m", "sandbox_service.bootstrap"],
        {**env, "SANDBOX_MIGRATION_DATABASE_URL": state["ledger_admin_url"]},
    )
    with psycopg.connect(state["admin_url"], autocommit=True) as connection:
        for role, group in (
            ("api", "beforetransfer_api"),
            ("worker", "beforetransfer_worker"),
            ("sandbox", "beforetransfer_sandbox_api"),
        ):
            connection.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(group), sql.Identifier(state["roles"][role]["name"])
                )
            )
    sys.path.insert(0, str(ROOT / "backend"))
    from app.core.models import Membership, Tenant
    from app.payments.models import Supplier, SupplierIdentity

    engine = create_engine(
        make_url(state["app_admin_url"]).set(drivername="postgresql+psycopg"), hide_parameters=True
    )
    with Session(engine) as session:
        for key, name in (
            ("tenant_id", "Acme Components · Local Sandbox"),
            ("other_tenant_id", "Isolation Test Workspace"),
        ):
            if not session.get(Tenant, UUID(state[key])):
                session.add(Tenant(id=UUID(state[key]), name=name))
        session.flush()
        for actor, role, tenant in (
            ("finance", "finance_admin", "tenant_id"),
            ("supplier", "supplier", "tenant_id"),
            ("outsider", "finance_admin", "other_tenant_id"),
        ):
            user_id = UUID(identities["actors"][actor]["user_id"])
            from sqlalchemy import select

            if not session.scalar(select(Membership).where(Membership.user_id == user_id)):
                session.add(Membership(user_id=user_id, tenant_id=UUID(state[tenant]), role=role))
        supplier_id = UUID(state["supplier_id"])
        if not session.get(Supplier, supplier_id):
            session.add(
                Supplier(
                    id=supplier_id, tenant_id=UUID(state["tenant_id"]), name="Kaveri Packaging"
                )
            )
            session.flush()
            session.add(
                SupplierIdentity(
                    tenant_id=UUID(state["tenant_id"]),
                    supplier_id=supplier_id,
                    user_id=UUID(identities["actors"]["supplier"]["user_id"]),
                )
            )
        session.commit()
    engine.dispose()
    if FRONTEND_ENV.exists() and not FRONTEND_ENV.read_text().startswith(
        "# Generated by scripts/local_demo.py"
    ):
        raise RuntimeError(
            "Existing frontend development environment preserved. Merge local fixture settings explicitly."
        )
    FRONTEND_ENV.write_text(
        "# Generated by scripts/local_demo.py — public synthetic configuration only\n"
        + f"VITE_LOCAL_SANDBOX=true\nVITE_SUPABASE_URL={identities['identity_origin']}\nVITE_SUPABASE_PUBLISHABLE_KEY={identities['publishable_key']}\nVITE_API_BASE_URL=\n"
    )
    FRONTEND_ENV.chmod(0o600)
    print(
        "Synthetic local databases, restricted roles, identities, and environment files prepared."
    )


def seed_http(state: dict, identities: dict) -> None:
    with httpx.Client(timeout=10, trust_env=False) as client:
        session = client.get(
            identities["identity_origin"] + "/local-demo/session", params={"actor": "finance"}
        ).json()
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        response = client.get("http://127.0.0.1:8000/api/suppliers", headers=headers)
        response.raise_for_status()
        supplier = next(
            item for item in response.json()["suppliers"] if item["id"] == state["supplier_id"]
        )
        if supplier["current_beneficiary"] is None:
            response = client.post(
                f"http://127.0.0.1:8000/api/suppliers/{supplier['id']}/beneficiaries",
                headers=headers,
                json={
                    "beneficiary_name": "Kaveri Packaging",
                    "sandbox_account_id": "SIM-KAVERI-001",
                    "expected_version_id": None,
                },
            )
            response.raise_for_status()
        response = client.get("http://127.0.0.1:8000/api/payments", headers=headers)
        response.raise_for_status()
        if not any(
            item["invoice_reference"] == "SYN-2026-001" for item in response.json()["payments"]
        ):
            response = client.post(
                "http://127.0.0.1:8000/api/payments",
                headers=headers,
                json={
                    "supplier_id": state["supplier_id"],
                    "invoice_reference": "SYN-2026-001",
                    "amount_minor": 12500000,
                    "currency": "INR",
                    "simulation": "success",
                },
            )
            response.raise_for_status()


def start() -> None:
    state, identities = json.loads(STATE.read_text()), json.loads(IDENTITY.read_text())
    env = environment(state, identities)
    for port in (8000, 8001, 54330, 5176):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(
                    f"Port {port} is already occupied; preserve the existing process and stop only a known previous PayVigil instance."
                )
    commands = [
        (
            "identity",
            [
                str(PYTHON),
                "-m",
                "uvicorn",
                "local_demo.identity:app",
                "--host",
                "127.0.0.1",
                "--port",
                "54330",
            ],
            ROOT,
        ),
        (
            "sandbox",
            [
                str(PYTHON),
                "-m",
                "uvicorn",
                "sandbox_service.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8001",
            ],
            ROOT,
        ),
        (
            "api",
            [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            ROOT / "backend",
        ),
        ("worker", [str(PYTHON), "-m", "app.payment_worker"], ROOT / "backend"),
        ("frontend", ["npm", "run", "dev"], ROOT / "frontend"),
    ]
    processes, logs = [], []

    def stop_signal(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_signal)
    try:
        for name, command, cwd in commands:
            log_path = DEMO / f"{name}.log"
            log = log_path.open("a")
            log_path.chmod(0o600)
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            )
        deadline = time.monotonic() + 30
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                if any(process.poll() is not None for process in processes):
                    raise RuntimeError("A local process stopped; inspect .local/demo logs.")
                try:
                    if all(
                        client.get(url).status_code == 200
                        for url in (
                            identities["identity_origin"] + "/auth/v1/health",
                            "http://127.0.0.1:8000/api/health",
                            "http://127.0.0.1:8001/health",
                            "http://127.0.0.1:5176",
                        )
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Local services did not become available.")
        seed_http(state, identities)
        print("Local synthetic sandbox running at http://127.0.0.1:5176", flush=True)
        print(
            "Simulated identities and fake INR transfers only. Ctrl+C stops these five processes.",
            flush=True,
        )
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise RuntimeError("A local service stopped; inspect .local/demo logs.")
    except KeyboardInterrupt:
        print("Stopping local synthetic services.")
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        for log in logs:
            log.close()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"setup", "start"}:
        raise SystemExit(__doc__)
    try:
        setup() if sys.argv[1] == "setup" else start()
    except (RuntimeError, KeyError, OSError) as error:
        raise SystemExit(str(error)) from None
