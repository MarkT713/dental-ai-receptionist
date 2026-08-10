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

HTTP mode is the CI release gate. It exercises 41 cases through FastAPI's ASGI request path, including middleware, request validation, routing, the real intake engine, and response serialization. It snapshots appointment and approval-queue counts before and after the run and aborts if the analyze-only endpoint mutates either. The five relative-date fixtures are intentionally excluded because that public endpoint does not accept a test clock.

Engine mode executes `deterministic_extract()` directly for all 46 cases and supplies the explicit reference dates attached to those five fixtures. Fixture responses embedded in the GuardBench corpus are deliberately unused in both modes.

The governed policies require every included case and category to pass, with zero critical/high failures and zero unstable repeated-trial cases. Every case declares a maximum of zero tool calls and forbids appointment, queue, record-update, and record-deletion tools. Reports retain per-trial structured responses, transport metadata, corpus/policy/target provenance, a hash-indexed evidence bundle, and a chained audit event. The stable report is committed; complete per-request/response/grade bundles are uploaded as CI artifacts because they can contain untrusted target output and should not accumulate in Git. Passing automation produces `awaiting_approval`; only an independent authorized reviewer can create an approved result.

## Interpretation

A perfect synthetic regression score means the declared deterministic rules matched this corpus. It does **not** mean the system has 100% clinical accuracy, understands unrestricted Spanish, or is safe for autonomous diagnosis. New policy terms should be added with positive, negative, negated, and adversarial cases to reduce one-sided overfitting.
