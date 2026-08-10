import importlib.util
import sys
from pathlib import Path

import pytest


def load_adapter_module():
    path = Path(__file__).resolve().parents[1] / "voice_pipeline" / "adapters.py"
    spec = importlib.util.spec_from_file_location("voice_adapters_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeSession:
    def __init__(self):
        self.messages = []

    def start(self):
        return "Synthetic greeting"

    def step(self, text):
        self.messages.append(text)
        return f"Recorded: {text}"


def test_provider_neutral_runtime_processes_synthetic_turns():
    adapters = load_adapter_module()
    session = FakeSession()
    runtime = adapters.VoiceRuntime(session, adapters.TextBytesSTT(), adapters.TextBytesTTS())

    greeting = runtime.greeting()
    assert greeting.response_audio == b"Synthetic greeting"
    assert greeting.response_content_type.startswith("text/plain")

    result = runtime.process_turn(b"I need a cleaning", content_type="text/plain")
    assert result.transcript == "I need a cleaning"
    assert result.response_text == "Recorded: I need a cleaning"
    assert result.response_audio == b"Recorded: I need a cleaning"
    assert session.messages == ["I need a cleaning"]


def test_synthetic_adapter_rejects_audio_and_empty_transcripts():
    adapters = load_adapter_module()
    stt = adapters.TextBytesSTT()
    with pytest.raises(ValueError, match="text/plain"):
        stt.transcribe(b"not really audio", content_type="audio/wav")
    with pytest.raises(ValueError, match="empty"):
        stt.transcribe(b"   ", content_type="text/plain")


def test_unconfigured_live_adapter_fails_closed():
    adapters = load_adapter_module()
    provider = adapters.ProviderNotConfigured("speech-to-text")
    with pytest.raises(RuntimeError, match="No live speech-to-text provider"):
        provider.transcribe(b"audio", content_type="audio/wav")
