#!/usr/bin/env python3
"""Seed and print a repeatable BrightSmile Dental after-hours receptionist demo.

Requires the mock PMS API running at PMS_BASE_URL (default http://127.0.0.1:8000).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

BASE_URL = os.getenv("PMS_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SCENARIOS = ["routine", "urgent", "new_patient", "needs_info"]


@dataclass
class ApiError(Exception):
    status: int
    body: str


def request(method: str, path: str, payload: dict | None = None) -> dict | list:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code, exc.read().decode("utf-8")) from exc


def main() -> int:
    try:
        meta = request("GET", "/metadata")
    except Exception as exc:
        print(f"ERROR: Could not reach PMS API at {BASE_URL}: {exc}", file=sys.stderr)
        print("Start it with: docker compose up --build", file=sys.stderr)
        return 1

    print("# BrightSmile Dental After-Hours Demo")
    print()
    print(f"Practice: {meta.get('practice_name')}")
    print(f"Dashboard: {BASE_URL}/")
    print(f"API docs:   {BASE_URL}/docs")
    print()
    print("Seeding staff-review cards...")
    created = []
    for scenario in SCENARIOS:
        result = request("POST", f"/demo/seed-queue/{scenario}")
        created.append(result)
        print(f"- {scenario}: {result['queue_id']}")

    queue = request("GET", "/appointment-queue")
    print()
    print("Demo talk track:")
    print("1. Ava answers after-hours and collects name, DOB, phone, reason, and preferred window.")
    print("2. Routine requests become human-reviewed queue cards, not direct PMS writes.")
    print("3. Urgent pain/swelling is marked stop-and-escalate with an ASAP call recommendation.")
    print("4. Staff can approve, call back, mark needs-info, reject, or request suggested slots.")
    print("5. Only an approved exact-match patient card can be scheduled into mock Appointment Book.")
    print()
    print("Current newest cards:")
    for item in queue[: min(6, len(queue))]:
        print(
            f"- {item['patient_name']} | {item['risk_level']} | {item['status']} | "
            f"{item.get('recommended_action')}"
        )
    print()
    print("Open the dashboard and start on the AI Queue tab.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
