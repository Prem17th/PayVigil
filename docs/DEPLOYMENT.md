# PayVigil deployment through Render APIs

This runbook deploys the reviewed repository through Render's REST API. Source
publication and local checks are separate from a verified hosted release. The
dedicated Render database has been prepared; application hosting, Supabase
Auth/Storage and live sponsor verification remain pending.

## Resources

| Service | Runtime / directory | Purpose |
| --- | --- | --- |
| payvigil-api | Python 3.13.12 / backend | Authenticated FastAPI; Alembic pre-deploy migration |
| payvigil-web | Node 24 build / frontend | Static React site with HTTPS API configuration |
| payvigil-worker | Python 3.13.12 / backend | Restricted-role outbox processing and readback |
| payvigil-sandbox | Python 3.13.12 / repository root | Independent fake-transfer API and PostgreSQL ledger |

The API, worker and sandbox use paid compute; review the selected workspace's
current prices/credit eligibility before creating them. Singapore is the prepared
region. Render PostgreSQL stores application state; Supabase supplies Auth and
private Storage.
The sandbox requires a separate database and restricted role. It must not share
the application runtime's credentials or grant that runtime ledger-table access.
No actual banking integration is included.

The [Blueprint](../render.yaml) and [API release tool](../scripts/render_release.py)
express this topology. Choose one provisioning method per resource; do not create
an extra set through both. Existing services can be adopted after identity checks.
Automatic deploys are disabled so a release selects an explicit reviewed commit.

Use the public GitHub repository `https://github.com/Prem17th/Payvigil`
and an explicitly reviewed commit. `RENDER_REPO_URL` must remain
`https://github.com/Prem17th/Payvigil`. Use `RENDER_NAME_PREFIX=payvigil`
for newly provisioned Render services.
Existing `beforetransfer` database,
schema and role identifiers, the `beforetransfer-evidence` bucket, and protocol
identifiers remain unchanged for compatibility with provisioned resources.
Historical reports retain the product name used during those checks.

## Before provisioning

The dedicated Render PostgreSQL target passed TLS, migration and restricted-role
checks; see [Render database setup](RENDER_DATABASE.md). For another environment,
repeat the read-only privilege/identity checks before applying its schema.
Supabase supplies Auth and private Storage only.

1. Select the authorised Render workspace, Git repository and branch. Prepare a
   reviewed, committed revision before asking Render to build it. The account
   must have access to the repository and the exact selected commit.
2. Apply [Supabase bootstrap](../supabase/bootstrap.md): migrations, restricted
   API and worker logins, controlled Auth users, supplier mappings, private bucket.
3. Apply [sandbox bootstrap](../sandbox_service/README.md) on its separate database.
   Configure authenticated TLS for both databases and distinct runtime credentials.
4. Review actual account plans, backup retention and restore access. The build
   does not claim sponsor credits have been redeemed or that a free tier is eligible.
5. Run `scripts/check.py --postgres` and review the generated evidence. Set the
   GitHub `Build and verify` check as a branch protection requirement if desired;
   that policy is not enabled merely by committing a workflow file.

## Secrets

Use Render managed environment settings or an approved secret manager. The
[environment reference](../.env.example) contains only empty credential fields.
Do not paste keys into chat or use `VITE_*` names for a privileged credential.

For operator-side API commands, supply configuration through the process
environment or an ignored owner-only `.env.release` file (`chmod 600`). Do not
upload this combined file to any service: the release tool sends only each
service's allowlisted subset. It never prints secret values or Render response
bodies on errors. Its ignored `.local/render-release.json` journal stores resource
IDs and deployment state, not environment-variable values.

Use a dedicated `RENDER_API_KEY` and exact `RENDER_OWNER_ID`, `RENDER_REPO_URL`,
`RENDER_BRANCH`. Optional names are `RENDER_NAME_PREFIX`, `RENDER_REGION`, and
`RENDER_COMPUTE_PLAN`. The offline plan names missing environment variables.

Database URLs require `sslmode=verify-full`. Use the verified Render PostgreSQL
endpoint with the custom-role username shown in bootstrap. The runtime
role must have no owner membership, superuser, BYPASSRLS, role creation or database
creation rights. The worker inherits `beforetransfer_worker`, not the API group.

Keep the credential scopes distinct:

| Service/process | Database credential | Other credentials/configuration |
| --- | --- | --- |
| API pre-deploy | Application `MIGRATION_DATABASE_URL` | Reviewed migration; shares the API service environment |
| API runtime | Application `DATABASE_URL`, inheriting `beforetransfer_api` | Supabase Auth/Storage and configured investigation/sponsor providers |
| Worker | Application `WORKER_DATABASE_URL`, inheriting `beforetransfer_worker` | Sandbox HTTPS origin and `PAYMENTS_SANDBOX_API_KEY` only |
| Sandbox pre-deploy | Separate-ledger `SANDBOX_MIGRATION_DATABASE_URL` | Explicit ledger bootstrap; shares the sandbox service environment |
| Sandbox runtime | Separate-ledger `SANDBOX_DATABASE_URL`, inheriting `beforetransfer_sandbox_api` | Its generated `SANDBOX_API_KEY` |
| Frontend build | None | `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, public `VITE_SUPABASE_PUBLISHABLE_KEY`; `VITE_LOCAL_SANDBOX=false` |

The API and worker connect to the same application database with different
restricted logins. The sandbox connects to a separate database. Its shared HTTP
key has two environment names: `SANDBOX_API_KEY` on the sandbox and
`PAYMENTS_SANDBOX_API_KEY` on the worker. The API release operator supplies the
former and the tool maps it to the worker's name. The main API and browser do
not receive this key or a ledger database credential.

Only public configuration may use `VITE_*` names. The frontend build rejects
privileged Supabase keys, non-HTTPS production origins, and the local synthetic
identity flag. Configuration presence does not prove provider authentication.

Provider settings in `.env.example` map to the API runtime as follows:

- OpenAI: `OPENAI_API_KEY` and an explicitly selected `OPENAI_MODEL` supporting
  Responses function calling. Breeth: `BREETH_API_KEY` for advisory memory.
- n8n: `N8N_WEBHOOK_URL` is the published, authenticated workflow webhook;
  `N8N_WEBHOOK_TOKEN` authenticates API-to-workflow requests.
  `N8N_CALLBACK_SECRET` is a distinct workflow-to-API credential.
  `N8N_CALLBACK_AUTH_MODE=header` is the prepared default; an explicitly configured
  `hmac` workflow must use the matching API setting. Callback timestamps and
  persisted event/attempt checks remain required in either mode. In the supplied
  Cloud workflow, edit the HTTP Request node's fixed callback origin to the actual
  public API origin. `BEFORETRANSFER_API_ORIGIN` is an optional self-hosted workflow
  convention; the Cloud template requires no `$env` access. Never derive the
  callback destination from a browser or invoice. See the [n8n runbook](n8n/README.md).
- ElevenLabs: `ELEVENLABS_API_KEY` needs voice-metadata and generation access.
  `ELEVENLABS_VOICE_ID` must resolve to an unmixed `premade` voice; configuration
  alone cannot satisfy that check. The provider now restricts default voices to
  older accounts, so new-account compatibility remains a release prerequisite.
  See the [voice report](reports/phase-07-voice.md) and [current provider notice](https://elevenlabs.io/docs/help-center/product/voices/my-voices/how-do-i-access-eleven-labs-default-voices).
- Dodo: `DODO_API_KEY`, `DODO_PRODUCT_ID`, and `DODO_WEBHOOK_SECRET` belong to the
  test environment. The adapter uses the fixed test API. The release tool sets
  `BILLING_FRONTEND_ORIGIN` to the actual frontend origin; a browser return URL
  never grants report access.

No sponsor callback credential grants database login, supplier confirmation,
beneficiary acceptance, payment approval, or transfer execution authority.

`PGSSLROOTCERT=system` works only when the actual endpoint has a trusted certificate
chain. Otherwise upload the project's verified CA as a Render secret file and
set the absolute path, for example `/etc/secrets/supabase-ca.crt`. Configure the
sandbox equivalent separately. Keep hostname and certificate verification on.
The API start command removes `MIGRATION_DATABASE_URL`; the sandbox command removes
its migration variable. The worker never receives either migration credential.
Render administrators still have access to deployment settings; process-level
removal does not create a separate secret-store access boundary.

## API release sequence

The default command is an offline, non-mutating plan:

```sh
.venv/bin/python scripts/render_release.py plan
```

Once the selected accounts and credentials are configured, validate the Blueprint
through Render's official validation endpoint. This endpoint does not provision:

```sh
.venv/bin/python scripts/render_release.py validate --env-file .env.release
```

Provision one reviewed service at a time. Render starts an initial branch build
on creation, so the tool creates inert services with no secret variables and no
application build/start commands. They do not serve the app yet. The final
configure command applies reviewed commands and verifies remote configuration;
then deploy starts the app at an explicit reviewed commit.

```sh
.venv/bin/python scripts/render_release.py create --service sandbox --env-file .env.release
.venv/bin/python scripts/render_release.py create --service api --env-file .env.release
.venv/bin/python scripts/render_release.py create --service web --env-file .env.release
.venv/bin/python scripts/render_release.py create --service worker --env-file .env.release
```

For an existing service use `adopt --service <name> --id <actual-srv-id>` instead.
The tool verifies workspace, repository, branch, service type, name and root
before recording it. If a create request times out, the journal records an
unknown outcome and refuses to create again. Inspect Render, find the service
and adopt its actual ID; do not delete the journal to bypass this protection.

Run `configure` for each service after all actual public origins are available.
The tool verifies build/start/migration settings and remote environment values,
and uses Render-returned URLs for browser API access, CORS and worker sandbox
access. It does not guess `.onrender.com` hostnames. Configuration changes take
effect on redeploy. Configure exact Supabase Auth Site URL/redirects and the
n8n/Dodo callbacks as described in their integration runbooks.

```sh
.venv/bin/python scripts/render_release.py configure --service api --env-file .env.release
.venv/bin/python scripts/render_release.py configure --service web --env-file .env.release
.venv/bin/python scripts/render_release.py configure --service sandbox --env-file .env.release
.venv/bin/python scripts/render_release.py configure --service worker --env-file .env.release
```

Then deploy the exact reviewed 40-character Git SHA with `deploy --service <name>
--commit <sha> --env-file .env.release`. Deploy sandbox/API before worker/frontend.
Check each with `status --service <name> --env-file .env.release`; the result must
be `live` at the expected commit. Request acceptance is not deployment success.
An uncertain deployment request must be checked by its actual deployment ID
before repeating a write. Do not print raw environment APIs when diagnosing it.

## Hosted checks and release evidence

`/api/health` reports process liveness. `/api/ready` checks restricted PostgreSQL,
Supabase Auth availability and the private evidence bucket. It is not proof of
working OpenAI or sponsor credentials. Missing dependencies fail protected actions
and remain visible as unconfigured in the application.

Supply actual HTTPS origins and three short-lived controlled user tokens via
`VERIFY_API_URL`, `VERIFY_WEB_URL`, `VERIFY_FINANCE_TOKEN`,
`VERIFY_SUPPLIER_TOKEN`, `VERIFY_UNASSIGNED_TOKEN`, then run:

```sh
.venv/bin/python scripts/verify_hosted.py --output artifacts/hosted-verification.json
```

The script checks access boundaries and a synthetic private-storage probe. Finish
real-provider tests using synthetic evidence only, and record provider operation
IDs without tokens, raw secrets or signed URLs:

- OpenAI investigation with valid source citations and rejected forbidden tools.
- n8n workflow delivery into the assigned supplier inbox and authenticated,
  duplicate-safe callback. Supplier confirmation remains a separate user action.
- Breeth write and later tenant-scoped advisory retrieval.
- ElevenLabs stock-voice explanation that plays in the deployed frontend.
- Dodo **test-mode** checkout, verified webhook, provider reconciliation and
  report entitlement; cancellation must remove future entitlement.
- Fake success/decline/lost-response payment execution through the hosted worker
  and independent ledger, with one persistent transfer per execution.
- Authenticated browser sign-in/sign-out, private source access, responsive layout,
  CORS, static headers, no privileged browser configuration, and deep-link refresh.

Only after these checks should the handoff be described as a verified hosted
release. Local transport tests, config presence and a green build cannot replace
these provider checks.

## Failure and rollback

A failed pre-deploy migration must block the new API release. Keep schema changes
additive and compatible with the previously running build. To roll back code,
use the release command with the previous reviewed SHA after confirming schema
compatibility; do not blindly downgrade or erase audit tables.

Stop new queueing if the ledger is unavailable. Existing UNKNOWN outcomes require
readback/operator investigation, never a replacement transfer. Provider outages
must leave payment controls intact. Review Render API/worker logs, deployment
status, database health and provider operation records without logging secrets.

## Official references

Verified during this build; account settings remain to be checked at release:

- [Render REST service creation](https://api-docs.render.com/reference/create-service)
- [Render exact-commit deploys](https://api-docs.render.com/reference/create-deploy)
- [Render OpenAPI specification](https://api-docs.render.com/docs/api-spec)
- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
- [Render environment variables and secret files](https://render.com/docs/configure-environment-variables)
- [Render pre-deploy commands](https://render.com/docs/deploys)
- [Supabase connection options](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase certificate verification](https://supabase.com/docs/guides/platform/ssl-enforcement)
