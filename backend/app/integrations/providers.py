import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from app.core.errors import AppError
from app.integrations.settings import SponsorSettings


def unavailable(provider: str):
    return AppError(
        503,
        f"{provider}_unavailable",
        f"{provider} could not be verified. No automatic retry was made.",
    )


async def bounded_json(client, method, url, *, headers, body=None):
    async with asyncio.timeout(20):
        async with client.stream(
            method,
            url,
            headers={**headers, "Accept-Encoding": "identity"},
            json=body,
            timeout=15,
            follow_redirects=False,
        ) as response:
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("compressed response rejected")
            data = bytearray()
            async for chunk in response.aiter_raw():
                if len(data) + len(chunk) > 256_000:
                    raise ValueError("response too large")
                data.extend(chunk)
            if response.status_code not in {200, 201, 202}:
                raise ValueError("provider did not succeed")
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("invalid response")
            return value


async def deliver(client, settings: SponsorSettings, delivery_id, attempt):
    if not settings.n8n_configured:
        raise AppError(503, "n8n_not_configured", "n8n delivery is not configured.")
    try:
        await bounded_json(
            client,
            "POST",
            settings.n8n_webhook_url,
            headers={"Authorization": f"Bearer {settings.n8n_webhook_token.get_secret_value()}"},
            body={"delivery_id": str(delivery_id), "attempt": attempt},
        )
    except (httpx.HTTPError, ValueError, TimeoutError):
        raise unavailable("n8n") from None


def verify_n8n(raw: bytes, headers, secret: str, mode: str = "hmac") -> dict:
    if not secret:
        raise AppError(503, "n8n_not_configured", "n8n callbacks are not configured.")
    try:
        stamp = headers.get("x-bt-timestamp", "")
        if abs(time.time() - int(stamp)) > 300:
            raise ValueError()
        expected = hmac.new(
            secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256
        ).hexdigest()
        if mode == "header":
            valid = hmac.compare_digest(headers.get("authorization", ""), "Bearer " + secret)
        else:
            valid = mode == "hmac" and hmac.compare_digest(
                headers.get("x-bt-signature", ""), "v1=" + expected
            )
        if not valid:
            raise ValueError()
        return json.loads(raw)
    except (ValueError, TypeError, OverflowError):
        raise AppError(
            401, "invalid_callback", "The delivery callback could not be authenticated."
        ) from None


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value):
        raise ValueError("invalid provider identifier")
    return value


async def dodo_json(client, settings, method, path, body=None):
    return await bounded_json(
        client,
        method,
        f"https://test.dodopayments.com{path}",
        headers={"Authorization": f"Bearer {settings.dodo_api_key.get_secret_value()}"},
        body=body,
    )


def checkout_url(value):
    parsed = urlsplit(value)
    if not (
        parsed.scheme == "https"
        and parsed.hostname in {"checkout.dodopayments.com", "test.checkout.dodopayments.com"}
        and parsed.port in {None, 443}
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
    ):
        raise ValueError("invalid checkout URL")
    return value


async def create_checkout(client, settings, operation_id):
    try:
        body = await dodo_json(
            client,
            settings,
            "POST",
            "/checkouts",
            {
                "product_cart": [{"product_id": settings.dodo_product_id, "quantity": 1}],
                "return_url": settings.billing_frontend_origin.rstrip("/") + "/",
                "metadata": {"beforetransfer_operation": str(operation_id)},
            },
        )
        return {
            "checkout_id": identifier(body["session_id"]),
            "checkout_url": checkout_url(body["checkout_url"]),
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError, TimeoutError):
        raise unavailable("billing") from None


async def reconcile_billing(client, settings, context):
    try:
        async with asyncio.timeout(35):
            return await _reconcile_billing(client, settings, context)
    except TimeoutError:
        raise unavailable("billing") from None


async def _reconcile_billing(client, settings, context):
    try:
        checkout = await dodo_json(
            client, settings, "GET", "/checkouts/" + identifier(context["checkout_id"])
        )
        if checkout.get("id") != context["checkout_id"]:
            raise ValueError()
        payment_id = checkout.get("payment_id")
        if not payment_id or checkout.get("payment_status") != "succeeded":
            return {
                "status": "FAILED"
                if checkout.get("payment_status") in {"failed", "cancelled"}
                else "CHECKOUT_PENDING",
                "customer_id": None,
                "subscription_id": None,
                "expires_at": None,
            }
        payment = await dodo_json(client, settings, "GET", "/payments/" + identifier(payment_id))
        if payment.get("payment_id") != payment_id or payment.get("status") != "succeeded":
            raise ValueError()
        subscriptions = payment.get("subscription_ids") or [payment.get("subscription_id")]
        if len(subscriptions) != 1:
            raise ValueError()
        subscription_id = identifier(subscriptions[0])
        subscription = await dodo_json(client, settings, "GET", "/subscriptions/" + subscription_id)
        customer_id = identifier(subscription["customer"]["customer_id"])
        if (
            subscription.get("subscription_id") != subscription_id
            or subscription.get("product_id") != context["product_id"]
            or payment.get("customer", {}).get("customer_id") != customer_id
            or context.get("customer_id") not in {None, customer_id}
            or context.get("subscription_id") not in {None, subscription_id}
        ):
            raise ValueError()
        status = subscription.get("status")
        expiry = datetime.fromisoformat(subscription["next_billing_date"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError()
        mapped = (
            "ACTIVE"
            if status == "active" and expiry > datetime.now(timezone.utc)
            else (
                "CANCELLED"
                if status == "cancelled"
                else "EXPIRED"
                if status == "expired" or expiry <= datetime.now(timezone.utc)
                else "FAILED"
            )
        )
        return {
            "status": mapped,
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "expires_at": expiry.isoformat() if mapped == "ACTIVE" else None,
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, TimeoutError):
        raise unavailable("billing") from None


def verify_dodo(raw: bytes, headers, secret: str) -> tuple[str, dict]:
    if not secret:
        raise AppError(503, "billing_not_configured", "Dodo webhooks are not configured.")
    try:
        event_id = identifier(headers.get("webhook-id", ""))
        stamp = headers.get("webhook-timestamp", "")
        if abs(time.time() - int(stamp)) > 300:
            raise ValueError()
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
        if len(key) < 16:
            raise ValueError()
        expected = base64.b64encode(
            hmac.new(
                key, event_id.encode() + b"." + stamp.encode() + b"." + raw, hashlib.sha256
            ).digest()
        ).decode()
        valid = any(
            hmac.compare_digest(part, "v1," + expected)
            for part in headers.get("webhook-signature", "").split()
        )
        if not valid:
            raise ValueError()
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError()
        return event_id, body
    except (ValueError, TypeError, OverflowError):
        raise AppError(
            401, "invalid_webhook", "The billing webhook could not be authenticated."
        ) from None
