import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from app.core.errors import AppError
from app.integrations.settings import SponsorSettings
from app.integrations import providers as p


class Raw(httpx.AsyncByteStream):
    def __init__(self, value):
        self.value = value

    async def __aiter__(self):
        yield self.value


def response(value, status=200, headers=None):
    return httpx.Response(
        status,
        stream=Raw(json.dumps(value).encode()),
        headers=headers or {"content-type": "application/json"},
    )


def settings(**changes):
    return SponsorSettings(
        _env_file=None,
        n8n_webhook_url="https://workflow.example.invalid/webhook/delivery",
        n8n_webhook_token="synthetic-request-token",
        n8n_callback_secret="synthetic-callback-secret",
        dodo_api_key="synthetic-key",
        dodo_product_id="pdt_test",
        dodo_webhook_secret="whsec_" + base64.b64encode(b"x" * 32).decode(),
        billing_frontend_origin="https://buyer.example.invalid",
        **changes,
    )


@pytest.mark.parametrize("mode", ["hmac", "header"])
def test_n8n_authentication_timestamp_and_body_integrity(mode):
    raw = b'{"delivery_id":"synthetic"}'
    stamp = str(int(time.time()))
    secret = "synthetic-only"
    headers = {
        "x-bt-timestamp": stamp,
        "x-bt-signature": "v1="
        + hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest(),
        "authorization": "Bearer " + secret,
    }
    assert p.verify_n8n(raw, headers, secret, mode)["delivery_id"] == "synthetic"
    broken = {**headers, "x-bt-timestamp": "1"}
    with pytest.raises(AppError):
        p.verify_n8n(raw, broken, secret, mode)
    broken = {**headers, "x-bt-signature": "v1=wrong", "authorization": "Bearer wrong"}
    with pytest.raises(AppError):
        p.verify_n8n(raw, broken, secret, mode)
    if mode == "hmac":
        with pytest.raises(AppError):
            p.verify_n8n(raw + b" ", headers, secret, mode)


def test_dodo_standard_webhook_raw_signature_and_replay_window():
    raw = b'{"type":"subscription.active","data":{}}'
    stamp = str(int(time.time()))
    eid = "msg_synthetic"
    key = b"x" * 32
    signature = base64.b64encode(
        hmac.new(key, eid.encode() + b"." + stamp.encode() + b"." + raw, hashlib.sha256).digest()
    ).decode()
    headers = {
        "webhook-id": eid,
        "webhook-timestamp": stamp,
        "webhook-signature": "v1,old v1," + signature,
    }
    assert p.verify_dodo(raw, headers, "whsec_" + base64.b64encode(key).decode())[0] == eid
    for changed in ({**headers, "webhook-id": "msg_other"}, {**headers, "webhook-timestamp": "1"}):
        with pytest.raises(AppError):
            p.verify_dodo(raw, changed, base64.b64encode(key).decode())
    with pytest.raises(AppError):
        p.verify_dodo(raw + b" ", headers, base64.b64encode(key).decode())


@pytest.mark.parametrize(
    "url",
    [
        "http://checkout.dodopayments.com/a",
        "https://evil.invalid/a",
        "https://checkout.dodopayments.com.evil.invalid/a",
        "https://user@checkout.dodopayments.com/a",
        "https://checkout.dodopayments.com:444/a",
    ],
)
def test_checkout_url_rejects_untrusted_origins(url):
    with pytest.raises(ValueError):
        p.checkout_url(url)


async def test_checkout_fixed_test_origin_server_product_and_return_url():
    operation = uuid4()

    async def handler(request):
        assert request.url == httpx.URL("https://test.dodopayments.com/checkouts")
        assert request.headers["authorization"] == "Bearer synthetic-key"
        assert json.loads(request.content) == {
            "product_cart": [{"product_id": "pdt_test", "quantity": 1}],
            "return_url": "https://buyer.example.invalid/",
            "metadata": {"beforetransfer_operation": str(operation)},
        }
        return response(
            {
                "session_id": "cks_test",
                "checkout_url": "https://test.checkout.dodopayments.com/session/test",
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (await p.create_checkout(client, settings(), operation))["checkout_id"] == "cks_test"


@pytest.mark.parametrize(
    "status,expected",
    [
        ("active", "ACTIVE"),
        ("cancelled", "CANCELLED"),
        ("expired", "EXPIRED"),
        ("on_hold", "FAILED"),
    ],
)
async def test_dodo_authoritative_checkout_payment_subscription_chain(status, expected):
    paths = []

    async def handler(request):
        paths.append(request.url.path)
        assert request.url.host == "test.dodopayments.com"
        values = {
            "/checkouts/cks_test": {
                "id": "cks_test",
                "payment_id": "pay_test",
                "payment_status": "succeeded",
            },
            "/payments/pay_test": {
                "payment_id": "pay_test",
                "status": "succeeded",
                "subscription_ids": ["sub_test"],
                "customer": {"customer_id": "cus_test"},
            },
            "/subscriptions/sub_test": {
                "subscription_id": "sub_test",
                "product_id": "pdt_test",
                "customer": {"customer_id": "cus_test"},
                "status": status,
                "next_billing_date": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            },
        }
        return response(values[request.url.path])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await p.reconcile_billing(
            client,
            settings(),
            {
                "checkout_id": "cks_test",
                "product_id": "pdt_test",
                "customer_id": None,
                "subscription_id": None,
            },
        )
    assert result["status"] == expected
    assert paths == ["/checkouts/cks_test", "/payments/pay_test", "/subscriptions/sub_test"]


async def test_mismatched_binding_cannot_entitle():
    async def handler(request):
        if request.url.path.startswith("/checkouts"):
            return response(
                {"id": "cks_test", "payment_id": "pay_test", "payment_status": "succeeded"}
            )
        if request.url.path.startswith("/payments"):
            return response(
                {
                    "payment_id": "pay_test",
                    "status": "succeeded",
                    "subscription_id": "sub_test",
                    "customer": {"customer_id": "cus_attacker"},
                }
            )
        return response(
            {
                "subscription_id": "sub_test",
                "product_id": "pdt_test",
                "customer": {"customer_id": "cus_test"},
                "status": "active",
                "next_billing_date": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError, match="billing_unavailable"):
            await p.reconcile_billing(
                client,
                settings(),
                {
                    "checkout_id": "cks_test",
                    "product_id": "pdt_test",
                    "customer_id": None,
                    "subscription_id": None,
                },
            )


@pytest.mark.parametrize("kind", ["compressed", "oversize", "redirect"])
async def test_provider_transport_rejects_unbounded_or_redirected_response(kind):
    async def handler(_):
        if kind == "compressed":
            return response({}, headers={"content-encoding": "gzip"})
        if kind == "oversize":
            return httpx.Response(200, stream=Raw(b"x" * 256001))
        return response({}, 302, {"location": "https://evil.invalid"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError):
            await p.create_checkout(client, settings(), uuid4())
