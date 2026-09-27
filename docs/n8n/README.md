# PayVigil supplier inbox delivery with n8n

The importable `supplier-inbox.workflow.json` uses standard Webhook, Code, HTTP
Request and Respond to Webhook nodes. It is prepared for n8n Cloud or self-hosted
n8n. It has not been imported into an account or run against a live provider.
The current local build uses no external delivery and requires no n8n key.

The workflow transports a finance-requested delivery UUID and attempt number to
the application. The application resolves the authenticated supplier assignment
from PostgreSQL and exposes a version-specific inbox request. Neither the
workflow nor its callback can confirm the supplier, accept a beneficiary or
approve/execute a payment. No account numbers, evidence, email addresses or
recipient URLs are sent to n8n.

## Connect an account after credentials are supplied

1. Import the JSON with the workflow inactive. Replace the HTTP Request node's
   fixed `https://YOUR-PAYVIGIL-API.example.invalid` origin with the
   application's reviewed, public HTTPS API origin. Do not derive this URL from
   an incoming payload. Keep TLS verification enabled and redirects disabled.
2. Create two separate **Header Auth** credentials in n8n's credential manager.
   The header name is `Authorization` for both. Set the incoming credential's
   value to `Bearer ` followed by the managed `N8N_WEBHOOK_TOKEN`. Set the
   outgoing callback credential's value to `Bearer ` followed by a different
   managed `N8N_CALLBACK_SECRET`. Do not paste either value into workflow JSON,
   node code, URLs, screenshots or source control. Bind the two placeholder
   credential references to those actual credentials.
3. In the application's server secret manager set `N8N_CALLBACK_AUTH_MODE=header`,
   `N8N_WEBHOOK_TOKEN`, `N8N_CALLBACK_SECRET`, and `N8N_WEBHOOK_URL` using the
   Webhook node's **production** HTTPS URL. The production URL becomes active
   when the workflow is published/activated. n8n Cloud cannot reach a private
   localhost API; this connection belongs to the later hosted verification step.
4. Review the nodes before activation. The Code node validates UUID/attempt,
   creates a stable `delivery_id:attempt` event ID and a fresh timestamp; it has
   no secret or `$env` access. The HTTP Request node sends its credential plus
   that timestamp and the exact JSON body. The application accepts only a
   matching persisted request/attempt and rejects expired timestamps. The
   callback receipt is committed before the webhook response is acknowledged.
5. With a controlled supplier identity, request delivery for the current
   beneficiary version. Check both the n8n execution and authenticated inbox.
   Confirm that an unrelated supplier cannot see it, a duplicate callback has
   one receipt, and changing the beneficiary makes the old request stale.
   Run a reminder after 60 seconds; no more than three total attempts are allowed.
   A current confirmed supplier version cannot receive further requests.

Only `DELIVERED` means the callback committed an inbox receipt. `PENDING` awaits
that callback; `UNKNOWN` means an external outcome could not be established.
Unknown requests are not resent automatically. n8n operators can inspect the
original execution and retry its callback with the same event ID and a fresh
timestamp. A duplicate receipt is acknowledged without another delivery.
`FAILED` is an authenticated terminal delivery failure and can be explicitly
retried subject to the same time/attempt budget. No request is sent merely by
opening the inbox.

Execution saving is disabled in the import template, including failed and manual
executions. Review account-level retention, logs, access and credential handling
before activation; the application does not control those account settings.
No production provider verification is claimed by local transport tests.

## Optional HMAC mode

`N8N_CALLBACK_AUTH_MODE=hmac` accepts `X-BT-Timestamp` plus `X-BT-Signature` equal
to `v1=` and the lowercase SHA-256 HMAC hex digest over the exact bytes
`timestamp + "." + request_body`, keyed by `N8N_CALLBACK_SECRET`. A 300-second
freshness window and persisted event/attempt deduplication also apply.

The supplied Cloud-compatible workflow uses Header Auth and requires no secrets
in Code. HMAC mode needs a reviewed workflow change and supported secure key
access; self-hosted Code-node crypto requires the documented module allowlist.
Do not assume n8n Cloud exposes host environment variables or put a key in Code.
Header mode uses authenticated TLS transport; it is not a body-signature claim.

## Official references checked 2026-09-27

- [Webhook authentication and production URLs](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/)
- [HTTP Request Header Auth credentials](https://docs.n8n.io/integrations/builtin/credentials/httprequest/)
- [HTTP Request body, timeout and redirect options](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/)
- [Self-hosted Code-node module allowlist](https://docs.n8n.io/hosting/configuration/configuration-examples/modules-in-code-node/)
