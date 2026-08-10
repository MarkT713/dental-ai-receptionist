#!/usr/bin/env python3
"""Run deterministic intake regression evaluations and emit a JSON report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "practice_management_software"))

from intake_engine import deterministic_extract  # noqa: E402


def main() -> int:
    cases = json.loads((ROOT / "evals" / "cases.json").read_text())
    results = []
    passed = 0
    assertions = 0
    matched = 0
    for case in cases:
        actual = deterministic_extract(case["transcript"]).to_dict()
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
        if not failures:
            passed += 1
        results.append({"id": case["id"], "passed": not failures, "failures": failures})
    report = {
        "engine": "deterministic-v1",
        "cases_passed": passed,
        "cases_total": len(cases),
        "assertions_matched": matched,
        "assertions_total": assertions,
        "accuracy": round(matched / assertions, 4) if assertions else 0,
        "results": results,
    }
    print(json.dumps(report, indent=2))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
