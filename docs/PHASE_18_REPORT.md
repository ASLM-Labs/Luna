# Phase 18 Report — Voice Gateway

Status: IMPLEMENTED_UNVERIFIED

## Implemented

- Provider-neutral STT/TTS adapter protocols plus deterministic/unbound local adapters.
- Verified local owner session and configured speaker identity binding.
- Session-bound transcript view with capture mode, chat/command type, action class, confidence,
  and confirmation progress.
- One explicit transcript-bound confirmation for read-only voice commands.
- Two explicit transcript-bound confirmations for high-impact voice requests.
- High-impact requests queue only as read-only approval-review work after double confirmation.
- `RequestSource.VOICE` durable queue integration with Level 1 read-only authority.
- Model-unavailable chat queue behavior.
- Interrupt/cancel handling that discards pending confirmation and cancels safe pre-dispatch work.
- Append-only audit containing transcript digests rather than raw spoken text/audio.
- Phase 18 CLI smoke, deterministic verifier, regression tests, CI and Windows quality-gate wiring.

## Security boundary

Voice transcription is untrusted data. A transcript cannot establish owner identity, raise
AutonomyLevel, enable workspace writes, enable process/terminal execution, grant network
access, deploy, publish, send, delete, or perform any other external side effect.

A double-confirmed high-impact request is still only an approval-review request. Side effects
require a separate non-voice bounded approval path.

## Deferred deliberately

- real microphone capture;
- wake-word engine implementation;
- cloud/local production STT provider selection;
- production TTS provider selection;
- Luna's final female voice/persona voice profile, tone, pitch, accent, or style;
- speaker biometric enrollment;
- direct voice-controlled external actions.

## Verification

Run:

```bat
.venv\Scripts\python.exe scripts\verify_phase18.py
.venv\Scripts\python.exe -m pytest -q tests\test_phase18_voice_gateway.py
.venv\Scripts\python.exe -m luna phase18-smoke
scripts\check_hold.bat
```

Commit/push is allowed only after the complete local quality gate passes.
