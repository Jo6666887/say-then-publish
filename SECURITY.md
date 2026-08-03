# Security Policy

## Never commit credentials

Keep all server credentials in the ignored local `.env` file. This includes:

- Supabase server credentials
- object-storage access credentials
- optional AI service credentials
- deployment usernames, passwords, certificates and private keys

Do not paste real values into issues, pull requests, screenshots, project JSON,
CLI examples or documentation.

If a credential was ever committed, removing it from the latest file is not
enough. Rotate it first, then clean the Git history before making the repository
public.

## Local-first default

The application works without cloud credentials. Projects are stored under
`runtime-data/` and browser-local databases. These locations are Git-ignored and
blocked by the static-file allowlist.

## Public deployment

The default service is intended for loopback access. A public deployment must
use an exact host allowlist, authentication and TLS. Never expose a credentialed
or unauthenticated local data service directly to the internet.

## Reporting a vulnerability

Please open a GitHub security advisory for vulnerabilities that could expose
projects, assets or server credentials. Avoid placing sensitive reproduction
data in a public issue.
