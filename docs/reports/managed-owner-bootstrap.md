# Managed PostgreSQL owner bootstrap compatibility

## Change

Migration `0005_managed_owner_bootstrap` permits the actual application table
owner to select and insert tenants, memberships, and supplier identity mappings
while FORCE RLS remains enabled. This supports a managed PostgreSQL owner with
`NOSUPERUSER NOBYPASSRLS`, without granting bootstrap authority to the API,
worker, or browser roles.

The migration checks actual table ownership and binds six policies to that
exact owner identity. It adds no UPDATE/DELETE policy, grants, RLS bypass, or
runtime role changes. Runtime rejection of application owners and inherited
owner roles remains in place. Migration configuration now also honors
`BEFORETRANSFER_DISABLE_DOTENV=1`, keeping isolated tests independent of locally
stored deployment configuration.

The bootstrap runbook now distinguishes Render PostgreSQL application data
from Supabase Auth and private Storage. Provisioning requires reviewed, real
Supabase Auth UUIDs; it does not fabricate confirmation, approval, or execution
records.

## Validation

Targeted local validation: **4 tests passed** (`test_managed_owner_bootstrap.py`
and `test_migrations.py`). The managed-owner fixture created and removed its
own generated database and role identities on loopback PostgreSQL 17.

- Migrations 0001–0004 ran as a generated non-superuser, non-bypass owner with
  CREATEROLE and CREATEDB; tenant bootstrap was denied before 0005.
- Migration 0005 enabled tenant/membership inserts and the documented checked
  supplier-assignment join. Re-running Alembic at head was harmless.
- Finance and supplier operations retained their tenant/assignment scoping.
- All application tables retained RLS and FORCE RLS; only the six expected
  SELECT/INSERT owner bootstrap policies were added.
- Owner UPDATE/DELETE attempts changed no bootstrap rows. API/worker bootstrap
  INSERT attempts remained denied, and runtime owner/inherited-owner checks
  rejected unsafe connections.
- Offline migration SQL generation and Python compilation passed.

## Remaining verification

These tests establish local compatibility, not hosted migration success. No
hosted database credential or remote database was accessed for this change.
The authorized deployment operator can now apply the reviewed migration chain,
inspect the resulting policy/role boundaries, and provision restricted runtime
logins. Hosted Auth memberships remain dependent on actual reviewed user UUIDs.
