"""Explicit transcript-bound confirmation policy for Phase 18."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from .models import VoiceActionClass, VoiceConfirmationEvent, VoiceTranscriptPacket


@dataclass(slots=True)
class _PendingConfirmation:
    packet: VoiceTranscriptPacket
    required: int
    event_ids: set[UUID] = field(default_factory=set)
    confirmed_count: int = 0


class VoiceConfirmationGate:
    """Requires one confirm for read-only commands and two for high-impact requests."""

    def __init__(self) -> None:
        self._pending: dict[UUID, _PendingConfirmation] = {}

    @staticmethod
    def required_for(action_class: VoiceActionClass) -> int:
        if action_class is VoiceActionClass.CONVERSATION:
            return 0
        if action_class is VoiceActionClass.READ_ONLY_COMMAND:
            return 1
        return 2

    def register(self, packet: VoiceTranscriptPacket) -> int:
        required = self.required_for(packet.action_class)
        if required:
            self._pending[packet.utterance_id] = _PendingConfirmation(
                packet=packet,
                required=required,
            )
        return required

    def apply(self, event: VoiceConfirmationEvent) -> tuple[VoiceTranscriptPacket, int, int, bool]:
        pending = self._pending.get(event.utterance_id)
        if pending is None:
            raise ValueError("voice confirmation target is not pending")
        packet = pending.packet
        if not event.transport_verified or not event.confirmed:
            raise ValueError("voice confirmation must be explicit and transport-verified")
        if event.event_id in pending.event_ids:
            raise ValueError("duplicate voice confirmation event")
        if event.session_id != packet.session_id or event.speaker_id != packet.speaker_id:
            raise ValueError("voice confirmation identity mismatch")
        if event.transcript_sha256 != packet.text_sha256:
            raise ValueError("voice confirmation transcript digest mismatch")
        expected_index = pending.confirmed_count + 1
        if event.confirmation_index != expected_index:
            raise ValueError("voice confirmation index is out of order")
        pending.event_ids.add(event.event_id)
        pending.confirmed_count += 1
        ready = pending.confirmed_count == pending.required
        if ready:
            del self._pending[event.utterance_id]
        return packet, pending.confirmed_count, pending.required, ready

    def discard_session(self, session_id: UUID) -> None:
        stale = [
            utterance_id
            for utterance_id, pending in self._pending.items()
            if pending.packet.session_id == session_id
        ]
        for utterance_id in stale:
            del self._pending[utterance_id]
