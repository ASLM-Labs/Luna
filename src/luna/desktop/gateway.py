"""Runtime-bound command gateway for the Phase 16 desktop shell."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from luna.autonomy import AutonomyGrantSource, AutonomyLevel, AutonomyPolicy
from luna.contracts import RiskLevel, TaskScope
from luna.operations import (
    DurableTaskQueue,
    NotificationOutbox,
    QueueItem,
    ResourceRequirement,
    WorkEnvelope,
)
from luna.runtime import RequestSource, RuntimeActor, RuntimeBudget, RuntimeMode, RuntimeRequest
from luna.tools import ToolPolicy

from .models import DesktopAccessMode, DesktopComposerDraft

_READ_ONLY_TOOLS = ("core.echo", "filesystem.read_text")
_CONTROLLED_WRITE_TOOLS = (
    "core.echo",
    "filesystem.read_text",
    "filesystem.write_text",
)


class DesktopCommandGateway:
    """Translate explicit UI intent into bounded RuntimeRequest + queue state.

    The gateway never calls a tool or model directly. It only builds a runtime-owned
    request envelope and hands it to the durable queue.
    """

    def __init__(
        self,
        *,
        queue: DurableTaskQueue,
        notifications: NotificationOutbox,
        actor: RuntimeActor,
    ) -> None:
        if not actor.verified:
            raise ValueError("desktop command gateway requires a verified local actor")
        self._queue = queue
        self._notifications = notifications
        self._actor = actor

    @property
    def actor(self) -> RuntimeActor:
        return self._actor

    def _read_only_envelope(self, draft: DesktopComposerDraft) -> WorkEnvelope:
        task_id = uuid4()
        scope = TaskScope(workspace_root=draft.workspace_root)
        autonomy = AutonomyPolicy(
            task_id=task_id,
            level=AutonomyLevel.LEVEL_1_READ_ONLY,
            grant_source=AutonomyGrantSource.RUNTIME_POLICY,
            allowed_tools=_READ_ONLY_TOOLS,
            max_risk=RiskLevel.LOW,
        )
        request = RuntimeRequest(
            task_id=task_id,
            raw_request=draft.text,
            source=RequestSource.DESKTOP,
            actor=self._actor,
            scope=scope,
            autonomy=autonomy,
            runtime_budget=RuntimeBudget(),
            required_conditions=("The runtime must truthfully report the task outcome.",),
            evidence_required=("runtime observations",),
            risk_level=RiskLevel.LOW,
            mode=RuntimeMode.EXECUTE,
        )
        return WorkEnvelope(
            request=request,
            tool_policy=ToolPolicy(
                allowed_tools=_READ_ONLY_TOOLS,
                autonomy_level=AutonomyLevel.LEVEL_1_READ_ONLY,
                autonomy_grant_source=AutonomyGrantSource.RUNTIME_POLICY,
                max_risk=RiskLevel.LOW,
            ),
        )

    def _controlled_write_envelope(self, draft: DesktopComposerDraft) -> WorkEnvelope:
        approval = draft.approval
        if approval is None or not approval.approved:
            raise ValueError("controlled desktop write requires explicit approval")
        task_id = uuid4()
        scope = TaskScope(
            workspace_root=draft.workspace_root,
            allowed_paths=approval.allowed_paths,
            write_allowed=True,
        )
        autonomy = AutonomyPolicy(
            task_id=task_id,
            level=AutonomyLevel.LEVEL_2_CONTROLLED,
            grant_source=AutonomyGrantSource.USER,
            allowed_tools=_CONTROLLED_WRITE_TOOLS,
            max_risk=RiskLevel.MEDIUM,
        )
        request = RuntimeRequest(
            task_id=task_id,
            raw_request=draft.text,
            source=RequestSource.DESKTOP,
            actor=self._actor,
            scope=scope,
            autonomy=autonomy,
            runtime_budget=RuntimeBudget.controlled_write(
                max_changed_files=approval.max_changed_files,
                max_added_lines=approval.max_added_lines,
                max_deleted_lines=approval.max_deleted_lines,
            ),
            required_conditions=(
                "The runtime must truthfully report the task outcome.",
                "Any workspace change must stay inside the approved desktop scope.",
            ),
            forbidden_outcomes=("Unapproved workspace paths must not be modified.",),
            evidence_required=("runtime observations", "workspace diff or verifier evidence"),
            risk_level=RiskLevel.MEDIUM,
            mode=RuntimeMode.EXECUTE,
        )
        return WorkEnvelope(
            request=request,
            tool_policy=ToolPolicy(
                allowed_tools=_CONTROLLED_WRITE_TOOLS,
                autonomy_level=AutonomyLevel.LEVEL_2_CONTROLLED,
                autonomy_grant_source=AutonomyGrantSource.USER,
                max_risk=RiskLevel.MEDIUM,
            ),
        )

    def build_envelope(self, draft: DesktopComposerDraft) -> WorkEnvelope:
        """Create authority-bound work; raw UI fields never become authority by themselves."""
        if draft.access_mode is DesktopAccessMode.READ_ONLY:
            return self._read_only_envelope(draft)
        return self._controlled_write_envelope(draft)

    def submit(self, draft: DesktopComposerDraft) -> QueueItem:
        """Persist one desktop task; actual execution remains Phase 15/runtime-owned."""
        envelope = self.build_envelope(draft)
        resources = ResourceRequirement(
            worker_slots=1,
            model_slots=1,
            network_slots=0,
        )
        return self._queue.enqueue(
            envelope=envelope,
            resources=resources,
        )

    def cancel_queued(self, item_id: str) -> QueueItem:
        """Desktop may cancel only work that has not crossed a queue/runtime fence."""
        from uuid import UUID

        return self._queue.cancel_queued(item_id=UUID(item_id))

    def acknowledge_notification(self, notification_id: str) -> None:
        """Acknowledge one local-only notification."""
        from uuid import UUID

        self._notifications.acknowledge(UUID(notification_id))

    @staticmethod
    def default_workspace(value: str | Path) -> str:
        return str(Path(value).expanduser().resolve())
