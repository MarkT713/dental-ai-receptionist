# Voice and telephony boundary

The public project contains an executable receptionist conversation state machine and provider-neutral STT/TTS contracts. It does **not** claim to include production speech recognition, speech synthesis, a carrier number, or a full-duplex telephone bridge.

## What runs without accounts

```bash
python scripts/run_voice_simulation.py
```

This connects:

1. UTF-8 synthetic test bytes (`TextBytesSTT`),
2. the after-hours receptionist state machine,
3. UTF-8 response bytes (`TextBytesTTS`), and
4. an in-memory mock PMS recorder.

The simulation verifies that a routine conversation creates one staff-review card and zero appointments. The adapters reject audio MIME types so they cannot be mistaken for real speech engines.

## Provider-neutral interfaces

`voice_pipeline/adapters.py` defines:

- `SpeechToText.transcribe(audio, content_type)`;
- `TextToSpeech.synthesize(text)`;
- `ReceptionistSession.start/step`;
- `VoiceRuntime.greeting/process_turn`.

A live implementation should add provider adapters behind these interfaces while retaining deterministic safety checks and the staff-approval queue.

## Fail-closed behavior

- Live/EAGI/telephony CLI modes exit with an explicit unsupported message.
- The legacy direct-booking demonstration is disabled unless `ALLOW_UNSAFE_DIRECT_BOOKING_DEMO=true` is deliberately set.
- `ProviderNotConfigured` raises instead of silently returning plausible audio/transcripts.

## External inputs required for a live call

A real call cannot be implemented responsibly without product and infrastructure choices:

- telephony provider and a securely configured test number;
- public TLS webhook/media endpoint and allowed source verification;
- STT and TTS providers, voices, supported languages, and retention settings;
- barge-in, silence timeout, retry, transfer, and after-hours policy decisions;
- secure provider credentials supplied through a secret manager, never chat or Git;
- consent/recording notices and office-approved emergency wording.

Provider credentials and real call recordings must remain outside this public repository.
