# Implementation phases

## Review rule

The latest user instruction authorises all remaining implementation phases,
with phase reports retained and no intermediate approval stops. Build locally
first; credentials will be supplied later. Prepare the Render API release flow
and report remaining live verification prerequisites clearly. No recurring
automation is configured.

## Current status

- Product branding: renamed to PayVigil; intended GitHub repository is
  `venupyneni07/payvigil`. Local SSH authentication and branding checks passed;
  see [the branding report](reports/payvigil-branding.md).
- Public repository: the user authorized public source publication without
  secrets. Domain packages, CI, repository guidance and publication checks are
  prepared; see [the public-source preflight](reports/public-repository-preflight.md).
  Public source publication does not establish hosted application readiness.
- Phase 1: complete; reviewed by the user.
- Phase 2 local foundation build: complete; reviewed by the user. See
  [the local build report](reports/phase-02-local-build.md). The latest user
  instruction defers production deployment until after local build review.
- Phase 2 hosted database setup: user supplied and confirmed a dedicated Render
  PostgreSQL target after the local build. Migrations, restricted runtime roles
  and a separate ledger database are verified; see [the database report](reports/hosted-database-setup.md).
  Public application hosting, Supabase Auth/Storage and provider verification remain pending.
- Phase 3: local payment controls and independent sandbox integrated; 40 HTTP
  workflow checks and browser confirmation-to-transfer flow passed. See
  [the phase 3 report](reports/phase-03-payment-authority.md).
- Phase 4: local evidence/agent implementation and tests complete; see
  [the phase 4 report](reports/phase-04-evidence-investigation.md). Live model and
  hosted Storage checks remain; protected PDF extraction needs Linux verification.
- Phase 5: n8n adapter, Cloud import workflow and local tests complete; see
  [the phase 5 report](reports/phase-05-delivery.md). Live import/delivery pending.
- Phase 6: Breeth SDK adapter and local tests complete; see
  [the phase 6 report](reports/phase-06-advisory-memory.md). Live memory checks pending.
- Phase 7: ElevenLabs adapter and local tests complete; see
  [the phase 7 report](reports/phase-07-voice.md). Actual audio generation pending.
  Current provider documentation restricts old default voices to older accounts;
  the adapter's premade-only check needs compatibility review for new accounts.
- Phase 8: Dodo test billing/entitlements and local tests complete; see
  [the phase 8 report](reports/phase-08-billing.md). Live test checkout pending.
- Phase 9: local integration checks, browser review, CI and Render REST release
  preparation complete; see [the final local report](reports/phase-09-local-release-readiness.md).
- Live provider verification and public Render deployment await credentials
  that the user will add after the build.

| Phase | Scope | Reviewable result and exit evidence |
| --- | --- | --- |
| 1. Workspace and readiness | Inspect repository, local tools, configuration presence, provider requirements, and boundaries. | Saved readiness report, phase plan, working instructions, and secret exclusions. |
| 2. Foundation, then deployment | First build and verify React/FastAPI locally with environment configuration, migrations, access controls, and Supabase adapters. Stop for review. After separate approval, connect hosted Supabase and deploy Render with managed secrets. | Local build report and isolated test evidence first. Separate production report must include live Auth/Storage checks and verified Render URLs. |
| 3. Payment authority and sandbox | Add supplier versions, payment intents, separate confirmation/acceptance/approval records, transactional execution, outbox/worker, and independent sandbox. | Synthetic cases prove exact approval binding, stale approval rejection, concurrent-request handling, and uncertain-outcome reconciliation. |
| 4. Document evidence and investigation agent | Add private ingestion, source-linked extraction, bounded tool calling, persisted investigation state, and evidence workspace. | Real model calls investigate contradictory evidence; uncertain fields remain in review; injected document instructions cannot obtain payment authority. |
| 5. n8n confirmation delivery | Connect finance-approved requests to controlled test inbox/portal delivery, callbacks, reminders, and supplier response handling. | Real n8n execution and delivery evidence, authenticated callback, duplicate handling, and a supplier response that remains separate from payment approval. |
| 6. Breeth investigation memory | Integrate the verified Python SDK, redaction, server-selected scope, and prior-case retrieval. | Real memory write and later retrieval with recorded source context; stale memory cannot override current payment records. |
| 7. ElevenLabs explanations | Generate and play a redacted case explanation using a stock voice. | Real provider-generated audio plays in the deployed application; text and payment controls remain usable on audio failure. |
| 8. Dodo subscription billing | Add a test subscription, checkout, verified webhooks, reconciliation, and premium report entitlement. | Real test-mode subscription changes a report entitlement; webhook failures, duplication, and cancellation cannot change payment authority. |
| 9. Integrated validation and demo | Exercise the deployed workflow, complete integration evidence, fix issues within scope, and document the demonstration. | Required tests, provider evidence, deployed demo, known limitations, and final handoff. |

## Reporting format

Every phase report records:

1. Objective and authorised scope.
2. Work completed and changed files.
3. Checks actually run and their results.
4. What remains unverified or blocked.
5. External access needed for the next phase.
6. Next phase and any deferred live checks. Continue authorised local work.

## Fixed product boundaries

- One business, a few synthetic suppliers, INR, one full payment per invoice.
- Real sponsor calls; clearly labelled simulated supplier transfers.
- Separate supplier attestation, beneficiary acceptance, and payment approval.
- PostgreSQL owns financial and authorisation state.
- Breeth context is advisory; n8n delivers approved requests; ElevenLabs explains;
  Dodo handles SaaS billing only.
- Render deployment is prepared, but deferred until separately authorised after
  local build review, following the user's revised sequence.
- Dependency versions and SDK contracts must be validated during the phase that
  introduces them; a proposed stack is not a compatibility guarantee.

## Completion standard

A phase requiring an external integration cannot be called fully complete
without its stated real-provider verification. The user explicitly authorised
continuing the whole build while deferring credentials. Report local completion
and exact remaining live checks separately, retain unresolved items in this plan,
and continue the remaining authorised local phases.
