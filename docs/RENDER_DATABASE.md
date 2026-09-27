# PayVigil Render PostgreSQL target

The user confirmed that the supplied Render PostgreSQL instance is new and
dedicated to PayVigil. Read-only external connection verification passed
using TLS 1.3 and full hostname/certificate verification with the installed CA
bundle. The database is empty, runs PostgreSQL 18.6, and its owner has CREATEROLE
and CREATEDB but no superuser or BYPASSRLS privilege. Hosted migrations reached
`0005_managed_owner_bootstrap` after local managed-owner tests passed. All 20
application tables force RLS. Separate API/worker accounts and the separate
`beforetransfer_sandbox` database/runtime account are provisioned and verified.
See the [hosted database report](reports/hosted-database-setup.md).

The connection is saved only in ignored owner-only `.env.release`; it was not
copied into source or reports. Rotate the chat-supplied password before release
and update the managed configuration. Do not paste the replacement into chat.

## Connection and scope

Repeat the credential-safe read-only check with the expected database name:

```sh
.venv/bin/python scripts/verify_database_target.py --env-file .env.release --expected-database <dedicated-database-name>
```

Use the database's **External Database URL** for verification from the local Mac.
The bare `dpg-…` internal hostname is intended for Render services in the same
account and region. Do not guess its external region suffix.

The current production database configuration enforces `sslmode=verify-full`.
Render documents self-signed internal TLS that does not support that mode. Keep
the existing verification requirement and use the external endpoint with its
trusted Render-managed certificate, pending actual certificate validation. Do not
change the application to test mode or disable certificate verification to make
the internal address connect.

The owner/migration connection is stored as `MIGRATION_DATABASE_URL`. It must not be
the API's `DATABASE_URL` or worker's `WORKER_DATABASE_URL`. Before migrating,
inspect the actual role's privileges, database identity, existing objects and
support for creating restricted roles. The local test cluster is not evidence
of those hosted permissions. Bootstrap writes must be verified under the actual
hosted administrator, including the effect of FORCE RLS on that role.

The generated application logins inherit `beforetransfer_api` and
`beforetransfer_worker`; their URLs are stored under the corresponding runtime
keys in `.env.release`. The separate fake-transfer ledger has its own restricted
login and migration/runtime URLs. Its generated API key is also stored there.
Do not upload the combined file to a service; the release tool forwards only each
service's permitted subset.

Render PostgreSQL can hold the application tables. Supabase remains required for
the implemented identity and private Storage adapters. Its project URL, public
key, server Storage key, controlled Auth users and private evidence bucket are
still needed. Auth user UUIDs are mapped to memberships in the Render application
database; browser requests cannot select a tenant or role.

Follow the schema/role/membership guidance in [bootstrap](../supabase/bootstrap.md)
against the approved application database, and the Auth/Storage sections against
the selected Supabase project. Do not apply schema mutations until the actual
target's read-only preflight has passed.

See [Render's connection and TLS documentation](https://render.com/docs/postgresql-creating-connecting)
and [credential rotation guidance](https://render.com/docs/postgresql-credentials).
