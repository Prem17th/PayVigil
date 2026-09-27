# Security reporting for PayVigil

PayVigil currently implements a supplier-payment investigation prototype with a
synthetic transfer ledger. Local test results and adapter implementations do not
establish a verified public production release. See the current [build status](README.md)
and [release runbook](docs/DEPLOYMENT.md) for the verification boundary.

## Report a vulnerability privately

If this repository has GitHub private vulnerability reporting enabled, open its
**Security → Advisories → Report a vulnerability** flow. Include the affected
revision, impact, preconditions, and a minimal synthetic reproduction. Do not
include real credentials, personal records, invoice evidence, or exploitable
customer data. [GitHub's reporting instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately)
describe the private flow.

If that button is unavailable, open an issue asking the maintainer to enable
private reporting or provide a private contact channel. Include no vulnerability
details, proof of concept, or sensitive data in that public request. This file
does not claim that private reporting is already enabled, promise a response
deadline, or establish a bounty or disclosure agreement.

## Relevant boundaries

Report suspected tenant isolation failures, identity or membership bypasses,
unauthorised evidence access, stale or mismatched payment approval, duplicate
execution, callback replay, provider-controlled authority, and secret exposure.
Investigate only systems and accounts you are authorised to test, using synthetic
data and controlled endpoints. Keep findings out of public issues and CI logs.

When a credential may have been exposed, its authorised owner should revoke or
rotate it in the issuing provider and update the managed configuration. Removing
the value from the current file does not remove it from Git history or revoke its
access. Coordinate any history rewrite and service recovery with the maintainer;
do not upload scanner reports containing sensitive values.
