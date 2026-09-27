# Phase 5 — controlled supplier inbox delivery

The local n8n adapter, durable receipts, authenticated callbacks, assigned supplier
inbox and bounded reminders are implemented. Live n8n Cloud import, credential
binding and provider execution remain pending credentials and hosted endpoints.
No external delivery occurred during this build.

## Implemented behavior

Finance selects an existing supplier's current beneficiary version. The server
resolves the assigned supplier identity and persists a delivery receipt before
calling the configured n8n webhook. The outbound payload contains only a UUID
and attempt number. Callbacks only affect delivery state; they cannot confirm a
supplier or change payment authority. Supplier reads use the existing verified
identity, membership and tenant RLS plus the supplier assignment.

The Cloud-compatible import workflow uses separate managed Header Auth
credentials for inbound requests and outbound callbacks. HTTPS, a five-minute
timestamp window, event-ID/body-digest matching and persisted version/attempt
checks protect callback processing. Optional HMAC authentication remains
available. Header mode is authenticated transport, not a body-signature claim.
A narrow PostgreSQL SECURITY DEFINER callback function has a fixed search path;
browser roles cannot invoke it or access the receipt tables. The runtime role
cannot inherit the function/table owner's authority.

A completed callback exposes the inbox item. Current unconfirmed delivered
requests may receive at most three total attempts, at least 60 seconds apart.
An authenticated FAILED receipt may be explicitly retried against the same
version and receipt ID under that same 60-second/three-attempt budget.
Stale beneficiary versions, old callbacks and confirmed versions cannot create
fresh confirmation authority. Provider uncertainty remains UNKNOWN without
another automatic POST. A callback that committed during a lost HTTP response
wins over the caller's stale in-memory state.

## Verification

The combined sponsor test run completed **67 tests**: 17 provider/signature tests,
9 real PostgreSQL receipt/authority tests, and 41 voice adapter tests. Delivery
coverage includes five concurrent requests producing one provider call, callback
replay/conflicting replay, cross-tenant and assigned inbox reads, no confirmation
or approval created by delivery, callback-versus-timeout overlap, version
staleness, old-attempt callbacks, the three-attempt reminder budget and an
explicit FAILED retry that preserves its original receipt and cannot duplicate
a pending attempt.

MockTransport verifies fixed request fields and bounded streaming; database
checks use a separate loopback `*_test` database and restricted runtime roles.
These results establish local behavior, not n8n account availability. The
workflow JSON is importable configuration prepared from official node contracts;
its live import and execution have not been performed.

## Files and remaining provider check

`docs/n8n/README.md` supplies credential-binding and verification instructions;
`docs/n8n/supplier-inbox.workflow.json` contains no secrets. Before enabling live
delivery, bind the two credentials, set the reviewed public HTTPS callback
origin, import/inspect the inactive workflow, and verify one controlled delivery,
a duplicate callback, wrong-supplier isolation and a stale version.

References checked 2026-09-27:
[Webhook](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/),
[Header Auth](https://docs.n8n.io/integrations/builtin/credentials/httprequest/),
[HTTP Request](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/).
