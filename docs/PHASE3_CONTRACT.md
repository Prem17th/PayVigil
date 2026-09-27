# Phase 3 implementation contract

Local implementation only. No real funds, sponsor calls, production deployment,
or Phase 4 document/agent work. Preserve Phase 2 authentication and secret rules.

## Authority and invariants

- Supplier confirmation, finance acceptance of a beneficiary version, and human
  approval of an exact payment revision are separate immutable records.
- A supplier identity is explicitly assigned to a supplier in the database.
  Tenant membership alone must not let it confirm another supplier's details.
- Beneficiary and payment revisions are immutable. Amount, supplier, destination,
  currency, invoice, and simulation scenario form the server's approval digest.
- Use integer paise and INR only. Only synthetic destination IDs beginning
  `SIM-` are accepted. Never accept a real bank account for execution.
- Approval requires the current beneficiary version to be confirmed and accepted.
  Changing the beneficiary or payment makes old approvals unusable. Expired
  approvals also fail closed. UI sends the exact revision ID and digest reviewed.
- Queueing and outbox creation are atomic. Concurrent or repeated queue calls
  create one execution. Persist a stable execution/idempotency ID before HTTP.
- Lock in a consistent order (supplier, payment) for changes, approval, queue,
  and dispatch. Recheck all conditions before dispatch. Do not permit changes
  while execution is SUBMITTING, UNKNOWN, or SUCCEEDED.
- A lost response is UNKNOWN. Reconcile by independent HTTP readback of the
  persisted idempotency ID; never create a new transfer or release the invoice
  on an uncertain result. NOT_FOUND is not proof that money did not move.
- Verify readback status and exact approved fields before SUCCEEDED. Conflicting
  readback stays UNKNOWN. Terminal sandbox rejection is FAILED and never retried
  automatically. One payment intent per tenant/supplier/canonical invoice ref.
- API and worker use restricted database roles, tenant isolation, immutable
  history, and append-only audit events. No user-selected role or tenant scope.

## API contract (backend owner publishes exact JSON examples promptly)

- `GET /api/suppliers` -> `{suppliers: SupplierView[]}`.
- `POST /api/suppliers` -> SupplierView. Body `{name}`.
- `POST /api/suppliers/{id}/beneficiaries` -> SupplierView. Body
  `{beneficiary_name, sandbox_account_id, expected_version_id: UUID|null}`.
- `POST /api/suppliers/{id}/confirmations` -> SupplierView. Supplier-only,
  assigned identity; body `{beneficiary_version_id}`.
- `POST /api/suppliers/{id}/acceptances` -> SupplierView. Finance-only;
  body `{beneficiary_version_id}`. Requires matching supplier confirmation.
- `GET /api/payments` -> `{payments: PaymentView[]}`; finance-only.
- `GET /api/payments/{id}` -> PaymentView; finance-only.
- `POST /api/payments` -> PaymentView. Body `{supplier_id, invoice_reference,
  amount_minor, currency: 'INR', simulation: 'success'|'decline'|'lost_response'}`.
- `POST /api/payments/{id}/revisions` -> PaymentView. Body
  `{expected_revision_id, amount_minor, simulation}`; adopts current beneficiary.
- `POST /api/payments/{id}/approvals` -> PaymentView. Body
  `{revision_id, digest}`.
- `POST /api/payments/{id}/queue` -> PaymentView. Body `{revision_id, digest}`,
  header `Idempotency-Key`. Finance requests execution, worker performs it.
- `GET /api/supplier/requests` -> `{suppliers: SupplierView[]}` scoped to the
  authenticated supplier assignment. No finance payment controls in this view.

Views must expose stable IDs, current version/revision, explicit prerequisite
states, allowed actions or hold reasons, expiry, and audit timeline. Server
enforces every action regardless of UI controls. Errors use existing AppError.

## Independent sandbox HTTP contract

Separate process and PostgreSQL database; application cannot read its tables.
Environment-provided shared API key as `Authorization: Bearer ...`; no redirect
following. HTTPS outside explicit loopback test configuration.

- `POST /v1/transfers`, `Idempotency-Key: <execution UUID>`.
- Body: `{payment_id, revision_id, tenant_id, invoice_reference, amount_minor,
  currency:'INR', beneficiary_name, sandbox_account_id, digest, simulation}`.
- Result: `{idempotency_key, transfer_id, status:'SUCCEEDED'|'FAILED', ...body}`.
- `GET /v1/transfers/by-idempotency/{key}` returns the same persisted result;
  absent or deliberately delayed visibility returns 404. Failure is persisted.
- Same key and identical body returns the same ledger result; changed body is
  409. Only one debit per idempotency key, including concurrent POSTs/restarts.
- `lost_response` commits the ledger, delays POST past the client timeout, and
  hides readback temporarily (configurable, e.g. 15 seconds for demonstration).
  It demonstrates UNKNOWN then safe reconciliation. Synthetic funds only.
- `GET /health` and `/ready` expose no credentials.

Worker configuration: `PAYMENTS_SANDBOX_URL`, `PAYMENTS_SANDBOX_API_KEY`,
`WORKER_DATABASE_URL` and bounded timeouts/lease/reconciliation intervals via env.
Backend and worker owners coordinate the persisted outbox/lease interface.

## Local review harness

Root owns an explicitly labelled local-only identity simulator and launcher.
It generates ephemeral secrets into ignored owner-readable environment files,
seeds controlled finance/supplier identities and synthetic fixtures, and runs
the unchanged Auth verification path against a loopback provider double.
This is test infrastructure and must be rejected/absent in production builds.
It is not a verified Supabase integration. Frontend local identity switching
will be explicitly labelled, available only in Vite DEV on loopback, and use
the same backend membership/role checks as ordinary sessions.

Exit evidence: real PostgreSQL migration/isolation/concurrency checks, actual
HTTP sandbox POST/readback and restart/idempotency checks, API stale approval
and UNKNOWN tests, responsive browser walkthrough, and phase report. Save the
phase report and continue the already authorised Phase 4. Production and
live sponsor verification remain deferred until credentials are supplied.
