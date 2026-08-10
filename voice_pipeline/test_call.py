#!/usr/bin/env python3
"""Local end-to-end after-hours simulation without Asterisk.

Usage:
  python3 test_call.py

Requires PMS API running at PMS_BASE_URL (default http://localhost:8000).
"""

from __future__ import annotations

from voice_bridge import VoiceStateMachine


def run_scripted_call() -> None:
    script = [
        "yes",
        "Alex Carter",
        "1968-09-04",
        "202-555-0100",
        "routine cleaning",
        "tomorrow morning",
        "no",
    ]

    sm = VoiceStateMachine(mode="after_hours")
    print("BOT:", sm.start())

    for turn in script:
        print("USER:", turn)
        reply = sm.step(turn)
        print("BOT:", reply)

    print("\n--- Call log ---")
    for line in sm.state.log:
        print(line)

    if sm.state.queue_id:
        print(f"\nQueued request: {sm.state.queue_id}")


if __name__ == "__main__":
    run_scripted_call()
