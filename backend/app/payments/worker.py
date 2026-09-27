"""Persisted outbox worker: uncertain submissions are reconciled, never resubmitted."""

import asyncio
import json
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.database import database_url


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_env: str = "production"
    worker_database_url: SecretStr = SecretStr("")
    pgsslmode: str = "verify-full"
    pgsslrootcert: str = "system"
    payments_sandbox_url: str = ""
    payments_sandbox_api_key: SecretStr = SecretStr("")
    payments_request_timeout_seconds: float = Field(default=3, ge=0.1, le=10)
    payments_poll_seconds: float = Field(default=1, ge=0.1, le=30)

    def sandbox_origin(self) -> str:
        value = self.payments_sandbox_url.strip().rstrip("/")
        try:
            parsed = urlsplit(value)
            _ = parsed.port
            loopback_test = (
                self.app_env == "test"
                and parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            )
            if not (
                parsed.hostname
                and (parsed.scheme == "https" or loopback_test)
                and not parsed.username
                and not parsed.password
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and self.payments_sandbox_api_key.get_secret_value()
            ):
                raise ValueError()
            return value
        except ValueError:
            raise ValueError("A secure sandbox origin and API key are required.") from None


def verified_readback(claim: dict, body: object) -> dict | None:
    """Validate independently read persisted data, including strict JSON value types."""
    if not isinstance(body, dict):
        return None
    snapshot = claim["body"]
    expected_keys = set(snapshot) | {"idempotency_key", "transfer_id", "status"}
    if set(body) != expected_keys or body.get("status") not in ("SUCCEEDED", "FAILED"):
        return None
    if body.get("idempotency_key") != str(claim["execution_id"]):
        return None
    try:
        transfer_id = body["transfer_id"]
        if not isinstance(transfer_id, str) or str(UUID(transfer_id)) != transfer_id:
            return None
        actual = {key: body[key] for key in snapshot}
        if json.dumps(actual, sort_keys=True, separators=(",", ":"), allow_nan=False) != json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ):
            return None
    except (ValueError, TypeError, KeyError):
        return None
    return body


async def reconcile_or_submit(
    client: httpx.AsyncClient, settings: WorkerSettings, claim: dict
) -> dict | None:
    origin = settings.sandbox_origin()
    key = str(UUID(str(claim["execution_id"])))
    headers = {"Authorization": f"Bearer {settings.payments_sandbox_api_key.get_secret_value()}"}
    try:
        if claim["state"] == "SUBMITTING":
            # The core has already committed this stable execution ID and lease.
            response = await client.post(
                f"{origin}/v1/transfers",
                json=claim["body"],
                headers={**headers, "Idempotency-Key": key},
                timeout=settings.payments_request_timeout_seconds,
                follow_redirects=False,
            )
            if response.status_code not in {200, 201}:
                return None
        elif claim["state"] != "UNKNOWN":
            return None
        # An uncertain claim never enters the POST branch, including a previous 404.
        response = await client.get(
            f"{origin}/v1/transfers/by-idempotency/{key}",
            headers=headers,
            timeout=settings.payments_request_timeout_seconds,
            follow_redirects=False,
        )
        if response.status_code != 200:
            return None
        return verified_readback(claim, response.json())
    except (httpx.HTTPError, ValueError, TypeError):
        return None


async def run_once(
    engine: AsyncEngine, client: httpx.AsyncClient, settings: WorkerSettings, worker_id: str
) -> bool:
    # This module owns HTTP orchestration; the core owns transactional authority checks.
    from app.payments.domain import claim_execution, claim_reconciliation, finish_execution

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        claim = await claim_reconciliation(session, worker_id)
    if claim is None:
        async with sessions() as session:
            claim = await claim_execution(session, worker_id)
    if claim is None:
        return False
    readback = await reconcile_or_submit(client, settings, claim)
    async with sessions() as session:
        await finish_execution(
            session,
            UUID(str(claim["execution_id"])),
            UUID(str(claim["lease_token"])),
            readback,
            uncertain=readback is None,
        )
    return True


async def run() -> None:
    settings = WorkerSettings()
    settings.sandbox_origin()
    db_settings = Settings(
        database_url=settings.worker_database_url,
        app_env=settings.app_env,
        pgsslmode=settings.pgsslmode,
        pgsslrootcert=settings.pgsslrootcert,
    )
    engine = create_async_engine(
        database_url(db_settings),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
        hide_parameters=True,
        echo=False,
        connect_args={"prepare_threshold": None},
    )
    worker_id = str(uuid4())
    try:
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            while True:
                try:
                    worked = await run_once(engine, client, settings, worker_id)
                except Exception:
                    # Preserve the committed claim. Expiry can only lead to GET reconciliation.
                    print("payment_worker_cycle_failed", flush=True)
                    worked = False
                if not worked:
                    await asyncio.sleep(settings.payments_poll_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    """Start the payment worker without changing its deployment command."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except Exception:
        raise SystemExit("Payment worker startup failed; check its secure configuration.") from None


if __name__ == "__main__":
    main()
