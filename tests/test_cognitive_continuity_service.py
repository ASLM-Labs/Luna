from __future__ import annotations

import sqlite3
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.audit.models import AuditEventKind
from luna.continuity import (
    CognitiveManifestNotFoundError,
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    ContinuityError,
    ContinuityService,
    SQLiteContinuityStore,
    StoredCheckpoint,
)
from luna.continuity.models import model_digest
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.contracts.enums import PlanStepStatus, TaskPhase
from luna.contracts.plan import PlanStep


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _contract(task_id: object) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Persist an opt-in cognitive checkpoint.",
        required_conditions=("Checkpoint binds current cognitive owners.",),
        evidence_required=("atomic cognitive checkpoint evidence",),
        scope=TaskScope(workspace_root="C:/workspace"),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def _state() -> TaskState:
    task_id = uuid4()
    return TaskState(
        task_id=task_id,
        contract=_contract(task_id),
        phase=TaskPhase.PLANNED,
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


def _identity_binding(
    *,
    suffix: str = "1",
    digest_seed: str = "identity",
) -> CognitiveOwnerBinding:
    return CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.IDENTITY_PROFILE,
        source_ref=f"identity://luna/profile/{suffix}",
        content_sha256=_digest(digest_seed),
    )


def _counts(database: Path) -> tuple[int, int, int, int]:
    connection = sqlite3.connect(database)
    try:
        checkpoint_count = connection.execute(
            "SELECT COUNT(*) FROM checkpoints"
        ).fetchone()
        state_count = connection.execute(
            "SELECT COUNT(*) FROM task_states"
        ).fetchone()
        manifest_count = connection.execute(
            "SELECT COUNT(*) FROM cognitive_rehydration_manifests"
        ).fetchone()
        binding_count = connection.execute(
            "SELECT COUNT(*) FROM checkpoint_cognitive_manifests"
        ).fetchone()
    finally:
        connection.close()

    assert checkpoint_count is not None
    assert state_count is not None
    assert manifest_count is not None
    assert binding_count is not None
    return (
        int(checkpoint_count[0]),
        int(state_count[0]),
        int(manifest_count[0]),
        int(binding_count[0]),
    )



class _RecordingLedger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def append(self, **event: object) -> None:
        self.events.append(event)


class _RecordingAudit:
    def __init__(self) -> None:
        self.ledger = _RecordingLedger()


def _create(
    service: ContinuityService,
    state: TaskState,
    *,
    cognitive_bindings: tuple[CognitiveOwnerBinding, ...] | None,
) -> StoredCheckpoint:
    return service.create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-b2b",
        next_step="Run second step.",
        cognitive_bindings=cognitive_bindings,
    )


def test_service_without_cognitive_bindings_preserves_legacy_path(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteContinuityStore(database)
    service = ContinuityService(store)
    state = _state()

    stored = _create(service, state, cognitive_bindings=None)

    assert isinstance(stored, StoredCheckpoint)
    assert _counts(database) == (1, 1, 0, 0)
    with pytest.raises(CognitiveManifestNotFoundError, match="no cognitive manifest"):
        store.load_checkpoint_cognitive_manifest(
            stored.envelope.checkpoint.checkpoint_id
        )


def test_service_opt_in_binds_manifest_to_exact_persisted_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteContinuityStore(database)
    service = ContinuityService(store)
    state = _state()

    stored = _create(
        service,
        state,
        cognitive_bindings=(_identity_binding(),),
    )
    loaded_manifest = store.load_checkpoint_cognitive_manifest(
        stored.envelope.checkpoint.checkpoint_id
    ).manifest

    assert isinstance(stored, StoredCheckpoint)
    assert loaded_manifest.task_id == stored.envelope.state.task_id
    assert loaded_manifest.checkpoint_id == stored.envelope.checkpoint.checkpoint_id
    assert loaded_manifest.task_revision == stored.envelope.state.revision
    assert loaded_manifest.task_state_sha256 == model_digest(stored.envelope.state)
    assert _counts(database) == (1, 1, 1, 1)


def test_service_nonterminal_manifest_hashes_checkpointed_state_not_input_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteContinuityStore(database)
    service = ContinuityService(store)
    state = _state()
    input_digest = model_digest(state)

    stored = _create(
        service,
        state,
        cognitive_bindings=(_identity_binding(),),
    )
    loaded_manifest = store.load_checkpoint_cognitive_manifest(
        stored.envelope.checkpoint.checkpoint_id
    ).manifest

    assert stored.envelope.state.phase is TaskPhase.CHECKPOINTED
    assert loaded_manifest.task_state_sha256 == model_digest(stored.envelope.state)
    assert loaded_manifest.task_state_sha256 != input_digest


def test_service_explicit_empty_bindings_reject_before_durable_write(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteContinuityStore(database)
    service = ContinuityService(store)
    state = _state()

    with pytest.raises(ValidationError):
        _create(service, state, cognitive_bindings=())

    assert _counts(database) == (0, 0, 0, 0)
    assert store.list_checkpoints(state.task_id) == ()
    with pytest.raises(ContinuityError, match="task state not found"):
        store.load_task_state(state.task_id)


def test_service_rejects_multiple_identity_bindings_before_durable_write(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteContinuityStore(database)
    service = ContinuityService(store)
    state = _state()

    bindings = (
        _identity_binding(suffix="1", digest_seed="identity-1"),
        _identity_binding(suffix="2", digest_seed="identity-2"),
    )

    with pytest.raises(ValidationError, match="exactly one identity binding"):
        _create(service, state, cognitive_bindings=bindings)

    assert _counts(database) == (0, 0, 0, 0)


def test_service_cognitive_checkpoint_preserves_return_type(
    tmp_path: Path,
) -> None:
    store = SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    service = ContinuityService(store)
    state = _state()

    stored = _create(
        service,
        state,
        cognitive_bindings=(_identity_binding(),),
    )

    assert type(stored) is StoredCheckpoint

def test_service_cognitive_checkpoint_preserves_checkpoint_created_audit_event(
    tmp_path: Path,
) -> None:
    store = SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    audit = _RecordingAudit()
    service = ContinuityService(store, audit=audit)  # type: ignore[arg-type]
    state = _state()
    trace_id = uuid4()

    stored = service.create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-b2b",
        next_step="Run second step.",
        trace_id=trace_id,
        cognitive_bindings=(_identity_binding(),),
    )

    assert len(audit.ledger.events) == 1
    event = audit.ledger.events[0]
    assert event["kind"] is AuditEventKind.CHECKPOINT_CREATED
    assert event["task_id"] == state.task_id
    assert event["trace_id"] == trace_id
    assert event["subject_id"] == str(stored.envelope.checkpoint.checkpoint_id)

    payload = event["payload"]
    assert isinstance(payload, dict)
    assert payload["payload_sha256"] == stored.payload_sha256
    assert "manifest_id" not in payload
