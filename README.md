# Dental AI Receptionist

[![CI](https://github.com/MarkT713/dental-ai-receptionist/actions/workflows/ci.yml/badge.svg)](https://github.com/MarkT713/dental-ai-receptionist/actions/workflows/ci.yml)
![Tests](https://img.shields.io/badge/tests-35%20passing-brightgreen)
![Evaluations](https://img.shields.io/badge/evals-46%2F46%20passing-brightgreen)

A privacy-conscious **after-hours dental intake and staff-approval workflow** built with FastAPI, SQLite, structured AI extraction, a deterministic safety policy, and a mock dental practice-management dashboard.

> **Portfolio/demo software only.** It uses synthetic patients and a mock PMS. It is not a live integration, medical device, or claim of HIPAA compliance.

**Live synthetic demo:** https://dental-ai-receptionist-demo.onrender.com

![Dashboard](docs/dashboard.png)

## Why this project exists

Dental offices lose after-hours calls, while unconstrained AI should not diagnose patients or write directly to scheduling systems. This project demonstrates a safer pattern:

```text
caller transcript
      │
      ▼
structured intake extraction ──► safety and prompt-injection checks
      │
      ▼
staff review queue ──► approve / call back / needs info / reject
      │
      ▼
verified patient + safe slot ──► mock appointment book
```

The AI prepares work. A human approves consequential scheduling actions.

## Demonstrated capabilities

- Transcript → structured appointment intake
- Credential-free deterministic engine for reproducible demos and CI
- Optional OpenAI-compatible structured extraction for **synthetic data only**
- Urgent-language escalation and emergency flags
- Prompt-injection detection; transcript instructions are treated as untrusted caller data
- Existing/new-patient intake and identity-confidence labels
- Staff approval queue with suggested slots
- Approval-gated scheduling into a mock PMS
- Strict API models, legal queue transitions, atomic/idempotent writes, and duration-aware provider/chair conflicts
- Optional viewer/staff/manager token roles and demo-mode gating
- Privacy-reduced audit trail, request IDs, security headers, rate limits, and aggregate operational metrics
- Embedded staff dashboard and OpenAPI documentation
- Regression evaluations for routine, urgent, incomplete, negated, limited Spanish, natural-date, and adversarial transcripts
- Provider-neutral voice contracts and a truthful synthetic turn simulation—no live-audio claim
- Hash-locked dependencies, pinned non-root container, security scans, Dependabot, and CycloneDX SBOM tooling
- Synthetic data only; no production credentials or patient records

## Quick start

### Docker

```bash
git clone https://github.com/MarkT713/dental-ai-receptionist.git
cd dental-ai-receptionist
docker compose up --build
```

Open:

- Dashboard: <http://localhost:8000>
- API docs: <http://localhost:8000/docs>

### Hosted synthetic sandbox

The included [Render Blueprint](render.yaml) deploys the Docker image as a free, public, synthetic-only sandbox in the Ohio region:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/MarkT713/dental-ai-receptionist)

The hosted profile uses no cloud AI credentials, resets its fictional SQLite records every 60 minutes, rate-limits clients, and may also reset whenever Render restarts or spins down the free service. Cold starts are expected on the free instance type.

### Python

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
DENTAL_SEED_DEMO_DATA=true uvicorn main:app \
  --app-dir practice_management_software --host 127.0.0.1 --port 8000
```

## Try the AI workflow

Use the **AI Transcript Intake** panel in the dashboard, or call the API:

```bash
curl -s http://localhost:8000/ai/intake/queue \
  -H 'content-type: application/json' \
  -d '{"transcript":"Hi, my name is Jamie Lee. I am an existing patient. Call me at 202-555-0142. I need a cleaning Tuesday morning."}'
```

The request is analyzed and queued for staff review. It is **not** booked directly.

## Tests and evaluations

```bash
pytest -q
python scripts/run_evals.py
python -m pip install -e '.[governance]'
python scripts/run_guardbench.py
```

Verified hosted-demo baseline:

- `35` automated tests passing
- `46/46` evaluation cases passing
- `127/127` field assertions matched
- `1.00` precision/recall/F1 for urgent and prompt-injection detection on this synthetic corpus

The evaluation set is synthetic and deterministic. It is a regression suite, not clinical or unrestricted-language validation. See [Evaluation methodology](docs/EVALUATIONS.md).

The GuardBench run executes the real deterministic intake engine—not canned GuardBench fixture responses—and applies a separate high-assurance policy across all 46 cases. It records per-case evidence, corpus and policy hashes, Git/Python provenance, a tamper-evident local audit chain, and a human-approval state. A successful automated run is labeled `conditional_pass` / `awaiting_approval`, never automatically approved.

GitHub Actions runs linting, tests, native and GuardBench evaluation gates, security scans, SBOM generation, compilation, and a hardened non-root container smoke test on every push and pull request.

To exercise the credential-free voice boundary:

```bash
python scripts/run_voice_simulation.py
```

The simulation uses UTF-8 test bytes, not speech audio. It verifies that a routine conversation creates one staff-review card and zero appointments. See [Voice boundary](docs/VOICE.md).

## Optional model provider

The default `AI_PROVIDER=deterministic` needs no API key. To test an OpenAI-compatible provider with synthetic transcripts:

```bash
cp voice_pipeline/.env.example .env
# Set AI_PROVIDER=openai_compatible, LLM_API_KEY, and
# ALLOW_CLOUD_SYNTHETIC_DATA=true.
```

Never put real patient data in this public demo or send it to a cloud model without an appropriate compliance program, contracts, access controls, retention policy, and vendor review.

## Repository map

```text
practice_management_software/
  main.py                 FastAPI API, SQLite model, and staff dashboard
  intake_engine.py        Structured extraction and safety classification
voice_pipeline/
  voice_bridge.py         Deterministic receptionist conversation state machine
  adapters.py             Provider-neutral STT/TTS contracts and synthetic adapters
  pms_client.py           Narrow PMS API adapter
scripts/
  run_after_hours_demo.py Repeatable queue demonstration
  run_evals.py            Structured intake regression evaluator
  run_voice_simulation.py Credential-free turn simulation
  secret_scan.py          Public-release artifact and secret scanner
evals/cases.json          Synthetic evaluation cases
tests/                    API, safety, queue, and conversation tests
docs/                     Architecture, privacy, threat model, screenshot
```

## Safety boundaries

- Urgent clinical language stops automated scheduling.
- Missing identity/contact data forces staff follow-up.
- Transcript content cannot authorize tools or override system policy.
- AI-created queue cards require staff approval.
- Scheduling additionally requires an exact matched demo patient.
- The mock PMS is isolated from real dental systems.

See [Architecture](docs/ARCHITECTURE.md), [Privacy](docs/PRIVACY.md), [Deployment](docs/DEPLOYMENT.md), and [Threat Model](docs/THREAT_MODEL.md).

## Honest limitations

- The public repository demonstrates browser and console intake; it does not ship a production phone carrier configuration or full-duplex audio bridge.
- Shared viewer/staff/manager tokens are available for deployment demonstrations but are not production identity management; a real service needs named users, MFA, revocation, and tenant-aware authorization.
- SQLite and the embedded UI are appropriate for a portfolio sandbox, not a multi-office deployment.
- Safety rules are illustrative and require office-specific legal and clinical review.
- English and limited Spanish examples are tested; unrestricted bilingual understanding is not claimed.
- No real Eaglesoft, Dentrix, or other PMS integration is included or implied.
- This software is not HIPAA compliant merely because it has privacy-conscious design.

## Trademark notice

This project is independent and is not affiliated with or endorsed by Patterson, Eaglesoft, Dentrix, Henry Schein, or any dental software vendor. Product names belong to their respective owners.

## License

MIT — see [LICENSE](LICENSE).
