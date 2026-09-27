from uuid import uuid4

import httpx
import pytest

from app.payments.worker import WorkerSettings, reconcile_or_submit, verified_readback


def claim():
    return {
        "execution_id": str(uuid4()),
        "lease_token": str(uuid4()),
        "state": "SUBMITTING",
        "body": {
            "payment_id": str(uuid4()),
            "revision_id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "invoice_reference": "INV-100",
            "amount_minor": 100,
            "currency": "INR",
            "beneficiary_name": "Synthetic Supplier",
            "sandbox_account_id": "SIM-TEST-100",
            "digest": "a" * 64,
            "simulation": "success",
        },
    }


def settings():
    import secrets

    return WorkerSettings(
        payments_sandbox_url="https://sandbox.example.invalid",
        payments_sandbox_api_key=secrets.token_urlsafe(32),
    )


def result(current):
    return {
        **current["body"],
        "idempotency_key": current["execution_id"],
        "transfer_id": str(uuid4()),
        "status": "SUCCEEDED",
    }


@pytest.mark.asyncio
async def test_successful_post_is_not_accepted_without_independent_readback():
    current, methods = claim(), []

    def handle(request):
        methods.append(request.method)
        return (
            httpx.Response(200, json=result(current))
            if request.method == "POST"
            else httpx.Response(404)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await reconcile_or_submit(client, settings(), current) is None
    assert methods == ["POST", "GET"]


@pytest.mark.asyncio
async def test_unknown_and_repeated_not_found_never_resubmit():
    current, methods = claim(), []
    current["state"] = "UNKNOWN"

    def handle(request):
        methods.append(request.method)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        for _ in range(3):
            assert await reconcile_or_submit(client, settings(), current) is None
    assert methods == ["GET", "GET", "GET"]


@pytest.mark.asyncio
async def test_transport_timeout_and_redirect_stay_uncertain():
    current = claim()
    for status in (302, 409, 500):
        methods = []

        def handle(request):
            methods.append(request.method)
            return httpx.Response(status, headers={"Location": "https://other.example.invalid"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), follow_redirects=True
        ) as client:
            assert await reconcile_or_submit(client, settings(), current) is None
        assert methods == ["POST"]

    def timeout(request):
        raise httpx.ReadTimeout("test timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        assert await reconcile_or_submit(client, settings(), current) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_minor", 101),
        ("amount_minor", 100.0),
        ("amount_minor", True),
        ("currency", "USD"),
        ("sandbox_account_id", "SIM-OTHER-123"),
        ("digest", "b" * 64),
        ("status", "PENDING"),
        ("transfer_id", "invalid"),
        ("idempotency_key", str(uuid4())),
    ],
)
def test_readback_must_match_exact_approved_snapshot(field, value):
    current = claim()
    response = result(current)
    assert verified_readback(current, response) is response
    response[field] = value
    assert verified_readback(current, response) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid",
        "https://user:password@example.invalid",
        "https://example.invalid/redirect",
        "https://example.invalid?secret=value",
    ],
)
def test_worker_rejects_unsafe_origins(url):
    configured = settings()
    configured.payments_sandbox_url = url
    with pytest.raises(ValueError, match="secure sandbox origin"):
        configured.sandbox_origin()


def test_loopback_http_requires_explicit_test_environment():
    configured = settings()
    configured.payments_sandbox_url = "http://127.0.0.1:8001"
    with pytest.raises(ValueError):
        configured.sandbox_origin()
    configured.app_env = "test"
    assert configured.sandbox_origin() == "http://127.0.0.1:8001"
