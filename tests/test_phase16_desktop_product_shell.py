from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from luna.autonomy import AutonomyLevel
from luna.contracts import CompletionStatus, TaskPhase, TaskState
from luna.contracts.task import TaskContract
from luna.desktop import (
    THEME_TOKENS,
    DesktopAccessMode,
    DesktopApproval,
    DesktopComposerDraft,
    DesktopTaskState,
    build_local_desktop_controller,
    task_card,
)
from luna.operations import QueueStatus, SQLiteOperationsStore
from luna.runtime import RuntimeOutcome, RuntimeStopReason, RuntimeUsage, build_task_fingerprint

NOW = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)


def _controller(tmp_path: Path):
    database = tmp_path / "ops.sqlite3"
    controller = build_local_desktop_controller(
        workspace_root=tmp_path,
        database_path=database,
        actor_id="phase16-test",
    )
    return controller, database


def _completed_outcome(item) -> RuntimeOutcome:
    request = item.payload.envelope.request
    contract = TaskContract(
        task_id=request.task_id,
        objective="Complete the Phase 16 fixture.",
        required_conditions=("The runtime must truthfully report the task outcome.",),
        evidence_required=("runtime observations",),
        scope=request.scope,
        owner=request.actor.actor_id,
    )
    state = TaskState(
        task_id=request.task_id,
        contract=contract,
        phase=TaskPhase.CLOSED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
    )
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
        started_at=NOW,
        finished_at=NOW,
    )


def test_theme_is_light_first_and_matches_locked_palette() -> None:
    assert THEME_TOKENS["canvas"] == "#FFFFFF"
    assert THEME_TOKENS["text"] == "#171717"
    assert THEME_TOKENS["surface"] == "#F5F6F8"
    assert THEME_TOKENS["blue"] == "#2563EB"


def test_read_only_draft_rejects_write_approval(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="read-only"):
        DesktopComposerDraft(
            text="Inspect",
            workspace_root=str(tmp_path),
            approval=DesktopApproval(
                approved=True,
                workspace_root=str(tmp_path),
                allowed_paths=("README.md",),
                max_changed_files=1,
                max_added_lines=1,
            ),
        )


def test_controlled_write_requires_explicit_bounded_approval(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="explicit approval"):
        DesktopComposerDraft(
            text="Change README",
            workspace_root=str(tmp_path),
            access_mode=DesktopAccessMode.CONTROLLED_WRITE,
        )


def test_desktop_submit_defaults_to_read_only_runtime_authority(tmp_path: Path) -> None:
    controller, database = _controller(tmp_path)
    item_id = controller.submit(
        DesktopComposerDraft(text="Inspect README", workspace_root=str(tmp_path))
    )
    item = SQLiteOperationsStore(database).load_queue_item(UUID(item_id))
    request = item.payload.envelope.request

    assert request.source.value == "DESKTOP"
    assert request.scope.write_allowed is False
    assert request.scope.network_allowed is False
    assert request.autonomy.level is AutonomyLevel.LEVEL_1_READ_ONLY
    assert request.runtime_budget.max_changed_files == 0
    assert item.status is QueueStatus.QUEUED


def test_controlled_write_is_bounded_and_cannot_grant_network(tmp_path: Path) -> None:
    controller, database = _controller(tmp_path)
    item_id = controller.submit(
        DesktopComposerDraft(
            text="Update README",
            workspace_root=str(tmp_path),
            access_mode=DesktopAccessMode.CONTROLLED_WRITE,
            approval=DesktopApproval(
                approved=True,
                workspace_root=str(tmp_path),
                allowed_paths=("README.md",),
                max_changed_files=1,
                max_added_lines=20,
                max_deleted_lines=10,
            ),
        )
    )
    item = SQLiteOperationsStore(database).load_queue_item(UUID(item_id))
    request = item.payload.envelope.request

    assert request.scope.write_allowed is True
    assert request.scope.allowed_paths == ("README.md",)
    assert request.scope.network_allowed is False
    assert request.autonomy.level is AutonomyLevel.LEVEL_2_CONTROLLED
    assert request.runtime_budget.max_changed_files == 1
    assert request.runtime_budget.max_added_lines == 20
    assert request.runtime_budget.max_network_requests == 0


def test_snapshot_is_durable_state_not_model_prose(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)
    controller.submit(DesktopComposerDraft(text="Inspect project", workspace_root=str(tmp_path)))

    snapshot = controller.snapshot()

    assert len(snapshot.tasks) == 1
    assert snapshot.tasks[0].state is DesktopTaskState.QUEUED
    assert snapshot.tasks[0].completion_status is None
    assert snapshot.tasks[0].verification_report_id is None


def test_verified_complete_card_requires_runtime_verification_artifacts(tmp_path: Path) -> None:
    controller, database = _controller(tmp_path)
    item_id = controller.submit(
        DesktopComposerDraft(text="Inspect project", workspace_root=str(tmp_path))
    )
    item = SQLiteOperationsStore(database).load_queue_item(UUID(item_id))
    outcome = _completed_outcome(item)
    rendered = task_card(
        item.model_copy(
            update={
                "status": QueueStatus.COMPLETED,
                "outcome": outcome,
                "dispatch_id": uuid4(),
                "dispatch_started_at": NOW,
                "updated_at": NOW,
            }
        )
    )

    assert rendered.state is DesktopTaskState.VERIFIED_COMPLETE
    assert rendered.state_label == "Doğrulandı"
    assert rendered.verification_report_id == outcome.verification_report_id
    assert rendered.final_report_id == outcome.final_report_id


def test_noncomplete_runtime_outcome_never_renders_verified_complete(tmp_path: Path) -> None:
    controller, database = _controller(tmp_path)
    item_id = controller.submit(
        DesktopComposerDraft(text="Inspect project", workspace_root=str(tmp_path))
    )
    item = SQLiteOperationsStore(database).load_queue_item(UUID(item_id))
    request = item.payload.envelope.request
    contract = TaskContract(
        task_id=request.task_id,
        objective="Suspend fixture.",
        required_conditions=("The runtime must truthfully report the task outcome.",),
        evidence_required=("runtime observations",),
        scope=request.scope,
        owner=request.actor.actor_id,
    )
    state = TaskState(task_id=request.task_id, contract=contract)
    outcome = RuntimeOutcome(
        request_id=request.request_id,
        task_id=request.task_id,
        trace_id=request.trace_id,
        task_fingerprint=build_task_fingerprint(request).digest,
        state=state,
        stop_reason=RuntimeStopReason.SUSPENDED,
        usage=RuntimeUsage(budget=request.runtime_budget),
        started_at=NOW,
        finished_at=NOW,
    )
    rendered = task_card(
        item.model_copy(
            update={
                "status": QueueStatus.SUSPENDED,
                "outcome": outcome,
                "dispatch_id": uuid4(),
                "dispatch_started_at": NOW,
                "updated_at": NOW,
            }
        )
    )

    assert rendered.state is DesktopTaskState.SUSPENDED
    assert rendered.state is not DesktopTaskState.VERIFIED_COMPLETE


def test_desktop_cancel_only_operates_before_dispatch(tmp_path: Path) -> None:
    controller, database = _controller(tmp_path)
    item_id = controller.submit(
        DesktopComposerDraft(text="Inspect project", workspace_root=str(tmp_path))
    )
    controller.cancel_queued(item_id)

    item = SQLiteOperationsStore(database).load_queue_item(UUID(item_id))
    assert item.status is QueueStatus.CANCELLED


def test_store_exposes_read_only_schedule_listing(tmp_path: Path) -> None:
    controller, database = _controller(tmp_path)
    assert controller.snapshot().schedules == ()
    assert SQLiteOperationsStore(database).list_schedules() == ()


def test_snapshot_keeps_notifications_local_only(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)
    snapshot = controller.snapshot()
    assert all(not event.external_delivery_allowed for event in snapshot.notifications)


def test_shell_message_is_conversation_first(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)
    snapshot = controller.snapshot()
    assert snapshot.shell_message == "Luna ile ne geliştirelim?"
    assert snapshot.workspace_root == str(tmp_path.resolve())
