"""Product Luna diagnostic scenarios."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from luna.autonomy import AutonomyPolicy
from luna.contracts.enums import (
    CompletionStatus,
    RiskLevel,
    TaskPhase,
)
from luna.contracts.state import TaskState
from luna.contracts.task import TaskContract, TaskScope
from luna.desktop import (
    THEME_TOKENS,
    DesktopAccessMode,
    DesktopComposerDraft,
    build_local_desktop_controller,
)
from luna.diagnostics.models import SmokeReport, legacy_contract_report
from luna.discord import (
    DiscordAuthorityConfig,
    DiscordChannelBinding,
    DiscordChannelPurpose,
    DiscordIngressDisposition,
    DiscordTransportEnvelope,
    build_local_discord_gateway,
)
from luna.operations import (
    DispatchResultStatus,
    DurableTaskQueue,
    NotificationKind,
    NotificationOutbox,
    OperationsCoordinator,
    QueueStatus,
    ResourceCapacity,
    ResourceManager,
    ScheduleKind,
    Scheduler,
    ScheduleSpec,
    SQLiteOperationsStore,
    WorkEnvelope,
)
from luna.runtime import (
    RequestSource,
    RuntimeActor,
    RuntimeBudget,
    RuntimeMode,
    RuntimeOutcome,
    RuntimeRequest,
    RuntimeStopReason,
    RuntimeUsage,
    build_task_fingerprint,
)
from luna.tools import (
    AutonomyLevel,
    ToolPolicy,
)
from luna.voice import (
    UnboundTextToSpeechAdapter,
    VoiceActionClass,
    VoiceAuthorityConfig,
    VoiceCaptureMode,
    VoiceConfirmationEvent,
    VoiceIngressDisposition,
    VoiceTranscriptPacket,
    VoiceUtteranceKind,
    build_local_voice_gateway,
)


class _Phase15SmokeRuntime:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, request: RuntimeRequest, tool_policy: ToolPolicy) -> RuntimeOutcome:
        del tool_policy
        self.calls += 1
        contract = TaskContract(
            task_id=request.task_id,
            objective="Complete the Phase 15 CLI smoke fixture.",
            required_conditions=("The queued runtime invocation is verified.",),
            evidence_required=("runtime outcome",),
            scope=request.scope,
            owner=request.actor.actor_id,
        )
        state = TaskState(
            task_id=request.task_id,
            contract=contract,
            phase=TaskPhase.CLOSED,
            completion_status=CompletionStatus.VERIFIED_COMPLETE,
        )
        now = datetime.now(UTC)
        return RuntimeOutcome(
            request_id=request.request_id,
            task_id=request.task_id,
            trace_id=request.trace_id,
            task_fingerprint=build_task_fingerprint(request).digest,
            state=state,
            stop_reason=RuntimeStopReason.COMPLETED,
            completion_status=CompletionStatus.VERIFIED_COMPLETE,
            verification_report_id=uuid4(),
            final_report_id=uuid4(),
            usage=RuntimeUsage(budget=request.runtime_budget),
            started_at=now,
            finished_at=now,
        )

    def resume(self, *, request: RuntimeRequest, tool_policy: ToolPolicy) -> RuntimeOutcome:
        return self.run(request=request, tool_policy=tool_policy)


def run_phase15() -> SmokeReport:
    with TemporaryDirectory(prefix="luna-phase15-smoke-") as temp:
        root = Path(temp)
        now = datetime.now(UTC)
        task_id = uuid4()
        request = RuntimeRequest(
            task_id=task_id,
            raw_request="Run the Phase 15 operations CLI smoke fixture.",
            source=RequestSource.SCHEDULER,
            actor=RuntimeActor.verified_owner("phase15-smoke"),
            scope=TaskScope(workspace_root=str(root)),
            autonomy=AutonomyPolicy(
                task_id=task_id, level=AutonomyLevel.LEVEL_1_READ_ONLY, max_risk=RiskLevel.LOW
            ),
            runtime_budget=RuntimeBudget(),
            required_conditions=("The queued runtime invocation is verified.",),
            evidence_required=("runtime outcome",),
            risk_level=RiskLevel.LOW,
            mode=RuntimeMode.EXECUTE,
            requested_at=now,
        )
        envelope = WorkEnvelope(
            request=request,
            tool_policy=ToolPolicy(
                autonomy_level=AutonomyLevel.LEVEL_1_READ_ONLY, max_risk=RiskLevel.LOW
            ),
        )
        store = SQLiteOperationsStore(root / "operations.sqlite3")
        queue = DurableTaskQueue(store)
        scheduler = Scheduler(store)
        resources = ResourceManager(store, ResourceCapacity(worker_slots=1, model_slots=1))
        notifications = NotificationOutbox(store)
        runtime = _Phase15SmokeRuntime()
        coordinator = OperationsCoordinator(
            queue=queue,
            scheduler=scheduler,
            resources=resources,
            notifications=notifications,
            runtime=runtime,
        )
        scheduler.create(
            envelope=envelope,
            spec=ScheduleSpec(kind=ScheduleKind.ONE_SHOT, first_run_at=now),
            now=now,
        )
        materialized = coordinator.materialize_due(now=now)
        result = coordinator.dispatch_one(worker_id="phase15-smoke-worker", now=now)
        queued = store.list_queue_items()
        pending = notifications.pending()
        payload = {
            "schema_version": store.schema_version(),
            "journal_mode": store.journal_mode(),
            "materialized": materialized,
            "runtime_calls": runtime.calls,
            "dispatch_status": result.status.value,
            "queue_status": queued[0].status.value if queued else None,
            "notification_kind": pending[0].kind.value if pending else None,
            "external_delivery_allowed": pending[0].external_delivery_allowed if pending else None,
            "held_worker_slots": resources.held_usage().worker_slots,
        }
        return legacy_contract_report(
            "phase15",
            payload,
            all(
                (
                    payload["schema_version"] == 1,
                    payload["journal_mode"] == "wal",
                    payload["materialized"] == 1,
                    payload["runtime_calls"] == 1,
                    payload["dispatch_status"] == DispatchResultStatus.OUTCOME_RECORDED.value,
                    payload["queue_status"] == QueueStatus.COMPLETED.value,
                    payload["notification_kind"] == NotificationKind.TASK_VERIFIED_COMPLETE.value,
                    payload["external_delivery_allowed"] is False,
                    payload["held_worker_slots"] == 0,
                )
            ),
        )


def run_phase16() -> SmokeReport:
    with TemporaryDirectory(prefix="luna-phase16-smoke-") as temp:
        root = Path(temp)
        database = root / "operations.sqlite3"
        controller = build_local_desktop_controller(
            workspace_root=root, database_path=database, actor_id="phase16-smoke"
        )
        item_id = controller.submit(
            DesktopComposerDraft(
                text="Inspect the Phase 16 desktop smoke workspace.",
                workspace_root=str(root),
                access_mode=DesktopAccessMode.READ_ONLY,
            )
        )
        snapshot = controller.snapshot()
        item = SQLiteOperationsStore(database).load_queue_item(UUID(item_id))
        request = item.payload.envelope.request
        payload = {
            "task_count": len(snapshot.tasks),
            "task_state": snapshot.tasks[0].state.value if snapshot.tasks else None,
            "request_source": request.source.value,
            "write_allowed": request.scope.write_allowed,
            "network_allowed": request.scope.network_allowed,
            "autonomy_level": request.autonomy.level.value,
            "queue_status": item.status.value,
            "theme_canvas": THEME_TOKENS["canvas"],
            "theme_sidebar": THEME_TOKENS["sidebar"],
            "shell_message": snapshot.shell_message,
        }
        return legacy_contract_report(
            "phase16",
            payload,
            all(
                (
                    payload["task_count"] == 1,
                    payload["task_state"] == "QUEUED",
                    payload["request_source"] == "DESKTOP",
                    payload["write_allowed"] is False,
                    payload["network_allowed"] is False,
                    payload["autonomy_level"] == "LEVEL_1_READ_ONLY",
                    payload["queue_status"] == "QUEUED",
                    payload["theme_canvas"] == "#FFFFFF",
                    payload["theme_sidebar"] == "#F1F5F9",
                    payload["shell_message"] == "Luna ile ne geliştirelim?",
                )
            ),
        )


def run_phase17() -> SmokeReport:
    with TemporaryDirectory(prefix="luna-phase17-smoke-") as temp:
        root = Path(temp)
        database = root / "operations.sqlite3"
        config = DiscordAuthorityConfig(
            guild_id="100",
            workspace_root=str(root),
            channels=(DiscordChannelBinding(channel_id="200", purpose=DiscordChannelPurpose.CHAT),),
            community_role_ids=("500",),
        )
        gateway = build_local_discord_gateway(
            config=config, database_path=database, audit_root=root / "audit"
        )
        result = gateway.ingest(
            DiscordTransportEnvelope(
                guild_id="100",
                channel_id="200",
                message_id="600",
                author_id="700",
                author_role_ids=("500",),
                content="Phase 17 Discord smoke mesajini kuyruga al.",
                transport_verified=True,
                verified_at=datetime(2026, 8, 8, 3, 30, tzinfo=UTC),
                received_at=datetime(2026, 8, 8, 3, 30, tzinfo=UTC),
            ),
            main_model_available=False,
        )
        if result.queue_item_id is None:
            return legacy_contract_report("phase17", result.model_dump(mode="json"), False)
        item = SQLiteOperationsStore(database).load_queue_item(result.queue_item_id)
        request = item.payload.envelope.request
        payload = {
            "disposition": result.disposition.value,
            "actor_role": result.actor_role.value if result.actor_role else None,
            "channel_purpose": result.channel_purpose.value if result.channel_purpose else None,
            "request_source": request.source.value,
            "queue_status": item.status.value,
            "write_allowed": request.scope.write_allowed,
            "process_allowed": request.scope.process_allowed,
            "network_allowed": request.scope.network_allowed,
            "autonomy_level": request.autonomy.level.value,
            "model_slots": item.payload.resources.model_slots,
            "network_slots": item.payload.resources.network_slots,
            "reply_channel": result.reply_route.channel_id,
        }
        return legacy_contract_report(
            "phase17",
            payload,
            all(
                (
                    payload["disposition"] == DiscordIngressDisposition.QUEUED_FOR_MODEL.value,
                    payload["actor_role"] == "COMMUNITY",
                    payload["channel_purpose"] == "CHAT",
                    payload["request_source"] == "DISCORD",
                    payload["queue_status"] == "QUEUED",
                    payload["write_allowed"] is False,
                    payload["process_allowed"] is False,
                    payload["network_allowed"] is False,
                    payload["autonomy_level"] == "LEVEL_1_READ_ONLY",
                    payload["model_slots"] == 1,
                    payload["network_slots"] == 0,
                    payload["reply_channel"] == "200",
                )
            ),
        )


def run_phase18() -> SmokeReport:
    with TemporaryDirectory(prefix="luna-phase18-smoke-") as temp:
        root = Path(temp)
        database = root / "operations.sqlite3"
        gateway = build_local_voice_gateway(
            config=VoiceAuthorityConfig(
                workspace_root=str(root),
                owner_actor_id="phase18-owner",
                allowed_speaker_ids=("phase18-speaker",),
            ),
            database_path=database,
            audit_root=root / "audit",
        )
        now = datetime(2026, 8, 8, 6, 30, tzinfo=UTC)
        session = gateway.open_owner_session(
            speaker_id="phase18-speaker",
            local_session_verified=True,
            speaker_verified=True,
            now=now,
        )
        packet = VoiceTranscriptPacket(
            session_id=session.session_id,
            speaker_id=session.speaker_id,
            text="Projeyi değiştir ve deploy et.",
            confidence=0.99,
            capture_mode=VoiceCaptureMode.PUSH_TO_TALK,
            utterance_kind=VoiceUtteranceKind.COMMAND,
            action_class=VoiceActionClass.HIGH_IMPACT,
            transport_verified=True,
            received_at=now,
        )
        pending = gateway.ingest(packet, main_model_available=True)
        first = gateway.confirm(
            VoiceConfirmationEvent(
                session_id=session.session_id,
                utterance_id=packet.utterance_id,
                speaker_id=session.speaker_id,
                transcript_sha256=packet.text_sha256,
                confirmation_index=1,
                confirmed=True,
                transport_verified=True,
                occurred_at=now,
            ),
            main_model_available=True,
        )
        final = gateway.confirm(
            VoiceConfirmationEvent(
                session_id=session.session_id,
                utterance_id=packet.utterance_id,
                speaker_id=session.speaker_id,
                transcript_sha256=packet.text_sha256,
                confirmation_index=2,
                confirmed=True,
                transport_verified=True,
                occurred_at=now,
            ),
            main_model_available=True,
        )
        if final.queue_item_id is None:
            return legacy_contract_report("phase18", final.model_dump(mode="json"), False)
        item = SQLiteOperationsStore(database).load_queue_item(final.queue_item_id)
        request = item.payload.envelope.request
        transcript = gateway.sessions.transcript_view(session.session_id)
        tts_plan = UnboundTextToSpeechAdapter().plan("Phase 18 voice response")
        payload = {
            "pending": pending.disposition.value,
            "first_confirmation": first.disposition.value,
            "final": final.disposition.value,
            "request_source": request.source.value,
            "queue_status": item.status.value,
            "write_allowed": request.scope.write_allowed,
            "process_allowed": request.scope.process_allowed,
            "network_allowed": request.scope.network_allowed,
            "autonomy_level": request.autonomy.level.value,
            "required_confirmations": final.required_confirmations,
            "confirmation_count": transcript[0].confirmation_count,
            "tts_provider_bound": tts_plan.provider_bound,
            "tts_voice_profile": tts_plan.voice_profile_id,
        }
        return legacy_contract_report(
            "phase18",
            payload,
            all(
                (
                    payload["pending"]
                    == VoiceIngressDisposition.DOUBLE_CONFIRMATION_REQUIRED.value,
                    payload["first_confirmation"]
                    == VoiceIngressDisposition.CONFIRMATION_PROGRESS.value,
                    payload["final"] == VoiceIngressDisposition.QUEUED_FOR_APPROVAL_REVIEW.value,
                    payload["request_source"] == "VOICE",
                    payload["queue_status"] == "QUEUED",
                    payload["write_allowed"] is False,
                    payload["process_allowed"] is False,
                    payload["network_allowed"] is False,
                    payload["autonomy_level"] == "LEVEL_1_READ_ONLY",
                    payload["required_confirmations"] == 2,
                    payload["confirmation_count"] == 2,
                    payload["tts_provider_bound"] is False,
                    payload["tts_voice_profile"] is None,
                )
            ),
        )
