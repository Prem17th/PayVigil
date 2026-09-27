import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import make_url


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))


def safe_test_url(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.skip("Explicit isolated sandbox PostgreSQL test settings are required.")
    url = make_url(value)
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    assert url.database and url.database.endswith("_test") and "sandbox" in url.database
    assert not set(url.query) - {"sslmode"}
    assert url.query.get("sslmode", "disable") == "disable"
    return value


class RunningSandbox:
    def __init__(self, environment: dict, port: int):
        self.environment = environment
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.process = None

    def start(self):
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "sandbox_service.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--no-access-log",
            ],
            cwd=ROOT,
            env=self.environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError("Sandbox process exited before readiness.")
            try:
                if httpx.get(f"{self.url}/ready", timeout=0.5, trust_env=False).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        self.stop()
        raise AssertionError("Sandbox did not become ready against the isolated database.")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def restart(self):
        self.stop()
        self.start()


@pytest.fixture(scope="session")
def sandbox_server():
    runtime = safe_test_url("SANDBOX_TEST_DATABASE_URL")
    migration = safe_test_url("SANDBOX_TEST_MIGRATION_DATABASE_URL")
    runtime_url, migration_url = make_url(runtime), make_url(migration)
    assert (runtime_url.host, runtime_url.port, runtime_url.database) == (
        migration_url.host,
        migration_url.port,
        migration_url.database,
    )
    assert runtime_url.username != migration_url.username
    environment = os.environ.copy()
    environment.pop("SANDBOX_MIGRATION_DATABASE_URL", None)
    environment.update(
        {
            "SANDBOX_DATABASE_URL": runtime,
            "SANDBOX_API_KEY": secrets.token_urlsafe(32),
            "SANDBOX_APP_ENV": "test",
            "SANDBOX_PGSSLMODE": "disable",
            "SANDBOX_LOST_RESPONSE_DELAY_SECONDS": "0.8",
            "SANDBOX_VISIBILITY_DELAY_SECONDS": "0.6",
        }
    )
    with socket.socket() as temporary:
        temporary.bind(("127.0.0.1", 0))
        port = temporary.getsockname()[1]
    server = RunningSandbox(environment, port)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def headers(sandbox_server):
    return {"Authorization": f"Bearer {sandbox_server.environment['SANDBOX_API_KEY']}"}
