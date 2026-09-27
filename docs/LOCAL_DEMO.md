# PayVigil local build and review

The user chose to finish the build before supplying provider credentials. This
review environment uses generated identities, private local file fixtures and a
separate fake-transfer ledger. Its banner explicitly identifies simulated
identity and funds. OpenAI, n8n, Breeth, ElevenLabs and Dodo are not silently
simulated by the running application; their actions report missing configuration.
Provider contract tests use injected transports and do not establish live access.

## Install

Use Python 3.13.12, Node 24 and a disposable PostgreSQL 17 instance bound only to
loopback. The database account used for setup must be able to create test roles
and databases. Never give this harness a production database or business data.

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd frontend
npm ci
cd ..
```

Set `LOCAL_TEST_ADMIN_URL` securely to the loopback PostgreSQL admin URL. Do not
paste passwords into chat, source, or command history. Setup generates random
restricted-role passwords and fixture keys, stored with owner-only permissions
under ignored `.local/demo/`. It creates `beforetransfer_demo_test` and
`beforetransfer_sandbox_demo_test` and applies their separate schemas.

```sh
.venv/bin/python scripts/local_demo.py setup
.venv/bin/python scripts/local_demo.py start
```

The launcher owns only these five processes and stops them on Ctrl+C:

| Component | Loopback port |
| --- | --- |
| Frontend | 5176 |
| FastAPI | 8000 |
| Independent payment sandbox | 8001 |
| Identity/private-storage simulator | 54330 |
| Payment worker | No listening port |

It refuses occupied ports instead of stopping another application. Process logs
are private under `.local/demo/`. The current machine's isolated PostgreSQL runs
on 54329; the application launcher does not start or stop PostgreSQL itself.

Visit [the local app](http://127.0.0.1:5176). **Finance** and **Supplier** in the
local banner switch between generated identities. The local identity service is
deliberately loopback-only and permits synthetic sessions without passwords.
The switch is gated by Vite development mode, explicit fixture configuration and
loopback origins; production builds reject it. Do not expose these local fixture
services through a tunnel or use them as production authentication.

## Review the payment workflow

1. As Finance, inspect the seeded draft and its holds.
2. Switch to Supplier. Confirm the displayed destination version with the
   acknowledgement checkbox.
3. Switch back to Finance → Supplier records. Accept that specific version.
4. Open the payment. Inspect INR amount, invoice, destination and full approval
   fingerprint. Acknowledge and approve the exact snapshot.
5. Queue the sandbox transfer. The worker persists and submits once, then
   independently reads the ledger result before reporting success.
6. Create another intent with **Lost response** selected. It enters UNKNOWN,
   holds edits/replacement, and later reconciles to the same persisted transfer.
7. Select **Decline** for a third intent to inspect the terminal rejection.
8. Revise an approved draft before queueing; the previous approval no longer
   applies. Changes after execution is queued are rejected.

The seeded invoice is created only once. Verification may already have completed
it. Create a fresh unique synthetic invoice for another walkthrough. Audit
history is append-only. The local fixture databases retain review actions.

## Review evidence and providers

Use the six labelled [synthetic documents](../fixtures/evidence/README.md) with a
new `SYN-EVIDENCE-001` draft. Private upload/source inspection works with local
storage. Model investigation, n8n delivery, Breeth memory, ElevenLabs audio and
Dodo test checkout require the corresponding real API credentials. Their absence
must appear clearly as unconfigured; it is not a successful integration check.

Use UTF-8 `.txt` sources on this Mac. Its operating system rejects the hard memory
limit required by the protected PDF subprocess, so PDF requests fail clearly.
The Linux path retains the memory/CPU/time limits and has a separate CI test;
successful protected PDF extraction still needs Linux/Render verification.

The fixture launcher intentionally overrides external provider credentials with
empty values. Later, run the normal API with securely configured real providers
for provider validation; retain synthetic test documents and destinations.

## Repeatable verification

```sh
.venv/bin/python scripts/check.py --postgres
.venv/bin/python scripts/verify_local_workflow.py
.venv/bin/python scripts/verify_local_evidence.py
```

The first command provisions fresh, randomly named disposable local test databases
and roles, migrates them, runs backend/provider/ledger/release tests, then frontend
checks and build. It preserves test history for diagnosis and records generated
resource names in `artifacts/build-checks.json`; it does not print passwords.
The second and third commands require the local demo running and perform synthetic
HTTP mutations against loopback only. They record `artifacts/local-workflow.json`
and `artifacts/local-evidence.json`. Evidence checks include original hash readback,
tenant denial, stale-revision holds and missing-provider failure behavior.
None of these commands contacts a real payment provider to move supplier funds.
