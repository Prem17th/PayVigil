# Phase 9 — local build and release readiness

Date: 2026-09-27. **Local implementation and verification are complete within
the agreed credential-free scope. The project is ready for deployment setup,
not a verified public production release.** All earlier phase reports remain
available through [the phase plan](../PHASE_PLAN.md).

The user authorised all remaining build phases, requested environment/managed
secrets, and explicitly deferred credentials until after the build. No provider
credits, external messages, real charges or bank transfers were used. The user's
dedicated hosted database was subsequently configured and verified; no Render
application services were created. The local preview remains available at
[127.0.0.1:5176](http://127.0.0.1:5176) while its launcher is running.

## Project and AI agent

BeforeTransfer investigates conflicting supplier-payment instructions for Indian
MSMEs. The selected event-brief track is **Track 3 — Bharat Business: AI for MSMEs
& Workers**. It is a synthetic-transfer prototype, with no real banking rail.

One bounded OpenAI Responses investigation agent is implemented. It selects from
five read-only tools: case snapshot, document search, page read, deterministic
field comparison, and Breeth prior-case context. It returns findings with exact
source quotations, limited to documents captured for the current investigation.
Six response rounds, eight tool calls and a 90-second deadline bound the loop.
Unconfigured providers never return invented successful investigations.

Supplier attestation, finance acceptance of a beneficiary version, human review
of evidence, exact payment approval and execution remain separate. The agent,
memory, voice, delivery and billing integrations cannot approve or move funds.
The worker submits only approved synthetic transfers to a separate persistent
ledger and independently reads results back. Unknown outcomes block replacement.

## Completed local deliverables

- React finance workspace, assigned supplier portal, evidence upload/source
  preview, investigation findings/tool trace/review, advisory memory, audio,
  Dodo test billing/report controls and honest configuration indicators.
- FastAPI routes with verified identity, tenant RLS, immutable financial
  revisions, append-only audit, evidence-bound approvals and a persistent worker.
- Five application migrations through `0005_managed_owner_bootstrap`; separate sandbox schema,
  runtime credentials and ledger. Readiness checks current tables and permissions.
- Real provider adapters for OpenAI, n8n, Breeth, ElevenLabs and Dodo, exercised
  through controlled transports. Missing settings fail clearly before a call.
- Importable inactive n8n Cloud workflow, using separate managed Header Auth
  credentials, a fixed callback origin and durable version/attempt receipts.
- Four-service Render Blueprint and REST tool: offline plan, validation,
  creation/adoption, configuration, exact-commit deployment and status readback.
  Creation uses inert commands and no secrets; configuration checks remote
  identity/settings before uploading allowlisted environment values. An exclusive
  journal lock prevents concurrent provisioning commands from duplicating resources.
- GitHub CI definition for fresh PostgreSQL migrations, backend/provider/ledger
  tests and frontend production checks. The workflow is prepared, not claimed run.
- Supabase bootstrap, deployment/runbooks, six labelled synthetic documents,
  ignored private local setup, and separate phase 1–9 reports.

## Verification actually performed

The final fresh-database aggregate run completed:

| Check | Result |
| --- | --- |
| Backend, PostgreSQL and provider-contract tests | 169 passed; 1 Linux-only PDF test skipped |
| Render REST release and database-preflight tests | 56 passed |
| Separate sandbox HTTP persistence/restart tests | 5 passed |
| Frontend INR, checkout URL, binary-response, uncertain-write and configuration boundaries | Passed |
| TypeScript and Vite production build | Passed |
| Production frontend configuration guard suite | Passed |
| Installed Python dependency consistency | No broken requirements |

The backend count includes the sponsor and voice tests; do not add phase-report
counts to it. Local Python 3.13.12/PostgreSQL 17 were exercised. The installed
Node runtime was 25.7; CI/Render are configured for Node 24, whose hosted build
still needs verification.

The running synthetic stack also passed **40 payment HTTP checks** and **29
evidence/provider-boundary HTTP checks**. Coverage includes concurrent queue
convergence, stale approvals, independent success/decline/lost-response readback,
private-original hash checks, tenant denial, evidence holds across revisions,
unconfigured-provider failures and unsigned callback denial.

Browser checks verified finance/supplier switching, evidence upload and preview,
current/previous-revision source labels, blocked approval awaiting investigation,
supplier inbox, disabled unconfigured checkout and configuration status. The
390-pixel mobile evidence view had no horizontal overflow. Browser console
inspection returned no warnings/errors. Live model findings, provider audio and
paid report success were not fabricated for screenshots.

Local evidence is saved under ignored `artifacts/`: `build-checks.json`,
`local-workflow.json`, `local-evidence.json`, `final-evidence-desktop.png`,
`final-evidence-mobile.png` and `final-payment-hold-detail.png`. Generated keys,
database passwords, local logs and identity files stay under ignored `.local/`.

## Known limitation

This Mac rejects the OS memory limit required by the PDF subprocess. UTF-8 text
upload works; PDF requests return actionable `pdf_resource_limits_unavailable`.
The parser does not run without protection. Pure synthetic text-PDF parsing was
tested separately, but protected-child success still needs Linux/Render testing.
The Linux-only test remains in CI. Scanned/image/encrypted PDFs are unsupported.

## Remaining before public release

After the credential-free build, the user supplied a dedicated Render PostgreSQL
target. Its connection is saved only in ignored owner-only `.env.release`.
Read-only verification succeeded with full certificate verification: TLS 1.3,
PostgreSQL 18.6, initially empty database, CREATEROLE/CREATEDB owner without BYPASSRLS.
Hosted migrations then reached `0005_managed_owner_bootstrap`; separate API,
worker and ledger runtime accounts were provisioned, with a separate ledger
database. **13 hosted verification checks passed**, including all 20 application
tables forcing RLS and API/worker denial of ledger-table access. No memberships
or transfers were created. Password rotation before public release remains
outstanding. See [the hosted database report](hosted-database-setup.md).

1. Select the Render workspace, service plan, accessible Git repository/branch
   and reviewed commit. The current workspace has uncommitted source and no
   release commit; the tool will not replace a commit with a branch name.
2. Configure hosted Supabase Auth/private Storage and controlled memberships and
   supplier mappings. The Render databases and restricted runtime roles are
   already prepared; verify them again after any credential rotation.
3. Add the actual provider and Render credentials through managed secrets or an
   ignored owner-only environment file. All five required sponsor integrations
   remain live-unverified; configuration indicators deliberately say so.
4. Validate the Blueprint, provision/adopt resources, set actual origins and
   callbacks, deploy the reviewed commit and verify each service is live at it.
5. Run hosted access/Storage checks and real provider checks using synthetic
   cases: OpenAI citations, n8n delivery, Breeth write/retrieve, ElevenLabs stock
   audio, Dodo test checkout/webhook/cancellation, Linux PDF and worker readback.
6. Review account backup/restore settings and deployment evidence before treating
   this prototype as a publicly verified release.

See [deployment commands](../DEPLOYMENT.md), [local reproduction](../LOCAL_DEMO.md)
and [Supabase bootstrap](../../supabase/bootstrap.md). No further local phase
approval is required; credentials and hosted verification are the next work.
