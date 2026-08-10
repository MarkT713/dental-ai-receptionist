# Privacy Design

This repository contains **synthetic demonstration data only**.

## Public-release rules

- Never commit `.env` files, API keys, phone-carrier credentials, recordings, transcripts from real callers, databases, logs, or screenshots containing real people.
- Use NANP reserved fictional numbers in the `202-555-01xx` range.
- Treat names, dates of birth, phone numbers, call audio, transcripts, appointment reasons, patient alerts, and scheduling records as potentially sensitive.
- The cloud-model path is disabled by default and requires `ALLOW_CLOUD_SYNTHETIC_DATA=true`.
- Audit payloads redact names, phones, DOB, reasons, transcripts, and staff notes; request logs contain route templates and operational metadata only.
- `scripts/secret_scan.py` rejects common credential patterns, private project paths, databases, and non-example `.env` files before release.

## This is not a compliance claim

HIPAA compliance depends on the entire operational environment: contracts/BAAs, policies, vendor selection, identity and access management, encryption, audit controls, incident response, retention, backups, workforce practices, and minimum-necessary data handling. This codebase alone cannot establish compliance.

## Safe demonstration

1. Run locally.
2. Use only the included synthetic scenarios.
3. Docker Compose binds port 8000 to loopback. Do not change that without enabling token mode, TLS, restrictive CORS, and the controls in [Deployment](DEPLOYMENT.md).
4. Delete the generated SQLite database after demos if desired.
5. Keep all real telephony and model secrets outside the repository.

The shared role-token mode is a portfolio control, not production identity management. Real deployments need named users, MFA, revocation, minimum-necessary permissions, tenant isolation, and an approved retention program.
