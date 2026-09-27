# Phase 2 — local build report

Status: local foundation build complete; awaiting user review. Verified on
27 September 2026. Production deployment is deferred by the user's latest
instruction and has not started.

## Scope and review gate

Complete the application foundation locally, keep credentials in environment
variables or managed secrets, then stop for review. The next step is production
deployment only after user approval. No work on Phase 3 payment controls is
authorised or included.

## Implemented foundation

- React/TypeScript interface with overview, sign-in, connection checks, phase
  roadmap, and a restricted supplier portal.
- FastAPI identity verification through Supabase Auth. Application permissions
  come from database membership, rather than browser-supplied tenant/role fields
  or editable identity metadata.
- PostgreSQL tenant and membership migration in a private application schema;
  row-level isolation and a restricted runtime database role.
- Private Storage adapter with a synthetic upload/read/delete probe and checks
  that public and anonymous reads are denied.
- Liveness, dependency readiness, and non-secret configuration indicators.
- Render deployment definitions and a live-service verification script prepared
  for the later production step. These have not been applied.

## Credential handling

Environment example files contain empty credential values. Server credentials
are excluded from Git and separated from the public frontend configuration.
Production connections require HTTPS and verified PostgreSQL TLS. Migration
and runtime database credentials have separate purposes; the prepared Render
start command removes migration credentials from the API process environment.

Automated tests use synthetic values and an isolated database. They do not
establish live Supabase authentication or storage access.

## Checks actually completed

| Check | Result |
| --- | --- |
| Frontend TypeScript and production asset build | Passed with `npm run build`; output in `frontend/dist`. |
| Backend suite, including actual PostgreSQL | **49 passed**: 42 configuration/API/storage/offline checks and 7 real database checks. |
| Frontend configuration guard | **6 passed**: valid public configuration builds; privileged key formats, HTTP API origins, URL credentials, and provider query strings are rejected without echoing the supplied values. |
| Dependency compatibility | `pip check` passed. |
| Frontend production dependency advisory check | `npm audit --omit=dev --audit-level=high` reported zero vulnerabilities at check time. |
| Browser navigation | Overview, access, connections, refresh, roadmap, mobile menu, and page reload checked. |
| Responsive layout | Desktop width 1280 and mobile width 390 checked; no horizontal overflow. |
| Browser console | No errors or warnings observed during these checks. |
| Missing-configuration behavior | API liveness returns 200; readiness and protected identity return 503; sign-in and privileged storage controls stay disabled. |
| Secret exclusions | Root/backend/frontend environment files, local database files, and dependencies are ignored by Git. |

The database checks used PostgreSQL 17.9 in an isolated loopback test instance.
They cover cross-tenant reads, context reset after pooled requests, denied
membership updates, privileged and inherited-owner roles, rollback after a
blocked-query timeout, and private Alembic metadata. The migration was also run
against a fresh database with permissive browser default grants to verify that
the application revokes that exposure. The isolated test database was stopped
after verification; it is not the application database.

The local verification used Python 3.13.12 and Node.js 25.7.0. The prepared
Render configuration selects Python 3.13.12 and Node.js 24; that hosted runtime
still needs its own build and integration verification when deployment is
authorised.

Repeat the standard checks from the repository root:

```sh
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python scripts/check_frontend_config.py
```

The seven database checks require securely supplied `TEST_ADMIN_DATABASE_URL`
and `TEST_DATABASE_URL`, an already migrated isolated database, and the test
fixtures described in `backend/tests/test_postgres.py`. Without those variables
they are explicitly skipped. The database guard requires loopback addresses and
a database name ending in `_test`. Never target a hosted business database.

For the frontend build, run `npm run build` from `frontend`.

## What is intentionally unavailable

Without Supabase configuration, the local interface reports that sign-in and
private data access are unavailable. It has no bypass login or fabricated
workspace. The liveness endpoint responds, while readiness and protected routes
refuse operation. Local build success does not mean the service is ready to
handle real supplier data.

Investigations, invoice ingestion, payment execution, n8n, Breeth AI,
ElevenLabs, and Dodo subscription billing remain in their later phases.

## Local review

From the repository root, start the backend in one terminal:

```sh
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Start the frontend in a second terminal:

```sh
cd frontend
npm run dev
```

Open `http://127.0.0.1:5176`. Ports 5173–5175 are already used by the existing
QueueNow applications; those processes were left unchanged. The API on port
8000 and frontend on port 5176 are running for review.
Installation instructions and the later production
procedure are in [the deployment guide](../DEPLOYMENT.md).

## Next review decision

Review the local interface and test evidence. Production deployment requires a
selected Render workspace, repository, Supabase project, and securely supplied
environment configuration. No cloud resources, paid plans, live financial
actions, or sponsor credit redemptions have been created by this build step.
