from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from luna.audit import AuditEventKind, AuditSession
from luna.continuity import (
    ContinuityService,
    ResumePolicy,
    ResumeStatus,
    SQLiteContinuityStore,
)
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.contracts.enums import (
    CompletionStatus,
    ObservationStatus,
    PlanStepStatus,
    TaskPhase,
)
from luna.contracts.plan import PlanStep
from luna.planning import AttemptBasis, AttemptRecord, RetryReason


def _state(*, active: bool = False) -> TaskState:
    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Resume safely.",
        required_conditions=("State resumes without blind replay.",),
        evidence_required=("checkpoint hash evidence",),
        scope=TaskScope(workspace_root="C:/workspace"),
        risk_level=RiskLevel.LOW,
        owner="user",
    )
    return TaskState(
        task_id=task_id,
        contract=contract,
        phase=TaskPhase.ACTING if active else TaskPhase.PLANNED,
        plan=(
            PlanStep(
                sequence=1,
                description="Resume step.",
                status=(
                    PlanStepStatus.ACTIVE
                    if active
                    else PlanStepStatus.PENDING
                ),
            ),
        ),
        revision=3,
    )


def _policy(
    *,
    runtime_revision: str = "rev-8",
    workspace: str = "workspace",
    environment: str = "environment",
) -> ResumePolicy:
    return ResumePolicy(
        runtime_revision=runtime_revision,
        workspace_fingerprint=workspace,
        environment_fingerprint=environment,
    )


def test_matching_restart_resumes_to_safe_phase(tmp_path: Path) -> None:
    state = _state()
    database = tmp_path / "runtime.sqlite3"
    ContinuityService(SQLiteContinuityStore(database)).create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step="Activate pending step.",
    )

    restarted = ContinuityService(SQLiteContinuityStore(database))
    decision = restarted.resume_latest(
        task_id=state.task_id,
        policy=_policy(),
    )

    assert decision.status is ResumeStatus.READY
    assert decision.resumed_state is not None
    assert decision.resumed_state.phase is TaskPhase.PLANNED
    assert decision.resumed_state.checkpoint_id is None


def test_revision_workspace_and_environment_mismatch_block_resume(
    tmp_path: Path,
) -> None:
    state = _state()
    service = ContinuityService(
        SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    )
    service.create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step="Activate pending step.",
    )

    decision = service.resume_latest(
        task_id=state.task_id,
        policy=_policy(
            runtime_revision="rev-9",
            workspace="changed",
            environment="changed",
        ),
    )

    assert decision.status is ResumeStatus.BLOCKED
    assert set(decision.reasons) == {
        "runtime revision mismatch",
        "workspace fingerprint mismatch",
        "environment fingerprint mismatch",
    }


def test_interrupted_active_action_is_not_replayed(tmp_path: Path) -> None:
    state = _state(active=True)
    service = ContinuityService(
        SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    )
    service.create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step="Reconcile interrupted action.",
    )

    decision = service.resume_latest(
        task_id=state.task_id,
        policy=_policy(),
    )

    assert decision.status is ResumeStatus.BLOCKED
    assert "interrupted action" in decision.reasons[-1]
    assert state.plan[0].step_id in decision.replay_prohibited_step_ids


def test_second_resume_is_blocked_as_stale(tmp_path: Path) -> None:
    state = _state()
    service = ContinuityService(
        SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    )
    service.create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step="Activate pending step.",
    )
    first = service.resume_latest(task_id=state.task_id, policy=_policy())
    second = service.resume_latest(task_id=state.task_id, policy=_policy())

    assert first.status is ResumeStatus.READY
    assert second.status is ResumeStatus.BLOCKED
    assert "already resumed" in second.reasons[0]


def test_terminal_checkpoint_returns_terminal(tmp_path: Path) -> None:
    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Finished task.",
        required_conditions=("Finished.",),
        evidence_required=("test result",),
        scope=TaskScope(workspace_root="C:/workspace"),
        risk_level=RiskLevel.LOW,
        owner="user",
    )
    state = TaskState(
        task_id=task_id,
        contract=contract,
        phase=TaskPhase.CLOSED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
        revision=8,
    )
    service = ContinuityService(
        SQLiteContinuityStore(tmp_path / "runtime.sqlite3")
    )
    service.create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step=None,
    )

    decision = service.resume_latest(
        task_id=task_id,
        policy=_policy(),
    )

    assert decision.status is ResumeStatus.TERMINAL
    assert decision.resumed_state is None


def test_retry_history_survives_restart_and_blocks_exact_retry(
    tmp_path: Path,
) -> None:
    state = _state()
    basis = AttemptBasis(
        action_key="run-tests",
        context_fingerprint="1" * 64,
        evidence_refs=("observation:one",),
        assumption_revision=0,
        execution_strategy="pytest",
        verification_strategy="exit-code",
        scope_fingerprint="2" * 64,
    )
    attempt = AttemptRecord(
        task_id=state.task_id,
        step_id=state.plan[0].step_id,
        basis=basis,
        observation_id=uuid4(),
        outcome=ObservationStatus.FAILURE,
    )
    database = tmp_path / "runtime.sqlite3"
    stored = ContinuityService(SQLiteContinuityStore(database)).create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step="Change retry basis.",
        attempts=(attempt,),
    )

    restarted = ContinuityService(SQLiteContinuityStore(database))
    decision = restarted.evaluate_retry(
        checkpoint_id=stored.envelope.checkpoint.checkpoint_id,
        candidate=basis,
    )

    assert not decision.allowed
    assert decision.reason is RetryReason.BLIND_RETRY_BLOCKED


def test_checkpoint_and_resume_are_audited(tmp_path: Path) -> None:
    state = _state()
    trace_id = uuid4()
    audit = AuditSession(tmp_path / "audit")
    audit.record_task_contract(contract=state.contract, trace_id=trace_id)
    service = ContinuityService(
        SQLiteContinuityStore(tmp_path / "runtime.sqlite3"),
        audit,
    )
    service.create_checkpoint(
        state=state,
        workspace_fingerprint="workspace",
        environment_fingerprint="environment",
        runtime_revision="rev-8",
        next_step="Activate pending step.",
        trace_id=trace_id,
    )
    service.resume_latest(
        task_id=state.task_id,
        policy=_policy(),
        trace_id=trace_id,
    )

    kinds = {
        event.kind for event in audit.events_for_task(state.task_id)
    }
    assert AuditEventKind.CHECKPOINT_CREATED in kinds
    assert AuditEventKind.RESUME_DECISION in kinds
    assert audit.verify_integrity().valid
