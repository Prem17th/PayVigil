import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text

from app.payment_worker import WorkerSettings, reconcile_or_submit
from sandbox_service.config import SandboxSettings, database_url


def payload(simulation="success"):
    return {
        "payment_id": str(uuid4()),
        "revision_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "invoice_reference": f"INV-{uuid4().hex[:8]}",
        "amount_minor": 125000,
        "currency": "INR",
        "beneficiary_name": "Synthetic Supplier",
        "sandbox_account_id": "SIM-TEST-1001",
        "digest": uuid4().hex + uuid4().hex,
        "simulation": simulation,
    }


def ledger_counts(key):
    settings = SandboxSettings(
        database_url=os.environ["SANDBOX_TEST_DATABASE_URL"],
        app_env="test",
        pgsslmode="disable",
    )
    engine = create_engine(database_url(settings), hide_parameters=True)
    try:
        with engine.connect() as connection:
            return tuple(
                connection.execute(
                    text(
                        f"SELECT count(*) FROM sandbox_ledger.{table} WHERE idempotency_key = :key"
                    ),
                    {"key": key},
                ).scalar_one()
                for table in ("transfers", "debits")
            )
    finally:
        engine.dispose()


def test_concurrent_idempotency_and_restart(sandbox_server, headers):
    key, body = str(uuid4()), payload()
    request_headers = {**headers, "Idempotency-Key": key}

    def submit(_):
        with httpx.Client(trust_env=False, timeout=10) as client:
            response = client.post(
                f"{sandbox_server.url}/v1/transfers", headers=request_headers, json=body
            )
            assert response.status_code == 200
            return response.json()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(submit, range(12)))
    assert all(result == results[0] for result in results)
    assert results[0]["status"] == "SUCCEEDED"
    assert ledger_counts(key) == (1, 1)
    sandbox_server.restart()
    with httpx.Client(trust_env=False) as client:
        readback = client.get(
            f"{sandbox_server.url}/v1/transfers/by-idempotency/{key}", headers=headers
        )
        repeat = client.post(
            f"{sandbox_server.url}/v1/transfers", headers=request_headers, json=body
        )
    assert readback.json() == repeat.json() == results[0]
    assert ledger_counts(key) == (1, 1)


def test_conflicting_payload_and_decline_are_persisted(sandbox_server, headers):
    key, body = str(uuid4()), payload("decline")
    request_headers = {**headers, "Idempotency-Key": key}
    with httpx.Client(trust_env=False) as client:
        declined = client.post(
            f"{sandbox_server.url}/v1/transfers", headers=request_headers, json=body
        )
        conflict = client.post(
            f"{sandbox_server.url}/v1/transfers",
            headers=request_headers,
            json={**body, "amount_minor": 500},
        )
        readback = client.get(
            f"{sandbox_server.url}/v1/transfers/by-idempotency/{key}", headers=headers
        )
    assert declined.status_code == 200 and declined.json()["status"] == "FAILED"
    assert conflict.status_code == 409
    assert readback.json() == declined.json()
    assert ledger_counts(key) == (1, 0)


def test_auth_and_real_destination_rejected(sandbox_server, headers):
    key, body = str(uuid4()), payload()
    with httpx.Client(trust_env=False) as client:
        assert (
            client.post(
                f"{sandbox_server.url}/v1/transfers", headers={"Idempotency-Key": key}, json=body
            ).status_code
            == 401
        )
        assert (
            client.get(f"{sandbox_server.url}/v1/transfers/by-idempotency/{key}").status_code == 401
        )
        response = client.post(
            f"{sandbox_server.url}/v1/transfers",
            headers={**headers, "Idempotency-Key": key},
            json={**body, "sandbox_account_id": "REAL-ACCOUNT-NOT-ACCEPTED"},
        )
        assert response.status_code == 422
    assert ledger_counts(key) == (0, 0)


def test_lost_response_worker_readback_survives_restart(sandbox_server):
    key, body = str(uuid4()), payload("lost_response")
    settings = WorkerSettings(
        app_env="test",
        payments_sandbox_url=sandbox_server.url,
        payments_sandbox_api_key=sandbox_server.environment["SANDBOX_API_KEY"],
        payments_request_timeout_seconds=0.1,
    )
    claim = {"execution_id": key, "body": body, "state": "SUBMITTING"}

    async def process(current):
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            return await reconcile_or_submit(client, settings, current)

    assert asyncio.run(process(claim)) is None
    assert ledger_counts(key) == (1, 1)
    claim["state"] = "UNKNOWN"
    assert asyncio.run(process(claim)) is None
    sandbox_server.restart()
    deadline = time.monotonic() + 3
    result = None
    while result is None and time.monotonic() < deadline:
        result = asyncio.run(process(claim))
        if result is None:
            time.sleep(0.1)
    assert result is not None and result["status"] == "SUCCEEDED"
    assert ledger_counts(key) == (1, 1)


def test_runtime_cannot_change_or_delete_ledger(sandbox_server):
    settings = SandboxSettings(
        database_url=os.environ["SANDBOX_TEST_DATABASE_URL"], app_env="test", pgsslmode="disable"
    )
    engine = create_engine(database_url(settings), hide_parameters=True)
    try:
        from sqlalchemy.exc import DBAPIError

        for statement in (
            "UPDATE sandbox_ledger.transfers SET status = 'FAILED' WHERE false",
            "DELETE FROM sandbox_ledger.debits WHERE false",
            "CREATE TABLE sandbox_ledger.forbidden (id int)",
        ):
            with engine.begin() as connection:
                with pytest.raises(DBAPIError):
                    connection.execute(text(statement))
    finally:
        engine.dispose()
