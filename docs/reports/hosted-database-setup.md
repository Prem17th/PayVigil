# Hosted database setup — 2026-09-27

The user supplied a Render PostgreSQL connection and confirmed it is a new,
dedicated BeforeTransfer database. This report covers database preparation only;
the API, frontend, worker and sandbox service have not been deployed publicly.

## Completed

- Verified the external endpoint with `sslmode=verify-full` and the installed
  trusted CA bundle. TLS 1.3 succeeded; the database runs PostgreSQL 18.6.
  The Mac's default CA lookup failed initially; certificate verification was
  retained and a trusted bundle resolved the issue.
- Confirmed the database was empty and the owner had CREATEROLE/CREATEDB without
  SUPERUSER/BYPASSRLS. Reproduced those privileges locally before migration.
- Applied migrations through `0005_managed_owner_bootstrap`. The final migration
  permits only the exact table owner to SELECT/INSERT into tenants, memberships
  and supplier assignments. Runtime role checks still reject table ownership or
  inheritance of an owner/privileged role. RLS remains enabled and forced.
- Provisioned `beforetransfer_runtime` and `beforetransfer_worker_runtime` with
  separate generated passwords and the restricted application groups.
- Created `beforetransfer_sandbox` on the same dedicated PostgreSQL instance,
  installed the separate two-table ledger schema, and provisioned
  `beforetransfer_sandbox_runtime` plus a generated sandbox API key.
- Stored database connections and generated secrets only in ignored,
  owner-only `.env.release`. Nothing was added to frontend configuration, source
  credentials or public resources. The release tool sends service-specific
  subsets of these settings.

## Verification

**13 hosted read-only checks passed.** The revision matches the final migration;
all 20 application tables enable and force RLS; six narrow bootstrap policies
exist; API/worker logins pass the application's actual restricted-role checks;
neither can insert memberships or read ledger tables. The separate sandbox login
passes its role check. There are no workspace memberships, ledger transfers or
debits. No Supabase users or application business data were fabricated.

Credential-free evidence is in ignored `artifacts/hosted-database-preflight.json`
and `artifacts/hosted-database-setup.json`. Private migration/bootstrap diagnostics
are under `.local/production/`. Do not publish the release environment file.

## Remaining

Rotate the password supplied in chat before public release and update the
migration connections securely. Generated runtime passwords were not printed.
Configure Supabase Auth/private Storage, controlled users and membership mappings;
select the Render workspace and accessible reviewed Git commit; add OpenAI and
sponsor credentials; then deploy services and verify real provider operations.
The hosted schema and role checks do not establish application readiness, backup
restorability, sponsor access, model accuracy, or a public deployment.

See [deployment](../DEPLOYMENT.md), [database connection notes](../RENDER_DATABASE.md)
and [managed-owner local verification](managed-owner-bootstrap.md).
