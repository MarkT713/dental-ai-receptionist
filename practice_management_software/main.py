"""
BrightSmile Dental — Mock dental PMS-style Practice Management Software
FastAPI + SQLite backend with embedded staff web UI.

Research anchors used for the mock shape:
- Public dental scheduling workflow concepts; no proprietary software or data is included.
- Generic appointment-book, intake-queue, patient-search, reminder, alert, and audit concepts.

Run:  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
Docs: http://localhost:8000/docs
UI:   http://localhost:8000/
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from intake_engine import extract_intake


app = FastAPI(
    title="BrightSmile Dental Mock Dental PMS",
    description=(
        "Dental Training Sandbox with dental PMS-style Appointment Book, "
        "patient search, appointment queue, confirmation status, and alert concepts."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.getenv("DENTAL_DB_PATH", os.path.join(os.path.dirname(__file__), "pms.db"))
OFFICE_OPEN = 8
OFFICE_CLOSE = 17
SLOT_MINUTES = 30
DEFAULT_PROVIDER = "Dr. Rivera DDS"
DEFAULT_HYGIENIST = "Hygiene 1"
DEFAULT_CHAIR = "Chair 1"
APPOINTMENT_TYPES = ["Periodic Exam", "Prophy", "New Patient Exam", "Limited/Emergency", "Crown Seat", "Consult"]
CONFIRMATION_STATUSES = ["Unconfirmed", "Confirmed", "Left Message", "Text Sent", "No Answer"]


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def rowdict(row: sqlite3.Row) -> dict:
    return dict(row)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(value: str) -> str:
    return " ".join(value.strip().split()).title()


def all_slots() -> List[str]:
    slots = []
    current = OFFICE_OPEN * 60
    end = OFFICE_CLOSE * 60
    while current < end:
        h, m = divmod(current, 60)
        slots.append(f"{h:02d}:{m:02d}")
        current += SLOT_MINUTES
    return slots


def fmt12(t: str) -> str:
    h, m = map(int, t.split(":"))
    suffix = "AM" if h < 12 else "PM"
    h12 = h if 1 <= h <= 12 else abs(h - 12)
    if h12 == 0:
        h12 = 12
    return f"{h12}:{m:02d} {suffix}"


def queue_recommendation(item: dict) -> dict:
    """Staff-facing safety recommendation for an appointment queue card."""
    risk = (item.get("risk_level") or "needs_review").lower()
    reason = (item.get("reason_for_visit") or "").lower()
    appt_type = (item.get("appointment_type") or "").lower()
    missing = []
    if not item.get("phone_number"):
        missing.append("callback phone")
    if not item.get("patient_name"):
        missing.append("patient name")
    urgent_terms = ["pain", "swelling", "bleeding", "trauma", "infection", "abscess", "broken tooth", "emergency"]
    urgent = risk in {"urgent", "stop"} or any(t in reason for t in urgent_terms) or "emergency" in appt_type
    if urgent:
        return {
            "recommended_action": "Call patient ASAP / follow office emergency policy",
            "automation_mode": "stop_and_escalate",
            "missing_info": missing,
            "safety_summary": "Clinical/urgent language detected. Do not auto-book; staff should triage.",
        }
    if missing:
        return {
            "recommended_action": f"Needs info: {', '.join(missing)}",
            "automation_mode": "needs_staff_followup",
            "missing_info": missing,
            "safety_summary": "Intake is incomplete. Staff should verify details before scheduling.",
        }
    return {
        "recommended_action": "Review and schedule routine appointment",
        "automation_mode": "human_approval_required",
        "missing_info": missing,
        "safety_summary": "Routine request. Staff approval required before final PMS write.",
    }


def enrich_queue_item(row: sqlite3.Row | dict) -> dict:
    item = rowdict(row) if isinstance(row, sqlite3.Row) else dict(row)
    item.update(queue_recommendation(item))
    if item.get("patient_id"):
        item["identity_confidence"] = "exact_patient_match"
        item["identity_summary"] = f"Matched chart {item['patient_id']}. Staff should still verify DOB/phone before final action."
    else:
        item["identity_confidence"] = "unmatched_or_new"
        item["identity_summary"] = "Verify identity or create/reuse the correct chart before scheduling."
    return item


def filtered_slots_for_preference(slots: list[dict], preference: Optional[str]) -> list[dict]:
    pref = (preference or "").lower()
    if "morning" in pref:
        return [s for s in slots if s["time_24"] < "12:00"]
    if "afternoon" in pref:
        return [s for s in slots if "12:00" <= s["time_24"] < "17:00"]
    if "evening" in pref:
        return [s for s in slots if s["time_24"] >= "16:00"]
    if preference and any(ch.isdigit() for ch in preference):
        return [s for s in slots if s["time_24"] == preference or s["time_12"].lower().startswith(pref)] or slots
    return slots


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS patients (
                patient_id TEXT PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                date_of_birth TEXT NOT NULL,
                phone_number TEXT,
                email TEXT,
                chart_number TEXT UNIQUE,
                preferred_provider TEXT,
                responsible_party TEXT,
                patient_alert TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS appointments (
                appointment_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                hygienist TEXT,
                chair TEXT NOT NULL,
                appointment_date TEXT NOT NULL,
                appointment_time TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL DEFAULT 30,
                appointment_type TEXT NOT NULL DEFAULT 'Prophy',
                reason_for_visit TEXT,
                confirmation_status TEXT NOT NULL DEFAULT 'Unconfirmed',
                confirmation_note TEXT,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'scheduled',
                created_at TEXT NOT NULL,
                FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
            );

            CREATE TABLE IF NOT EXISTS appointment_queue (
                queue_id TEXT PRIMARY KEY,
                patient_id TEXT,
                patient_name TEXT NOT NULL,
                phone_number TEXT,
                requested_date TEXT,
                requested_time TEXT,
                duration_minutes INTEGER NOT NULL DEFAULT 30,
                appointment_type TEXT NOT NULL DEFAULT 'Prophy',
                provider TEXT,
                hygienist TEXT,
                chair TEXT,
                reason_for_visit TEXT,
                source TEXT NOT NULL DEFAULT 'AI receptionist',
                risk_level TEXT NOT NULL DEFAULT 'needs_review',
                status TEXT NOT NULL DEFAULT 'queued',
                staff_note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        # Tolerate earlier demo database schemas during local iteration.
        for table, additions in {
            "patients": {
                "email": "TEXT",
                "chart_number": "TEXT UNIQUE",
                "preferred_provider": "TEXT",
                "responsible_party": "TEXT",
                "patient_alert": "TEXT",
            },
            "appointments": {
                "hygienist": "TEXT",
                "chair": "TEXT DEFAULT 'Chair 1'",
                "appointment_type": "TEXT DEFAULT 'Prophy'",
                "confirmation_status": "TEXT DEFAULT 'Unconfirmed'",
                "confirmation_note": "TEXT",
                "note": "TEXT",
            },
        }.items():
            with contextlib.suppress(sqlite3.OperationalError):
                for col, definition in additions.items():
                    add_column_if_missing(conn, table, col, definition)
        if os.getenv("DENTAL_SEED_DEMO_DATA", "false").strip().lower() in {"1", "true", "yes", "on"}:
            seed_demo_data(conn)


def audit(conn: sqlite3.Connection, event_type: str, summary: str, payload: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_log (event_id, event_type, summary, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        [str(uuid.uuid4()), event_type, summary, payload, now()],
    )


def seed_demo_data(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0] > 0:
        return
    patients = [
        ("P1001", "Jane", "Doe", "1990-01-01", "202-555-0101", "jane@example.com", "DEMO1001", DEFAULT_PROVIDER, "Self", "Premedication alert: ask hygienist before scheduling invasive care."),
        ("P1002", "John", "Smith", "1985-05-20", "202-555-0102", "john@example.com", "DEMO1002", DEFAULT_PROVIDER, "Self", None),
        ("P1003", "Maria", "Garcia", "1978-09-14", "202-555-0103", "maria@example.com", "DEMO1003", "Dr. Chen DDS", "Self", "Spanish preferred."),
    ]
    for p in patients:
        conn.execute(
            """INSERT INTO patients
               (patient_id, first_name, last_name, date_of_birth, phone_number, email, chart_number,
                preferred_provider, responsible_party, patient_alert, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [*p, now()],
        )
    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
    conn.execute(
        """INSERT INTO appointments
           (appointment_id, patient_id, provider, hygienist, chair, appointment_date, appointment_time,
            duration_minutes, appointment_type, reason_for_visit, confirmation_status, confirmation_note, note, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
        [str(uuid.uuid4()), "P1002", DEFAULT_PROVIDER, DEFAULT_HYGIENIST, DEFAULT_CHAIR, tomorrow, "09:00", 60,
         "New Patient Exam", "New patient exam and x-rays", "Text Sent", "eReminder sent", "Seeded demo appointment", now()],
    )
    audit(conn, "seed", "Seeded BrightSmile Dental demo patients and Appointment Book appointment")


init_db()


class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: str
    phone_number: Optional[str] = None
    email: Optional[str] = None
    preferred_provider: Optional[str] = DEFAULT_PROVIDER
    responsible_party: Optional[str] = "Self"
    patient_alert: Optional[str] = None


class AppointmentCreate(BaseModel):
    patient_id: str
    appointment_date: str
    appointment_time: str
    reason_for_visit: Optional[str] = None
    provider: Optional[str] = DEFAULT_PROVIDER
    hygienist: Optional[str] = DEFAULT_HYGIENIST
    chair: Optional[str] = DEFAULT_CHAIR
    duration_minutes: Optional[int] = SLOT_MINUTES
    appointment_type: Optional[str] = "Prophy"
    confirmation_status: Optional[str] = "Unconfirmed"
    confirmation_note: Optional[str] = None
    note: Optional[str] = None


class AppointmentUpdate(BaseModel):
    status: str


class ConfirmationUpdate(BaseModel):
    confirmation_status: str
    confirmation_note: Optional[str] = None


class QueueCreate(BaseModel):
    patient_id: Optional[str] = None
    patient_name: str
    phone_number: Optional[str] = None
    requested_date: Optional[str] = None
    requested_time: Optional[str] = None
    duration_minutes: int = 30
    appointment_type: str = "Prophy"
    provider: Optional[str] = DEFAULT_PROVIDER
    hygienist: Optional[str] = DEFAULT_HYGIENIST
    chair: Optional[str] = DEFAULT_CHAIR
    reason_for_visit: Optional[str] = None
    source: str = "AI receptionist"
    risk_level: str = Field("needs_review", description="safe/read-only | needs_review | stop")
    staff_note: Optional[str] = None


class QueueUpdate(BaseModel):
    status: str
    staff_note: Optional[str] = None


class QueueScheduleRequest(BaseModel):
    appointment_date: str
    appointment_time: str
    staff_note: Optional[str] = "Scheduled from human-approved after-hours queue card."


class IntakeAnalyzeRequest(BaseModel):
    transcript: str = Field(..., min_length=3, max_length=5000)


class IntakeQueueRequest(IntakeAnalyzeRequest):
    create_queue_card: bool = True



@app.get("/metadata", tags=["Dental PMS Mock"])
def metadata():
    return {
        "practice_name": "BrightSmile Dental",
        "mock_pms": "dental PMS-style training sandbox",
        "modules": ["Appointment Book", "Appointment Queue", "Patient Search", "Patient Alerts", "Reminder Status", "Audit Log"],
        "appointment_types": APPOINTMENT_TYPES,
        "confirmation_statuses": CONFIRMATION_STATUSES,
        "safety_note": "Prototype mock only. Use human approval before live PMS writes.",
        "research_sources": [
            "Generic dental scheduling workflow concepts",
            "Generic appointment-book, queue, patient-search, reminder, and alert concepts",
        ],
    }


@app.get("/health", tags=["Operations"])
def health():
    return {"ok": True, "service": "dental-ai-receptionist", "version": app.version}


@app.get("/patients", tags=["Patients"])
def search_patients(name: Optional[str] = Query(None), dob: Optional[str] = Query(None), phone: Optional[str] = Query(None)):
    with get_conn() as conn:
        query = "SELECT * FROM patients WHERE 1=1"
        params: list[str] = []
        if name:
            like = f"%{name}%"
            query += " AND (first_name LIKE ? OR last_name LIKE ? OR chart_number LIKE ?)"
            params += [like, like, like]
        if dob:
            query += " AND date_of_birth = ?"
            params.append(dob)
        if phone:
            query += " AND phone_number LIKE ?"
            params.append(f"%{phone}%")
        query += " ORDER BY last_name, first_name"
        rows = conn.execute(query, params).fetchall()
    return [rowdict(r) for r in rows]


@app.get("/patients/{patient_id}", tags=["Patients"])
def get_patient(patient_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM patients WHERE patient_id = ?", [patient_id]).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Patient not found")
    return rowdict(row)


@app.post("/patients", status_code=201, tags=["Patients"])
def create_patient(p: PatientCreate):
    first = normalize_name(p.first_name)
    last = normalize_name(p.last_name)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM patients WHERE lower(first_name)=lower(?) AND lower(last_name)=lower(?) AND date_of_birth=?",
            [first, last, p.date_of_birth],
        ).fetchone()
        if existing:
            return {"message": "Patient already exists", "patient": rowdict(existing)}
        pid = str(uuid.uuid4())
        chart = f"DEMO{conn.execute('SELECT COUNT(*) FROM patients').fetchone()[0] + 1001}"
        conn.execute(
            """INSERT INTO patients
               (patient_id, first_name, last_name, date_of_birth, phone_number, email, chart_number,
                preferred_provider, responsible_party, patient_alert, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [pid, first, last, p.date_of_birth, p.phone_number, p.email, chart, p.preferred_provider,
             p.responsible_party, p.patient_alert, now()],
        )
        audit(conn, "patient_create", f"Created patient {first} {last}", pid)
    return {"message": "Patient created", "patient_id": pid, "chart_number": chart}


@app.get("/appointments/available", tags=["Appointment Book"])
def get_available_slots(date: str = Query(...), provider: Optional[str] = DEFAULT_PROVIDER, chair: Optional[str] = None):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    with get_conn() as conn:
        query = """SELECT appointment_time FROM appointments
                   WHERE appointment_date=? AND provider=? AND status!='cancelled'"""
        params = [date, provider]
        if chair:
            query += " AND chair=?"
            params.append(chair)
        booked = conn.execute(query, params).fetchall()
    booked_times = {r["appointment_time"] for r in booked}
    available = [s for s in all_slots() if s not in booked_times]
    return {
        "date": date,
        "provider": provider,
        "chair": chair or "any",
        "available_slots": [{"time_24": s, "time_12": fmt12(s)} for s in available],
        "total_available": len(available),
    }


@app.get("/appointments", tags=["Appointment Book"])
def list_appointments(date: Optional[str] = None, provider: Optional[str] = None, status: Optional[str] = None):
    with get_conn() as conn:
        query = """
            SELECT a.*, p.first_name, p.last_name, p.date_of_birth, p.phone_number, p.chart_number, p.patient_alert
            FROM appointments a JOIN patients p ON a.patient_id = p.patient_id WHERE 1=1
        """
        params = []
        if date:
            query += " AND a.appointment_date=?"
            params.append(date)
        if provider:
            query += " AND a.provider=?"
            params.append(provider)
        if status:
            query += " AND a.status=?"
            params.append(status)
        query += " ORDER BY a.appointment_date, a.appointment_time"
        rows = conn.execute(query, params).fetchall()
    return [rowdict(r) for r in rows]


@app.get("/appointments/{appointment_id}", tags=["Appointment Book"])
def get_appointment(appointment_id: str):
    with get_conn() as conn:
        row = conn.execute(
            """SELECT a.*, p.first_name, p.last_name, p.phone_number, p.chart_number, p.patient_alert
               FROM appointments a JOIN patients p ON a.patient_id=p.patient_id WHERE a.appointment_id=?""",
            [appointment_id],
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return rowdict(row)


@app.post("/appointments", status_code=201, tags=["Appointment Book"])
def create_appointment(a: AppointmentCreate):
    try:
        datetime.strptime(a.appointment_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    if a.appointment_time not in all_slots():
        raise HTTPException(status_code=400, detail="Invalid time slot. Office hours are 08:00–16:30 in 30-min increments.")
    provider = a.provider or DEFAULT_PROVIDER
    chair = a.chair or DEFAULT_CHAIR
    with get_conn() as conn:
        patient = conn.execute("SELECT * FROM patients WHERE patient_id=?", [a.patient_id]).fetchone()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        conflict = conn.execute(
            """SELECT appointment_id FROM appointments
               WHERE appointment_date=? AND appointment_time=? AND provider=? AND chair=? AND status!='cancelled'""",
            [a.appointment_date, a.appointment_time, provider, chair],
        ).fetchone()
        if conflict:
            raise HTTPException(status_code=409, detail="That Appointment Book time/chair is already booked.")
        aid = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO appointments
               (appointment_id, patient_id, provider, hygienist, chair, appointment_date, appointment_time,
                duration_minutes, appointment_type, reason_for_visit, confirmation_status, confirmation_note, note, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
            [aid, a.patient_id, provider, a.hygienist, chair, a.appointment_date, a.appointment_time,
             a.duration_minutes or SLOT_MINUTES, a.appointment_type or "Prophy", a.reason_for_visit,
             a.confirmation_status or "Unconfirmed", a.confirmation_note, a.note, now()],
        )
        audit(conn, "appointment_create", f"Booked {patient['first_name']} {patient['last_name']} on {a.appointment_date} at {a.appointment_time}", aid)
    return {
        "message": "Appointment booked successfully",
        "appointment_id": aid,
        "patient": f"{patient['first_name']} {patient['last_name']}",
        "date": a.appointment_date,
        "time": a.appointment_time,
        "provider": provider,
        "chair": chair,
        "appointment_type": a.appointment_type or "Prophy",
        "reason": a.reason_for_visit,
        "patient_alert": patient["patient_alert"],
    }


@app.put("/appointments/{appointment_id}", tags=["Appointment Book"])
def update_appointment_status(appointment_id: str, update: AppointmentUpdate):
    valid = {"scheduled", "completed", "cancelled", "failed", "no_show"}
    if update.status not in valid:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {sorted(valid)}")
    with get_conn() as conn:
        row = conn.execute("SELECT appointment_id FROM appointments WHERE appointment_id=?", [appointment_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Appointment not found")
        conn.execute("UPDATE appointments SET status=? WHERE appointment_id=?", [update.status, appointment_id])
        audit(conn, "appointment_status", f"Appointment status changed to {update.status}", appointment_id)
    return {"message": f"Appointment status updated to '{update.status}'"}


@app.put("/appointments/{appointment_id}/cancel", tags=["Appointment Book"])
def cancel_appointment(appointment_id: str):
    return update_appointment_status(appointment_id, AppointmentUpdate(status="cancelled"))


@app.put("/appointments/{appointment_id}/confirmation", tags=["Reminders"])
def update_confirmation(appointment_id: str, update: ConfirmationUpdate):
    if update.confirmation_status not in CONFIRMATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid confirmation status. Use {CONFIRMATION_STATUSES}")
    with get_conn() as conn:
        row = conn.execute("SELECT appointment_id FROM appointments WHERE appointment_id=?", [appointment_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Appointment not found")
        conn.execute(
            "UPDATE appointments SET confirmation_status=?, confirmation_note=? WHERE appointment_id=?",
            [update.confirmation_status, update.confirmation_note, appointment_id],
        )
        audit(conn, "confirmation", f"Confirmation updated to {update.confirmation_status}", appointment_id)
    return {"message": "Confirmation status updated"}


@app.get("/appointment-queue", tags=["Appointment Queue"])
def list_queue(status: Optional[str] = None):
    with get_conn() as conn:
        query = "SELECT * FROM appointment_queue WHERE 1=1"
        params = []
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
    return [enrich_queue_item(r) for r in rows]


@app.post("/appointment-queue", status_code=201, tags=["Appointment Queue"])
def create_queue_item(q: QueueCreate):
    qid = str(uuid.uuid4())
    with get_conn() as conn:
        if q.patient_id:
            patient = conn.execute("SELECT * FROM patients WHERE patient_id=?", [q.patient_id]).fetchone()
            if not patient:
                raise HTTPException(status_code=404, detail="Patient not found")
        conn.execute(
            """INSERT INTO appointment_queue
               (queue_id, patient_id, patient_name, phone_number, requested_date, requested_time, duration_minutes,
                appointment_type, provider, hygienist, chair, reason_for_visit, source, risk_level, status, staff_note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)""",
            [qid, q.patient_id, q.patient_name, q.phone_number, q.requested_date, q.requested_time,
             q.duration_minutes, q.appointment_type, q.provider, q.hygienist, q.chair, q.reason_for_visit,
             q.source, q.risk_level, q.staff_note, now()],
        )
        audit(conn, "queue_create", f"Queued appointment request for {q.patient_name}", qid)
    return {"message": "Appointment request added to dental PMS-style Appointment Queue", "queue_id": qid, "status": "queued"}


@app.put("/appointment-queue/{queue_id}", tags=["Appointment Queue"])
def update_queue_item(queue_id: str, update: QueueUpdate):
    valid = {"queued", "approved", "needs_info", "called", "rejected", "scheduled"}
    if update.status not in valid:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {sorted(valid)}")
    with get_conn() as conn:
        row = conn.execute("SELECT queue_id FROM appointment_queue WHERE queue_id=?", [queue_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Queue item not found")
        conn.execute("UPDATE appointment_queue SET status=?, staff_note=COALESCE(?, staff_note) WHERE queue_id=?", [update.status, update.staff_note, queue_id])
        audit(conn, "queue_update", f"Queue item moved to {update.status}", json.dumps({"queue_id": queue_id, "status": update.status, "staff_note": update.staff_note}))
    return {"message": f"Queue item updated to {update.status}"}


@app.get("/appointment-queue/{queue_id}/recommended-slots", tags=["Appointment Queue"])
def recommended_slots(queue_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM appointment_queue WHERE queue_id=?", [queue_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Queue item not found")
        item = enrich_queue_item(row)
        if item["automation_mode"] == "stop_and_escalate":
            return {"queue_id": queue_id, "recommended_slots": [], "reason": item["safety_summary"]}
        requested_date = item.get("requested_date") or (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            datetime.strptime(requested_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Queue item requested_date must be YYYY-MM-DD for slot recommendation")
        booked = conn.execute(
            """SELECT appointment_time FROM appointments
               WHERE appointment_date=? AND provider=? AND chair=? AND status!='cancelled'""",
            [requested_date, item.get("provider") or DEFAULT_PROVIDER, item.get("chair") or DEFAULT_CHAIR],
        ).fetchall()
    booked_times = {r["appointment_time"] for r in booked}
    available = [{"time_24": s, "time_12": fmt12(s)} for s in all_slots() if s not in booked_times]
    preferred = filtered_slots_for_preference(available, item.get("requested_time"))
    return {
        "queue_id": queue_id,
        "date": requested_date,
        "preference": item.get("requested_time"),
        "recommended_slots": preferred[:5],
        "automation_mode": item["automation_mode"],
        "recommended_action": item["recommended_action"],
    }


@app.post("/appointment-queue/{queue_id}/schedule", status_code=201, tags=["Appointment Queue"])
def schedule_from_queue(queue_id: str, request: QueueScheduleRequest):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM appointment_queue WHERE queue_id=?", [queue_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Queue item not found")
        item = enrich_queue_item(row)
        if item["status"] != "approved":
            raise HTTPException(status_code=400, detail="Queue item must be approved by staff before scheduling")
        if item["automation_mode"] == "stop_and_escalate":
            raise HTTPException(status_code=400, detail="Urgent/escalated items cannot be auto-scheduled")
        if not item.get("patient_id"):
            raise HTTPException(status_code=400, detail="Queue item needs an exact patient match before scheduling")
    appointment = create_appointment(
        AppointmentCreate(
            patient_id=item["patient_id"],
            appointment_date=request.appointment_date,
            appointment_time=request.appointment_time,
            reason_for_visit=item.get("reason_for_visit"),
            provider=item.get("provider") or DEFAULT_PROVIDER,
            hygienist=item.get("hygienist") or DEFAULT_HYGIENIST,
            chair=item.get("chair") or DEFAULT_CHAIR,
            duration_minutes=item.get("duration_minutes") or SLOT_MINUTES,
            appointment_type=item.get("appointment_type") or "Prophy",
            note=f"Scheduled from approved after-hours queue card {queue_id}. {request.staff_note or ''}".strip(),
            confirmation_note=request.staff_note,
        )
    )
    with get_conn() as conn:
        conn.execute(
            "UPDATE appointment_queue SET status='scheduled', requested_date=?, requested_time=?, staff_note=COALESCE(?, staff_note) WHERE queue_id=?",
            [request.appointment_date, request.appointment_time, request.staff_note, queue_id],
        )
        audit(conn, "queue_scheduled", f"Queue item scheduled into Appointment Book for {item['patient_name']}", json.dumps({"queue_id": queue_id, "appointment_id": appointment["appointment_id"]}))
    return {"message": "Approved queue item scheduled", "queue_id": queue_id, **appointment}


@app.post("/ai/intake/analyze", tags=["AI Intake"])
def analyze_intake(request: IntakeAnalyzeRequest):
    """Convert an untrusted caller transcript into a structured, safety-scored intake."""
    return extract_intake(request.transcript).to_dict()


@app.post("/ai/intake/queue", status_code=201, tags=["AI Intake"])
def analyze_and_queue_intake(request: IntakeQueueRequest):
    """Analyze a transcript and create a staff-review card; never books directly."""
    result = extract_intake(request.transcript).to_dict()
    if not request.create_queue_card:
        return {"analysis": result, "queue": None}
    queued = create_queue_item(
        QueueCreate(
            patient_name=result["patient_name"] or "Unidentified caller",
            phone_number=result["phone_number"],
            requested_date=result["requested_date"],
            requested_time=result["requested_time"],
            appointment_type=result["appointment_type"],
            reason_for_visit=result["reason_for_visit"],
            risk_level=result["risk_level"],
            source=f"AI intake ({result['engine']})",
            staff_note=(
                "Safety flags: " + ", ".join(result["safety_flags"])
                if result["safety_flags"]
                else "Structured from synthetic demo transcript; staff verification required."
            ),
        )
    )
    return {"analysis": result, "queue": queued}


@app.post("/demo/seed-queue/{scenario}", status_code=201, tags=["Demo"])
def seed_queue_scenario(scenario: str):
    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
    scenarios = {
        "routine": QueueCreate(patient_name="Alex Carter", phone_number="202-555-0100", requested_date=tomorrow, requested_time="morning", appointment_type="Prophy", reason_for_visit="Routine cleaning after-hours request", risk_level="routine", source="Demo seed: routine after-hours"),
        "urgent": QueueCreate(patient_name="Alex Carter", phone_number="202-555-0100", appointment_type="Limited/Emergency", reason_for_visit="Severe tooth pain and swelling", risk_level="urgent", source="Demo seed: urgent after-hours"),
        "new_patient": QueueCreate(patient_name="Taylor Newpatient", phone_number="202-555-0199", requested_date=tomorrow, requested_time="afternoon", appointment_type="New Patient Exam", reason_for_visit="New patient exam and x-rays", risk_level="needs_review", source="Demo seed: new patient"),
        "needs_info": QueueCreate(patient_name="Unclear Caller", phone_number=None, requested_date=tomorrow, requested_time="sometime", appointment_type="Periodic Exam", reason_for_visit="Caller wants appointment but phone number was unclear", risk_level="needs_review", source="Demo seed: needs info", staff_note="Needs callback number before scheduling"),
    }
    if scenario not in scenarios:
        raise HTTPException(status_code=404, detail=f"Unknown scenario. Use one of: {sorted(scenarios)}")
    created = create_queue_item(scenarios[scenario])
    if scenario == "needs_info":
        update_queue_item(created["queue_id"], QueueUpdate(status="needs_info", staff_note="Needs callback number before scheduling"))
    return {"scenario": scenario, **created}


@app.get("/audit-log", tags=["Audit"])
def audit_log(limit: int = Query(50, ge=1, le=200)):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", [limit]).fetchall()
    return [rowdict(r) for r in rows]


@app.get("/stats", tags=["Dashboard"])
def get_stats(date: Optional[str] = None):
    today = date or datetime.utcnow().strftime("%Y-%m-%d")
    with get_conn() as conn:
        total_today = conn.execute("SELECT COUNT(*) FROM appointments WHERE appointment_date=? AND status!='cancelled'", [today]).fetchone()[0]
        completed_today = conn.execute("SELECT COUNT(*) FROM appointments WHERE appointment_date=? AND status='completed'", [today]).fetchone()[0]
        total_patients = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        upcoming = conn.execute("SELECT COUNT(*) FROM appointments WHERE appointment_date>=? AND status='scheduled'", [today]).fetchone()[0]
        queued = conn.execute("SELECT COUNT(*) FROM appointment_queue WHERE status='queued'").fetchone()[0]
    return {"date": today, "total_today": total_today, "completed_today": completed_today,
            "remaining_today": total_today - completed_today, "total_patients": total_patients,
            "upcoming": upcoming, "queued_requests": queued}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def staff_ui():
    return HTMLResponse(STAFF_UI_HTML)


STAFF_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>BrightSmile Dental — After-Hours Queue</title>
<style>
:root{--navy:#153e75;--blue:#2864a7;--sky:#d7e8f7;--gold:#f6c343;--green:#1f9d55;--red:#c0392b;--orange:#d35400;--bg:#eef3f8;--card:#fff;--border:#cfd9e5}*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;background:var(--bg);font-size:14px;color:#17202a}header{background:linear-gradient(90deg,var(--navy),var(--blue));color:white;padding:12px 22px;display:flex;align-items:center;gap:16px;box-shadow:0 2px 8px #0003}h1{font-size:20px;margin:0}.pill{border:1px solid #ffffff80;border-radius:20px;padding:4px 10px;font-size:12px}.wrap{max-width:1320px;margin:auto;padding:18px}.help{background:#fff8df;border:1px solid #f6d26f;border-radius:8px;padding:10px 12px;margin-bottom:14px}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.stat,.card,.queue-card{background:var(--card);border:1px solid var(--border);border-radius:8px}.stat{text-align:center;padding:14px}.num{font-size:26px;font-weight:bold;color:var(--navy)}.lbl{font-size:12px;color:#5d6d7e}.tabs,.demo-row{display:flex;gap:8px;margin:16px 0;flex-wrap:wrap}.tabs button{background:white;color:var(--navy);border:1px solid var(--blue)}button{background:var(--blue);color:#fff;border:0;border-radius:6px;padding:8px 12px;cursor:pointer;font-weight:bold}button:hover{filter:brightness(1.08)}button.success{background:var(--green)}button.warn{background:var(--orange)}button.danger{background:var(--red)}button.light{background:#eef4fa;color:var(--navy);border:1px solid var(--border)}.grid{display:grid;grid-template-columns:1fr 420px;gap:16px}.head{background:var(--navy);color:white;padding:10px 14px;border-radius:8px 8px 0 0;font-weight:bold;display:flex;justify-content:space-between}.body{padding:14px}.row{display:flex;gap:10px;margin-bottom:10px;align-items:center}input,select,textarea{border:1px solid var(--border);border-radius:6px;padding:7px 9px;width:100%}.schedule{max-height:650px;overflow:auto}.slot{display:grid;grid-template-columns:75px 1fr;gap:10px;border-bottom:1px solid #edf1f5;padding:9px}.time{font-weight:bold;color:var(--navy)}.appt{border-left:4px solid var(--blue);background:#edf5fd;border-radius:6px;padding:9px}.empty{border-left-color:#c8d2dc;background:#fafbfc;color:#9aa6b2}.alert{color:#8a5a00;background:#fff4cc;border-radius:5px;padding:4px 6px;margin-top:5px;font-size:12px}.badge{display:inline-block;border-radius:12px;padding:3px 8px;font-size:12px;margin:2px;background:#edf1f5;color:#34495e}.badge.urgent{background:#ffe0dc;color:#9d2418}.badge.routine{background:#e7f6ee;color:#136a3a}.badge.needs{background:#fff4cc;color:#8a5a00}.queue-card{padding:12px;margin-bottom:12px;border-left:6px solid var(--blue)}.queue-card.urgent{border-left-color:var(--red)}.queue-card.needs{border-left-color:var(--gold)}.queue-title{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}.small{font-size:12px;color:#5d6d7e}.rec{margin:8px 0;padding:8px;border-radius:6px;background:#f6f9fc;border:1px solid #dbe6f1}.actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.msg{margin-top:8px;font-size:13px}.ok{color:var(--green)}.err{color:var(--red)}pre{white-space:pre-wrap;background:#f8fafc;border:1px solid var(--border);padding:8px;border-radius:6px}
</style></head>
<body><header><h1>🦷 BrightSmile Dental</h1><span class="pill">After-Hours Receptionist + Mock Dental PMS Queue</span><span style="margin-left:auto" id="clock"></span></header>
<div class="wrap">
<div class="help"><b>Human-approved safety boundary:</b> Ava collects after-hours requests and creates queue cards. Staff reviews, calls back, or approves before any mock Appointment Book write.</div>
<div class="stats"><div class="stat"><div id="s-total" class="num">—</div><div class="lbl">Today</div></div><div class="stat"><div id="s-done" class="num">—</div><div class="lbl">Completed</div></div><div class="stat"><div id="s-rem" class="num">—</div><div class="lbl">Remaining</div></div><div class="stat"><div id="s-pts" class="num">—</div><div class="lbl">Patients</div></div><div class="stat"><div id="s-queue" class="num">—</div><div class="lbl">Queued</div></div></div>
<div class="tabs"><button onclick="showTab('queue')">AI Queue</button><button onclick="showTab('schedule')">Appointment Book</button><button onclick="showTab('audit')">Audit Log</button><input type="date" id="dateInput" onchange="currentDate=this.value;loadAll()" style="max-width:170px"><button onclick="currentDate=new Date().toISOString().slice(0,10);loadAll()">Today</button></div>
<section id="tab-queue"><div class="card" style="margin-bottom:16px"><div class="head">✨ AI Transcript Intake</div><div class="body"><p class="small">Paste a synthetic caller transcript. The default credential-free engine extracts structured intake, detects urgency and prompt injection, and sends the result to staff review—never directly to scheduling.</p><textarea id="aiTranscript" rows="3">Hi, my name is Jamie Lee. I am an existing patient. Call me at 202-555-0142. I need a cleaning Tuesday morning.</textarea><br><br><button onclick="analyzeTranscript(false)">Analyze only</button> <button class="success" onclick="analyzeTranscript(true)">Analyze + queue for staff</button><div id="aiResult" class="msg"></div></div></div><div class="grid"><div class="card"><div class="head"><span>📥 Staff Review Cards</span><span id="queueCount"></span></div><div class="body"><div class="demo-row"><button class="light" onclick="seedDemo('routine')">Seed routine</button><button class="light" onclick="seedDemo('urgent')">Seed urgent</button><button class="light" onclick="seedDemo('new_patient')">Seed new patient</button><button class="light" onclick="seedDemo('needs_info')">Seed needs-info</button></div><div id="queueList"></div></div></div><div class="card"><div class="head">🤖 Manual Queue Card</div><div class="body"><input id="qName" placeholder="Patient name"><br><br><input id="qPhone" placeholder="Phone"><br><br><input type="date" id="qDate"><br><br><input id="qTime" placeholder="Requested time, e.g. morning or 14:00"><br><br><select id="qType"></select><br><br><textarea id="qReason" placeholder="Reason / intake summary"></textarea><br><br><select id="qRisk"><option>routine</option><option>needs_review</option><option>urgent</option><option>stop</option></select><br><br><button onclick="createQueue()" style="width:100%">Add to Appointment Queue</button><div id="queueMsg" class="msg"></div></div></div></div></section>
<section id="tab-schedule" style="display:none"><div class="grid"><div class="card"><div class="head"><span>📅 Appointment Book — <span id="dateLabel"></span></span><span id="apptCount"></span></div><div class="schedule" id="slotList"></div></div><div class="card"><div class="head">➕ Controlled Mock Booking</div><div class="body"><div class="row"><input id="ptSearch" placeholder="Search patient name, chart #, DOB…" oninput="searchPatients()"></div><div id="searchResults"></div><div id="selectedPatient" class="help" style="display:none"></div><div class="row"><input type="date" id="bookDate"></div><div class="row"><select id="apptType"></select><select id="chair"><option>Chair 1</option><option>Chair 2</option><option>Hygiene 1</option></select></div><div class="row"><select id="provider"><option>Dr. Rivera DDS</option><option>Dr. Chen DDS</option></select></div><div class="row"><button onclick="loadAvailSlots()">Check Slots</button></div><div id="availSlots"></div><div class="row"><input id="bookReason" placeholder="Reason / services"></div><div class="row"><input id="bookNote" placeholder="Confirmation note / AI intake trace"></div><button onclick="bookAppointment()" style="width:100%">Book in Mock Appointment Book</button><div id="bookMsg" class="msg"></div></div></div></div></section>
<section id="tab-audit" style="display:none"><div class="card"><div class="head">Audit Log</div><div class="body" id="auditList"></div></div></section>
</div><script>
let currentDate=new Date().toISOString().slice(0,10), selectedPatientId=null, selectedSlot=null; const ALL=[]; for(let h=8;h<17;h++)for(let m=0;m<60;m+=30)ALL.push(`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`); const TYPES=['Periodic Exam','Prophy','New Patient Exam','Limited/Emergency','Crown Seat','Consult'];
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function fmt12(t){let [h,m]=t.split(':').map(Number),s=h<12?'AM':'PM'; if(h==0)h=12; else if(h>12)h-=12; return `${h}:${String(m).padStart(2,'0')} ${s}`}
function msg(id,text,ok=true){let e=document.getElementById(id); e.className='msg '+(ok?'ok':'err'); e.textContent=text}
function showTab(t){['schedule','queue','audit'].forEach(x=>document.getElementById('tab-'+x).style.display=x==t?'block':'none'); if(t==='queue')loadQueue(); if(t==='audit')loadAudit(); if(t==='schedule')loadSchedule()}
setInterval(()=>clock.textContent=new Date().toLocaleTimeString(),1000); TYPES.forEach(t=>{apptType.innerHTML+=`<option>${t}</option>`; qType.innerHTML+=`<option>${t}</option>`})
async function loadStats(){let d=await(await fetch('/stats?date='+currentDate)).json(); ['total','done','rem','pts','queue'].forEach((k,i)=>document.getElementById('s-'+k).textContent=[d.total_today,d.completed_today,d.remaining_today,d.total_patients,d.queued_requests][i])}
async function loadSchedule(){dateInput.value=currentDate; bookDate.value=currentDate; qDate.value=qDate.value||currentDate; dateLabel.textContent=new Date(currentDate+'T00:00').toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric'}); let appts=await(await fetch('/appointments?date='+currentDate)).json(); let by={}; appts.forEach(a=>by[a.appointment_time]=a); slotList.innerHTML=ALL.map(s=>{let a=by[s]; if(!a)return `<div class="slot"><div class="time">${fmt12(s)}</div><div class="appt empty">— Available —</div></div>`; return `<div class="slot"><div class="time">${fmt12(s)}</div><div class="appt"><b>${esc(a.first_name)} ${esc(a.last_name)}</b> <span class="small">${esc(a.chart_number||'')}</span><br><span class="small">${esc(a.appointment_type)} · ${esc(a.provider)} · ${esc(a.chair)} · ${esc(a.confirmation_status)}</span>${a.patient_alert?`<div class="alert">⚠ ${esc(a.patient_alert)}</div>`:''}<div>${esc(a.reason_for_visit||'')}</div><span class="badge">${esc(a.status)}</span> <button class="success" onclick="statusAppt('${a.appointment_id}','completed')">Complete</button> <button class="danger" onclick="statusAppt('${a.appointment_id}','cancelled')">Cancel</button></div></div>`}).join(''); apptCount.textContent=appts.length+' appointment(s)'}
async function searchPatients(){let q=ptSearch.value.trim(); if(!q){searchResults.innerHTML='';return} let pts=await(await fetch('/patients?name='+encodeURIComponent(q))).json(); searchResults.innerHTML=pts.map(p=>`<div class="queue-card" onclick="selectPatient('${p.patient_id}','${esc(p.first_name+' '+p.last_name)}','${p.date_of_birth}','${p.chart_number}','${esc(p.patient_alert||'')}')"><b>${esc(p.first_name)} ${esc(p.last_name)}</b> <span class="small">${esc(p.chart_number)}</span><br><span class="small">DOB ${esc(p.date_of_birth)} · ${esc(p.phone_number||'')}</span>${p.patient_alert?`<div class="alert">⚠ ${esc(p.patient_alert)}</div>`:''}</div>`).join('')||'<div class=small>No patients found</div>'}
function selectPatient(id,name,dob,chart,alert){selectedPatientId=id; searchResults.innerHTML=''; ptSearch.value=''; selectedPatient.style.display='block'; selectedPatient.innerHTML=`✓ Selected <b>${name}</b> · ${chart} · DOB ${dob}${alert?`<div class="alert">⚠ ${alert}</div>`:''}`}
async function loadAvailSlots(){let d=bookDate.value||currentDate, c=chair.value; let data=await(await fetch(`/appointments/available?date=${d}&chair=${encodeURIComponent(c)}`)).json(); availSlots.innerHTML=data.available_slots.map(s=>`<button style="margin:3px" onclick="selectedSlot='${s.time_24}'; availSlots.querySelectorAll('button').forEach(b=>b.style.background='var(--blue)'); this.style.background='var(--green)'">${s.time_12}</button>`).join('')||'<div class=alert>No slots available</div>'}
async function bookAppointment(){if(!selectedPatientId)return msg('bookMsg','Select a patient first',false); if(!selectedSlot)return msg('bookMsg','Select a slot first',false); let payload={patient_id:selectedPatientId,appointment_date:bookDate.value||currentDate,appointment_time:selectedSlot,appointment_type:apptType.value,provider:provider.value,chair:chair.value,reason_for_visit:bookReason.value,note:bookNote.value,confirmation_note:bookNote.value}; let r=await fetch('/appointments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); let d=await r.json(); if(r.ok){msg('bookMsg',`Booked ${d.patient} ${d.date} ${d.time}`); selectedSlot=null; loadAll()} else msg('bookMsg',d.detail||'Booking failed',false)}
async function statusAppt(id,status){await fetch('/appointments/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})}); loadAll()}
async function analyzeTranscript(queue){let transcript=aiTranscript.value.trim(); if(!transcript)return msg('aiResult','Enter a synthetic transcript first',false); let path=queue?'/ai/intake/queue':'/ai/intake/analyze'; let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({transcript})}); let d=await r.json(); if(!r.ok)return msg('aiResult',d.detail||'Analysis failed',false); let a=d.analysis||d; aiResult.className='msg ok'; aiResult.innerHTML=`<b>${esc(a.patient_name||'Unidentified caller')}</b> · ${esc(a.appointment_type)} · <b>${esc(a.risk_level)}</b><br>${esc(a.phone_number||'missing phone')} · ${esc(a.requested_date||'no date')} ${esc(a.requested_time||'')}<br>mode: ${esc(a.automation_mode)} · confidence: ${esc(a.confidence)}${a.safety_flags.length?'<br>flags: '+esc(a.safety_flags.join(', ')):''}${queue?'<br><b>Sent to staff review queue.</b>':''}`; if(queue)loadAll()}
function riskClass(q){if(q.automation_mode==='stop_and_escalate')return 'urgent'; if((q.missing_info||[]).length)return 'needs'; return 'routine'}
async function loadQueue(){let qs=await(await fetch('/appointment-queue')).json(); queueCount.textContent=qs.length+' card(s)'; queueList.innerHTML=qs.map(q=>`<div class="queue-card ${riskClass(q)}"><div class="queue-title"><div><b>${esc(q.patient_name)}</b> <span class="badge ${riskClass(q)}">${esc(q.risk_level)}</span> <span class="badge">${esc(q.status)}</span></div><span class="small">${esc(q.created_at)}</span></div><div class="small">☎ ${esc(q.phone_number||'missing phone')} · ${esc(q.requested_date||'no date')} ${esc(q.requested_time||'')} · ${esc(q.appointment_type)}</div><div>${esc(q.reason_for_visit||'')}</div><div class="rec"><b>Recommended:</b> ${esc(q.recommended_action)}<br><span class="small">${esc(q.safety_summary)} · identity: ${esc(q.identity_confidence||'unknown')} · mode: ${esc(q.automation_mode)}</span><br><span class="small">${esc(q.identity_summary||'')}</span>${q.staff_note?`<br><b>Staff note:</b> ${esc(q.staff_note)}`:''}</div><div id="slots-${q.queue_id}" class="small"></div><div class="actions"><button class="success" onclick="queueStatus('${q.queue_id}','approved')">Approve</button><button class="warn" onclick="queueStatus('${q.queue_id}','called')">Call Back</button><button onclick="queueStatus('${q.queue_id}','needs_info')">Needs Info</button><button class="danger" onclick="queueStatus('${q.queue_id}','rejected')">Reject</button><button class="light" onclick="showSlots('${q.queue_id}')">Suggest Slots</button>${q.status==='approved'&&q.patient_id?`<button class="success" onclick="scheduleFirst('${q.queue_id}')">Schedule first slot</button>`:''}</div></div>`).join('')||'<div class=small>No queued requests</div>'}
async function createQueue(){let payload={patient_name:qName.value,phone_number:qPhone.value,requested_date:qDate.value,requested_time:qTime.value,appointment_type:qType.value,reason_for_visit:qReason.value,risk_level:qRisk.value,source:'Manual staff demo card'}; let r=await fetch('/appointment-queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); let d=await r.json(); msg('queueMsg',r.ok?'Queued request: '+d.queue_id:(d.detail||'Queue failed'),r.ok); loadQueue(); loadStats()}
async function queueStatus(id,status){let note=prompt('Staff note (optional):','')||null; await fetch('/appointment-queue/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status,staff_note:note})}); loadQueue(); loadStats(); loadAudit()}
async function showSlots(id){let r=await fetch(`/appointment-queue/${id}/recommended-slots`); let d=await r.json(); let box=document.getElementById('slots-'+id); if(!r.ok){box.innerHTML=`<div class="alert">${esc(d.detail||'No slots')}</div>`;return} box.innerHTML=d.recommended_slots.length?`<b>Suggested ${esc(d.date)}:</b> `+d.recommended_slots.map(s=>`<button class="light" onclick="scheduleQueue('${id}','${d.date}','${s.time_24}')">${s.time_12}</button>`).join(' '):`<div class="alert">No safe slot recommendation: ${esc(d.reason||'none')}</div>`}
async function scheduleFirst(id){let d=await(await fetch(`/appointment-queue/${id}/recommended-slots`)).json(); if(!d.recommended_slots.length)return alert('No recommended slots'); scheduleQueue(id,d.date,d.recommended_slots[0].time_24)}
async function scheduleQueue(id,date,time){let r=await fetch(`/appointment-queue/${id}/schedule`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({appointment_date:date,appointment_time:time,staff_note:'Scheduled from staff approval dashboard'})}); let d=await r.json(); if(!r.ok)alert(d.detail||'Schedule failed'); loadAll(); showTab('queue')}
async function seedDemo(s){let r=await fetch('/demo/seed-queue/'+s,{method:'POST'}); let d=await r.json(); msg('queueMsg',r.ok?'Seeded '+s+': '+d.queue_id:(d.detail||'Seed failed'),r.ok); loadAll()}
async function loadAudit(){let rows=await(await fetch('/audit-log')).json(); auditList.innerHTML=rows.map(a=>`<div class="queue-card"><b>${esc(a.event_type)}</b> <span class="small">${esc(a.created_at)}</span><br>${esc(a.summary)}${a.payload?`<pre>${esc(a.payload)}</pre>`:''}</div>`).join('')}
function loadAll(){loadStats();loadSchedule();loadQueue();loadAudit()} loadAll();
</script></body></html>"""
