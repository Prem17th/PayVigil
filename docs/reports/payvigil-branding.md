# PayVigil branding and Git configuration

Date: 2026-09-27

## Scope and changes

The user selected PayVigil as the product name and requested maintainer
`Prem T H` (`Prem17th`) with repository `Prem17th/Payvigil`.

- Updated frontend wordmark, favicon letter, browser titles, sign-in copy,
  billing copy, downloaded-report prefix and package metadata to PayVigil.
- Updated API/sandbox display titles, hosted frontend verification, current
  documentation, operator messages, and n8n workflow/credential display labels.
- Changed the default prefix for future Render services to `payvigil` and updated
  matching Blueprint references. No Render resources were created or renamed.
- Configured local Git origin as `https://github.com/Prem17th/Payvigil.git`.
- Render's repository setting continues to require the credential-free HTTPS
  form: `https://github.com/Prem17th/Payvigil`.

## Compatibility

Existing PostgreSQL schemas, roles and databases, the private storage bucket,
health service discriminator, n8n paths/headers, Dodo metadata, memory namespaces,
environment variable names, and historical reports retain their original
`beforetransfer` identifiers. This branding change requires no data migration.
No credentials were changed, printed, staged or committed.

## Validation

- Existing frontend tests passed, including amount/download/checkout and
  security configuration guards.
- Frontend TypeScript/Vite production build passed.
- Backend API tests: 11 passed.
- Render release-tool tests: 25 passed.
- n8n JSON parses and remains inactive; Blueprint service references match the
  four new service names and preserve the existing storage bucket.
- SSH authentication succeeded for the requested GitHub account. The default
  `github.com` SSH host failed; the configured account alias succeeded.

## Remaining work

The GitHub repository has been configured and migrated to
`Prem17th/Payvigil`.
Provider verification and public deployment remain pending. The previously
identified ElevenLabs default-voice compatibility issue also remains open;
branding checks do not establish live-provider readiness.
