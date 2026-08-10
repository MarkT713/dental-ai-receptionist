#!/usr/bin/env python3
"""Run the receptionist through GuardBench using engine or live HTTP mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess  # nosec B404
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

# Git provenance uses resolved executable paths, fixed argv, and no shell or user input.
ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "practice_management_software"
sys.path.insert(0, str(APP_DIR))

try:
    from guardbench.audit import verify_chain
    from guardbench.governance import apply_gate
    from guardbench.models import EvalCase, TargetOutput, ToolTrace
    from guardbench.runner import execute_suite
except ImportError as exc:  # pragma: no cover - operator guidance
    raise SystemExit(
        "GuardBench is required. Install with `python -m pip install -e '.[governance]'`."
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


def target_git_provenance(require_clean: bool = True) -> dict[str, str | bool]:
    git_binary = shutil.which("git")
    if not git_binary:
        raise RuntimeError("git is required to capture target provenance")
    commit = subprocess.run(  # nosec B603
        [git_binary, "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    status = subprocess.run(  # nosec B603
        [git_binary, "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    if require_clean and status:
        raise RuntimeError("release evaluation requires a clean target worktree")
    provenance: dict[str, str | bool] = {"commit": commit, "dirty": bool(status)}
    if status:
        diff = subprocess.run(  # nosec B603
            [git_binary, "diff", "--binary", "HEAD"],
            cwd=ROOT, check=True, capture_output=True,
        ).stdout
        provenance["tracked_diff_sha256"] = hashlib.sha256(diff).hexdigest()
        provenance["status_sha256"] = hashlib.sha256(status.encode()).hexdigest()
    return provenance


def _normalized(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    return value


def database_snapshot(path: Path) -> dict[str, str]:
    """Hash schema and every row of every non-internal SQLite table."""
    with sqlite3.connect(path) as conn:
        tables = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        snapshot = {}
        for table, schema in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = [
                [_normalized(value) for value in row]
                for row in conn.execute(f"SELECT * FROM {quoted}").fetchall()  # nosec B608
            ]
            rows.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))
            rendered = json.dumps(
                {"schema": schema, "rows": rows}, sort_keys=True, separators=(",", ":")
            ).encode()
            snapshot[table] = hashlib.sha256(rendered).hexdigest()
        return snapshot


@dataclass
class ReceptionistEngineAdapter:
    """Execute extraction directly with deterministic reference-date support."""

    provenance: dict[str, Any]
    name: str = "dental-receptionist:deterministic-intake-v1"

    def generate(self, case: EvalCase) -> TargetOutput:
        reference_date = None
        for tag in case.tags:
            if tag.startswith("reference_date="):
                reference_date = date.fromisoformat(tag.split("=", 1)[1])
        actual = deterministic_extract(case.prompt, reference_date=reference_date).to_dict()
        return TargetOutput(
            text=render_evidence(actual), metadata={"transport": "in-process-engine"}
        )


class ReceptionistHttpAdapter:
    """Exercise a real Uvicorn TCP server and observe persistent SQLite effects."""

    name = "dental-receptionist:analyze-only-http-v2"

    def __init__(self, target_git: dict[str, Any]):
        self._tempdir = tempfile.TemporaryDirectory(prefix="guardbench-receptionist-")
        self.db_path = Path(self._tempdir.name) / "pms.db"
        self.viewer_token = f"synthetic-eval-{uuid4().hex}"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        environment = os.environ.copy()
        environment.pop("DENTAL_STAFF_TOKEN", None)
        environment.pop("DENTAL_MANAGER_TOKEN", None)
        environment.update({
            "DENTAL_AUTH_MODE": "token",
            "DENTAL_VIEWER_TOKEN": self.viewer_token,
            "DENTAL_DB_PATH": str(self.db_path),
            "DENTAL_SEED_DEMO_DATA": "true",
            "DENTAL_DEMO_MODE": "false",
            "DENTAL_PUBLIC_SANDBOX": "false",
            "DENTAL_AUTO_RESET_MINUTES": "0",
            "DENTAL_RATE_LIMIT_PER_MINUTE": "10000",
        })
        self.process = subprocess.Popen(  # nosec B603
            [
                sys.executable, "-m", "uvicorn", "main:app", "--app-dir", str(APP_DIR),
                "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning",
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.viewer_token}"},
            timeout=httpx.Timeout(10.0, connect=2.0),
            follow_redirects=False,
            trust_env=False,
        )
        try:
            self._wait_until_ready()
            self.initial_snapshot = database_snapshot(self.db_path)
        except Exception:
            self.close()
            raise
        self.provenance = {
            "target_git": target_git,
            "transport": "uvicorn-loopback-tcp",
            "endpoint": "POST /ai/intake/analyze",
            "authorization_role": "viewer",
            "state_observer": "all-sqlite-business-table-hashes",
        }

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("evaluation Uvicorn process exited before readiness")
            try:
                response = self.client.get("/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError("evaluation Uvicorn process did not become ready")

    def generate(self, case: EvalCase) -> TargetOutput:
        before = database_snapshot(self.db_path)
        response = self.client.post("/ai/intake/analyze", json={"transcript": case.prompt})
        if response.status_code != 200:
            raise RuntimeError(f"analyze endpoint returned HTTP {response.status_code}")
        if len(response.content) > 1_000_000:
            raise RuntimeError("analyze response exceeded one megabyte")
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise RuntimeError("analyze endpoint did not return JSON")
        after = database_snapshot(self.db_path)
        changed_tables = sorted(
            table for table in before.keys() | after.keys() if before.get(table) != after.get(table)
        )
        trace = ()
        if changed_tables:
            trace = (
                ToolTrace(
                    name="database_mutation",
                    arguments={"tables": changed_tables},
                    authorization="none",
                    executed=True,
                    observer="sqlite_business_table_snapshot",
                ),
            )
        return TargetOutput(
            text=render_evidence(response.json()),
            trusted_tool_trace=trace,
            metadata={
                "transport": "uvicorn-loopback-tcp",
                "status_code": response.status_code,
                "request_id": response.headers.get("x-request-id"),
                "endpoint": "/ai/intake/analyze",
                "observed_sqlite_mutations": changed_tables,
            },
        )

    def assert_read_only(self) -> None:
        after = database_snapshot(self.db_path)
        if after != self.initial_snapshot:
            changed = sorted(
                table for table in self.initial_snapshot.keys() | after.keys()
                if self.initial_snapshot.get(table) != after.get(table)
            )
            raise RuntimeError(f"analyze-only evaluation mutated SQLite tables: {changed}")

    def close(self) -> None:
        self.client.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self._tempdir.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("http", "engine"), default="http")
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--submitter", default="receptionist-ci")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument(
        "--allow-dirty-target", action="store_true",
        help="development only; release evidence requires a clean target tree",
    )
    args = parser.parse_args()

    target_git = target_git_provenance(require_clean=not args.allow_dirty_target)
    if args.mode == "http":
        corpus = args.corpus or ROOT / "evals" / "guardbench-http-cases.json"
        policy_path = args.policy or ROOT / "evals" / "guardbench-http-policy.json"
        adapter: ReceptionistHttpAdapter | ReceptionistEngineAdapter = ReceptionistHttpAdapter(
            target_git
        )
        stable_report = ROOT / "evals" / "guardbench-http-latest-report.json"
    else:
        corpus = args.corpus or ROOT / "evals" / "guardbench-cases.json"
        policy_path = args.policy or ROOT / "evals" / "guardbench-policy.json"
        adapter = ReceptionistEngineAdapter({"target_git": target_git, "transport": "engine"})
        stable_report = ROOT / "evals" / "guardbench-latest-report.json"

    try:
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
        governed = apply_gate(report_path, policy_path, audit_path)
        stable_report.write_text(
            json.dumps(governed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
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
    finally:
        if isinstance(adapter, ReceptionistHttpAdapter):
            adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
