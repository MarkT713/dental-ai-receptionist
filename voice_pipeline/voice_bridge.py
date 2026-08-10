#!/usr/bin/env python3
"""BrightSmile Dental receptionist state machine.

Modes:
- after_hours (default): collect patient request and create an Appointment Queue card.
- booking_demo: explicit opt-in legacy mock booking; disabled by default.
- live transports: not included; unsupported modes fail closed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

from pms_client import PMSClient

STAFF_EXTENSION = os.getenv("STAFF_EXTENSION", "100")
PROVIDER = os.getenv("PMS_PROVIDER", "Dr. Rivera DDS")
PRACTICE_NAME = os.getenv("PRACTICE_NAME", "BrightSmile Dental")
RECEPTIONIST_NAME = os.getenv("RECEPTIONIST_NAME", "Ava")
DEFAULT_MODE = os.getenv("DENTAL_RECEPTIONIST_MODE", "after_hours").strip().lower()
URGENT_TERMS = ["pain", "severe", "swelling", "bleeding", "trauma", "broken tooth", "emergency", "infection", "abscess", "fever"]


@dataclass
class SessionState:
    patient_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    dob: Optional[str] = None
    phone_number: Optional[str] = None
    existing_patient: Optional[bool] = None
    reason: Optional[str] = None
    selected_date: Optional[str] = None
    selected_time: Optional[str] = None
    preferred_window: Optional[str] = None
    queue_id: Optional[str] = None
    queue_created: bool = False
    awaiting_more: bool = False
    turns: int = 0
    transferred: bool = False
    transfer_requested: bool = False
    log: List[str] = field(default_factory=list)

    @property
    def patient_name(self) -> str:
        return " ".join(p for p in [self.first_name, self.last_name] if p).strip() or "Unknown patient"


class VoiceStateMachine:
    def __init__(self, pms: Optional[PMSClient] = None, mode: Optional[str] = None):
        self.pms = pms or PMSClient()
        self.mode = (mode or DEFAULT_MODE or "after_hours").strip().lower()
        if self.mode == "booking_demo" and os.getenv("ALLOW_UNSAFE_DIRECT_BOOKING_DEMO", "false").lower() not in {
            "1", "true", "yes"
        }:
            raise RuntimeError("booking_demo is disabled; after_hours preserves the human-approval boundary")
        if self.mode not in {"after_hours", "booking_demo"}:
            raise ValueError(f"Unsupported receptionist mode: {self.mode}")
        self.state = SessionState()

    def _say(self, text: str) -> str:
        self.state.log.append(f"BOT: {text}")
        return text

    def _extract_dob(self, text: str) -> Optional[str]:
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        return m.group(1) if m else None

    def _extract_name(self, text: str) -> Optional[tuple[str, str]]:
        m = re.search(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b", text)
        if not m:
            # tolerate lowercase console tests/call transcripts
            m = re.search(r"\b([a-z]+)\s+([a-z]+)\b", text.lower())
        if not m:
            return None
        return m.group(1).title(), m.group(2).title()

    def _extract_phone(self, text: str) -> Optional[str]:
        digits = re.sub(r"\D", "", text)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        if 7 <= len(digits) < 10:
            return digits
        return None

    def _extract_time_24(self, text: str) -> Optional[str]:
        m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
        m2 = re.search(r"\b(1[0-2]|[1-9])\s*(am|pm)\b", text.lower())
        if not m2:
            return None
        h = int(m2.group(1))
        ap = m2.group(2)
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return f"{h:02d}:00"

    def _extract_date(self, text: str) -> Optional[str]:
        iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if iso:
            return iso.group(1)
        lower = text.lower()
        if "tomorrow" in lower:
            return (date.today() + timedelta(days=1)).isoformat()
        if "today" in lower:
            return date.today().isoformat()
        return None

    def _extract_preferred_window(self, text: str) -> tuple[Optional[str], Optional[str]]:
        lower = text.lower()
        requested_date = self._extract_date(text)
        if "morning" in lower:
            return requested_date, "morning"
        if "afternoon" in lower:
            return requested_date, "afternoon"
        if "evening" in lower:
            return requested_date, "evening"
        time_24 = self._extract_time_24(text)
        if time_24:
            return requested_date, time_24
        return requested_date, text.strip()

    def _is_yes(self, text: str) -> bool:
        return text.strip().lower() in {"yes", "yeah", "yep", "correct", "existing", "i am", "yes i am"}

    def _is_no(self, text: str) -> bool:
        return text.strip().lower() in {"no", "nope", "new", "not", "that's all", "thats all", "nothing", "nothing else", "all good"}

    def _is_urgent(self, text: str) -> bool:
        lower = text.lower()
        return any(term in lower for term in URGENT_TERMS)

    def _appointment_type(self, reason: str) -> str:
        lower = reason.lower()
        if any(k in lower for k in ["cleaning", "prophy", "hygiene"]):
            return "Prophy"
        if any(k in lower for k in ["new patient", "first visit"]):
            return "New Patient Exam"
        if self._is_urgent(reason):
            return "Limited/Emergency"
        if "consult" in lower:
            return "Consult"
        return "Periodic Exam"

    def transfer_to_staff(self, reason: str = "caller request") -> str:
        self.state.transfer_requested = True
        self.state.awaiting_more = True
        return self._say(
            f"I can’t complete a live transfer in this demo. I’ll flag a front-desk callback request "
            f"for extension {STAFF_EXTENSION}. Reason: {reason}. Is there anything else I should add?"
        )

    def start(self) -> str:
        if self.mode == "booking_demo":
            return self._say(
                f"Hello, this is {RECEPTIONIST_NAME} with {PRACTICE_NAME}. "
                f"I can help with a dental appointment request for {PROVIDER}. "
                "Please say your first and last name."
            )
        return self._say(
            f"Thanks for calling {PRACTICE_NAME}. This is {RECEPTIONIST_NAME}. "
            "Our office is currently closed, but I can collect your appointment request or message for the team. "
            "Are you an existing patient?"
        )

    def step(self, user_text: str) -> str:
        self.state.turns += 1
        self.state.log.append(f"USER: {user_text}")
        lower = user_text.lower()

        if any(k in lower for k in ["human", "agent", "representative", "front desk", "transfer"]):
            return self.transfer_to_staff("caller asked for human")

        if self.mode == "booking_demo":
            return self._step_booking_demo(user_text)
        return self._step_after_hours(user_text)

    def _step_after_hours(self, user_text: str) -> str:
        if self.state.awaiting_more:
            if self._is_no(user_text):
                return self._say("You’re all set. I’ll make sure the team gets your request. Have a good day.")
            return self._say("Got it. I’ll add that to the message for the team. Have a good day.")

        if self.state.existing_patient is None:
            if self._is_yes(user_text):
                self.state.existing_patient = True
                return self._say("Great, I have you as an existing patient. Please say your first and last name.")
            if self._is_no(user_text):
                self.state.existing_patient = False
                return self._say("No problem. Please say your first and last name.")
            return self._say("Are you an existing patient? Please say yes or no.")

        if self.state.first_name is None or self.state.last_name is None:
            maybe = self._extract_name(user_text)
            if not maybe:
                return self._say("Please say your first and last name, like John Smith.")
            self.state.first_name, self.state.last_name = maybe
            if self.state.existing_patient:
                return self._say("Thanks. Please provide your date of birth in YYYY-MM-DD format so the team can match your chart.")
            return self._say("Thanks. What is the best callback phone number?")

        if self.state.existing_patient and self.state.dob is None:
            dob = self._extract_dob(user_text)
            if not dob:
                return self._say("I didn’t catch that. Please provide date of birth as YYYY-MM-DD.")
            self.state.dob = dob
            existing = self.pms.find_patients(name=self.state.last_name, dob=dob)
            if len(existing) == 1:
                self.state.patient_id = existing[0].get("patient_id")
            # Multiple/no matches are still queued for staff review rather than auto-created.
            return self._say("Thank you. What is the best callback phone number?")

        if self.state.phone_number is None:
            phone = self._extract_phone(user_text)
            if not phone:
                return self._say("Please say the best callback phone number, including area code.")
            self.state.phone_number = phone
            return self._say("What is the reason for your call? For example, cleaning, new patient exam, tooth concern, or another message.")

        if self.state.reason is None:
            self.state.reason = user_text.strip()
            if self._is_urgent(self.state.reason):
                self._create_queue_item(risk_level="urgent")
                self.state.awaiting_more = True
                return self._say(
                    "I’m sorry you’re dealing with that. This may be urgent, so if symptoms are severe or worsening, "
                    "please seek emergency care or use the office emergency instructions. I’ll send this urgent message to the team. "
                    "Is there anything else I should add?"
                )
            return self._say("Do you have a preferred day or time for the appointment or callback?")

        if self.state.preferred_window is None:
            requested_date, requested_time = self._extract_preferred_window(user_text)
            self.state.selected_date = requested_date
            self.state.preferred_window = requested_time or user_text.strip()
            result = self._create_queue_item(risk_level="routine")
            self.state.awaiting_more = True
            qid = result.get("queue_id", "the request") if isinstance(result, dict) else "the request"
            return self._say(
                f"Got it. I’ll send this request to the team as {qid}, and they’ll follow up to confirm availability. "
                "Is there anything else I can add?"
            )

        return self._say("I already have the request queued for the team. Is there anything else I should add?")

    def _create_queue_item(self, risk_level: str) -> dict:
        result = self.pms.create_queue_item(
            patient_id=self.state.patient_id,
            patient_name=self.state.patient_name,
            phone_number=self.state.phone_number,
            requested_date=self.state.selected_date,
            requested_time=self.state.preferred_window,
            reason_for_visit=self.state.reason,
            appointment_type=self._appointment_type(self.state.reason or ""),
            risk_level=risk_level,
        )
        if isinstance(result, dict):
            self.state.queue_id = result.get("queue_id")
        self.state.queue_created = True
        return result if isinstance(result, dict) else {}

    def _step_booking_demo(self, user_text: str) -> str:
        if self._is_urgent(user_text):
            return self.transfer_to_staff("possible urgent dental symptom")

        if self.state.first_name is None or self.state.last_name is None:
            maybe = self._extract_name(user_text)
            if not maybe:
                return self._say("Please say your first and last name, like John Smith.")
            self.state.first_name, self.state.last_name = maybe
            return self._say("Thanks. Please provide your date of birth in YYYY-MM-DD format.")

        if self.state.dob is None:
            dob = self._extract_dob(user_text)
            if not dob:
                return self._say("I didn’t catch that. Please provide date of birth as YYYY-MM-DD.")
            self.state.dob = dob
            existing = self.pms.find_patients(name=self.state.last_name, dob=dob)
            if existing:
                self.state.patient_id = existing[0]["patient_id"]
            else:
                created = self.pms.create_patient(
                    first_name=self.state.first_name,
                    last_name=self.state.last_name,
                    date_of_birth=dob,
                    phone_number=self.state.phone_number,
                )
                self.state.patient_id = created.get("patient_id") or created.get("patient", {}).get("patient_id")
            return self._say("What day would you like? You can say a date like 2026-06-15 or tomorrow.")

        if self.state.selected_date is None:
            d = self._extract_date(user_text)
            if not d:
                return self._say("Please say the appointment date as YYYY-MM-DD, or say tomorrow.")
            self.state.selected_date = d
            slots = self.pms.available_slots(d).get("available_slots", [])
            if not slots:
                self.state.selected_date = None
                return self._say("That day is full. Please choose another date.")
            top = ", ".join(s["time_24"] for s in slots[:5])
            return self._say(f"Available times include {top}. Which time works for you?")

        if self.state.selected_time is None:
            t = self._extract_time_24(user_text)
            if not t:
                return self._say("Please provide a time like 09:30 or 2 PM.")
            self.state.selected_time = t
            return self._say("What is the reason for your visit?")

        if self.state.reason is None:
            self.state.reason = user_text.strip()
            try:
                result = self.pms.book_appointment(
                    patient_id=self.state.patient_id,
                    appointment_date=self.state.selected_date,
                    appointment_time=self.state.selected_time,
                    reason_for_visit=self.state.reason,
                    provider=PROVIDER,
                    appointment_type=self._appointment_type(self.state.reason),
                )
            except Exception as e:
                self.state.selected_time = None
                return self._say(f"That slot could not be booked ({e}). Please choose a different time.")

            return self._say(
                f"You are all set. Appointment confirmed on {result['date']} at {result['time']} "
                f"with {result['provider']}."
            )

        return self._say("Your appointment is already booked. Say transfer if you need the front desk.")


def run_console_demo() -> None:
    sm = VoiceStateMachine()
    print(sm.start())
    while True:
        try:
            msg = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            return
        if not msg:
            continue
        if msg.lower() in {"quit", "exit"}:
            print("Goodbye.")
            return
        reply = sm.step(msg)
        print(reply)
        if sm.state.transferred or (sm.state.awaiting_more and "Have a good day" in reply):
            return


def reject_unconfigured_live_transport() -> None:
    raise SystemExit(
        "Live telephony is not included in this public demo. Configure and test a provider adapter before deployment."
    )


def main() -> None:
    mode = os.getenv("DENTAL_AI_MODE", "console").strip().lower()
    if mode in {"eagi", "live", "telephony"}:
        reject_unconfigured_live_transport()
    else:
        run_console_demo()


if __name__ == "__main__":
    main()
