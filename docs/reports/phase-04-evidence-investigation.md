# Phase 4 — private evidence and bounded investigation

Local implementation is complete. Live OpenAI and hosted Supabase verification
remain pending credentials. No model accuracy or fraud-detection performance is
claimed from transport fixtures.

## Implemented

- Finance-only evidence upload and original download, with tenant RLS, server
  object paths, SHA-256 verification, private-bucket checks, and anonymous-access
  denial checks. Original response bytes are bounded before parsing and content
  encoding is rejected. Uncertain uploads are persisted; repeating identical
  content performs readback, without sending another upload.
- UTF-8 text up to 2 MiB and 40,000 extracted characters. PDF parsing runs in a
  child with an 8-second deadline, 5-second CPU limit, 192 MiB memory limit,
  20-page limit, and one concurrent parser. Scanned/encrypted documents and
  unsupported media are rejected. The API never runs the PDF parser in-process.
- Immutable document metadata, page references, investigation snapshots and
  human-review records in migration `0003_evidence_memory`.
- The OpenAI Responses adapter offers only case snapshot, document search,
  page read, deterministic comparison and advisory-memory retrieval tools.
  The model selects tools conditionally; there is no payment, approval, SQL,
  arbitrary network or role-changing tool. The loop is capped at six responses,
  eight tool calls and 90 seconds. Requests use strict function/output schemas,
  `store:false`, a configured model, and bounded raw response bytes.
- Citations must quote text actually present on the named page of a document in
  the captured case. Deterministic field mismatches cannot be omitted by model
  output. More than 80 explicit field observations produces a critical manual
  review finding; final results are schema-validated and limited to 20 findings.
- Investigations are durable before the provider call. A repeat request returns
  the existing operation. One active investigation per payment and a maximum of
  five investigations bound concurrency and model cost.
- Once a payment has evidence, a current completed investigation and explicit
  finance acknowledgement are necessary for approval and queueing. Evidence
  digests bind immutable approvals; additional sources invalidate old reviews
  and approvals. Earlier-revision sources remain in the payment evidence scope,
  so creating a new revision cannot bypass the review hold. Queue/upload races
  use the existing supplier-then-payment lock order.

## Verification performed

- Phase 3 baseline: 85 tests passed against fresh isolated PostgreSQL before
  evidence work.
- Focused evidence/payment/Auth/PostgreSQL suite: 50 passed, including actual
  RLS and concurrent transactions. This proved approval invalidation, pending
  upload holds, corrupted-original recovery, single investigation reservation,
  uncertain memory-write handling and supplier/tenant isolation.
- Final provider/parser tests after streaming changes: 8 passed, 1 skipped.
  They verify real Breeth SDK request serialization through HTTPX test
  transports, the conditional Responses loop, forbidden-tool rejection,
  fabricated-citation rejection, deterministic contradictions/coverage limits,
  UTF-8 parsing, pure parsing of a synthetic text PDF, and encoded/oversize
  provider-response rejection.
- Python compilation and whitespace checks passed. Root maintains the final
  consolidated regression and browser/full-HTTP results in the build report.

## Host limitation and remaining live checks

This macOS host rejects the attempted memory resource limits, including when
the positive test was repeated outside the execution sandbox. Protected PDF
ingestion therefore returns `pdf_resource_limits_unavailable` with guidance to
upload UTF-8 text. It does not fall back to an unbounded parser. The positive
protected-child test is Linux-only; its successful Linux/Render execution has
not been established locally. The pure parser test is separate and is not a
claim that local protected PDF ingestion works.

Hosted Supabase private Storage, a configured OpenAI model, successful Linux
protected PDF extraction and real-provider citation quality still need a live
deployment validation. No external messages or real supplier transfers were
performed. The user authorised continuation through the remaining local build
phases; this report does not authorise production deployment by itself.

Implementation follows the official [OpenAI function-calling
contract](https://developers.openai.com/api/docs/guides/function-calling).
