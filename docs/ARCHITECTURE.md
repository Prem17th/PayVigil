# PayVigil architecture

## Product boundary

PayVigil helps a finance team investigate invoice and supplier-payment changes.
The model interprets evidence and produces source-backed findings. Authenticated
people confirm instructions, accept beneficiary versions and approve exact
payment revisions. Deterministic application and database rules enforce those
permissions. The transfer integration is an explicitly synthetic sandbox.

## Backend organization

| Package | Responsibility | Key boundaries |
| --- | --- | --- |
| `app.core` | Environment configuration, verified identity, tenant membership, database access, request limits, private storage and error handling | No browser-selected tenant or role; secret settings stay server-side |
| `app.payments` | Supplier/beneficiary versions, payment revisions, confirmations, approval, audit, outbox and worker | Material changes require fresh approval; uncertain execution blocks replacement |
| `app.evidence` | Private evidence ingestion, protected extraction, citation validation, bounded investigation tools and advisory memory access | Documents are untrusted input; tools cannot mutate payment authority |
| `app.integrations` | Approved confirmation delivery, redacted voice explanations, subscription entitlements and provider status | Callbacks have narrow authority; billing cannot approve or execute transfers |
| `app.main` | Application factory, lifecycle, routes, CORS and shared HTTP safeguards | Composition only; stable ASGI entrypoint `app.main:app` |

Each domain keeps routes, request/response schemas, persistence models and domain
logic together. Provider adapters own network timeouts, accepted endpoints and
response validation. Shared primitives belong in `core`; business rules belong
in their domain rather than generic utility modules.

The payment worker implementation is `app.payments.worker`; `app.payment_worker`
remains a compatibility entrypoint for existing runtime commands. The independent
`sandbox_service` owns its own database role and ledger. It cannot share the
application API's database identity.

## Request and execution flow

1. Supabase Auth establishes identity. FastAPI verifies the bearer token and
   resolves membership from PostgreSQL; token metadata does not grant roles.
2. Database work receives a server-selected tenant scope. Application tables use
   enabled and forced row-level security, with restricted API/worker roles.
3. Evidence uploads and access are authenticated. Source originals remain in a
   private storage bucket; extraction is bounded and provider content is escaped.
4. The investigation agent receives a fixed tool set and bounded execution.
   It compares evidence and records findings with validated source references.
5. Supplier confirmation, finance acceptance and payment approval are separate
   persisted actions. Confirmation is not bank-account ownership verification.
6. Approval binds to the exact payment snapshot. The transactional outbox lets a
   restricted worker execute an approved synthetic transfer with idempotency.
7. The worker reads the independent ledger to establish the outcome. An uncertain
   submission cannot authorize another payment attempt with a new identity.

## Integration authority

- **OpenAI:** bounded evidence investigation with read-only tools.
- **Breeth:** redacted, tenant-scoped advisory context. Current PostgreSQL state
  remains authoritative even when memory differs.
- **n8n:** delivery of finance-approved requests into assigned supplier inboxes.
  An authenticated callback reports delivery; it cannot confirm supplier details.
- **ElevenLabs:** spoken redacted explanations. Audio grants neither identity nor
  payment authority. Current default-voice compatibility needs live validation.
- **Dodo:** test-mode subscriptions and report entitlements. Payment-provider
  callbacks never grant supplier-payment authority.

## Deployment and configuration

The frontend, API, worker and independent sandbox are separate Render services.
Render PostgreSQL stores application and separate-ledger data. Supabase supplies
Auth and private Storage. Migration credentials are distinct from runtime roles;
release tooling forwards only each service's allowed environment variables.
The operator's combined secret file never belongs on a deployed service.

The frontend is built with public configuration only. Local synthetic identity
and storage services live outside production packages, bind to loopback and have
explicit development guards. Render does not deploy `local_demo`.

## Verification and change discipline

- Keep API paths, approval fingerprints, SQL permissions and persisted identifiers
  stable unless a reviewed change explicitly migrates their contract.
- Add schema changes through Alembic and verify them against disposable
  PostgreSQL, including existing-role and managed-owner behavior.
- Test domain decisions, tenant isolation, retries, duplicate callbacks and
  uncertain outcomes; a mocked provider test does not establish live access.
- Run the full CI gate, secret scan and explicit hosted/provider checks before
  claiming a production release. Keep automatic deployment disabled until the
  selected release commit and managed configuration have been reviewed.

See [deployment](DEPLOYMENT.md), [payment authority](PHASE3_CONTRACT.md) and
[integration contracts](INTEGRATION_CONTRACT.md) for operational details.
