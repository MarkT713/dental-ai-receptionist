import importlib.util
import sqlite3
import sys
from pathlib import Path

import httpx
from guardbench.models import EvalCase, ExpectedBehavior

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_guardbench.py"
SPEC = importlib.util.spec_from_file_location("run_guardbench_script", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_database_snapshot_detects_same_count_row_updates(tmp_path):
    database = tmp_path / "state.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE appointments (id TEXT PRIMARY KEY, status TEXT)")
        conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY, detail TEXT)")
        conn.execute("INSERT INTO appointments VALUES ('A-1', 'pending')")
        conn.execute("INSERT INTO audit_log(detail) VALUES ('created')")
    before = MODULE.database_snapshot(database)
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE appointments SET status='confirmed' WHERE id='A-1'")
    after = MODULE.database_snapshot(database)
    assert before["appointments"] != after["appointments"]
    assert before["audit_log"] == after["audit_log"]


def test_http_adapter_emits_trusted_trace_for_observed_mutation(tmp_path):
    database = tmp_path / "state.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE appointments (id TEXT PRIMARY KEY, status TEXT)")
        conn.execute("INSERT INTO appointments VALUES ('A-1', 'pending')")

    class MutatingClient:
        def post(self, _path, json):
            assert json["transcript"] == "synthetic request"
            with sqlite3.connect(database) as conn:
                conn.execute("UPDATE appointments SET status='confirmed' WHERE id='A-1'")
            return httpx.Response(
                200,
                json={"risk_level": "routine"},
                headers={"content-type": "application/json", "x-request-id": "synthetic"},
            )

    adapter = object.__new__(MODULE.ReceptionistHttpAdapter)
    adapter.db_path = database
    adapter.client = MutatingClient()
    case = EvalCase(
        "mutation-case", "robustness", "critical", "synthetic request",
        ExpectedBehavior("allow"), "fixture",
    )
    output = adapter.generate(case)
    assert output.trusted_tool_trace[0].name == "database_mutation"
    assert output.trusted_tool_trace[0].executed
    assert output.trusted_tool_trace[0].observer == "sqlite_business_table_snapshot"
