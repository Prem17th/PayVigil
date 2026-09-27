# Phase 3 — payment authority and independent sandbox

Date: 2026-09-27. Local implementation and integrated workflow verified.
Hosted verification remains deferred while the user supplies credentials later.
The user authorised continuing all remaining local build phases.

## Delivered

- Immutable supplier destinations, assigned supplier attestations, separate
  finance acceptances, versioned INR payment intents and expiring exact approvals.
- Canonical invoice uniqueness, tenant isolation, append-only history and
  restricted API/worker roles. Changes invalidate previous approval.
- Transactional execution outbox, worker leases and stable idempotency keys.
- Independent PostgreSQL sandbox ledger with success, decline and deliberately
  lost responses. Unknown outcomes use GET readback and block replacement; they
  never trigger a second POST from the worker.
- Finance payment/supplier screens and a supplier-only confirmation portal.
- A loopback-only synthetic identity/storage harness with generated ignored
  credentials. Production frontend builds reject the local identity switch.

## Verification actually run

- Eighty-five backend tests passed against a fresh isolated PostgreSQL database,
  including role restrictions, tenant boundaries, expiry, stale revisions,
  concurrent queue/worker claims and immutable history. Two test fixture cleanup
  issues were fixed by settling queued fixtures through the actual state machine.
- Five sandbox tests against an isolated real PostgreSQL database and actual HTTP
  server: concurrent identical requests, conflicting replay, decline, authentication,
  immutable ledger permissions, timeout, delayed visibility and server restart.
- Seventeen worker checks covering exact readback, malformed fields, redirects,
  timeouts and the prohibition on POST retries for unknown outcomes.
- Forty complete local HTTP workflow checks recorded in
  `artifacts/local-workflow.json`. Each success/decline/lost-response scenario
  included six concurrent queue calls converging on the same execution, stale
  approval rejection, tenant denial and terminal replay. The lost-response case
  visibly entered UNKNOWN, blocked edits and replacement, then reconciled.
- Browser: supplier confirmation → finance acceptance → exact approval → queued
  transfer → independently verified success. No JavaScript warnings/errors were
  observed. Desktop 1280 and mobile 390 layouts had no horizontal overflow.
- Frontend TypeScript and production build passed, with eleven INR conversion
  boundary cases and six build-security guards. Production output excludes the
  local identity-switch endpoint and banner.
- Private storage simulator upload/read/anonymous denial/delete passed. A route
  ordering defect discovered in that simulator was corrected and the complete
  workflow rerun successfully.

Screenshots are in `artifacts/phase3-desktop.png` and
`artifacts/phase3-mobile.png`. Artifacts are ignored generated local evidence.
Database authority-suite results are included in the final consolidated report.

## Limits and next work

All payments use invented SIM destinations and fake funds. Supplier confirmation
does not prove bank-account ownership. This phase does not implement real payment
rails. Local identities/storage are explicitly labelled provider simulators.
No live Supabase or Render access is claimed. Continue phases 4–8 integrations
and phase 9 release preparation under the user's existing authorisation.
