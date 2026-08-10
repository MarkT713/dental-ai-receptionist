# Deployment and access-control guide

This repository is a synthetic portfolio sandbox, not a production patient system. The secure defaults below reduce accidental exposure; they do not establish HIPAA compliance.

## Local demo mode

Docker Compose binds only to `127.0.0.1`, runs the container as UID/GID `10001`, drops Linux capabilities, enables a read-only root filesystem, and stores SQLite under `/data`.

```bash
docker compose up --build
```

## Role-token mode

Set `DENTAL_AUTH_MODE=token` and provide three independently generated values through your secret manager or deployment environment:

- `DENTAL_VIEWER_TOKEN`: read-only API access and transcript analysis.
- `DENTAL_STAFF_TOKEN`: queue creation and normal staff transitions.
- `DENTAL_MANAGER_TOKEN`: patient/appointment writes, scheduling, and demo reset.

Generate tokens locally, never in chat or source control. For example:

```bash
openssl rand -hex 32
```

The dashboard's **Optional role token** box stores the selected token in browser local storage and attaches it as a Bearer token. Use this only on a trusted workstation. A production application should use an external identity provider, short-lived sessions, MFA, revocation, and named-user audit attribution instead of shared static tokens.

## Public synthetic sandbox on Render

`render.yaml` defines the recommended portfolio deployment: a free Docker web service in Render's Ohio region with `/health` checks and deployment only after GitHub CI passes.

The public profile deliberately uses:

- deterministic extraction with cloud-provider access disabled;
- fictional seeded records only;
- an ephemeral SQLite database under `/tmp`;
- automatic reset every 60 minutes;
- a lower process-local request limit;
- a visible synthetic-sandbox notice;
- no shared role-token secrets.

Render documents that free services spin down after 15 minutes without inbound traffic, take about a minute to restart, and lose local filesystem changes on spin-down, restart, or redeploy. Those limitations are desirable for this disposable demo but unsuitable for real office data.

Deploy through the repository's **Deploy to Render** button or create a Render Blueprint from `render.yaml`. Sign into Render and authorize the GitHub repository interactively; never place Render or GitHub credentials in this repository or chat.

## Internet-facing deployment checklist

Before exposing any instance:

1. Set `DENTAL_AUTH_MODE=token` and verify all three tokens are distinct.
2. Set `DENTAL_DEMO_MODE=false` and `DENTAL_SEED_DEMO_DATA=false`.
3. Place the service behind TLS and a trusted reverse proxy.
4. Restrict `CORS_ALLOWED_ORIGINS` to the exact dashboard origin.
5. Persist `/data` on encrypted storage with tested backup/restore.
6. Send logs to an access-controlled store; the built-in structured request metrics intentionally omit patient fields.
7. Replace process-local rate limiting with proxy/API-gateway controls for multi-worker deployments.
8. Perform legal, privacy, clinical-safety, vendor, retention, incident-response, and business-associate reviews.
9. Use a real identity provider and database before handling identifiable information.

## Operational endpoints

- `GET /health`: liveness/health response; public.
- `GET /metrics`: process-local aggregate counts and latency; viewer role in token mode.
- `GET /metadata`: public feature and mode description; never includes token values.

The service emits structured `request_complete` log events with request ID, route template, status, latency, and actor role. It does not include request bodies, transcripts, phone numbers, names, DOB, or notes.
