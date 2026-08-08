"""Verified local voice session and transcript-view state."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from luna.contracts.base import require_utc

from .models import (
    VoiceAuthorityConfig,
    VoiceSessionIdentity,
    VoiceSessionStatus,
    VoiceTranscriptEntry,
    VoiceTranscriptPacket,
)


class VoiceSessionRegistry:
    """In-process presentation/session state; it never grants tool or runtime authority."""

    def __init__(self, config: VoiceAuthorityConfig) -> None:
        self._config = config
        self._sessions: dict[UUID, VoiceSessionIdentity] = {}
        self._transcripts: dict[UUID, list[VoiceTranscriptEntry]] = {}

    def open_owner_session(
        self,
        *,
        speaker_id: str,
        local_session_verified: bool,
        speaker_verified: bool,
        now: datetime,
        session_id: UUID | None = None,
    ) -> VoiceSessionIdentity:
        current = require_utc(now)
        allowed = speaker_id in self._config.allowed_speaker_ids
        verified = local_session_verified and speaker_verified and allowed
        identity = VoiceSessionIdentity(
            session_id=session_id or uuid4(),
            actor_id=self._config.owner_actor_id,
            speaker_id=speaker_id,
            session_verified=verified,
            speaker_verified=verified,
            verified_at=current if verified else None,
            opened_at=current,
        )
        self._sessions[identity.session_id] = identity
        self._transcripts[identity.session_id] = []
        return identity

    def get(self, session_id: UUID) -> VoiceSessionIdentity | None:
        return self._sessions.get(session_id)

    def append_transcript(
        self,
        packet: VoiceTranscriptPacket,
        *,
        required_confirmations: int,
    ) -> VoiceTranscriptEntry:
        session = self._sessions.get(packet.session_id)
        if session is None or session.status is not VoiceSessionStatus.OPEN:
            raise ValueError("voice session is not open")
        entry = VoiceTranscriptEntry(
            utterance_id=packet.utterance_id,
            session_id=packet.session_id,
            speaker_id=packet.speaker_id,
            text=packet.text,
            confidence=packet.confidence,
            capture_mode=packet.capture_mode,
            utterance_kind=packet.utterance_kind,
            action_class=packet.action_class,
            required_confirmations=required_confirmations,
            confirmation_count=0,
            created_at=packet.received_at,
        )
        self._transcripts[packet.session_id].append(entry)
        return entry

    def mark_confirmed(self, *, session_id: UUID, utterance_id: UUID, count: int) -> None:
        entries = self._transcripts.get(session_id)
        if entries is None:
            raise ValueError("voice session transcript view not found")
        for index, entry in enumerate(entries):
            if entry.utterance_id == utterance_id:
                entries[index] = entry.model_copy(update={"confirmation_count": count})
                return
        raise ValueError("voice transcript entry not found")

    def transcript_view(self, session_id: UUID) -> tuple[VoiceTranscriptEntry, ...]:
        entries = self._transcripts.get(session_id)
        return tuple(entries) if entries is not None else ()

    def interrupt(self, session_id: UUID) -> VoiceSessionIdentity:
        return self._transition(session_id, VoiceSessionStatus.INTERRUPTED)

    def cancel(self, session_id: UUID) -> VoiceSessionIdentity:
        return self._transition(session_id, VoiceSessionStatus.CANCELLED)

    def close(self, session_id: UUID) -> VoiceSessionIdentity:
        return self._transition(session_id, VoiceSessionStatus.CLOSED)

    def _transition(self, session_id: UUID, status: VoiceSessionStatus) -> VoiceSessionIdentity:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("voice session not found")
        updated = session.model_copy(update={"status": status})
        self._sessions[session_id] = updated
        return updated
