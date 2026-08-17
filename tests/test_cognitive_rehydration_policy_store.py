from __future__ import annotations

import sqlite3
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from luna.context import (
    ContextClaimType,
    ContextFailureAction,
    ContextRequirement,
)
from luna.continuity import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    ContinuityConflictError,
    ContinuityService,
    SQLiteContinuityStore,
    build_cognitive_rehydration_manifest,
)
from luna.continuity.cognitive import (
    CognitiveRehydrationPolicy,
    StoredCognitiveRehydrationPolicy,
    build_cognitive_rehydration_policy,
)
from luna.continuity.models import CheckpointEnvelope, model_digest
from luna.continuity.store import CognitivePolicyNotFoundError
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.contracts.enums import PlanStepStatus, TaskPhase
from luna.contracts.plan import PlanStep


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _contract(task_id: UUID) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Persist exact cognitive rehydration readiness policy.",
        required_conditions=("Historical context policy survives restart.",),
        evidence_required=("atomic policy persistence evidence",),
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
        runtime_revision="rev-c2b-p1",
        next_step="Run second step.",
    )
    return stored.envelope


def _manifest_for(envelope: CheckpointEnvelope):
    return build_cognitive_rehydration_manifest(
        task_id=envelope.state.task_id,
        checkpoint_id=envelope.checkpoint.checkpoint_id,
        task_revision=envelope.state.revision,
        task_state_sha256=model_digest(envelope.state),
        bindings=(_binding(),),
    )


def _requirement(
    *,
    key: str = "current_head",
    claim_type: ContextClaimType = ContextClaimType.REPOSITORY_STATE,
    critical: bool = True,
    require_verified: bool = True,
    max_age_seconds: int | None = 60,
    failure_action: ContextFailureAction = ContextFailureAction.STOP,
) -> ContextRequirement:
    return ContextRequirement(
        key=key,
        claim_type=claim_type,
        critical=critical,
        require_verified=require_verified,
        max_age_seconds=max_age_seconds,
        failure_action=failure_action,
    )


def _policy_for(
    envelope: CheckpointEnvelope,
    *,
    requirements: tuple[ContextRequirement, ...] | None = None,
    task_id: UUID | None = None,
    checkpoint_id: UUID | None = None,
    task_revision: int | None = None,
    task_state_sha256: str | None = None,
) -> CognitiveRehydrationPolicy:
    resolved_requirements = (_requirement(),) if requirements is None else requirements
    return build_cognitive_rehydration_policy(
        task_id=task_id or envelope.state.task_id,
        checkpoint_id=checkpoint_id or envelope.checkpoint.checkpoint_id,
        task_revision=(
            envelope.state.revision
            if task_revision is None
            else task_revision
        ),
        task_state_sha256=task_state_sha256 or model_digest(envelope.state),
        requirements=resolved_requirements,
    )


def _counts(database: Path) -> tuple[int, int, int, int, int, int]:
    tables = (
        "checkpoints",
        "task_states",
        "cognitive_rehydration_manifests",
        "checkpoint_cognitive_manifests",
        "cognitive_rehydration_policies",
        "checkpoint_cognitive_policies",
    )
    values: list[int] = []
    with sqlite3.connect(database) as connection:
        for table in tables:
            row = connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()
            assert row is not None
            values.append(int(row[0]))
    assert len(values) == 6
    return (
        values[0],
        values[1],
        values[2],
        values[3],
        values[4],
        values[5],
    )


def test_policy_is_content_addressed_and_requirement_order_independent(
    tmp_path: Path,
) -> None:
    envelope = _envelope(tmp_path, suffix="policy-order")
    first_requirement = _requirement()
    second_requirement = _requirement(
        key="active_failure_class",
        claim_type=ContextClaimType.EXECUTION_STATE,
        max_age_seconds=30,
        failure_action=ContextFailureAction.VERIFY,
    )

    forward = _policy_for(
        envelope,
        requirements=(first_requirement, second_requirement),
    )
    reverse = _policy_for(
        envelope,
        requirements=(second_requirement, first_requirement),
    )

    assert forward == reverse
    assert forward.policy_id == reverse.policy_id
    assert tuple(item.key for item in forward.requirements) == (
        "active_failure_class",
        "current_head",
    )


def test_policy_empty_requirement_set_is_valid(tmp_path: Path) -> None:
    envelope = _envelope(tmp_path, suffix="policy-empty")

    policy = _policy_for(envelope, requirements=())

    assert policy.requirements == ()
    assert policy.policy_id.startswith(
        "cognitive-rehydration-policy:sha256:"
    )


@pytest.mark.parametrize(
    "changed_requirement",
    (
        _requirement(require_verified=False),
        _requirement(max_age_seconds=120),
        _requirement(failure_action=ContextFailureAction.VERIFY),
    ),
)
def test_policy_identity_changes_with_exact_requirement_semantics(
    tmp_path: Path,
    changed_requirement: ContextRequirement,
) -> None:
    envelope = _envelope(tmp_path, suffix=str(uuid4()))
    baseline = _policy_for(envelope)
    changed = _policy_for(
        envelope,
        requirements=(changed_requirement,),
    )

    assert changed.policy_id != baseline.policy_id


@pytest.mark.parametrize(
    "field_name",
    (
        "runtime_authority",
        "execution_authority",
        "verification_authority",
        "completion_authority",
    ),
)
def test_policy_cannot_grant_authority(
    tmp_path: Path,
    field_name: str,
) -> None:
    envelope = _envelope(tmp_path, suffix=str(uuid4()))
    policy = _policy_for(envelope)
    payload = policy.model_dump(mode="python")
    payload[field_name] = True

    with pytest.raises(ValidationError):
        CognitiveRehydrationPolicy.model_validate(payload)


def test_stored_policy_rejects_wrong_payload_digest(tmp_path: Path) -> None:
    envelope = _envelope(tmp_path, suffix="stored-policy-digest")
    policy = _policy_for(envelope)

    with pytest.raises(ValidationError, match="payload digest mismatch"):
        StoredCognitiveRehydrationPolicy(
            policy=policy,
            payload_sha256="0" * 64,
        )


def test_atomic_checkpoint_manifest_policy_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "target-round-trip.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix="source-round-trip-policy")
    manifest = _manifest_for(envelope)
    policy = _policy_for(envelope)

    stored_checkpoint, stored_manifest, stored_policy = (
        store.save_checkpoint_with_cognitive_manifest_and_policy(
            envelope=envelope,
            manifest=manifest,
            policy=policy,
        )
    )

    assert store.schema_version() == 4
    assert store.load_checkpoint(envelope.checkpoint.checkpoint_id) == stored_checkpoint
    assert (
        store.load_checkpoint_cognitive_manifest(
            envelope.checkpoint.checkpoint_id
        )
        == stored_manifest
    )
    assert (
        store.load_checkpoint_cognitive_policy(
            envelope.checkpoint.checkpoint_id
        )
        == stored_policy
    )
    assert _counts(database) == (1, 1, 1, 1, 1, 1)
    assert store.verify_integrity().valid


def test_atomic_checkpoint_policy_only_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "target-policy-only.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix="source-policy-only")
    policy = _policy_for(envelope)

    stored_checkpoint, stored_policy = store.save_checkpoint_with_cognitive_policy(
        envelope=envelope,
        policy=policy,
    )

    assert store.load_checkpoint(envelope.checkpoint.checkpoint_id) == stored_checkpoint
    assert (
        store.load_checkpoint_cognitive_policy(
            envelope.checkpoint.checkpoint_id
        )
        == stored_policy
    )
    assert _counts(database) == (1, 1, 0, 0, 1, 1)
    assert store.verify_integrity().valid


def test_policy_only_sidecar_failure_rolls_back_checkpoint(tmp_path: Path) -> None:
    database = tmp_path / "target-policy-only-rollback.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix="source-policy-only-rollback")
    policy = _policy_for(envelope)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER force_policy_only_binding_failure
            BEFORE INSERT ON checkpoint_cognitive_policies
            BEGIN
                SELECT RAISE(ABORT, 'forced policy-only binding failure');
            END
            """
        )

    with pytest.raises(
        sqlite3.DatabaseError,
        match="forced policy-only binding failure",
    ):
        store.save_checkpoint_with_cognitive_policy(
            envelope=envelope,
            policy=policy,
        )

    assert _counts(database) == (0, 0, 0, 0, 0, 0)
    assert store.verify_integrity().valid


@pytest.mark.parametrize(
    "mismatch",
    ("task_id", "checkpoint_id", "task_revision", "task_state_sha256"),
)
def test_atomic_policy_rejects_checkpoint_binding_mismatch_before_write(
    tmp_path: Path,
    mismatch: str,
) -> None:
    database = tmp_path / f"target-policy-{mismatch}.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix=f"source-policy-{mismatch}")
    manifest = _manifest_for(envelope)

    overrides: dict[str, object] = {}
    if mismatch == "task_id":
        overrides["task_id"] = uuid4()
    elif mismatch == "checkpoint_id":
        overrides["checkpoint_id"] = uuid4()
    elif mismatch == "task_revision":
        overrides["task_revision"] = envelope.state.revision + 1
    else:
        overrides["task_state_sha256"] = _digest("wrong-task-state")

    policy = _policy_for(envelope, **overrides)

    with pytest.raises(ContinuityConflictError):
        store.save_checkpoint_with_cognitive_manifest_and_policy(
            envelope=envelope,
            manifest=manifest,
            policy=policy,
        )

    assert _counts(database) == (0, 0, 0, 0, 0, 0)


def test_policy_sidecar_failure_rolls_back_complete_cognitive_checkpoint(
    tmp_path: Path,
) -> None:
    database = tmp_path / "target-policy-rollback.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix="source-policy-rollback")
    manifest = _manifest_for(envelope)
    policy = _policy_for(envelope)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER force_cognitive_policy_binding_failure
            BEFORE INSERT ON checkpoint_cognitive_policies
            BEGIN
                SELECT RAISE(ABORT, 'forced policy binding failure');
            END
            """
        )

    with pytest.raises(
        sqlite3.DatabaseError,
        match="forced policy binding failure",
    ):
        store.save_checkpoint_with_cognitive_manifest_and_policy(
            envelope=envelope,
            manifest=manifest,
            policy=policy,
        )

    assert _counts(database) == (0, 0, 0, 0, 0, 0)
    assert store.verify_integrity().valid


def test_manifest_only_cognitive_checkpoint_remains_policy_unbound(
    tmp_path: Path,
) -> None:
    database = tmp_path / "target-manifest-only.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix="source-manifest-only")
    manifest = _manifest_for(envelope)

    store.save_checkpoint_with_cognitive_manifest(
        envelope=envelope,
        manifest=manifest,
    )

    with pytest.raises(
        CognitivePolicyNotFoundError,
        match="no cognitive policy",
    ):
        store.load_checkpoint_cognitive_policy(
            envelope.checkpoint.checkpoint_id
        )

    assert _counts(database) == (1, 1, 1, 1, 0, 0)
    assert store.verify_integrity().valid


def test_policy_sidecar_semantic_tampering_is_detected(tmp_path: Path) -> None:
    database = tmp_path / "target-policy-tamper.sqlite3"
    store = SQLiteContinuityStore(database)

    first = _envelope(tmp_path, suffix="source-policy-tamper-a")
    first_manifest = _manifest_for(first)
    first_policy = _policy_for(first)
    store.save_checkpoint_with_cognitive_manifest_and_policy(
        envelope=first,
        manifest=first_manifest,
        policy=first_policy,
    )

    second = _envelope(tmp_path, suffix="source-policy-tamper-b")
    second_manifest = _manifest_for(second)
    second_policy = _policy_for(second)
    store.save_checkpoint_with_cognitive_manifest_and_policy(
        envelope=second,
        manifest=second_manifest,
        policy=second_policy,
    )

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM checkpoint_cognitive_policies WHERE checkpoint_id = ?",
            (str(second.checkpoint.checkpoint_id),),
        )
        connection.execute(
            """
            UPDATE checkpoint_cognitive_policies
            SET policy_id = ?
            WHERE checkpoint_id = ?
            """,
            (
                second_policy.policy_id,
                str(first.checkpoint.checkpoint_id),
            ),
        )

    integrity = store.verify_integrity()
    assert not integrity.valid
    assert integrity.first_error is not None
    assert "does not match checkpoint" in integrity.first_error

    with pytest.raises(
        ContinuityConflictError,
        match="does not match checkpoint",
    ):
        store.load_checkpoint_cognitive_policy(
            first.checkpoint.checkpoint_id
        )


def test_v3_to_v4_migration_preserves_manifest_checkpoint_digest(
    tmp_path: Path,
) -> None:
    database = tmp_path / "target-v3-to-v4.sqlite3"
    store = SQLiteContinuityStore(database)
    envelope = _envelope(tmp_path, suffix="source-v3-to-v4")
    manifest = _manifest_for(envelope)
    stored_checkpoint, stored_manifest = (
        store.save_checkpoint_with_cognitive_manifest(
            envelope=envelope,
            manifest=manifest,
        )
    )

    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE checkpoint_cognitive_policies")
        connection.execute("DROP TABLE cognitive_rehydration_policies")
        connection.execute("DELETE FROM schema_migrations WHERE version = 4")

    restarted = SQLiteContinuityStore(database)

    assert restarted.schema_version() == 4
    assert (
        restarted.load_checkpoint(envelope.checkpoint.checkpoint_id)
        == stored_checkpoint
    )
    assert (
        restarted.load_checkpoint_cognitive_manifest(
            envelope.checkpoint.checkpoint_id
        )
        == stored_manifest
    )
    with pytest.raises(CognitivePolicyNotFoundError):
        restarted.load_checkpoint_cognitive_policy(
            envelope.checkpoint.checkpoint_id
        )
    assert restarted.verify_integrity().valid
