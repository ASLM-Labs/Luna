from __future__ import annotations

import sqlite3
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from luna.continuity import (
    CognitiveManifestNotFoundError,
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    ContinuityConflictError,
    ContinuityService,
    SQLiteContinuityStore,
    build_cognitive_rehydration_manifest,
)
from luna.continuity.cognitive import CognitiveRehydrationManifest
from luna.continuity.models import CheckpointEnvelope, model_digest
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.contracts.enums import PlanStepStatus, TaskPhase
from luna.contracts.plan import PlanStep


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _contract(task_id: object) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Persist one atomic cognitive checkpoint binding.",
        required_conditions=("Checkpoint and manifest remain bound.",),
        evidence_required=("atomic persistence evidence",),
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


def _binding() -> CognitiveOwnerBinding:
    return CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.IDENTITY_PROFILE,
        source_ref="identity://luna/profile/1",
        content_sha256=_digest("identity"),
    )


def _envelope(tmp_path: Path, *, suffix: str) -> CheckpointEnvelope:
    state = _state()
    source = SQLiteContinuityStore(tmp_path / f"{suffix}.sqlite3")
    stored = ContinuityService(source).create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-b2a",
        next_step="Run second step.",
    )
    return stored.envelope


def _manifest_for(
    envelope: CheckpointEnvelope,
    *,
    task_id: UUID | None = None,
    checkpoint_id: UUID | None = None,
    task_revision: int | None = None,
    task_state_sha256: str | None = None,
) -> CognitiveRehydrationManifest:
    return build_cognitive_rehydration_manifest(
        task_id=task_id or envelope.state.task_id,
        checkpoint_id=checkpoint_id or envelope.checkpoint.checkpoint_id,
        task_revision=(
            envelope.state.revision if task_revision is None else task_revision
        ),
        task_state_sha256=task_state_sha256 or model_digest(envelope.state),
        bindings=(_binding(),),
    )


def _counts(database: Path) -> tuple[int, int, int, int]:
    with sqlite3.connect(database) as connection:
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


def test_atomic_checkpoint_manifest_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "target.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix="source-round-trip")
    manifest = _manifest_for(envelope)

    stored_checkpoint, stored_manifest = store.save_checkpoint_with_cognitive_manifest(
        envelope=envelope,
        manifest=manifest,
    )

    assert store.schema_version() == 4
    assert store.load_checkpoint(envelope.checkpoint.checkpoint_id) == stored_checkpoint
    assert (
        store.load_checkpoint_cognitive_manifest(envelope.checkpoint.checkpoint_id)
        == stored_manifest
    )
    assert stored_checkpoint.payload_sha256 == model_digest(envelope)
    assert _counts(database) == (1, 1, 1, 1)
    assert store.verify_integrity().valid


@pytest.mark.parametrize(
    "mismatch",
    ("task_id", "checkpoint_id", "task_revision", "task_state_sha256"),
)
def test_atomic_checkpoint_manifest_rejects_mismatched_binding_before_write(
    tmp_path: Path,
    mismatch: str,
) -> None:
    database = tmp_path / f"target-{mismatch}.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix=f"source-{mismatch}")

    overrides: dict[str, object] = {}
    if mismatch == "task_id":
        overrides["task_id"] = uuid4()
    elif mismatch == "checkpoint_id":
        overrides["checkpoint_id"] = uuid4()
    elif mismatch == "task_revision":
        overrides["task_revision"] = envelope.state.revision + 1
    else:
        overrides["task_state_sha256"] = _digest("wrong-task-state")

    manifest = _manifest_for(envelope, **overrides)

    with pytest.raises(ContinuityConflictError):
        store.save_checkpoint_with_cognitive_manifest(
            envelope=envelope,
            manifest=manifest,
        )

    assert _counts(database) == (0, 0, 0, 0)


def test_atomic_binding_failure_rolls_back_checkpoint_state_and_manifest(
    tmp_path: Path,
) -> None:
    database = tmp_path / "target-rollback.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix="source-rollback")
    manifest = _manifest_for(envelope)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER force_cognitive_binding_failure
            BEFORE INSERT ON checkpoint_cognitive_manifests
            BEGIN
                SELECT RAISE(ABORT, 'forced binding failure');
            END
            """
        )

    with pytest.raises(sqlite3.DatabaseError, match="forced binding failure"):
        store.save_checkpoint_with_cognitive_manifest(
            envelope=envelope,
            manifest=manifest,
        )

    assert _counts(database) == (0, 0, 0, 0)
    assert store.verify_integrity().valid


def test_legacy_checkpoint_save_remains_unbound(tmp_path: Path) -> None:
    database = tmp_path / "target-legacy.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix="source-legacy")

    stored = store.save_checkpoint(envelope)

    assert store.load_checkpoint(envelope.checkpoint.checkpoint_id) == stored
    with pytest.raises(CognitiveManifestNotFoundError, match="no cognitive manifest"):
        store.load_checkpoint_cognitive_manifest(envelope.checkpoint.checkpoint_id)
    assert _counts(database) == (1, 1, 0, 0)
    assert store.verify_integrity().valid


def test_binding_row_semantic_tampering_is_detected(tmp_path: Path) -> None:
    database = tmp_path / "target-tamper.sqlite3"
    store = SQLiteContinuityStore(database)

    first_envelope = _envelope(tmp_path, suffix="source-tamper-a")
    first_manifest = _manifest_for(first_envelope)
    store.save_checkpoint_with_cognitive_manifest(
        envelope=first_envelope,
        manifest=first_manifest,
    )

    second_envelope = _envelope(tmp_path, suffix="source-tamper-b")
    second_manifest = _manifest_for(second_envelope)
    store.save_checkpoint_with_cognitive_manifest(
        envelope=second_envelope,
        manifest=second_manifest,
    )

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM checkpoint_cognitive_manifests WHERE checkpoint_id = ?",
            (str(second_envelope.checkpoint.checkpoint_id),),
        )
        connection.execute(
            """
            UPDATE checkpoint_cognitive_manifests
            SET manifest_id = ?
            WHERE checkpoint_id = ?
            """,
            (
                second_manifest.manifest_id,
                str(first_envelope.checkpoint.checkpoint_id),
            ),
        )

    integrity = store.verify_integrity()
    assert not integrity.valid
    assert integrity.first_error is not None
    assert "does not match checkpoint" in integrity.first_error

    with pytest.raises(ContinuityConflictError, match="does not match checkpoint"):
        store.load_checkpoint_cognitive_manifest(
            first_envelope.checkpoint.checkpoint_id
        )


def test_v2_to_current_migration_preserves_legacy_checkpoint_digest(
    tmp_path: Path,
) -> None:
    database = tmp_path / "target-migration.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix="source-migration")
    stored_before = store.save_checkpoint(envelope)

    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE checkpoint_cognitive_policies")
        connection.execute("DROP TABLE cognitive_rehydration_policies")
        connection.execute("DROP TABLE checkpoint_cognitive_manifests")
        connection.execute("DELETE FROM schema_migrations WHERE version >= 3")

    restarted = SQLiteContinuityStore(database)
    stored_after = restarted.load_checkpoint(envelope.checkpoint.checkpoint_id)

    assert restarted.schema_version() == 4
    assert stored_after == stored_before
    assert stored_after.payload_sha256 == stored_before.payload_sha256
    assert stored_after.payload_sha256 == model_digest(envelope)
    assert restarted.verify_integrity().valid
