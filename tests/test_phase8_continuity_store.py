from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from luna.continuity import (
    ContinuityConflictError,
    ContinuityIntegrityError,
    ContinuityService,
    SQLiteContinuityStore,
)
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.contracts.enums import PlanStepStatus, TaskPhase
from luna.contracts.plan import PlanStep


def _contract(task_id: object) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Persist restart-safe state.",
        required_conditions=("Checkpoint can be loaded.",),
        evidence_required=("checkpoint hash evidence",),
        scope=TaskScope(workspace_root="C:/workspace"),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def _state(*, phase: TaskPhase = TaskPhase.PLANNED) -> TaskState:
    task_id = uuid4()
    contract = _contract(task_id)
    return TaskState(
        task_id=task_id,
        contract=contract,
        phase=phase,
        plan=(
            PlanStep(
                sequence=1,
                description="First step.",
                status=PlanStepStatus.COMPLETE,
            ),
            PlanStep(
                sequence=2,
                description="Second step.",
                status=PlanStepStatus.PENDING,
            ),
        ),
        revision=5,
    )


def test_store_uses_wal_and_schema_migration(tmp_path: Path) -> None:
    store = SQLiteContinuityStore(tmp_path / "runtime.sqlite3")

    assert store.journal_mode() == "wal"
    assert store.schema_version() == 4


def test_checkpoint_round_trip_survives_new_store_instance(
    tmp_path: Path,
) -> None:
    state = _state()
    first_store = SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    stored = ContinuityService(first_store).create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step="Run second step.",
    )

    restarted = SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    loaded = restarted.load_latest(state.task_id)

    assert loaded == stored
    assert restarted.verify_integrity().valid
    assert restarted.load_task_state(state.task_id).phase is TaskPhase.CHECKPOINTED


def test_checkpoint_payload_tampering_is_detected(tmp_path: Path) -> None:
    state = _state()
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteContinuityStore(database)
    stored = ContinuityService(store).create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step="Run second step.",
    )

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE checkpoints SET payload_json = ? WHERE checkpoint_id = ?",
            ("{}", str(stored.envelope.checkpoint.checkpoint_id)),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ContinuityIntegrityError):
        store.load_checkpoint(stored.envelope.checkpoint.checkpoint_id)
    assert not store.verify_integrity().valid


def test_stale_revision_cannot_write_new_checkpoint(tmp_path: Path) -> None:
    state = _state()
    service = ContinuityService(
        SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    )
    service.create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step="Run second step.",
    )

    with pytest.raises(ContinuityConflictError, match="revision"):
        service.create_checkpoint(
            state=state,
            workspace_fingerprint="workspace",
            environment_fingerprint="environment",
            runtime_revision="rev-8",
            next_step="Repeat stale state.",
        )


def test_terminal_checkpoint_is_immutable(tmp_path: Path) -> None:
    task_id = uuid4()
    contract = _contract(task_id)
    closed = TaskState(
        task_id=task_id,
        contract=contract,
        phase=TaskPhase.CLOSED,
        completion_status="VERIFIED_COMPLETE",
        revision=9,
    )
    service = ContinuityService(
        SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    )
    service.create_checkpoint(
        state=closed,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step=None,
    )

    with pytest.raises(ContinuityConflictError, match="terminal"):
        service.create_checkpoint(
            state=closed.model_copy(update={"revision": 10}),
            workspace_fingerprint="workspace",
            environment_fingerprint="environment",
            runtime_revision="rev-9",
            next_step=None,
        )

def test_read_connections_release_windows_file_handles(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    database = runtime_root / "runtime.sqlite3"
    state = _state()
    store = SQLiteContinuityStore(database)
    service = ContinuityService(store)
    stored = service.create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step="Run second step.",
    )

    assert store.schema_version() == 4
    assert store.journal_mode() == "wal"
    assert store.load_checkpoint(stored.envelope.checkpoint.checkpoint_id) == stored
    assert store.load_latest(state.task_id) == stored
    assert store.list_checkpoints(state.task_id) == (stored,)
    assert store.load_task_state(state.task_id).phase is TaskPhase.CHECKPOINTED
    assert store.verify_integrity().valid

    # Windows refuses this removal while any sqlite3.Connection is still open.
    shutil.rmtree(runtime_root)
    assert not runtime_root.exists()

