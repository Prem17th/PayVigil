# PayVigil frontend

React, TypeScript, Vite, and Tailwind. Local development uses port 5176 and an
explicit Vite proxy from `/api` to the loopback API on port 8000.

Run `npm ci`, `npm run dev`, `npm test`, and `npm run build` from this directory.
Browser-safe configuration names are documented in `.env.example`; provide
values through ignored environment files or managed build settings. Never use
a Supabase secret/service-role key in the frontend. Production builds reject
privileged keys, unsafe origins, and the local identity flag.

## Local payment workflow

Finance uses **Payment authority → Supplier records** to propose a synthetic
beneficiary. Its assigned supplier confirms the exact version in the separate
supplier portal. Finance then accepts that version, creates an INR payment
intent, reviews the immutable snapshot, explicitly approves it, and queues a
sandbox transfer. Only server-returned allowed actions expose controls.

The workspace shows current revisions, approval expiry, holds, execution IDs,
independent readback status, and audit events. A revised payment requires fresh
approval. Queued, submitting, and unknown executions are read every four seconds
for up to two minutes; this polls status and never retries transfer submission.
An unknown outcome has no replacement-transfer action.

## Synthetic identity harness

The root project's local harness may supply `VITE_LOCAL_SANDBOX=true` and a
loopback identity fixture through environment configuration. The switch exists
only in Vite development mode when the page, identity fixture, and any explicit
API origin are loopback. It requests a fixture session and passes it through
`supabase.auth.setSession`; backend token verification and database membership
remain enforced. A persistent banner labels the identity and funds as
simulated. This does not verify a hosted Supabase integration.

Disable the local flag and provide HTTPS production origins for a production
build. The fixture switch is removed from a normal production bundle.

## Verification scope

`npm test` checks exact INR-to-paise conversion, rejection of unsupported amount
forms, the sandbox amount cap, and six build-time security boundaries. TypeScript
and a production bundle are checked by `npm run build`. End-to-end authority,
tenant isolation, sandbox HTTP execution, and browser walkthrough evidence are
reported by the root project; the frontend does not establish those guarantees
by itself.

## Evidence and provider interfaces

Finance has an **Evidence & investigation** workspace for payment-revision-bound
text/PDF evidence, escaped source previews, authenticated original downloads,
source quotations and page citations, a read-only tool trace, and explicit human
review. An investigation must match the current payment revision and a
server-confirmed current evidence snapshot before the UI enables review.
Provider calls stay disabled when configuration is absent or unavailable.

Supplier records include a separate finance-approved n8n delivery request;
supplier accounts receive only their assigned inbox records. Reviewed
investigations expose advisory Breeth memory and ElevenLabs stock-voice audio.
Audio is fetched with the bearer token, kept in a bounded Blob, and revoked on
replacement or unmount. Original evidence and reports use authenticated,
size-limited downloads; provider text is never rendered as HTML.

**Subscription & reports** uses server-configured Dodo test checkout and
authoritative subscription reconciliation. Returned checkout links must match
the exact approved Dodo HTTPS hosts. Downloading a report remains subject to the
server's current entitlement check. Billing never controls payment safety.

**Connections** reports configuration presence separately from recorded live
provider verification. Building these interfaces does not verify the providers.
