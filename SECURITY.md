# Security Policy

## Reporting vulnerabilities

If you discover a security vulnerability in Interpres, please report it privately by email to the repository owner. Do not open a public issue.

## Secrets and credentials

- Never commit API keys, tokens, or passwords
- Use `.env` for local secrets (git-ignored)
- Use `.env.example` to document required environment variables
- Configuration files contain model names and settings, never secrets

## Provider safety

- Model providers are untrusted external services
- The pipeline fails closed when providers are unavailable
- Fallback models are configured explicitly, never substituted silently
- Witness responses are validated locally before any downstream stage

## Audit integrity

- Raw model responses are immutable
- Stage outputs are content-addressed
- Tampering with cached records invalidates downstream provenance
- The audit trail is append-only

## Data handling

- Corpus data may have separate licenses (see `docs/data-and-licensing.md`)
- Review artifacts may contain sensitive human review data
- Do not publish review artifacts without reviewer consent
