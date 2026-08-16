from __future__ import annotations

import sqlite3
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from luna.context import (
    ContextClaimType,
    ContextFailureAction,
    ContextRequirement,
)
from luna.continuity import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    ContinuityService,
    SQLiteContinuityStore,
)
from luna.continuity.models import StoredCheckpoint, model_digest
from luna.continuity.store import CognitivePolicyNotFoundError
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.contracts.enums import PlanStepStatus, TaskPhase
from luna.contracts.plan import PlanStep


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _contract(task_id: UUID) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Bind exact rehydration policy through ContinuityService.",
        required_conditions=("Historical policy is checkpoint-bound.",),
        evidence_required=("service persistence evidence",),
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


def _create(
    store: SQLiteContinuityStore,
    state: TaskState,
    *,
    cognitive_bindings: tuple[CognitiveOwnerBinding, ...] | None = None,
    cognitive_requirements: tuple[ContextRequirement, ...] | None = None,
) -> StoredCheckpoint:
    return ContinuityService(store).create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-c2b-p1b",
        next_step="Run second step.",
        cognitive_bindings=cognitive_bindings,
        cognitive_requirements=cognitive_requirements,
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


def test_service_requirement_policy_persists_without_cognitive_bindings(
    tmp_path: Path,
) -> None:
    database = tmp_path / "policy-only.sqlite3"
    store = SQLiteContinuityStore(database)
    state = _state()
    requirement = _requirement()

    stored = _create(
        store,
        state,
        cognitive_requirements=(requirement,),
    )

    policy = store.load_checkpoint_cognitive_policy(
        stored.envelope.checkpoint.checkpoint_id
    ).policy

    assert policy.requirements == (requirement,)
    assert _counts(database) == (1, 1, 0, 0, 1, 1)
    assert store.verify_integrity().valid


def test_service_policy_opt_in_persists_exact_requirements(
    tmp_path: Path,
) -> None:
    database = tmp_path / "policy-opt-in.sqlite3"
    store = SQLiteContinuityStore(database)
    state = _state()
    requirements = (
        _requirement(),
        _requirement(
            key="active_failure_class",
            claim_type=ContextClaimType.EXECUTION_STATE,
            max_age_seconds=30,
            failure_action=ContextFailureAction.VERIFY,
        ),
    )

    stored = _create(
        store,
        state,
        cognitive_bindings=(_binding(),),
        cognitive_requirements=requirements,
    )

    policy = store.load_checkpoint_cognitive_policy(
        stored.envelope.checkpoint.checkpoint_id
    ).policy

    assert policy.task_id == stored.envelope.state.task_id
    assert policy.checkpoint_id == stored.envelope.checkpoint.checkpoint_id
    assert policy.task_revision == stored.envelope.state.revision
    assert policy.task_state_sha256 == model_digest(stored.envelope.state)
    assert policy.requirements == tuple(
        sorted(
            requirements,
            key=lambda item: (item.key, item.claim_type.value),
        )
    )
    assert _counts(database) == (1, 1, 1, 1, 1, 1)
    assert store.verify_integrity().valid


def test_service_explicit_empty_requirements_persists_empty_policy(
    tmp_path: Path,
) -> None:
    database = tmp_path / "policy-empty.sqlite3"
    store = SQLiteContinuityStore(database)
    state = _state()

    stored = _create(
        store,
        state,
        cognitive_requirements=(),
    )

    policy = store.load_checkpoint_cognitive_policy(
        stored.envelope.checkpoint.checkpoint_id
    ).policy

    assert policy.requirements == ()
    assert _counts(database) == (1, 1, 0, 0, 1, 1)


def test_service_manifest_only_path_remains_policy_unbound(
    tmp_path: Path,
) -> None:
    database = tmp_path / "manifest-only.sqlite3"
    store = SQLiteContinuityStore(database)
    state = _state()

    stored = _create(
        store,
        state,
        cognitive_bindings=(_binding(),),
    )

    store.load_checkpoint_cognitive_manifest(
        stored.envelope.checkpoint.checkpoint_id
    )
    with pytest.raises(CognitivePolicyNotFoundError):
        store.load_checkpoint_cognitive_policy(
            stored.envelope.checkpoint.checkpoint_id
        )

    assert _counts(database) == (1, 1, 1, 1, 0, 0)
    assert store.verify_integrity().valid


def test_service_policy_hashes_checkpointed_state_not_input_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "checkpointed-state.sqlite3"
    store = SQLiteContinuityStore(database)
    input_state = _state()

    stored = _create(
        store,
        input_state,
        cognitive_bindings=(_binding(),),
        cognitive_requirements=(_requirement(),),
    )
    policy = store.load_checkpoint_cognitive_policy(
        stored.envelope.checkpoint.checkpoint_id
    ).policy

    assert stored.envelope.state.phase is TaskPhase.CHECKPOINTED
    assert stored.envelope.state.revision > input_state.revision
    assert policy.task_revision == stored.envelope.state.revision
    assert policy.task_revision != input_state.revision
    assert policy.task_state_sha256 == model_digest(stored.envelope.state)
    assert policy.task_state_sha256 != model_digest(input_state)


def test_service_duplicate_requirement_keys_reject_before_durable_write(
    tmp_path: Path,
) -> None:
    database = tmp_path / "duplicate-requirements.sqlite3"
    store = SQLiteContinuityStore(database)
    state = _state()

    requirements = (
        _requirement(),
        _requirement(require_verified=False),
    )

    with pytest.raises(
        ValueError,
        match="requirement keys must be unique",
    ):
        _create(
            store,
            state,
            cognitive_bindings=(_binding(),),
            cognitive_requirements=requirements,
        )

    assert _counts(database) == (0, 0, 0, 0, 0, 0)


def test_service_policy_path_preserves_stored_checkpoint_return_type(
    tmp_path: Path,
) -> None:
    database = tmp_path / "return-type.sqlite3"
    store = SQLiteContinuityStore(database)
    state = _state()

    stored = _create(
        store,
        state,
        cognitive_bindings=(_binding(),),
        cognitive_requirements=(_requirement(),),
    )

    assert isinstance(stored, StoredCheckpoint)
