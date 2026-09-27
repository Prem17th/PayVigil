# PayVigil independent synthetic payment sandbox

This service records synthetic INR transfers in its own PostgreSQL database.
It never contacts a bank or uses real payment rails. The main application's
database credentials must not have access to this database; its worker uses the
HTTP API and a generated shared key.

Supply settings from [.env.example](.env.example) through a secure environment.
No environment file is loaded automatically and no credential is embedded in
the code. Install the repository backend requirements into the root `.venv`.

From the repository root, run the explicit bootstrap with only the migration
credential available to that operator process:

```sh
.venv/bin/python -m sandbox_service.bootstrap
```

Bootstrap creates the `sandbox_ledger` schema and restricted NOLOGIN group
`beforetransfer_sandbox_api`. Provision a separate LOGIN role with no superuser,
BYPASSRLS, role/database creation, replication, or owner-group membership, and
grant it `beforetransfer_sandbox_api`. Set its password through a secure prompt
or secret manager and use it for `SANDBOX_DATABASE_URL`. Runtime privileges are
SELECT and INSERT only; transfers and debit records cannot be edited/deleted by
the service. Browser roles receive no direct access. The API does no startup DDL.

Start the local process after removing the migration credential:

```sh
env -u SANDBOX_MIGRATION_DATABASE_URL .venv/bin/uvicorn sandbox_service.app:app --host 127.0.0.1 --port 8001
```

Production settings require authenticated TLS to PostgreSQL. Isolated local
tests may set `SANDBOX_APP_ENV=test`, `SANDBOX_PGSSLMODE=disable`, and a loopback
database whose name ends in `_test`. This is not a hosted provider integration.

The API implements `docs/PHASE3_CONTRACT.md`. Every protected endpoint requires
`Authorization: Bearer` with the generated `SANDBOX_API_KEY`. The worker uses
the same value as `PAYMENTS_SANDBOX_API_KEY`. Idempotency keys are execution UUIDs.
Concurrent identical POSTs share one persisted transfer/debit. A changed body
with the same key is rejected with 409; a decline persists without a debit.

`lost_response` commits before delaying the POST response. Readback is hidden
until the persisted visibility timestamp, including across restarts. Configure
the response delay longer than the worker timeout and visibility delay longer
than its first reconciliation interval. Defaults are 10 and 15 seconds.

Run the worker from `backend` using `../.venv/bin/python -m app.payment_worker`.
It needs `WORKER_DATABASE_URL` for the core's restricted worker login,
`PAYMENTS_SANDBOX_URL`, `PAYMENTS_SANDBOX_API_KEY`, and the backend TLS/environment
settings. Optional `PAYMENTS_REQUEST_TIMEOUT_SECONDS` (default 3, maximum 10) and
`PAYMENTS_POLL_SECONDS` (default 1) bound HTTP calls/polling. The core controls
`PAYMENT_WORKER_LEASE_SECONDS` and `PAYMENT_RECONCILE_INTERVAL_SECONDS`.
Once a result is uncertain, only independent GET readback can resolve it. Even
a successful POST response requires matching readback before finalization.

For actual HTTP/database tests, provision a separate isolated sandbox test
database and restricted runtime login with the bootstrap above. Supply
`SANDBOX_TEST_DATABASE_URL` and `SANDBOX_TEST_MIGRATION_DATABASE_URL` through a
secure environment. Both must select the same explicit loopback database with
`sandbox` in its name and an `_test` suffix, using distinct runtime/admin roles.
The test suite starts its own local API on a random port and generates its own
shared key; it does not reuse the running demonstration ledger.

```sh
.venv/bin/python -m pytest sandbox_service/tests -q
```
