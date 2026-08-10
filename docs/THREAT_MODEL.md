# Threat Model

## Assets

- Caller identity and contact details
- Appointment requests and reasons
- Patient-match status and scheduling records
- Model, PMS, speech, and telephony credentials
- Staff approval decisions and audit events

## Trust boundaries

1. Caller transcript/audio → extraction or speech provider
2. Provider output → deterministic policy layer
3. Staff browser/client → API authorization middleware
4. API → SQLite mock database
5. Optional cloud model/telephony provider → external service
6. Container → host volume and reverse proxy

## Threats and current controls

| Threat | Demonstrated control | Production gap |
|---|---|---|
| Prompt injection in caller text | Adversarial patterns flagged; transcript never authorizes tools; deterministic flags override optional model output | Broader multilingual/red-team corpus and constrained provider schema |
| AI schedules urgent request | Urgent classification forces `stop_and_escalate`; urgent cards cannot enter approved state | Office-specific clinical/legal policy validation |
| AI writes without approval | Legal transition map, exact patient match, staff approval, manager role for schedule endpoint | Named staff identity, MFA, signed approvals, tenant policies |
| Wrong patient selected | Exact demo patient ID required | Multi-factor demographic verification and PMS-side recheck |
| Duplicate/competing writes | `BEGIN IMMEDIATE`, duration-overlap checks, idempotent queue schedule replay | Distributed idempotency store and target-PMS transaction semantics |
| Malformed or injected fields | Strict Pydantic models, extra-field rejection, length/range/date/phone enums, HTML escaping | Central schema governance and fuzzing at production scale |
| Stored/browser XSS | Input markup rejection, contextual escaping, CSP, frame denial, DOM adversarial test | Remove inline scripts/styles and adopt nonce-based CSP |
| Credential leakage | Ignore rules, public-release scanner, placeholders, dependency lock/SBOM | Managed secret store, automated rotation, push protection |
| Unauthorized API use | Optional viewer/staff/manager Bearer-token mode | External IdP, short-lived sessions, MFA, revocation, named-user audit |
| Denial of service | Body limits through framework validation and process-local request rate limit | Gateway limits, multi-instance coordination, load testing |
| Sensitive logs/metrics | Request logs omit bodies; audit payload fields are redacted; `/metrics` is aggregate-only | Central access-controlled logging, retention, DLP review |
| Supply-chain compromise | Hash-locked runtime dependencies, non-root pinned-base container, pip-audit/Bandit/Dependabot definitions, CycloneDX SBOM | Active CI policy, signature/provenance verification, image scanning |
| Public exposure | Loopback-only Compose port, read-only root filesystem, dropped capabilities | TLS proxy, network policy, WAF/API gateway, hardened database |
| Sensitive cloud disclosure | Cloud provider disabled by default and synthetic-data gate required | Vendor/BAA review, de-identification, consent, retention and DLP |
| Misleading voice claim | Synthetic adapters reject audio; live modes fail closed; capability boundary documented | Validated STT/TTS/carrier adapters and consent-aware call testing |

## Residual risk

Shared static role tokens, process-local rate limits/metrics, SQLite, inline dashboard JavaScript, and deterministic phrase policies are appropriate only for a synthetic portfolio demonstration. They are not sufficient controls for identifiable patient data or a multi-office production service.

## Non-goals

This public demo does not claim clinical validation, autonomous diagnosis, HIPAA compliance, real PMS interoperability, unrestricted bilingual understanding, or production telephony.
