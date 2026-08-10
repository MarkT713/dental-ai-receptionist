"""Provider-neutral contracts for a voice receptionist runtime.

The included adapters are text-byte simulators, not speech engines. They make the
turn-taking boundary executable and testable without claiming live STT/TTS or
telephony. Production adapters can implement the same protocols after a provider
and secure deployment are selected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SpeechToText(Protocol):
    def transcribe(self, audio: bytes, *, content_type: str) -> str: ...


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> tuple[bytes, str]: ...


class ReceptionistSession(Protocol):
    def start(self) -> str: ...

    def step(self, user_text: str) -> str: ...


@dataclass(frozen=True)
class VoiceTurn:
    transcript: str
    response_text: str
    response_audio: bytes
    response_content_type: str


class TextBytesSTT:
    """Decode UTF-8 test bytes as a transcript; for simulations only."""

    def transcribe(self, audio: bytes, *, content_type: str) -> str:
        if content_type not in {"text/plain", "text/plain; charset=utf-8"}:
            raise ValueError("TextBytesSTT only accepts text/plain synthetic input")
        text = audio.decode("utf-8").strip()
        if not text:
            raise ValueError("Synthetic transcript cannot be empty")
        return text


class TextBytesTTS:
    """Encode response text as UTF-8 test bytes; this does not synthesize speech."""

    def synthesize(self, text: str) -> tuple[bytes, str]:
        return text.encode("utf-8"), "text/plain; charset=utf-8"


class VoiceRuntime:
    """Connect a receptionist state machine to provider-neutral STT/TTS contracts."""

    def __init__(self, session: ReceptionistSession, stt: SpeechToText, tts: TextToSpeech):
        self.session = session
        self.stt = stt
        self.tts = tts

    def greeting(self) -> VoiceTurn:
        response_text = self.session.start()
        response_audio, response_content_type = self.tts.synthesize(response_text)
        return VoiceTurn("", response_text, response_audio, response_content_type)

    def process_turn(self, audio: bytes, *, content_type: str) -> VoiceTurn:
        transcript = self.stt.transcribe(audio, content_type=content_type)
        response_text = self.session.step(transcript)
        response_audio, response_content_type = self.tts.synthesize(response_text)
        return VoiceTurn(transcript, response_text, response_audio, response_content_type)


class ProviderNotConfigured:
    """Fail closed when code attempts to use an unconfigured live provider."""

    def __init__(self, capability: str):
        self.capability = capability

    def transcribe(self, audio: bytes, *, content_type: str) -> str:
        raise RuntimeError(f"No live {self.capability} provider is configured")

    def synthesize(self, text: str) -> tuple[bytes, str]:
        raise RuntimeError(f"No live {self.capability} provider is configured")
