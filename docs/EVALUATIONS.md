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
python scripts/run_guardbench.py
```

`scripts/run_guardbench.py` uses a receptionist-specific adapter to execute `deterministic_extract()` for every case. Fixture responses embedded in the GuardBench corpus are deliberately unused. The adapter renders structured field evidence for deterministic grading, including explicit `allow` versus `escalate` behavior.

The governed policy requires all 46 cases and every category to pass, with zero critical/high failures. It records corpus and policy hashes, runtime/Git provenance, and a chained audit event. Passing automation produces `awaiting_approval`; only an independent authorized reviewer can create an approved result.

## Interpretation

A perfect synthetic regression score means the declared deterministic rules matched this corpus. It does **not** mean the system has 100% clinical accuracy, understands unrestricted Spanish, or is safe for autonomous diagnosis. New policy terms should be added with positive, negative, negated, and adversarial cases to reduce one-sided overfitting.
