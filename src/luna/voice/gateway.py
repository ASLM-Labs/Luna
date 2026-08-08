"""Runtime-bound local Voice Gateway for Phase 18."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

from luna.audit import AppendOnlyAuditLedger, AuditEventKind
from luna.autonomy import AutonomyGrantSource, AutonomyLevel, AutonomyPolicy
from luna.contracts import RiskLevel, TaskScope
from luna.operations import DurableTaskQueue, ResourceRequirement, WorkEnvelope
from luna.operations.store import OperationsConflictError
from luna.runtime import (
    ActorRole,
    ActorVerificationSource,
    RequestSource,
    RuntimeActor,
    RuntimeBudget,
    RuntimeMode,
    RuntimePriority,
    RuntimeRequest,
)
from luna.tools import ToolPolicy

from .confirmation import VoiceConfirmationGate
from .models import (
    VoiceActionClass,
    VoiceAuthorityConfig,
    VoiceConfirmationEvent,
    VoiceIngressDisposition,
    VoiceIngressResult,
    VoiceSessionIdentity,
    VoiceSessionStatus,
    VoiceTranscriptPacket,
)
from .session import VoiceSessionRegistry

_VOICE_READ_ONLY_TOOLS = ("core.echo", "filesystem.read_text")


class VoiceGateway:
    """Translate verified local voice transcripts into bounded durable runtime work.

    Phase 18 never executes STT/TTS network calls, never selects Luna's final voice, and never
    grants write/process/network authority from spoken text. High-impact requests require two
    transcript-bound confirmations and are then queued only as read-only approval-review work.
    """

    def __init__(
        self,
        *,
        config: VoiceAuthorityConfig,
        queue: DurableTaskQueue,
        audit: AppendOnlyAuditLedger,
        sessions: VoiceSessionRegistry | None = None,
        confirmations: VoiceConfirmationGate | None = None,
    ) -> None:
        self.config = config
        self._queue = queue
        self._audit = audit
        self.sessions = sessions or VoiceSessionRegistry(config)
        self._confirmations = confirmations or VoiceConfirmationGate()
        self._queued_by_session: dict[UUID, list[UUID]] = {}

    def open_owner_session(
        self,
        *,
        speaker_id: str,
        local_session_verified: bool,
        speaker_verified: bool,
        now: datetime,
        session_id: UUID | None = None,
    ) -> VoiceSessionIdentity:
        return self.sessions.open_owner_session(
            speaker_id=speaker_id,
            local_session_verified=local_session_verified,
            speaker_verified=speaker_verified,
            now=now,
            session_id=session_id,
        )

    def _validate_packet(self, packet: VoiceTranscriptPacket) -> VoiceIngressResult | None:
        session = self.sessions.get(packet.session_id)
        if session is None or session.status is not VoiceSessionStatus.OPEN:
            return self._simple_result(
                packet=packet,
                disposition=VoiceIngressDisposition.DENIED_SESSION,
                acknowledgment="Voice session is not open or verified.",
                reason="voice session is unavailable",
            )
        if not session.session_verified or not session.speaker_verified:
            return self._simple_result(
                packet=packet,
                disposition=VoiceIngressDisposition.DENIED_SESSION,
                acknowledgment="Voice session identity is not verified.",
                reason="voice local session identity is not verified",
            )
        if packet.speaker_id != session.speaker_id:
            return self._simple_result(
                packet=packet,
                disposition=VoiceIngressDisposition.DENIED_SPEAKER,
                acknowledgment="Voice speaker does not match the verified local session.",
                reason="voice speaker/session identity mismatch",
            )
        if not packet.transport_verified:
            return self._simple_result(
                packet=packet,
                disposition=VoiceIngressDisposition.DENIED_TRANSPORT,
                acknowledgment="Voice transcript transport is not verified.",
                reason="voice transcript transport is not verified",
            )
        return None

    def ingest(
        self,
        packet: VoiceTranscriptPacket,
        *,
        main_model_available: bool,
    ) -> VoiceIngressResult:
        denied = self._validate_packet(packet)
        if denied is not None:
            self._audit_decision(packet=packet, result=denied)
            return denied

        required = self._confirmations.register(packet)
        self.sessions.append_transcript(packet, required_confirmations=required)
        if required == 1:
            result = self._simple_result(
                packet=packet,
                disposition=VoiceIngressDisposition.DIRECT_CONFIRMATION_REQUIRED,
                acknowledgment="Read-only voice command requires one explicit confirmation.",
                reason="direct transcript confirmation required before queueing command",
                required=1,
            )
        elif required == 2:
            result = self._simple_result(
                packet=packet,
                disposition=VoiceIngressDisposition.DOUBLE_CONFIRMATION_REQUIRED,
                acknowledgment="High-impact voice request requires two explicit confirmations.",
                reason="high-impact voice request cannot proceed from one transcript",
                required=2,
            )
        else:
            result = self._queue_packet(packet, main_model_available=main_model_available)
        self._audit_decision(packet=packet, result=result)
        return result

    def confirm(
        self,
        event: VoiceConfirmationEvent,
        *,
        main_model_available: bool,
    ) -> VoiceIngressResult:
        try:
            packet, count, required, ready = self._confirmations.apply(event)
        except ValueError as exc:
            result = VoiceIngressResult(
                disposition=VoiceIngressDisposition.DENIED_CONFIRMATION,
                session_id=event.session_id,
                utterance_id=event.utterance_id,
                transcript_sha256=event.transcript_sha256,
                acknowledgment="Voice confirmation was rejected.",
                reason=str(exc),
            )
            self._audit_confirmation(event=event, result=result)
            return result
        self.sessions.mark_confirmed(
            session_id=packet.session_id,
            utterance_id=packet.utterance_id,
            count=count,
        )
        if not ready:
            result = self._simple_result(
                packet=packet,
                disposition=VoiceIngressDisposition.CONFIRMATION_PROGRESS,
                acknowledgment="First high-impact confirmation recorded; one more is required.",
                reason="high-impact voice confirmation is incomplete",
                required=required,
                count=count,
            )
            self._audit_confirmation(event=event, result=result)
            return result
        result = self._queue_packet(packet, main_model_available=main_model_available)
        self._audit_confirmation(event=event, result=result)
        return result

    def interrupt(self, session_id: UUID, *, now: datetime) -> VoiceIngressResult:
        self.sessions.interrupt(session_id)
        self._confirmations.discard_session(session_id)
        self._cancel_queued(session_id, now=now)
        result = VoiceIngressResult(
            disposition=VoiceIngressDisposition.INTERRUPTED,
            session_id=session_id,
            acknowledgment=(
                "Voice output/session interrupted; queued pre-dispatch work was cancelled."
            ),
            reason="local user interruption wins before dispatch",
        )
        self._audit_session(result)
        return result

    def cancel(self, session_id: UUID, *, now: datetime) -> VoiceIngressResult:
        self.sessions.cancel(session_id)
        self._confirmations.discard_session(session_id)
        self._cancel_queued(session_id, now=now)
        result = VoiceIngressResult(
            disposition=VoiceIngressDisposition.CANCELLED,
            session_id=session_id,
            acknowledgment="Voice session cancelled.",
            reason="local user cancelled the voice session",
        )
        self._audit_session(result)
        return result

    def _cancel_queued(self, session_id: UUID, *, now: datetime) -> None:
        for item_id in self._queued_by_session.get(session_id, []):
            try:
                self._queue.cancel_queued(item_id=item_id, now=now)
            except OperationsConflictError:
                continue

    def _queue_packet(
        self,
        packet: VoiceTranscriptPacket,
        *,
        main_model_available: bool,
    ) -> VoiceIngressResult:
        work = self._read_only_envelope(packet)
        queue_item = self._queue.enqueue(
            envelope=work,
            resources=ResourceRequirement(worker_slots=1, model_slots=1, network_slots=0),
            priority=RuntimePriority.NORMAL,
            idempotency_key=self._idempotency_key(packet),
            now=packet.received_at,
        )
        self._queued_by_session.setdefault(packet.session_id, []).append(queue_item.item_id)
        if packet.action_class is VoiceActionClass.HIGH_IMPACT:
            disposition = VoiceIngressDisposition.QUEUED_FOR_APPROVAL_REVIEW
            reason = (
                "double-confirmed high-impact voice request queued only for read-only approval "
                "review; side effects remain unauthorized"
            )
        else:
            disposition = (
                VoiceIngressDisposition.QUEUED
                if main_model_available
                else VoiceIngressDisposition.QUEUED_FOR_MODEL
            )
            reason = "verified voice transcript persisted as bounded read-only runtime work"
        return VoiceIngressResult(
            disposition=disposition,
            session_id=packet.session_id,
            utterance_id=packet.utterance_id,
            queue_item_id=queue_item.item_id,
            request_id=queue_item.payload.envelope.request.request_id,
            task_id=queue_item.payload.envelope.request.task_id,
            trace_id=queue_item.payload.envelope.request.trace_id,
            transcript_sha256=packet.text_sha256,
            required_confirmations=VoiceConfirmationGate.required_for(packet.action_class),
            confirmation_count=VoiceConfirmationGate.required_for(packet.action_class),
            acknowledgment=(
                "High-impact request recorded for explicit non-voice approval review."
                if packet.action_class is VoiceActionClass.HIGH_IMPACT
                else "Voice request queued for Luna."
            ),
            reason=reason,
        )

    def _read_only_envelope(self, packet: VoiceTranscriptPacket) -> WorkEnvelope:
        session = self.sessions.get(packet.session_id)
        if session is None or not session.session_verified or not session.speaker_verified:
            raise ValueError("verified voice session required to create runtime work")
        identity = f"voice-v1|{packet.session_id}|{packet.utterance_id}"
        task_id = uuid5(NAMESPACE_URL, f"{identity}|task")
        request_id = uuid5(NAMESPACE_URL, f"{identity}|request")
        trace_id = uuid5(NAMESPACE_URL, f"{identity}|trace")
        actor = RuntimeActor(
            actor_id=session.actor_id,
            role=ActorRole.OWNER,
            verified=True,
            verification_source=ActorVerificationSource.LOCAL_SESSION,
            verified_at=session.verified_at,
        )
        scope = TaskScope(
            workspace_root=self.config.workspace_root,
            write_allowed=False,
            network_allowed=False,
            process_allowed=False,
        )
        autonomy = AutonomyPolicy(
            task_id=task_id,
            level=AutonomyLevel.LEVEL_1_READ_ONLY,
            grant_source=AutonomyGrantSource.RUNTIME_POLICY,
            allowed_tools=_VOICE_READ_ONLY_TOOLS,
            max_risk=RiskLevel.LOW,
        )
        high_impact = packet.action_class is VoiceActionClass.HIGH_IMPACT
        request = RuntimeRequest(
            request_id=request_id,
            task_id=task_id,
            trace_id=trace_id,
            raw_request=packet.text,
            source=RequestSource.VOICE,
            actor=actor,
            scope=scope,
            autonomy=autonomy,
            runtime_budget=RuntimeBudget(),
            required_conditions=(
                "Voice transcript must remain visible and attributable to its verified session.",
                (
                    "High-impact voice request requires a separate non-voice bounded approval "
                    "before any side effect."
                    if high_impact
                    else "Voice-originated runtime work remains read-only."
                ),
            ),
            forbidden_outcomes=(
                "Spoken text must not grant workspace write authority.",
                "Spoken text must not grant process, terminal, deploy, or network authority.",
                "One transcript must never trigger a high-impact external action.",
            ),
            evidence_required=("runtime observations",),
            risk_level=RiskLevel.LOW,
            mode=RuntimeMode.EXECUTE,
            requested_at=packet.received_at,
        )
        return WorkEnvelope(
            request=request,
            tool_policy=ToolPolicy(
                allowed_tools=_VOICE_READ_ONLY_TOOLS,
                autonomy_level=AutonomyLevel.LEVEL_1_READ_ONLY,
                autonomy_grant_source=AutonomyGrantSource.RUNTIME_POLICY,
                max_risk=RiskLevel.LOW,
            ),
        )

    @staticmethod
    def _idempotency_key(packet: VoiceTranscriptPacket) -> str:
        material = f"voice-v1|{packet.session_id}|{packet.utterance_id}|{packet.text_sha256}"
        return sha256(material.encode("ascii")).hexdigest()

    def _simple_result(
        self,
        *,
        packet: VoiceTranscriptPacket,
        disposition: VoiceIngressDisposition,
        acknowledgment: str,
        reason: str,
        required: int = 0,
        count: int = 0,
    ) -> VoiceIngressResult:
        return VoiceIngressResult(
            disposition=disposition,
            session_id=packet.session_id,
            utterance_id=packet.utterance_id,
            transcript_sha256=packet.text_sha256,
            required_confirmations=required,
            confirmation_count=count,
            acknowledgment=acknowledgment,
            reason=reason,
        )

    def _audit_decision(self, *, packet: VoiceTranscriptPacket, result: VoiceIngressResult) -> None:
        task_id = result.task_id or uuid5(NAMESPACE_URL, f"voice-audit-task|{packet.utterance_id}")
        trace_id = result.trace_id or uuid5(
            NAMESPACE_URL, f"voice-audit-trace|{packet.utterance_id}"
        )
        self._audit.append(
            kind=AuditEventKind.OBSERVATION,
            task_id=task_id,
            trace_id=trace_id,
            subject_id=f"voice:{packet.utterance_id}",
            payload={
                "gateway": "voice",
                "session_id": str(packet.session_id),
                "utterance_id": str(packet.utterance_id),
                "speaker_id": packet.speaker_id,
                "transcript_sha256": packet.text_sha256,
                "transcript_chars": len(packet.text),
                "capture_mode": packet.capture_mode.value,
                "utterance_kind": packet.utterance_kind.value,
                "action_class": packet.action_class.value,
                "disposition": result.disposition.value,
                "required_confirmations": result.required_confirmations,
                "confirmation_count": result.confirmation_count,
                "queue_item_id": str(result.queue_item_id) if result.queue_item_id else None,
                "reason": result.reason,
            },
        )

    def _audit_confirmation(
        self,
        *,
        event: VoiceConfirmationEvent,
        result: VoiceIngressResult,
    ) -> None:
        task_id = result.task_id or uuid5(NAMESPACE_URL, f"voice-confirm-task|{event.utterance_id}")
        trace_id = result.trace_id or uuid5(
            NAMESPACE_URL, f"voice-confirm-trace|{event.utterance_id}"
        )
        self._audit.append(
            kind=AuditEventKind.OBSERVATION,
            task_id=task_id,
            trace_id=trace_id,
            subject_id=f"voice-confirm:{event.event_id}",
            payload={
                "gateway": "voice",
                "session_id": str(event.session_id),
                "utterance_id": str(event.utterance_id),
                "speaker_id": event.speaker_id,
                "transcript_sha256": event.transcript_sha256,
                "confirmation_index": event.confirmation_index,
                "transport_verified": event.transport_verified,
                "disposition": result.disposition.value,
                "queue_item_id": str(result.queue_item_id) if result.queue_item_id else None,
                "reason": result.reason,
            },
        )

    def _audit_session(self, result: VoiceIngressResult) -> None:
        self._audit.append(
            kind=AuditEventKind.OBSERVATION,
            task_id=uuid5(NAMESPACE_URL, f"voice-session-task|{result.session_id}"),
            trace_id=uuid5(NAMESPACE_URL, f"voice-session-trace|{result.session_id}"),
            subject_id=f"voice-session:{result.session_id}",
            payload={
                "gateway": "voice",
                "session_id": str(result.session_id),
                "disposition": result.disposition.value,
                "reason": result.reason,
            },
        )
