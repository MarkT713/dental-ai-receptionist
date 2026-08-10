# Threat Model

## Assets

- Caller identity and contact details
- Appointment requests and reasons
- Patient-match status
- Scheduling records
- Model and telephony credentials
- Staff approval decisions and audit events

## Trust boundaries

1. Caller transcript → extraction engine
2. Extraction engine → deterministic policy layer
3. Staff browser → API
4. API → mock database
5. Optional cloud model → external provider

## Threats and current controls

| Threat | Demonstrated control | Production gap |
|---|---|---|
| Prompt injection in caller text | Injection terms flagged; transcript never authorizes tools | Add broader adversarial evals and model-side constrained decoding |
| AI schedules urgent request | Urgent classification forces `stop_and_escalate` | Office-specific clinical policy validation |
| AI writes without approval | Queue status must be `approved` | Authenticated staff identity and signed approval |
| Wrong patient selected | Exact demo patient ID required | Multi-factor demographic verification and PMS-side recheck |
| Duplicate/competing writes | Slot conflict check | Idempotency keys and transactional integration |
| Credential leakage | `.env` and databases excluded from Git | Secret manager and rotation |
| Public exposure | Documentation says local bind only | Authentication, TLS, rate limiting, network policy |
| Sensitive cloud disclosure | Cloud provider disabled by default | Vendor/BAA review, de-identification and DLP |

## Non-goals

This public demo does not claim clinical validation, production security, HIPAA compliance, real PMS interoperability, or autonomous diagnosis/triage.
