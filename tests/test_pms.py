from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    project = Path(__file__).resolve().parents[1] / "practice_management_software"
    monkeypatch.setenv("DENTAL_SEED_DEMO_DATA", "true")
    monkeypatch.syspath_prepend(str(project))
    import main

    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "pms.db"))
    main.init_db()
    return TestClient(main.app)


def test_metadata_and_health_identify_public_demo(app_client):
    health = app_client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    response = app_client.get("/metadata")
    assert response.status_code == 200
    data = response.json()
    assert data["practice_name"] == "BrightSmile Dental"
    assert "Appointment Book" in data["modules"]
    assert "Appointment Queue" in data["modules"]


def test_patient_search_and_appointment_book_booking(app_client):
    patients = app_client.get("/patients", params={"name": "Doe", "dob": "1990-01-01"}).json()
    assert patients
    patient = patients[0]

    slots = app_client.get("/appointments/available", params={"date": "2026-07-01", "chair": "Chair 1"}).json()
    assert slots["available_slots"]
    slot = slots["available_slots"][0]["time_24"]

    payload = {
        "patient_id": patient["patient_id"],
        "appointment_date": "2026-07-01",
        "appointment_time": slot,
        "appointment_type": "Prophy",
        "provider": "Dr. Rivera DDS",
        "chair": "Chair 1",
        "reason_for_visit": "Routine dental cleaning",
    }
    created = app_client.post("/appointments", json=payload)
    assert created.status_code == 201
    data = created.json()
    assert data["patient"] == "Jane Doe"
    assert data["appointment_type"] == "Prophy"
    assert data["chair"] == "Chair 1"

    conflict = app_client.post("/appointments", json=payload)
    assert conflict.status_code == 409


def test_appointment_queue_for_receptionist_drafts(app_client):
    response = app_client.post(
        "/appointment-queue",
        json={
            "patient_name": "Sam Example",
            "phone_number": "202-555-0122",
            "requested_date": "2026-07-02",
            "requested_time": "morning",
            "appointment_type": "New Patient Exam",
            "reason_for_visit": "New patient appointment request from AI receptionist",
            "risk_level": "needs_review",
        },
    )
    assert response.status_code == 201
    queue_id = response.json()["queue_id"]

    queue = app_client.get("/appointment-queue").json()
    assert any(item["queue_id"] == queue_id and item["status"] == "queued" for item in queue)

    queue = app_client.get("/appointment-queue").json()
    created = next(item for item in queue if item["queue_id"] == queue_id)
    assert created["recommended_action"] == "Review and schedule routine appointment"
    assert created["automation_mode"] == "human_approval_required"

    updated = app_client.put(f"/appointment-queue/{queue_id}", json={"status": "approved", "staff_note": "Looks good"})
    assert updated.status_code == 200
    queue = app_client.get("/appointment-queue", params={"status": "approved"}).json()
    assert any(item["queue_id"] == queue_id for item in queue)


def test_urgent_queue_card_has_recommended_action_and_action_audit(app_client):
    response = app_client.post(
        "/appointment-queue",
        json={
            "patient_name": "Alex Carter",
            "phone_number": "202-555-0100",
            "appointment_type": "Limited/Emergency",
            "reason_for_visit": "Severe tooth pain and swelling",
            "risk_level": "urgent",
        },
    )
    assert response.status_code == 201
    queue_id = response.json()["queue_id"]

    item = app_client.get("/appointment-queue", params={"status": "queued"}).json()[0]
    assert item["queue_id"] == queue_id
    assert item["recommended_action"] == "Call patient ASAP / follow office emergency policy"
    assert item["automation_mode"] == "stop_and_escalate"

    updated = app_client.put(
        f"/appointment-queue/{queue_id}",
        json={"status": "called", "staff_note": "Left voicemail and alerted clinical lead"},
    )
    assert updated.status_code == 200
    audit = app_client.get("/audit-log").json()
    assert any("called" in row["summary"] and queue_id in row["payload"] for row in audit)


def test_demo_seed_endpoint_creates_distinct_after_hours_cards(app_client):
    for scenario in ["routine", "urgent", "new_patient", "needs_info"]:
        response = app_client.post(f"/demo/seed-queue/{scenario}")
        assert response.status_code == 201
        assert response.json()["scenario"] == scenario

    queue = app_client.get("/appointment-queue").json()
    reasons = "\n".join(item.get("reason_for_visit") or "" for item in queue)
    assert "Routine cleaning" in reasons
    assert "Severe tooth pain" in reasons
    assert "New patient" in reasons
    assert any(item["status"] == "needs_info" for item in queue)


def test_queue_recommended_slots_and_approved_scheduling(app_client):
    patients = app_client.get("/patients", params={"name": "Doe", "dob": "1990-01-01"}).json()
    patient = patients[0]
    response = app_client.post(
        "/appointment-queue",
        json={
            "patient_id": patient["patient_id"],
            "patient_name": "Jane Doe",
            "phone_number": "202-555-0101",
            "requested_date": "2026-07-03",
            "requested_time": "morning",
            "appointment_type": "Prophy",
            "reason_for_visit": "Routine cleaning",
            "risk_level": "routine",
        },
    )
    queue_id = response.json()["queue_id"]

    slots = app_client.get(f"/appointment-queue/{queue_id}/recommended-slots").json()
    assert slots["recommended_slots"]
    assert all(slot["time_24"] < "12:00" for slot in slots["recommended_slots"])
    chosen = slots["recommended_slots"][0]

    blocked = app_client.post(
        f"/appointment-queue/{queue_id}/schedule",
        json={"appointment_date": "2026-07-03", "appointment_time": chosen["time_24"]},
    )
    assert blocked.status_code == 400

    assert app_client.put(f"/appointment-queue/{queue_id}", json={"status": "approved"}).status_code == 200
    scheduled = app_client.post(
        f"/appointment-queue/{queue_id}/schedule",
        json={"appointment_date": "2026-07-03", "appointment_time": chosen["time_24"]},
    )
    assert scheduled.status_code == 201
    assert scheduled.json()["appointment_id"]
    queue = app_client.get("/appointment-queue", params={"status": "scheduled"}).json()
    assert any(item["queue_id"] == queue_id for item in queue)


def test_queue_cards_expose_identity_confidence(app_client):
    patient = app_client.get("/patients", params={"name": "Doe", "dob": "1990-01-01"}).json()[0]
    exact = app_client.post(
        "/appointment-queue",
        json={
            "patient_id": patient["patient_id"],
            "patient_name": "Jane Doe",
            "phone_number": "202-555-0101",
            "appointment_type": "Prophy",
            "reason_for_visit": "Routine cleaning",
            "risk_level": "routine",
        },
    ).json()["queue_id"]
    unknown = app_client.post(
        "/appointment-queue",
        json={
            "patient_name": "Mystery Caller",
            "phone_number": "202-555-0133",
            "appointment_type": "Periodic Exam",
            "reason_for_visit": "Wants appointment but no DOB collected",
            "risk_level": "needs_review",
        },
    ).json()["queue_id"]

    queue = {item["queue_id"]: item for item in app_client.get("/appointment-queue").json()}
    assert queue[exact]["identity_confidence"] == "exact_patient_match"
    assert queue[exact]["identity_summary"].startswith("Matched chart")
    assert queue[unknown]["identity_confidence"] == "unmatched_or_new"
    assert "Verify identity" in queue[unknown]["identity_summary"]
