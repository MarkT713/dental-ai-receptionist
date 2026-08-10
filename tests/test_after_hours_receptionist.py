import importlib.util
import sys
from pathlib import Path

import pytest


class FakePMS:
    def __init__(self):
        self.queue_items = []
        self.bookings = []
        self.created_patients = []

    def find_patients(self, name=None, dob=None):
        if name == "Carter" and dob == "1968-09-04":
            return [{"patient_id": "P-DEMO", "first_name": "Alex", "last_name": "Carter"}]
        return []

    def create_patient(self, **kwargs):
        self.created_patients.append(kwargs)
        return {"patient_id": "P-NEW"}

    def available_slots(self, day):
        return {"available_slots": [{"time_24": "09:30", "time_12": "9:30 AM"}]}

    def book_appointment(self, **kwargs):
        self.bookings.append(kwargs)
        return {"date": kwargs["appointment_date"], "time": kwargs["appointment_time"], "provider": "Dr. Rivera DDS"}

    def create_queue_item(self, **kwargs):
        self.queue_items.append(kwargs)
        return {"queue_id": "Q1", "status": "queued"}


def load_voice_module():
    voice_dir = Path(__file__).resolve().parents[1] / "voice_pipeline"
    path = voice_dir / "voice_bridge.py"
    if str(voice_dir) not in sys.path:
        sys.path.insert(0, str(voice_dir))
    spec = importlib.util.spec_from_file_location("voice_bridge_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_after_hours_routine_flow_collects_phone_and_creates_queue_card():
    voice = load_voice_module()
    pms = FakePMS()
    sm = voice.VoiceStateMachine(pms=pms, mode="after_hours")

    assert "currently closed" in sm.start().lower()
    assert "existing patient" in sm.step("yes").lower()
    assert "date of birth" in sm.step("Alex Carter").lower()
    assert "callback" in sm.step("1968-09-04").lower()
    assert "reason" in sm.step("202-555-0100").lower()
    assert "preferred" in sm.step("routine cleaning").lower()
    reply = sm.step("tomorrow morning")

    assert "team" in reply.lower()
    assert "confirm" in reply.lower()
    assert "anything else" in reply.lower()
    assert len(pms.queue_items) == 1
    item = pms.queue_items[0]
    assert item["patient_id"] == "P-DEMO"
    assert item["patient_name"] == "Alex Carter"
    assert item["phone_number"] == "202-555-0100"
    assert item["requested_date"] is not None
    assert item["requested_time"] == "morning"
    assert item["reason_for_visit"] == "routine cleaning"
    assert item["risk_level"] == "routine"
    assert pms.bookings == []

    closing = sm.step("no")
    assert "have a good day" in closing.lower()


def test_after_hours_urgent_flow_creates_urgent_queue_not_transfer_only():
    voice = load_voice_module()
    pms = FakePMS()
    sm = voice.VoiceStateMachine(pms=pms, mode="after_hours")

    sm.start()
    sm.step("yes")
    sm.step("Alex Carter")
    sm.step("1968-09-04")
    sm.step("202-555-0100")
    reply = sm.step("I have severe tooth pain and swelling")

    assert "urgent" in reply.lower() or "emergency" in reply.lower()
    assert len(pms.queue_items) == 1
    item = pms.queue_items[0]
    assert item["risk_level"] == "urgent"
    assert "pain" in item["reason_for_visit"].lower()
    assert pms.bookings == []


def test_demo_booking_mode_can_still_book_directly(monkeypatch):
    voice = load_voice_module()
    monkeypatch.setenv("ALLOW_UNSAFE_DIRECT_BOOKING_DEMO", "true")
    pms = FakePMS()
    sm = voice.VoiceStateMachine(pms=pms, mode="booking_demo")

    sm.start()
    sm.step("Alex Carter")
    sm.step("1968-09-04")
    sm.step("tomorrow")
    sm.step("9:30")
    reply = sm.step("routine cleaning")

    assert "appointment confirmed" in reply.lower()
    assert len(pms.bookings) == 1
    assert pms.queue_items == []


def test_direct_booking_demo_is_disabled_by_default(monkeypatch):
    voice = load_voice_module()
    monkeypatch.delenv("ALLOW_UNSAFE_DIRECT_BOOKING_DEMO", raising=False)
    with pytest.raises(RuntimeError, match="human-approval boundary"):
        voice.VoiceStateMachine(pms=FakePMS(), mode="booking_demo")


def test_human_request_does_not_claim_an_unsupported_live_transfer():
    voice = load_voice_module()
    sm = voice.VoiceStateMachine(pms=FakePMS(), mode="after_hours")
    response = sm.step("Please transfer me to a human")
    assert "can’t complete a live transfer" in response.lower()
    assert "callback" in response.lower()
    assert sm.state.transfer_requested is True
    assert sm.state.transferred is False
