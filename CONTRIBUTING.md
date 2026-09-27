# Contributing to PayVigil

Read [AGENTS.md](AGENTS.md) for the product and authority boundaries. Keep changes
focused, preserve existing data/protocol compatibility, and use synthetic fixtures
for development. Product naming does not rename provisioned `beforetransfer`
schemas, roles, storage buckets, or protocol identifiers.

## Local setup

Use the Python and Node versions in [.python-version](.python-version) and
[.node-version](.node-version), plus a disposable loopback PostgreSQL 17 instance.
Create the virtual environment, then install the pinned Python requirements and
frontend lockfile:

```sh
python3.13 -m venv .venv
make install
```

The application database, identity, private evidence storage, and synthetic ledger
have separate responsibilities. Follow [the local runbook](docs/LOCAL_DEMO.md);
never point its setup or tests at a production database.

## Verification

Configure `LOCAL_TEST_ADMIN_URL` through your local secret manager or protected
environment. It must identify a disposable loopback PostgreSQL administrator;
the checks create fresh test databases and restricted roles. Do not put a password
in source, a shell command, or a pull request.

```sh
make check
```

This runs migrations, tenant/authority controls, provider contracts, independent
ledger HTTP checks, frontend boundary tests, a production build, and configuration
guards, after the Python formatting and basic correctness checks. `make lint`
runs only those Ruff checks. `make check-fast` omits the real PostgreSQL and ledger checks and is only
an iteration aid. Linux CI additionally exercises the protected PDF subprocess;
the macOS limitation is documented in the runbook. Test results do not establish
working cloud credentials, live provider integrations, or a public deployment.

## Change structure

- `frontend/` owns the React interface and browser configuration boundaries.
- `backend/app/` owns authentication, domain services, provider adapters, and API
  routes; `backend/migrations/` owns application schema changes.
- `sandbox_service/` owns the separate synthetic ledger. Keep its credentials and
  database permissions separate from the main application.
- `scripts/` contains explicit setup, verification, and release commands.
- `docs/` contains runbooks and dated reports. Preserve historical evidence;
  record new verification instead of rewriting an old result.

Add meaningful regression coverage when changing authority, tenant isolation,
external side effects, parsing limits, or uncertain-outcome handling. The model,
memory, voice, billing, and delivery providers must never acquire payment approval
or execution authority. Keep supplier confirmation, beneficiary acceptance, and
exact payment approval separate.

Update the frontend lockfile with dependency changes. Keep Python dependency
versions explicit and check installed dependency consistency. GitHub Actions are
pinned to reviewed commit SHAs; Dependabot proposes updates without merging them.
Python uses the pinned Ruff version in the development requirements, with the
formatter and the basic `E4`, `E7`, `E9`, and `F` checks configured in
`pyproject.toml`. Review fixes before applying them: imports used for model or
adapter registration may need a documented narrow exemption rather than removal.
The Gitleaks binary version and SHA-256 checksum are pinned in the secret-scan
workflow; verify both against its official release when updating.

## Pull requests and secrets

Explain the resulting behavior, relevant checks, migration requirements, and
remaining limitations. Do not add real invoices, personal data, access tokens,
signed URLs, private keys, or credentials. Example environment files contain empty
credential fields; private local files and generated artifacts stay untracked.

CI scans fetched Git history with redacted Gitleaks output. A passing scanner is
additional evidence, not a guarantee that every credential pattern is detected.
Review the staged diff before pushing, and use [SECURITY.md](SECURITY.md) for
suspected exposure. Do not suppress a finding simply to pass CI.

CI has read-only repository permission and does not deploy. Render releases remain
explicit operator actions against a reviewed commit and selected resource journal;
see [deployment](docs/DEPLOYMENT.md). Branch protection and private vulnerability
reporting are repository settings and are not enabled by these files alone.
