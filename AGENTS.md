# PayVigil working instructions

## User-controlled phases

The user initially requested phase-by-phase review. Their latest instruction
authorises completing ALL remaining build phases without stopping between them,
then reporting readiness for public deployment through Render APIs. They also
explicitly chose: "Build first; I’ll add credentials later."

- Phases 3–9 implementation and local validation are now authorised.
- Finish that phase's reviewable deliverables and verification.
- Save a report in `docs/reports/` describing changes, checks, limitations,
  external dependencies, and the proposed next phase.
- Update `docs/PHASE_PLAN.md` and continue to the next build phase.
- Preserve separate phase reports, but no intermediate approval gate is needed.
- Provider credentials and real integration checks are deferred. Build adapters,
  controlled local fixtures, and meaningful tests; label all simulated behavior.
- Do not claim public-deployment readiness without distinguishing code/build
  readiness from the outstanding secrets, live checks, and deployment actions.
- Corrections to a completed phase remain within that phase.

## Product and authority

PayVigil investigates supplier-payment instructions for an Indian MSME.
The LLM interprets evidence; authenticated humans accept beneficiary changes and
approve payments; deterministic backend code enforces execution.

Keep supplier confirmation, finance acceptance of a beneficiary change, and
approval of one exact payment separate. Supplier confirmation is not proof of
bank-account ownership. Payment execution is an explicitly labelled sandbox.

## Required integrations

All five are required for final project completion:

- Render: early deployment and application hosting.
- n8n: approved, server-addressed confirmation delivery and reminders.
- ElevenLabs: spoken, redacted case explanations using a stock voice.
- Breeth AI: advisory investigation memory. The correct provider is Breeth at
  `thebreeth.com`, with official docs at `docs.thebreeth.com`.
- Dodo Payments: test-mode SaaS subscription billing and report entitlements.

The user subsequently supplied and confirmed a new, dedicated Render PostgreSQL
database for the application. Supabase still supplies Auth and private Storage.
Use the supplied external database target only through ignored/managed secrets;
never reproduce its credentials in source, reports or chat. The application
uses React/Vite/TypeScript, FastAPI/Pydantic/SQLAlchemy/Alembic, OpenAI Responses,
and a PostgreSQL-backed worker. Verify dependency compatibility before pinning.

## Non-negotiable boundaries

- The agent, memory service, voice service, billing provider, and n8n cannot
  approve beneficiaries, approve payments, clear holds, or execute transfers.
- Payment approvals bind to immutable versions. Material changes require fresh
  approval. An unknown execution result blocks a replacement payment.
- Preserve tenant isolation, server-side authorisation, idempotency, and
  independent payment readback.
- Use synthetic fixtures and controlled test destinations. Do not send external
  messages, redeem one-time credits, create live charges, or move real supplier
  funds without explicit authorisation for those actions.
- Do not print secrets, commit credentials, or ask for API keys in chat.
- A mock, adapter, or documentation check is not a verified provider integration.
- Missing external access must be reported accurately; it does not justify
  silently replacing a required provider.

## Production foundation

The user requires environment variables or managed secrets. Their latest
instruction is to finish the local build first and review it before continuing
to production. Render and hosted Supabase remain the production targets.

- Never embed credentials in source, deployment manifests, frontend bundles,
  fixtures, or documentation. Example environment files contain empty values.
- Supply server secrets through Render environment settings or secret files.
  Only Supabase publishable configuration belongs in the frontend.
- Separate privileged migration credentials from the restricted runtime role.
- Require TLS, explicit frontend origins, verified identity, and database-backed
  roles. Missing dependencies must fail readiness and protected operations.
- Isolated automated tests may run locally with synthetic data. Their success
  does not establish a successful hosted deployment or provider verification.
- Report local builds separately from deployment. Prepare Render API release
  tooling, but do not invent credentials or treat local fixtures as live services.
- Never describe local tests as a verified Render/Supabase deployment.

## Current state

The user selected PayVigil as the product name and venupyneni07 as the GitHub
owner and explicitly authorized creating a public repository and pushing the
code without secrets. Use payvigil for the repository and new Render service prefix.
Maintain the domain-oriented backend packages, checked CI gates and documented
release boundaries. Public source publication is not a verified hosted deployment.
Retain existing beforetransfer database/role/storage names, protocol identifiers,
environment variable names and historical reports for compatibility.

See `docs/PHASE_PLAN.md` and the latest report before beginning work.
