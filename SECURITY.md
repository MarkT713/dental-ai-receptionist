# Security Policy

## Supported version

Security fixes are applied to the current default branch and latest tagged release of this portfolio project.

## Reporting a vulnerability

Please use GitHub's **Report a vulnerability** / private security-advisory flow rather than a public issue when a finding could expose credentials or sensitive information. Include reproduction steps using synthetic data only.

## Deployment warning

The repository includes optional viewer/staff/manager Bearer-token authorization, strict input models, rate limiting, privacy-reduced audit events, and a hardened non-root container. These are portfolio controls—not a production identity, compliance, or clinical-safety system.

- Docker Compose binds to loopback by default.
- Do not use real patient data.
- Do not expose the app without token mode, TLS, restrictive CORS, and the controls in `docs/DEPLOYMENT.md`.
- Replace shared tokens with named users, MFA, revocation, and tenant-aware RBAC for any real service.

## Secrets

Never commit `.env`, database files, recordings, transcripts, logs, private keys, access tokens, or telephony credentials. If a credential is accidentally committed, rotate it immediately and remove it from Git history. Run:

```bash
python scripts/secret_scan.py
```

## Dependency and artifact checks

The project maintains hash-locked runtime dependencies, a CycloneDX SBOM, Dependabot configuration, and ready-to-enable CI steps for Ruff, pytest, evaluations, Bandit, pip-audit, compilation, and a non-root container smoke test.
