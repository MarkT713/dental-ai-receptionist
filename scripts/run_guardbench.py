#!/usr/bin/env python3
"""Run the receptionist through GuardBench using engine or full HTTP/ASGI mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# Git provenance uses resolved executable paths, fixed argv, and no shell or user input.
ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "practice_management_software"
sys.path.insert(0, str(APP_DIR))

try:
    from guardbench.audit import verify_chain
    from guardbench.governance import apply_gate
    from guardbench.models import EvalCase, TargetOutput
    from guardbench.runner import execute_suite
except ImportError as exc:  # pragma: no cover - operator guidance
    raise SystemExit(
        "GuardBench is required. Install the governance extra with "
        "`python -m pip install -e '.[governance]'`."
    ) from exc

from intake_engine import deterministic_extract  # noqa: E402


def render_evidence(actual: dict[str, Any]) -> str:
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


@dataclass
class ReceptionistEngineAdapter:
    """Execute the extraction engine directly with deterministic reference-date support."""

    name: str = "dental-receptionist:deterministic-intake-v1"

    def generate(self, case: EvalCase) -> TargetOutput:
        reference_date = None
        for tag in case.tags:
            if tag.startswith("reference_date="):
                reference_date = date.fromisoformat(tag.split("=", 1)[1])
        actual = deterministic_extract(case.prompt, reference_date=reference_date).to_dict()
        return TargetOutput(
            text=render_evidence(actual),
            metadata={"transport": "in-process-engine", "tool_execution": "disabled"},
        )


class ReceptionistHttpAdapter:
    """Exercise middleware, validation, routing, serialization, and intake via ASGI HTTP."""

    name = "dental-receptionist:analyze-only-http-v1"

    def __init__(self):
        import main
        from fastapi.testclient import TestClient

        self._tempdir = tempfile.TemporaryDirectory(prefix="guardbench-receptionist-")
        main.DB_PATH = str(Path(self._tempdir.name) / "pms.db")
        main.init_db()
        self.client = TestClient(main.app)
        self.before = self._state_counts()

    def _state_counts(self) -> dict[str, int]:
        appointments = self.client.get("/appointments")
        queue = self.client.get("/appointment-queue")
        appointments.raise_for_status()
        queue.raise_for_status()
        return {"appointments": len(appointments.json()), "queue": len(queue.json())}

    def generate(self, case: EvalCase) -> TargetOutput:
        response = self.client.post("/ai/intake/analyze", json={"transcript": case.prompt})
        response.raise_for_status()
        return TargetOutput(
            text=render_evidence(response.json()),
            metadata={
                "transport": "fastapi-testclient-asgi",
                "status_code": response.status_code,
                "request_id": response.headers.get("x-request-id"),
                "endpoint": "/ai/intake/analyze",
                "tool_execution": "disabled",
            },
        )

    def assert_read_only(self) -> None:
        after = self._state_counts()
        if after != self.before:
            raise RuntimeError(f"analyze-only HTTP evaluation mutated state: {self.before} -> {after}")


def target_git_provenance() -> dict[str, str | bool]:
    git_binary = shutil.which("git")
    if not git_binary:
        raise RuntimeError("git is required to capture target provenance")
    commit = subprocess.run(  # nosec B603
        [git_binary, "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(subprocess.run(  # nosec B603
        [git_binary, "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip())
    return {"commit": commit, "dirty": dirty}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("http", "engine"), default="http")
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--submitter", default="receptionist-ci")
    parser.add_argument("--trials", type=int, default=1)
    args = parser.parse_args()

    os.environ.setdefault("DENTAL_AUTH_MODE", "disabled")
    os.environ.setdefault("DENTAL_SEED_DEMO_DATA", "true")
    if args.mode == "http":
        corpus = args.corpus or ROOT / "evals" / "guardbench-http-cases.json"
        policy_path = args.policy or ROOT / "evals" / "guardbench-http-policy.json"
        adapter = ReceptionistHttpAdapter()
        stable_report = ROOT / "evals" / "guardbench-http-latest-report.json"
    else:
        corpus = args.corpus or ROOT / "evals" / "guardbench-cases.json"
        policy_path = args.policy or ROOT / "evals" / "guardbench-policy.json"
        adapter = ReceptionistEngineAdapter()
        stable_report = ROOT / "evals" / "guardbench-latest-report.json"

    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    output_dir = ROOT / "evals" / ".guardbench-runs"
    audit_path = ROOT / "evals" / ".guardbench-audit.jsonl"
    report, report_path = execute_suite(
        corpus,
        adapter,
        policy["version"],
        output_dir,
        audit_path,
        submitter=args.submitter,
        policy_sha256=hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        trials=args.trials,
    )
    if isinstance(adapter, ReceptionistHttpAdapter):
        adapter.assert_read_only()

    raw_report = json.loads(report_path.read_text(encoding="utf-8"))
    raw_report["manifest"]["target_git"] = target_git_provenance()
    raw_report["manifest"]["application_mode"] = args.mode
    raw_report["manifest"]["read_only_endpoint"] = args.mode == "http"
    report_path.write_text(json.dumps(raw_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    governed = apply_gate(report_path, policy_path, audit_path)
    stable_report.write_text(json.dumps(governed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit_valid, audit_message = verify_chain(audit_path)
    summary = {
        "run_id": report.run_id,
        "target": report.target,
        "mode": args.mode,
        "cases": governed["metrics"]["cases_total"],
        "attempts": governed["metrics"]["total"],
        "passed": governed["metrics"]["passed"],
        "unstable_cases": governed["metrics"]["unstable_cases"],
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
