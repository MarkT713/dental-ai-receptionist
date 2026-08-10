#!/usr/bin/env python3
"""Run the receptionist's real deterministic intake engine through GuardBench."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
# Fixed Git provenance commands use resolved executable paths, fixed argv, and no shell/user input.
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "practice_management_software"
sys.path.insert(0, str(APP_DIR))

try:
    from guardbench.audit import verify_chain
    from guardbench.governance import apply_gate
    from guardbench.models import EvalCase
    from guardbench.runner import execute_suite
except ImportError as exc:  # pragma: no cover - operator guidance
    raise SystemExit(
        "GuardBench is required. Install the governance extra with "
        "`python -m pip install -e '.[governance]'`."
    ) from exc

from intake_engine import deterministic_extract  # noqa: E402


@dataclass
class ReceptionistAdapter:
    """Execute actual receptionist extraction and expose deterministic grading evidence."""

    name: str = "dental-receptionist:deterministic-intake-v1"

    def generate(self, case: EvalCase) -> str:
        reference_date = None
        for tag in case.tags:
            if tag.startswith("reference_date="):
                reference_date = date.fromisoformat(tag.split("=", 1)[1])
        actual = deterministic_extract(case.prompt, reference_date=reference_date).to_dict()
        decision = "escalate" if actual["risk_level"] in {"urgent", "needs_review"} else "allow"
        evidence = [decision]
        for key, value in sorted(actual.items()):
            rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            evidence.append(f"{key}={rendered}")
            if isinstance(value, list):
                evidence.extend(
                    f"{key}_contains={json.dumps(item, ensure_ascii=False, separators=(',', ':'))}"
                    for item in value
                )
        return "\n".join(evidence)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "evals" / "guardbench-cases.json")
    parser.add_argument("--policy", type=Path, default=ROOT / "evals" / "guardbench-policy.json")
    parser.add_argument("--submitter", default="receptionist-ci")
    args = parser.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    output_dir = ROOT / "evals" / ".guardbench-runs"
    audit_path = ROOT / "evals" / ".guardbench-audit.jsonl"
    report, report_path = execute_suite(
        args.corpus,
        ReceptionistAdapter(),
        policy["version"],
        output_dir,
        audit_path,
        submitter=args.submitter,
        policy_sha256=hashlib.sha256(args.policy.read_bytes()).hexdigest(),
    )
    git_binary = shutil.which("git")
    if not git_binary:
        raise RuntimeError("git is required to capture target provenance")
    target_commit = subprocess.run(  # nosec B603
        [git_binary, "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    target_dirty = bool(subprocess.run(  # nosec B603
        [git_binary, "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip())
    raw_report = json.loads(report_path.read_text(encoding="utf-8"))
    raw_report["manifest"]["target_git"] = {"commit": target_commit, "dirty": target_dirty}
    report_path.write_text(json.dumps(raw_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    governed = apply_gate(report_path, args.policy, audit_path)
    stable_report = ROOT / "evals" / "guardbench-latest-report.json"
    stable_report.write_text(json.dumps(governed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit_valid, audit_message = verify_chain(audit_path)
    summary = {
        "run_id": report.run_id,
        "target": report.target,
        "cases": governed["metrics"]["total"],
        "passed": governed["metrics"]["passed"],
        "pass_rate": governed["metrics"]["pass_rate"],
        "gate": governed["gate"]["decision"],
        "status": governed["status"],
        "evidence_scope": governed["gate"]["evidence"]["scope"],
        "audit": audit_message,
        "report": str(stable_report),
    }
    print(json.dumps(summary, indent=2))
    return 0 if governed["status"] == "awaiting_approval" and audit_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
