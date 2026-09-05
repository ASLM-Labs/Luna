from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from luna.continuity import (
    ContinuityService,
    ResumeCompatibilityDimension,
    ResumeCompatibilityVector,
    ResumePolicy,
    ResumeStatus,
    SQLiteContinuityStore,
)
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.contracts.base import SCHEMA_VERSION as CONTRACT_SCHEMA_VERSION
from luna.contracts.enums import PlanStepStatus, TaskPhase
from luna.contracts.plan import PlanStep
from luna.runtime import DeterministicFingerprintProvider, SQLiteRuntimeJournal


def _state(workspace: Path) -> TaskState:
    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Resume only across compatible runtime state.",
        required_conditions=("Compatibility dimensions match.",),
        evidence_required=("resume compatibility decision",),
        scope=TaskScope(workspace_root=str(workspace)),
        risk_level=RiskLevel.LOW,
        owner="user",
    )
    return TaskState(
        task_id=task_id,
        contract=contract,
        phase=TaskPhase.PLANNED,
        plan=(
            PlanStep(
                sequence=1,
                description="Continue safely.",
                status=PlanStepStatus.PENDING,
            ),
        ),
        revision=3,
    )


def _vector(
    *,
    runtime_revision: str = "r7c-test",
    continuity_schema_version: int = 1,
    runtime_journal_schema_version: int = 2,
    contract_schema_version: str = CONTRACT_SCHEMA_VERSION,
    workspace: str = "workspace",
    environment: str = "environment",
) -> ResumeCompatibilityVector:
    return ResumeCompatibilityVector(
        runtime_revision=runtime_revision,
        continuity_schema_version=continuity_schema_version,
        runtime_journal_schema_version=runtime_journal_schema_version,
        contract_schema_version=contract_schema_version,
        workspace_fingerprint=workspace,
        environment_fingerprint=environment,
    )


def _policy(vector: ResumeCompatibilityVector) -> ResumePolicy:
    return ResumePolicy(
        runtime_revision=vector.runtime_revision,
        workspace_fingerprint=vector.workspace_fingerprint,
        environment_fingerprint=vector.environment_fingerprint,
        compatibility_vector=vector,
    )


def _checkpoint(
    service: ContinuityService,
    state: TaskState,
    vector: ResumeCompatibilityVector,
) -> None:
    service.create_checkpoint(
        state=state,
        workspace_fingerprint=vector.workspace_fingerprint,
        environment_fingerprint=vector.environment_fingerprint,
        runtime_revision=vector.runtime_revision,
        compatibility_vector=vector,
        next_step="Continue safely.",
    )


def test_matching_extended_vector_resumes(tmp_path: Path) -> None:
    state = _state(tmp_path)
    service = ContinuityService(SQLiteContinuityStore(tmp_path / "continuity.sqlite3"))
    vector = _vector()
    _checkpoint(service, state, vector)

    decision = service.resume_latest(task_id=state.task_id, policy=_policy(vector))

    assert decision.status is ResumeStatus.READY
    assert decision.compatibility_mismatches == ()
    assert decision.reasons[0] == "extended resume compatibility vector matched"


def test_schema_dimension_mismatches_block_with_structured_codes(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    service = ContinuityService(SQLiteContinuityStore(tmp_path / "continuity.sqlite3"))
    persisted = _vector()
    _checkpoint(service, state, persisted)
    current = _vector(
        continuity_schema_version=2,
        runtime_journal_schema_version=3,
        contract_schema_version="2.0",
    )

    decision = service.resume_latest(task_id=state.task_id, policy=_policy(current))

    assert decision.status is ResumeStatus.BLOCKED
    assert set(decision.compatibility_mismatches) == {
        ResumeCompatibilityDimension.CONTINUITY_SCHEMA_VERSION,
        ResumeCompatibilityDimension.RUNTIME_JOURNAL_SCHEMA_VERSION,
        ResumeCompatibilityDimension.CONTRACT_SCHEMA_VERSION,
    }
    assert set(decision.reasons) == {
        "continuity schema version mismatch",
        "runtime journal schema version mismatch",
        "contract schema version mismatch",
    }


def test_extended_policy_blocks_legacy_checkpoint_without_vector(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    service = ContinuityService(SQLiteContinuityStore(tmp_path / "continuity.sqlite3"))
    service.create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="r7c-test",
        next_step="Continue safely.",
    )

    decision = service.resume_latest(
        task_id=state.task_id,
        policy=_policy(_vector()),
    )

    assert decision.status is ResumeStatus.BLOCKED
    assert decision.compatibility_mismatches == (
        ResumeCompatibilityDimension.VECTOR,
    )
    assert "resume compatibility vector missing" in decision.reasons


def test_legacy_low_level_policy_remains_phase8_compatible(tmp_path: Path) -> None:
    state = _state(tmp_path)
    service = ContinuityService(SQLiteContinuityStore(tmp_path / "continuity.sqlite3"))
    service.create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="legacy",
        next_step="Continue safely.",
    )

    decision = service.resume_latest(
        task_id=state.task_id,
        policy=ResumePolicy(
            runtime_revision="legacy",
            workspace_fingerprint="workspace",
            environment_fingerprint="environment",
        ),
    )

    assert decision.status is ResumeStatus.READY
    assert decision.compatibility_mismatches == ()


def test_provider_builds_extended_vector_only_when_all_versions_supplied(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    provider = DeterministicFingerprintProvider(runtime_revision="r7c-test")

    policy = provider.resume_policy(
        task_contract=state.contract,
        continuity_schema_version=1,
        runtime_journal_schema_version=2,
        contract_schema_version=CONTRACT_SCHEMA_VERSION,
    )

    assert policy.compatibility_vector is not None
    assert policy.compatibility_vector.continuity_schema_version == 1
    assert policy.compatibility_vector.runtime_journal_schema_version == 2
    assert policy.compatibility_vector.contract_schema_version == CONTRACT_SCHEMA_VERSION

    with pytest.raises(ValueError, match="all schema versions"):
        provider.resume_policy(
            task_contract=state.contract,
            continuity_schema_version=1,
        )


def test_runtime_journal_reports_applied_schema_version(tmp_path: Path) -> None:
    journal = SQLiteRuntimeJournal(tmp_path / "journal.sqlite3")

    assert journal.schema_version() == 4


def test_vector_has_only_resume_compatibility_facts() -> None:
    assert set(ResumeCompatibilityVector.model_fields) == {
        "schema_version",
        "runtime_revision",
        "continuity_schema_version",
        "runtime_journal_schema_version",
        "contract_schema_version",
        "workspace_fingerprint",
        "environment_fingerprint",
    }
