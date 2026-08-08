"""Provider-neutral STT/TTS adapter boundaries for Phase 18."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from luna.contracts.base import require_utc

from .models import (
    VoiceActionClass,
    VoiceCaptureMode,
    VoiceSynthesisPlan,
    VoiceTranscriptPacket,
    VoiceUtteranceKind,
)


class SpeechToTextAdapter(Protocol):
    """STT provider contract. Implementations may not grant runtime authority."""

    def transcribe(
        self,
        audio: bytes,
        *,
        session_id: UUID,
        speaker_id: str,
        capture_mode: VoiceCaptureMode,
        utterance_kind: VoiceUtteranceKind,
        action_class: VoiceActionClass,
        now: datetime,
    ) -> VoiceTranscriptPacket: ...


class TextToSpeechAdapter(Protocol):
    """TTS provider contract. Phase 18 does not select Luna's final voice."""

    def plan(self, text: str) -> VoiceSynthesisPlan: ...


class ScriptedSpeechToTextAdapter:
    """Deterministic local test adapter; it performs no microphone or network I/O."""

    def __init__(self, *, text: str, confidence: float = 1.0) -> None:
        self._text = text
        self._confidence = confidence

    def transcribe(
        self,
        audio: bytes,
        *,
        session_id: UUID,
        speaker_id: str,
        capture_mode: VoiceCaptureMode,
        utterance_kind: VoiceUtteranceKind,
        action_class: VoiceActionClass,
        now: datetime,
    ) -> VoiceTranscriptPacket:
        if not audio:
            raise ValueError("scripted STT requires non-empty audio bytes")
        return VoiceTranscriptPacket(
            session_id=session_id,
            speaker_id=speaker_id,
            text=self._text,
            confidence=self._confidence,
            capture_mode=capture_mode,
            utterance_kind=utterance_kind,
            action_class=action_class,
            transport_verified=True,
            received_at=require_utc(now),
        )


class UnboundTextToSpeechAdapter:
    """Creates synthesis plans without selecting a provider, voice, or audio output."""

    def plan(self, text: str) -> VoiceSynthesisPlan:
        return VoiceSynthesisPlan(
            text=text,
            adapter_name="unbound-phase18",
            provider_bound=False,
            voice_profile_id=None,
        )
