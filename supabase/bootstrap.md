# Managed PostgreSQL and Supabase bootstrap for PayVigil

This is the prepared hosted setup, to apply after the current local-build review.
Use the production project selected by the user. These steps do not create a
project, redeem credits, send invitations, or configure billing automatically.
Review the selected plan's idle-pausing behavior, backup retention, and restore
procedure before loading business data. No paid plan or upgrade is assumed.
The selected application database is dedicated Render PostgreSQL; Supabase
supplies Auth and private Storage. Keep these separate provider responsibilities
when collecting configuration and running SQL. Prefer dedicated resources over
changing an unrelated application's schema or Storage policies.

## 1. Collect project configuration securely

From the Supabase Dashboard, obtain the Auth/Storage project URL, publishable key,
and server secret key. Obtain application database connection details from the
selected Render PostgreSQL instance's connection settings. If using Supabase
PostgreSQL instead, obtain its **Connect** strings: prefer a reachable direct
connection for migrations, or its shared **Session pooler** for a persistent
runtime on an IPv4-only network.
See [deployment settings](../docs/DEPLOYMENT.md) for the exact environment names.
Keep database and secret keys in approved secret storage or Render environment
settings. The frontend uses the project URL and publishable key only. Provide
separate `MIGRATION_DATABASE_URL`, restricted API `DATABASE_URL`, and restricted
worker `WORKER_DATABASE_URL` values. These three target the application database
with different credentials; never run the API or worker as its owner. They use
`PGSSLMODE=verify-full` with
system roots or the project's verified CA file. The deployment guide documents
Render's certificate mount and migration-variable removal at API start.

The project secret key bypasses RLS. It is not a user's access token and does not
establish their tenant or role. The API must verify the user's Supabase session
and consult its own membership table before any privileged Storage operation.

## 2. Apply application migrations and provision runtime roles

From a trusted checkout with its virtual environment installed, review the
target project and run:

```sh
cd backend
../.venv/bin/alembic upgrade head
```

Provide `MIGRATION_DATABASE_URL` through secure environment configuration before
running this command. Alembic owns the schema; do not recreate its tables here.
The current chain includes membership, payment authority, evidence/memory,
sponsor receipts, and `0005_managed_owner_bootstrap`. Confirm `alembic current`
matches `alembic heads` from the same
reviewed checkout. Alembic keeps its version table in `beforetransfer_migrations`,
separate from the application schema. Keep both schemas outside the Data API's
exposed schemas.

Run migrations as the existing application table owner. A managed owner with
`NOSUPERUSER NOBYPASSRLS` can bootstrap this application; superuser or RLS bypass
is not required. Migration `0005_managed_owner_bootstrap` checks the owner of
each affected table before adding policies. It gives that exact owner only
`SELECT` and `INSERT` policies on `tenants`, `memberships`, and
`supplier_identities`, preserving FORCE RLS. These policies add no `UPDATE` or
`DELETE` permission and no runtime or browser grants. Their expressions require
the exact owner identity, not simply an inherited role membership. Do not
disable RLS to provision users. The API and worker continue to reject owner
credentials and runtime roles that inherit an application table owner.

The migrations create the `beforetransfer` schema and restricted NOLOGIN groups.
The API group receives the specific table/column rights needed by the application.
Application tables enable and force RLS; policies scope the verified user to their
active membership, role and assigned supplier records. The backend sets
transaction-local `app.user_id` only after verifying the Supabase session. It
must never come from a request-supplied role or user identifier.

Supabase browser roles (`anon`, `authenticated`) get no direct application-table
access. Keep `beforetransfer` outside the Data API's exposed schemas. There are
no browser policies for these tables. RLS complements the API authorization
checks; it does not establish an identity by itself.

After migration, create two separate LOGIN roles using the authorised project
administrator. These examples contain no passwords and intentionally fail if a
role already exists, so existing privileges are not silently reused:

```sql
create role beforetransfer_runtime
  login inherit nosuperuser nobypassrls nocreatedb nocreaterole noreplication;
grant beforetransfer_api to beforetransfer_runtime;

create role beforetransfer_worker_runtime
  login inherit nosuperuser nobypassrls nocreatedb nocreaterole noreplication;
grant beforetransfer_worker to beforetransfer_worker_runtime;
```

Set a newly generated password using the provider's secure role-management
interface, or an interactive `psql` session connected as the authorised
administrator. PostgreSQL's password prompt avoids embedding a cleartext
password in SQL/history:

```text
\password beforetransfer_runtime
\password beforetransfer_worker_runtime
```

Store each distinct password directly in approved secret storage. Render direct
connections use the selected login role's ordinary username. Only Supabase's
shared session pooler uses `<LOGIN_ROLE>.<PROJECT_REF>` for custom usernames;
its direct connection uses `<LOGIN_ROLE>`. Obtain the host and connection mode
from the selected provider's connection settings; do not invent a hostname.

| Environment variable | Login | Inherited application group |
| --- | --- | --- |
| `DATABASE_URL` | `beforetransfer_runtime` | `beforetransfer_api` only |
| `WORKER_DATABASE_URL` | `beforetransfer_worker_runtime` | `beforetransfer_worker` only |
| `MIGRATION_DATABASE_URL` | Actual application table owner | Separate privileged credential |

Construct connection URLs only in secure environment settings, percent-encoding
the passwords. Do not grant either runtime membership in `postgres`, a migration
or table-owner role, or the other runtime group. The worker reads the committed
outbox and updates only its permitted execution state. It has no Auth, Storage,
model, voice, memory, billing, or n8n credential. Its sole provider credential is
the independent sandbox's HTTP key; it does not connect to the ledger database.

Read-only SQL for the authorised SQL editor:

```sql
select n.nspname as schema_name, c.relname as table_name,
       c.relrowsecurity, c.relforcerowsecurity
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'beforetransfer' and c.relkind = 'r'
order by c.relname;

select grantee, table_schema, table_name, privilege_type
from information_schema.table_privileges
where table_schema = 'beforetransfer'
  and grantee in ('anon', 'authenticated', 'beforetransfer_api', 'beforetransfer_worker');

select grantee, table_name, column_name, privilege_type
from information_schema.column_privileges
where table_schema = 'beforetransfer'
  and grantee in ('beforetransfer_api', 'beforetransfer_worker')
order by grantee, table_name, column_name, privilege_type;

select schemaname, tablename, policyname, roles, cmd
from pg_policies
where schemaname = 'beforetransfer';

select tablename, policyname, roles, cmd, qual, with_check
from pg_policies
where schemaname = 'beforetransfer'
  and policyname in ('managed_owner_bootstrap_select', 'managed_owner_bootstrap_insert')
order by tablename, cmd;

select rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication
from pg_roles
where rolname in ('beforetransfer_api', 'beforetransfer_runtime',
                 'beforetransfer_worker', 'beforetransfer_worker_runtime');

select child.rolname as runtime_role, parent.rolname as inherited_role
from pg_auth_members m
join pg_roles parent on parent.oid = m.roleid
join pg_roles child on child.oid = m.member
where child.rolname in ('beforetransfer_runtime', 'beforetransfer_worker_runtime');
```

Expect RLS and FORCE RLS on application tables and no direct browser grants.
Review API/worker column privileges and role-specific policies against the
checked-in migrations; financial history must remain append-only. All privilege flags shown for
the group/runtime role must be false. Review inherited permissions and ownership;
the runtime must not be an application-table owner or inherit one. Do not revoke
unrelated applications' grants or change a shared project indiscriminately.
The managed-owner policy query must return six rows: `SELECT` and `INSERT` for
each of the three bootstrap tables, naming only the actual migration owner.

## 3. Provision controlled Auth users and memberships

The app supports existing-user email/password sign-in. There is no public signup
or application membership-provisioning endpoint. Use Supabase Auth's user
administration to create controlled test users, with separate identities for:

- `finance_admin`: finance administrator.
- `finance_reviewer`: finance reviewer.
- `supplier`: supplier account.

Also create a separate controlled Auth user with **no application membership**
for the negative hosted-access check. Do not add this user to the SQL below.

Create confirmed test accounts without sending external invitations; do not
store passwords in SQL, documentation, fixtures, or source. Copy each account's
Auth user UUID. A valid Supabase login alone does not grant application access.

In a trusted SQL session connected to the application database as its actual
migration/table owner, replace every placeholder below with the appropriate
reviewed value. Generate the tenant UUID once and reuse it. For the selected
Render application database, these queries run there, not in Supabase's SQL
editor. The runtime role intentionally cannot write memberships. These are not
a public API, and a Supabase server key is not a PostgreSQL connection credential:

```sql
begin;

insert into beforetransfer.tenants (id, name, created_at)
values ('<TENANT_UUID>'::uuid, '<REVIEWED_WORKSPACE_NAME>', now());

insert into beforetransfer.memberships
  (id, user_id, tenant_id, role, is_active, created_at)
values
  (gen_random_uuid(), '<FINANCE_ADMIN_AUTH_USER_UUID>'::uuid,
   '<TENANT_UUID>'::uuid, 'finance_admin', true, now()),
  (gen_random_uuid(), '<FINANCE_REVIEWER_AUTH_USER_UUID>'::uuid,
   '<TENANT_UUID>'::uuid, 'finance_reviewer', true, now()),
  (gen_random_uuid(), '<SUPPLIER_AUTH_USER_UUID>'::uuid,
   '<TENANT_UUID>'::uuid, 'supplier', true, now());

commit;
```

Check that the UUIDs belong to the intended Auth users before executing. The
current membership model intentionally permits one tenant per user. The snippet
does not use an upsert: accidentally rerunning it should not silently change a
user's tenant or elevate a role. Membership is not derived from a browser field,
email domain, or user-editable Auth metadata. No supplier is granted payment
authority by these roles.

### Assign the supplier account to an actual supplier record

Use the finance workspace to create a synthetic supplier record, then obtain its
actual UUID from the authenticated `GET /api/suppliers` response or a reviewed
administrator query of `beforetransfer.suppliers`. A `supplier` membership alone
does not assign any record.
The API runtime cannot insert into `supplier_identities`; assignment is a
separate administrator bootstrap operation.

Run this only as the same authorized migration/table owner. It checks that the
supplier record and active supplier
membership belong to the same reviewed tenant. A missing match raises an error;
a duplicate assignment fails instead of silently changing access.

```sql
do $bootstrap$
begin
  insert into beforetransfer.supplier_identities
    (id, tenant_id, created_at, supplier_id, user_id)
  select gen_random_uuid(), s.tenant_id, now(), s.id, m.user_id
  from beforetransfer.suppliers s
  join beforetransfer.memberships m on m.tenant_id = s.tenant_id
  where s.id = '<ACTUAL_SUPPLIER_UUID>'::uuid
    and s.tenant_id = '<TENANT_UUID>'::uuid
    and m.user_id = '<SUPPLIER_AUTH_USER_UUID>'::uuid
    and m.role = 'supplier'
    and m.is_active;

  if not found then
    raise exception 'No matching supplier record and active supplier membership';
  end if;
end;
$bootstrap$;
```

Inspect the result as that same migration/table owner:

```sql
select si.id as assignment_id, si.tenant_id, si.supplier_id,
       s.name as supplier_name, si.user_id, m.role, m.is_active
from beforetransfer.supplier_identities si
join beforetransfer.suppliers s
  on s.id = si.supplier_id and s.tenant_id = si.tenant_id
join beforetransfer.memberships m
  on m.user_id = si.user_id and m.tenant_id = si.tenant_id
where si.tenant_id = '<TENANT_UUID>'::uuid;
```

The schema permits multiple explicit assignments; the initial demonstration can
use one supplier identity per supplier record. These mappings grant access to
assigned supplier records and confirmation requests only. They do not confirm a
beneficiary, accept one, approve a payment, or establish bank-account ownership.
Perform those separate user actions through the application. Never bootstrap
approval or transfer rows to make a demonstration appear complete.

Set Supabase Auth's Site URL to the actual deployed frontend origin once known.
For later email confirmation/password-reset flows, configure exact controlled
redirect URLs; the app's password sign-in does not introduce those flows. Do not
enable anonymous login as a workaround for missing setup.

## 4. Create a private evidence bucket

In **Storage → New bucket**, create `beforetransfer-evidence` with **Public
bucket disabled**. If a different name is selected, use that exact name in
`SUPABASE_STORAGE_BUCKET`. Create it through the authenticated Dashboard or a
trusted server-side Storage API client; the browser must not hold the secret key
or create buckets. The app does not create the bucket during startup.

Do not add browser upload/download policies for the evidence bucket. Inspect existing
`storage.objects` policies too: an existing broad policy can allow authenticated
users into a private bucket. The intended access path is an authenticated,
authorized FastAPI operation using a server-held secret, not direct client access.
Avoid unrelated bucket/policy changes in a shared project.

Read-only inspection SQL in the Supabase project (Storage remains there):

```sql
select id, name, public
from storage.buckets
where id = 'beforetransfer-evidence';

select policyname, roles, cmd, qual, with_check
from pg_policies
where schemaname = 'storage' and tablename = 'objects';
```

Expect the named bucket with `public = false`. The backend's finance-only
Storage probe must succeed with real provider access before marking Storage
verified. Using a synthetic probe object, separately attempt a direct read or
list with an ordinary user's JWT/publishable key and with no authentication;
neither should expose an object. Test an object known to exist so an absent file
cannot disguise an access-control failure. Never record JWTs, secret keys, or
signed URLs in the phase report. A successful privileged API probe does not by
itself prove correct browser restrictions.

## 5. Bootstrap the independent synthetic ledger

Provision a dedicated PostgreSQL database for the sandbox, with a separate
administrator and runtime credential. A separate Supabase project or another
authorized PostgreSQL service is suitable; it is not a second schema inside the
application database. The main API and worker must have no ledger-table grants
or ledger database credential. The sandbox must have no application-table access.

From the repository root, with `SANDBOX_MIGRATION_DATABASE_URL` supplied securely
for that separate database, run:

```sh
.venv/bin/python -m sandbox_service.bootstrap
```

Use `SANDBOX_APP_ENV=production`, `SANDBOX_PGSSLMODE=verify-full`, and
`SANDBOX_PGSSLROOTCERT` pointing to the appropriate trusted roots. This command
creates `sandbox_ledger.transfers`, `sandbox_ledger.debits`, their policies, and
the restricted `beforetransfer_sandbox_api` group. It performs no bank transfer.

In that database's authorized administrative session, create a distinct login:

```sql
create role beforetransfer_sandbox_runtime
  login inherit nosuperuser nobypassrls nocreatedb nocreaterole noreplication;
grant beforetransfer_sandbox_api to beforetransfer_sandbox_runtime;
```

Set its unique password with `\password beforetransfer_sandbox_runtime` and store
the resulting restricted connection URL as `SANDBOX_DATABASE_URL`. Grant no
application role to this login. Keep `SANDBOX_MIGRATION_DATABASE_URL` only for
bootstrap/pre-deploy; the sandbox start command removes it before API startup.
Runtime ledger privileges are SELECT and INSERT only. Check the actual tables
and role grants using the inspection queries above with `sandbox_ledger` and the
sandbox role names. Both tables must enforce RLS and FORCE RLS, with no direct
browser grants.

Generate a separate strong HTTP key in the approved secret manager. Configure
the same value as the sandbox's `SANDBOX_API_KEY` and the worker's
`PAYMENTS_SANDBOX_API_KEY`; do not reuse a Supabase key. Set the worker's
`PAYMENTS_SANDBOX_URL` to the actual sandbox HTTPS origin. The Render API release
tool derives the URL from the created service and sends the shared key only to
the sandbox and worker. The Blueprint uses a generated value and service
reference instead. Do not combine both provisioning methods.

See the [sandbox runbook](../sandbox_service/README.md) for readiness, synthetic
outcomes, durable readback, and isolated tests. A healthy process is not proof of
successful execution: verify one stable execution ID produces one ledger entry
and that a lost response is resolved through readback without resubmission.

## 6. Verification boundary

With no Supabase settings, liveness may succeed while readiness returns 503
and protected access remains unavailable. With real settings, verify a
no-membership user is denied, then check the three explicitly provisioned roles
through the API and deployed UI.
Record the selected project, migration revision, successful provider checks,
and negative-access results without credentials. Use the automated hosted
verification command in [deployment](../docs/DEPLOYMENT.md) after deployment.
The current local build can be completed without cloud credentials; isolated
PostgreSQL and mocked provider tests are not Supabase integration evidence.

The managed-owner compatibility test provisions a disposable loopback PostgreSQL
database and a non-superuser, non-bypass migration owner. It proves that bootstrap
is denied before migration 0005, succeeds afterwards through owner-only policies,
and leaves runtime tenant isolation and owner-role rejection intact. This local
test does not establish that the hosted migration or provider checks succeeded.

## Official references

- [Supabase connection options](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Custom-role pooler usernames](https://supabase.com/docs/guides/troubleshooting/tenant-or-user-not-found)
- [PostgreSQL password prompt](https://www.postgresql.org/docs/current/app-psql.html)
- [Securing database access](https://supabase.com/docs/guides/database/secure-data)
- [Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Auth user administration](https://supabase.com/docs/guides/auth/users)
- [Auth redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls)
- [Storage quickstart](https://supabase.com/docs/guides/storage/quickstart)
- [Private buckets](https://supabase.com/docs/guides/storage/buckets/fundamentals)
- [Storage access control](https://supabase.com/docs/guides/storage/security/access-control)
