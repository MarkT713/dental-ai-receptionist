# Evaluation methodology

The deterministic engine is evaluated with synthetic transcripts only. The suite is a regression and safety-policy test; it is not clinical validation and does not establish performance on real calls.

## Corpus

`evals/cases.json` contains 46 scenarios across:

- routine scheduling requests;
- missing-name and missing-callback cases;
- urgent and possible-emergency language;
- explicit negation to measure false escalation;
- prompt-injection attempts;
- limited English/Spanish intake examples.

Every case declares expected structured fields. Relative-date cases carry an explicit reference date so their expected calendar values remain deterministic.

## Metrics and release gate

Run:

```bash
python scripts/run_evals.py
```

The runner writes the stable report `evals/latest-report.json` and exits nonzero unless:

- all cases pass;
- urgent-language recall is at least 95%;
- prompt-injection recall is at least 95%.

The report includes case and assertion accuracy, category pass counts, and precision/recall/F1 for urgent and prompt-injection detection.

## GuardBench governance evaluation

Install and run the separately versioned governance harness:

```bash
python -m pip install -e '.[governance]'
python scripts/run_guardbench.py --mode http --trials 3
python scripts/run_guardbench.py --mode engine --trials 3
```

HTTP mode is the CI release gate. It starts a real ephemeral Uvicorn process configured deterministically with viewer-only token authentication, a temporary SQLite database, disabled demo reset behavior, and a high fixed evaluation rate limit. It sends 41 cases over loopback TCP through middleware, validation, routing, the real intake engine, and response serialization. Before and after every request it hashes the schema and every row of every non-internal SQLite table. A changed table becomes a trusted `database_mutation` trace and fails the zero-tool/execution gate; the final snapshot must also equal the initial state. This control observes persistent SQLite mutations, not arbitrary network, filesystem, or third-party effects.

Engine mode executes `deterministic_extract()` directly for all 46 cases and supplies the explicit reference dates attached to those five fixtures. Fixture responses embedded in the GuardBench corpus are deliberately unused in both modes.

The governed policies require every included case and category to pass, with zero critical/high failures and zero unstable repeated-trial cases. Every case permits zero calls and forbids appointment, queue, record-update, record-deletion, and observed database-mutation operations. Target-returned proposals remain untrusted; execution decisions use only harness-observed traces. CI uploads the stable report, exact request/response/grade bundle, manifest, corpus, policy, and anchored audit chain. Replay reconstructs outputs from those verified response artifacts rather than trusting report fields. Passing automation produces `awaiting_approval`; only an independent authorized reviewer can create an approved result.

## Interpretation

A perfect synthetic regression score means the declared deterministic rules matched this corpus. It does **not** mean the system has 100% clinical accuracy, understands unrestricted Spanish, or is safe for autonomous diagnosis. New policy terms should be added with positive, negative, negated, and adversarial cases to reduce one-sided overfitting.
