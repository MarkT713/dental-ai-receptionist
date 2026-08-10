#!/usr/bin/env python3
"""Run an end-to-end synthetic voice-turn simulation with no external providers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "voice_pipeline"))

from adapters import TextBytesSTT, TextBytesTTS, VoiceRuntime  # noqa: E402
from voice_bridge import VoiceStateMachine  # noqa: E402


class RecordingPMS:
    def __init__(self):
        self.queue_items: list[dict] = []
        self.bookings: list[dict] = []

    def find_patients(self, name=None, dob=None):
        if name == "Carter" and dob == "1968-09-04":
            return [{"patient_id": "P-SYNTHETIC"}]
        return []

    def create_queue_item(self, **kwargs):
        self.queue_items.append(kwargs)
        return {"queue_id": "Q-SYNTHETIC", "status": "queued"}

    def create_patient(self, **kwargs):
        raise AssertionError("After-hours simulation must not create a patient")

    def available_slots(self, day):
        raise AssertionError("After-hours simulation must not read live slots")

    def book_appointment(self, **kwargs):
        self.bookings.append(kwargs)
        raise AssertionError("After-hours simulation must not book directly")


def main() -> int:
    pms = RecordingPMS()
    runtime = VoiceRuntime(VoiceStateMachine(pms=pms, mode="after_hours"), TextBytesSTT(), TextBytesTTS())
    turns = [{"speaker": "assistant", "text": runtime.greeting().response_text}]
    for caller_text in [
        "yes",
        "Alex Carter",
        "1968-09-04",
        "202-555-0100",
        "routine cleaning",
        "tomorrow morning",
        "no",
    ]:
        result = runtime.process_turn(caller_text.encode(), content_type="text/plain")
        turns.extend([
            {"speaker": "caller", "text": result.transcript},
            {"speaker": "assistant", "text": result.response_text},
        ])

    report = {
        "transport": "synthetic-text-bytes",
        "live_audio_claimed": False,
        "queue_cards_created": len(pms.queue_items),
        "appointments_created": len(pms.bookings),
        "human_approval_preserved": len(pms.queue_items) == 1 and not pms.bookings,
        "turns": turns,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["human_approval_preserved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
