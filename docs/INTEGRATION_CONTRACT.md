# Remaining build contract — phases 4–9

User authorises all local implementation now and supplies credentials later.
Real adapters must fail clearly when unconfigured. Fixture/test results do not
establish real-provider verification. No external messaging is performed during
this build. Existing phase 3 financial authority remains authoritative.

## Shared implementation

- Finance-only integration routes use trusted Principal and tenant RLS.
- JSON field names are snake_case. UUIDs are strings and times are ISO8601.
- Configuration uses separate BaseSettings modules where useful to avoid edit
  conflicts; secrets are SecretStr. Production URLs are fixed official endpoints
  or validated HTTPS configuration; tests inject transports, not unsafe live URLs.
- Model, memory, voice, billing and delivery have no transfer or approval tools.
- Persist operations before provider calls. Do not blindly repeat uncertain
  non-idempotent provider writes. Use bounded timeouts, sizes and call budgets.
- Text from documents and providers is untrusted. Escape in React and never
  render supplied HTML. Provider errors and audit records must not leak secrets.
- Core agent owns evidence/memory modules and migration 0003. Sponsor agent owns
  delivery/voice/billing modules and migration 0004 (down_revision=0003).
- Root integrates routers/version/readiness, environment docs, CI and deployment.

## Evidence and investigation (phase 4)

Evidence belongs to a payment and immutable revision. Accept bounded UTF-8 text,
text PDFs and images if a verified model vision path is implemented; explicitly
reject unsupported/scanned formats rather than invent extracted content. Store
original bytes privately in Supabase; database stores content hash, source name,
bounded extracted text/page references, upload actor and timestamp. Source names
are display metadata, never object paths. No document-supplied recipient routing.

GET `/api/payments/{payment_id}/evidence` -> `{documents:[...]}`.
POST same path JSON `{revision_id,filename,media_type,content_base64}` -> document.
GET `/api/evidence/{document_id}/content` -> authenticated original bytes.
GET `/api/payments/{payment_id}/investigations` -> `{investigations:[...]}`.
POST same path `{revision_id}` -> persisted investigation with bounded tool trace.
POST `/api/investigations/{id}/reviews` `{acknowledged:true,note}` -> investigation.

Document: `{id,payment_id,revision_id,filename,media_type,sha256,created_at,
extracted_text,extraction_status}`. Investigation: `{id,payment_id,revision_id,
status,summary,findings:[{severity,code,explanation,citations:[{document_id,quote,
page}]}],tool_trace:[{tool,status}],review:{reviewed_at,note}|null,created_at,
provider,advisory:true}`. Extend shape only after informing frontend.

OpenAI Responses agent chooses from read-only case snapshot, document search,
document read, prior-case memory, deterministic comparison tools. Server supplies
case scope, no caller-selected tenant IDs, no SQL/general network tools. Bound
iterations/tool calls/output size; strict JSON result validation; reject citations
unless quote actually exists in that case's source. Missing/contradictory fields
remain findings, not accepted financial details. No autonomous approval.

Once evidence exists on a payment, approval/queue must require current evidence
review across its revisions. Adding evidence invalidates a previous review/approval by a deterministic
evidence snapshot/version binding. Lock supplier/payment consistently with queue;
reject evidence mutations after execution is queued. A stale result cannot clear
a hold. Human review is an acknowledgement, not bank ownership verification.

## Breeth advisory memory (phase 6)

Verified PyPI package `breeth==0.1.0`, AsyncBreethClient.write/retrieve,
https://docs.thebreeth.com/docs/sdks/python. Cached docs `.local/breeth-sdk-doc.html`.
Server selects opaque tenant group, redacts personal/bank/account/contact details,
stores only reviewed redacted case context, and persists provenance in PostgreSQL.
POST `/api/investigations/{id}/memory` -> `{status,operation_id,advisory:true}`.
GET `/api/payments/{id}/memory` -> `{items:[{text,source,advisory:true}]}`.
Memory has no power to replace any accepted financial field or current evidence.

## Delivery (phase 5)

Use n8n to deliver finance-approved version-specific confirmation requests into
the assigned supplier's authenticated in-app inbox. This avoids requiring an
email account; request routing comes from SupplierIdentity in the database.
GET `/api/suppliers/{id}/deliveries` -> `{deliveries:[...]}`.
POST same path `{beneficiary_version_id}` -> delivery.
POST `/api/deliveries/{id}/reminders` `{}` -> delivery, rate/attempt bounded.
POST `/api/integrations/n8n/callback` authenticated callback for delivery
status only; cannot confirm a supplier, accept a destination or approve payment.
The Cloud workflow uses a separate Header Auth credential over HTTPS and a fresh
timestamp; optional HMAC mode also signs the raw body. Persisted event/attempt
checks apply in both modes.
GET `/api/supplier/inbox` -> `{deliveries:[...]}` only assigned current user.
Delivery `{id,supplier_id,beneficiary_version_id,status,created_at,delivered_at,
attempts}`. Stable request ID, duplicate callback handling and stale version
handling. Include importable n8n workflow JSON with environment/credential refs.
No supplied external URL/email accepted from browser or evidence. Real n8n
execution pending credentials; transport mock proves contract locally only.

## Voice (phase 7)

POST `/api/investigations/{id}/audio` `{}` -> audio/mpeg bytes; frontend Blob URL
revoked on replacement/unmount. Redacted reviewed case summary only; fixed stock
voice configured via ELEVENLABS_VOICE_ID. Bound text/audio sizes and timeout.
No voice identity, cloning, consent inference, beneficiary or payment approvals.

## Dodo billing (phase 8)

Test-mode subscription checkout with configured DODO_PRODUCT_ID only. Return URL
comes from configured exact frontend origin; no browser-supplied destination.
GET `/api/billing` -> `{mode:"test",configured,entitled,status,expires_at}`.
POST `/api/billing/checkout` `{}` -> `{checkout_url,checkout_id}`.
POST `/api/billing/reconcile` `{}` -> billing view.
POST `/api/integrations/dodo/webhook` verifies Standard Webhooks raw body
signature/time, stores event IDs once, reconciles authoritative provider status.
GET `/api/payments/{id}/report` -> downloadable JSON evidence report, entitlement
checked server-side; payment and safety controls always available without billing.
No browser return parameter, arbitrary metadata or unverified event enables
entitlement. Bind checkout/customer/subscription IDs to tenant in PostgreSQL.
Provider status must expire/recheck; out-of-order events cannot restore cancelled
subscription. Dodo never handles supplier funds. Real test checkout pending keys.

## Integration status and local demo

Root will expose GET `/api/integrations` (finance-only) with configuration-presence
indicators and explicit `live_verified:false` unless persisted actual evidence is
implemented. Presence does not imply successful provider authentication.
Local identity/storage/payment simulators stay clearly labelled. Unit provider
transports are test code. Do not silently make unconfigured production adapters
return successful fake investigations, delivery, memory, voice or entitlements.
