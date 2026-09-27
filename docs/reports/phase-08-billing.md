# Phase 8 — Dodo test subscription and evidence export

The local test-mode Dodo checkout, verified webhook processing, reconciliation,
entitlement gate and downloadable evidence report are implemented. No real Dodo
checkout, subscription, webhook or charge was performed; account credentials and
live test-provider verification remain outstanding.

## Implemented behavior

Only finance users can request checkout. The server selects the configured test
subscription product, quantity one and exact configured frontend return origin.
All Dodo calls use the fixed `https://test.dodopayments.com` origin. Checkout
responses must contain the documented session ID and an HTTPS checkout URL on
the explicit Dodo hostname allowlist; redirects and oversized/compressed provider
responses are rejected. A durable operation exists before the provider POST.
An unknown creation outcome cannot trigger another automatic checkout.

Entitlement is derived from independent GETs of the stored checkout, its payment
and its subscription. Their payment, customer, subscription and product IDs must
agree. The subscription must be active with a future billing date. The last
verified status expires after five minutes; report export then requires
reconciliation. Payment review and all safety controls remain available without
a subscription. Dodo never receives supplier funds or payment instructions.

Webhooks verify Standard Webhooks signatures against exact raw bytes, event ID
and timestamp, including the five-minute freshness window. PostgreSQL stores
received event IDs and body digests once. Provider metadata is only a routing
hint to an existing operation; an event stating `active` cannot grant access.
The handler reads the authoritative stored checkout chain before changing
entitlement. Reconciliation tokens prevent an older active response from
replacing a newer cancellation. Previously bound customer/subscription IDs
cannot silently change. Browser roles cannot call the narrow callback functions
or access private sponsor tables.

`GET /api/payments/{id}/report` enforces tenant and finance authority plus a fresh
entitlement before exporting JSON with the payment, supplier, evidence hashes,
investigations and generation time. Private storage paths and provider credentials
are absent. Browser return parameters have no entitlement authority.

## Verification

The combined sponsor test run completed **67 tests**: 17 provider/signature tests,
9 real PostgreSQL receipt/authority tests, and 41 voice adapter tests. Billing
checks cover the exact test checkout payload, fixed origins, malicious checkout
URLs, authoritative checkout/payment/subscription chain, mismatched customer
binding, active/cancelled/expired/on-hold statuses, raw signature tampering,
stale timestamps, replay/conflicting replay, cross-tenant reads, lost checkout
responses, five-minute expiry and server-side report denial. A controlled overlap
proves an older ACTIVE response cannot overwrite a newer CANCELLED state.

MockTransport is injected only in tests. Database checks use isolated local
PostgreSQL and restricted roles. Configuration presence is not provider
verification; the UI reports unconfigured integrations honestly.

## Connect and verify later

Set managed `DODO_API_KEY`, `DODO_PRODUCT_ID`, `DODO_WEBHOOK_SECRET` and
`BILLING_FRONTEND_ORIGIN` for the selected Dodo test account. The product must be
a recurring subscription; a one-time product cannot satisfy the subscription
readback gate. Configure the HTTPS webhook endpoint at
`/api/integrations/dodo/webhook` using that endpoint's Standard Webhooks secret.
The first binding can also be established through the authenticated Reconcile
control if an initial webhook has no matching operation metadata.

Create one controlled test checkout, complete it using Dodo's test flow, reconcile
it, and verify entitlement/report access. Then test cancellation, replay and
expired verification. An uncertain checkout POST with no stored session ID
requires operator investigation in the provider account; the application does
not guess a replacement session or automatically repeat the purchase request.
Use managed secrets and account permissions, with no credentials in source or
workflow exports. No paid plan or credits were assumed or purchased.

## Primary references checked 2026-09-27

- [Create checkout — POST /checkouts, session_id response](https://docs.dodopayments.com/api-reference/checkout-sessions/create)
- [Retrieve checkout — id and payment_id response](https://docs.dodopayments.com/api-reference/checkout-sessions/get-checkouts)
- [Payment detail — customer and subscription binding](https://docs.dodopayments.com/api-reference/payments/get-payments-1)
- [Subscription detail — product, status and next billing date](https://docs.dodopayments.com/api-reference/subscriptions/get-subscriptions)
- [Webhook raw-body verification and delivery behavior](https://docs.dodopayments.com/developer-resources/webhooks)
