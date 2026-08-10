#!/usr/bin/env python3
"""Run deterministic intake regressions and emit stable, portfolio-ready metrics."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "practice_management_software"))

from intake_engine import deterministic_extract  # noqa: E402


def safe_ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def classification_metrics(tp: int, fp: int, fn: int) -> dict:
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
    }


def evaluate(cases: list[dict]) -> dict:
    results = []
    passed = assertions = matched = 0
    category_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "total": 0})
    urgent_tp = urgent_fp = urgent_fn = 0
    injection_tp = injection_fp = injection_fn = 0

    for case in cases:
        reference_date = date.fromisoformat(case["reference_date"]) if case.get("reference_date") else None
        actual = deterministic_extract(case["transcript"], reference_date=reference_date).to_dict()
        failures = []
        for key, expected in case["expected"].items():
            assertions += 1
            if key.endswith("_contains"):
                actual_key = key.removesuffix("_contains")
                ok = expected in actual.get(actual_key, [])
            else:
                ok = actual.get(key) == expected
            if ok:
                matched += 1
            else:
                failures.append({"field": key, "expected": expected, "actual": actual.get(key)})

        case_passed = not failures
        passed += int(case_passed)
        category = case.get("category", "uncategorized")
        category_counts[category]["total"] += 1
        category_counts[category]["passed"] += int(case_passed)
        results.append({"id": case["id"], "category": category, "passed": case_passed, "failures": failures})

        expected_urgent = case["expected"].get("risk_level") == "urgent"
        predicted_urgent = actual["risk_level"] == "urgent"
        urgent_tp += int(expected_urgent and predicted_urgent)
        urgent_fp += int(not expected_urgent and predicted_urgent)
        urgent_fn += int(expected_urgent and not predicted_urgent)

        expected_injection = category == "prompt_injection"
        predicted_injection = "prompt_injection_attempt" in actual["safety_flags"]
        injection_tp += int(expected_injection and predicted_injection)
        injection_fp += int(not expected_injection and predicted_injection)
        injection_fn += int(expected_injection and not predicted_injection)

    urgent = classification_metrics(urgent_tp, urgent_fp, urgent_fn)
    injection = classification_metrics(injection_tp, injection_fp, injection_fn)
    release_gate = {
        "all_cases_pass": passed == len(cases),
        "urgent_recall_at_least_0_95": urgent["recall"] >= 0.95,
        "prompt_injection_recall_at_least_0_95": injection["recall"] >= 0.95,
    }
    return {
        "engine": "deterministic-v1",
        "cases_passed": passed,
        "cases_total": len(cases),
        "case_pass_rate": safe_ratio(passed, len(cases)),
        "assertions_matched": matched,
        "assertions_total": assertions,
        "assertion_accuracy": safe_ratio(matched, assertions),
        "categories": dict(sorted(category_counts.items())),
        "safety_metrics": {"urgent_detection": urgent, "prompt_injection_detection": injection},
        "release_gate": release_gate,
        "release_gate_passed": all(release_gate.values()),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=ROOT / "evals" / "cases.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "latest-report.json")
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text())
    report = evaluate(cases)
    rendered = json.dumps(report, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if report["release_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
