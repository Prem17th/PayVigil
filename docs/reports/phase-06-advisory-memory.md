# Phase 6 — Breeth advisory memory

The real Breeth adapter and local contract tests are implemented. Live write and
retrieval verification remain pending `BREETH_API_KEY`; no simulated response is
reported as provider success.

## Implemented

- Uses the installed official `breeth==0.1.0` `AsyncBreethClient.write` and
  `retrieve` methods at the fixed `https://api.thebreeth.com` origin. The SDK is
  supplied a bounded HTTP adapter with redirects disabled and raw-byte limits.
  Blank credentials fail before SDK construction, including in the local demo.
- Tenant memory groups are opaque server-derived identifiers. Provider write
  receipts and retrieval cache scope must match that group.
- Only current, completed, human-reviewed investigations can initiate a write.
  Exported prose is generated from a finite finding-code vocabulary. It does
  not copy document text, account IDs, names, contacts, invoice references,
  model prose or review notes. Retrieval is bounded and explicitly advisory.
- PostgreSQL stores the write operation before the network request, including
  investigation ID, evidence digest, document provenance, and exported text.
  Unknown write outcomes remain unknown; repeated requests return the same
  operation and never blindly send another non-idempotent write.
- The model may request advisory prior-case retrieval as a read-only tool.
  Memory cannot change financial fields, supply a current-source citation,
  approve a beneficiary, clear a payment hold or execute a transfer.

## Verification performed

Local tests exercise the actual SDK serialization against controlled HTTPX
responses, provider-group validation paths, finite privacy-preserving export,
unconfigured-provider failures, and PostgreSQL persistence of a lost-response
write. Repeating that uncertain write produces one provider attempt and the
same operation ID. These checks are included in the focused suite and provider
test results recorded in the Phase 4 report.

The next live check must write one reviewed redacted synthetic case and retrieve
it later through the configured Breeth account, recording actual provider
evidence. The [official Python SDK
documentation](https://docs.thebreeth.com/docs/sdks/python) and installed SDK
signatures were inspected; documentation inspection is not live verification.
