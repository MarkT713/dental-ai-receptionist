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

Every case declares expected structured fields. Relative dates are not scored as fixed calendar values, avoiding time-dependent fixtures.

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

## Interpretation

A perfect synthetic regression score means the declared deterministic rules matched this corpus. It does **not** mean the system has 100% clinical accuracy, understands unrestricted Spanish, or is safe for autonomous diagnosis. New policy terms should be added with positive, negative, negated, and adversarial cases to reduce one-sided overfitting.
