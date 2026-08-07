from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.actions import (
    ActionDenial,
    ActionDenialCode,
    ActionDenialStage,
)
from luna.contracts import Observation, RiskLevel, TaskContract, TaskScope
from luna.contracts.enums import ObservationStatus
from luna.planning import RetryDecision, RetryReason
from luna.recovery import (
    ChangeEstimate,
    FailureCategory,
    FailureClassifier,
    IsolationMode,
    MinimalChangeDenialCode,
    MinimalChangePolicy,
    RecoveryAction,
    RecoveryPolicy,
    WorkspaceIsolationPolicy,
)
from luna.runtime import RuntimeBudget
from luna.tools import ToolResult, ToolResultStatus

_ZERO = sha256(b"").hexdigest()


def _task(*, risk: RiskLevel = RiskLevel.LOW, write_allowed: bool = True) -> TaskContract:
    return TaskContract(
        objective="Verify Phase 12D deterministic recovery policy.",
        required_conditions=("Recovery policy remains runtime-owned.",),
        evidence_required=("Phase 12D verifier",),
        scope=TaskScope(
            workspace_root=".",
            allowed_paths=("src", "tests"),
            protected_paths=("src/luna/governance.py",),
            write_allowed=write_allowed,
        ),
        risk_level=risk,
        owner="user",
    )


def _tool_failure(error_class: str | None) -> ToolResult:
    return ToolResult(
        request_id=uuid4(),
        tool_name="process.run_argv",
        status=ToolResultStatus.FAILURE,
        exit_code=None if error_class is not None else 2,
        stdout_digest=_ZERO,
        stderr_digest=_ZERO,
        output_chars=0,
        duration_ms=1,
        error_class=error_class,
    )


def _denial(code: ActionDenialCode) -> ActionDenial:
    return ActionDenial(
        proposal_id=uuid4(),
        task_id=uuid4(),
        trace_id=uuid4(),
        stage=ActionDenialStage.POLICY_PREFLIGHT,
        code=code,
        reason="synthetic denial",
        checks=("fixture:FAIL",),
    )


def test_invalid_action_denial_is_non_retryable_replan() -> None:
    failure = FailureClassifier().from_action_denial(
        _denial(ActionDenialCode.INVALID_ARGUMENTS)
    )
    decision = RecoveryPolicy().decide(failure=failure)
    assert failure.category is FailureCategory.INVALID_ACTION
    assert failure.retryable is False
    assert decision.action is RecoveryAction.REPLAN


def test_policy_denial_requires_owner_approval_and_never_retry() -> None:
    failure = FailureClassifier().from_action_denial(
        _denial(ActionDenialCode.POLICY_DENIED)
    )
    decision = RecoveryPolicy().decide(failure=failure)
    assert failure.category is FailureCategory.PERMISSION_OR_SCOPE_DENIED
    assert decision.action is RecoveryAction.REQUEST_APPROVAL
    assert decision.owner_action_required is True


def test_only_allowlisted_error_class_is_transient() -> None:
    classifier = FailureClassifier(transient_error_classes=("TimeoutError",))
    task_id = uuid4()
    trace_id = uuid4()
    transient = classifier.from_tool_result(
        task_id=task_id,
        trace_id=trace_id,
        result=_tool_failure("TimeoutError"),
    )
    unknown = classifier.from_tool_result(
        task_id=task_id,
        trace_id=trace_id,
        result=_tool_failure("ModelSaysTransient"),
    )
    assert transient.category is FailureCategory.TRANSIENT_ENVIRONMENT
    assert transient.retryable is True
    assert unknown.category is FailureCategory.DETERMINISTIC_EXECUTION
    assert unknown.retryable is False


def test_generic_blocked_observation_does_not_invent_permission_cause() -> None:
    failure = FailureClassifier.from_observation(
        task_id=uuid4(),
        observation=Observation(
            trace_id=uuid4(),
            status=ObservationStatus.BLOCKED,
            errors=("blocked without structured denial",),
        ),
    )
    assert failure.category is FailureCategory.UNKNOWN_FAILURE
    assert failure.owner_action_required is False


def test_success_tool_result_cannot_be_classified_as_failure() -> None:
    result = ToolResult(
        request_id=uuid4(),
        tool_name="core.echo",
        status=ToolResultStatus.SUCCESS,
        stdout_digest=_ZERO,
        stderr_digest=_ZERO,
        output_chars=0,
        duration_ms=0,
    )
    with pytest.raises(ValueError, match="successful"):
        FailureClassifier().from_tool_result(
            task_id=uuid4(),
            trace_id=uuid4(),
            result=result,
        )


def test_transient_failure_retries_only_with_changed_basis() -> None:
    failure = FailureClassifier().from_tool_result(
        task_id=uuid4(),
        trace_id=uuid4(),
        result=_tool_failure("TimeoutError"),
    )
    blocked = RecoveryPolicy().decide(failure=failure)
    assert blocked.action is RecoveryAction.REPLAN

    allowed = RecoveryPolicy().decide(
        failure=failure,
        retry_decision=RetryDecision(
            allowed=True,
            reason=RetryReason.CHANGED_BASIS,
            matching_attempt_id=uuid4(),
            changed_dimensions=("evidence",),
        ),
    )
    assert allowed.action is RecoveryAction.RETRY
    assert allowed.changed_dimensions == ("evidence",)


def test_fresh_action_does_not_count_as_retry_authority() -> None:
    failure = FailureClassifier().from_tool_result(
        task_id=uuid4(),
        trace_id=uuid4(),
        result=_tool_failure("TimeoutError"),
    )
    decision = RecoveryPolicy().decide(
        failure=failure,
        retry_decision=RetryDecision(
            allowed=True,
            reason=RetryReason.FRESH_ACTION,
        ),
    )
    assert decision.action is RecoveryAction.REPLAN


def test_stale_state_requires_reinspection() -> None:
    failure = FailureClassifier.stale_state(
        task_id=uuid4(),
        trace_id=uuid4(),
        reason="workspace digest changed",
    )
    assert RecoveryPolicy().decide(failure=failure).action is RecoveryAction.REINSPECT


def test_verification_failure_rolls_back_active_mutation() -> None:
    failure = FailureClassifier.verification_failure(
        task_id=uuid4(),
        trace_id=uuid4(),
        reason="post-change verifier failed",
    )
    decision = RecoveryPolicy().decide(failure=failure, mutation_active=True)
    assert decision.action is RecoveryAction.ROLLBACK
    assert decision.rollback_required is True


def test_integrity_failure_stops_without_retry() -> None:
    failure = FailureClassifier.integrity_failure(
        task_id=uuid4(),
        trace_id=uuid4(),
        reason="audit hash chain failed",
    )
    decision = RecoveryPolicy().decide(failure=failure)
    assert decision.action is RecoveryAction.STOP
    assert failure.retryable is False


def test_budget_exhaustion_cannot_self_extend() -> None:
    failure = FailureClassifier.budget_exhausted(
        task_id=uuid4(),
        trace_id=uuid4(),
        reason="tool call budget exhausted",
    )
    assert RecoveryPolicy().decide(failure=failure).action is RecoveryAction.STOP


def test_resource_unavailable_suspends_instead_of_retrying() -> None:
    failure = FailureClassifier.resource_unavailable(
        task_id=uuid4(),
        trace_id=uuid4(),
        reason="required local service unavailable",
    )
    assert RecoveryPolicy().decide(failure=failure).action is RecoveryAction.SUSPEND


def test_change_estimate_rejects_path_traversal() -> None:
    with pytest.raises(ValidationError, match="relative"):
        ChangeEstimate(touched_paths=("../escape.py",), added_lines=1)


def test_minimal_change_allows_bounded_declared_change() -> None:
    task = _task()
    estimate = ChangeEstimate(
        touched_paths=("src/luna/recovery/policy.py", "tests/test_recovery.py"),
        added_lines=30,
        deleted_lines=5,
    )
    decision = MinimalChangePolicy().evaluate_declared(
        estimate=estimate,
        scope=task.scope,
        budget=RuntimeBudget.controlled_write(
            max_changed_files=3,
            max_added_lines=100,
            max_deleted_lines=50,
        ),
    )
    assert decision.allowed is True


def test_minimal_change_blocks_outside_scope() -> None:
    task = _task()
    decision = MinimalChangePolicy().evaluate_declared(
        estimate=ChangeEstimate(touched_paths=("README.md",), added_lines=1),
        scope=task.scope,
        budget=RuntimeBudget.controlled_write(),
    )
    assert decision.allowed is False
    assert decision.denial_code is MinimalChangeDenialCode.OUTSIDE_ALLOWED_PATHS


def test_minimal_change_blocks_protected_path() -> None:
    task = _task()
    decision = MinimalChangePolicy().evaluate_declared(
        estimate=ChangeEstimate(
            touched_paths=("src/luna/governance.py",),
            added_lines=1,
        ),
        scope=task.scope,
        budget=RuntimeBudget.controlled_write(),
    )
    assert decision.denial_code is MinimalChangeDenialCode.PROTECTED_PATH


def test_minimal_change_blocks_file_and_line_budget_growth() -> None:
    task = _task()
    file_denial = MinimalChangePolicy().evaluate_declared(
        estimate=ChangeEstimate(
            touched_paths=("src/a.py", "src/b.py"),
            added_lines=2,
        ),
        scope=task.scope,
        budget=RuntimeBudget.controlled_write(
            max_changed_files=1,
            max_added_lines=10,
            max_deleted_lines=10,
        ),
    )
    assert file_denial.denial_code is MinimalChangeDenialCode.FILE_BUDGET_EXCEEDED

    line_denial = MinimalChangePolicy().evaluate_declared(
        estimate=ChangeEstimate(touched_paths=("src/a.py",), added_lines=11),
        scope=task.scope,
        budget=RuntimeBudget.controlled_write(
            max_changed_files=1,
            max_added_lines=10,
            max_deleted_lines=10,
        ),
    )
    assert line_denial.denial_code is MinimalChangeDenialCode.ADDED_LINE_BUDGET_EXCEEDED


def test_minimal_change_rejects_no_effect_mutation() -> None:
    task = _task()
    decision = MinimalChangePolicy().evaluate_declared(
        estimate=ChangeEstimate(touched_paths=("src/a.py",)),
        scope=task.scope,
        budget=RuntimeBudget.controlled_write(),
    )
    assert decision.denial_code is MinimalChangeDenialCode.NO_EFFECT


def test_observed_change_cannot_expand_approved_scope() -> None:
    task = _task()
    policy = MinimalChangePolicy()
    approved = ChangeEstimate(touched_paths=("src/a.py",), added_lines=20)
    observed = ChangeEstimate(
        touched_paths=("src/a.py", "tests/extra.py"),
        added_lines=20,
    )
    decision = policy.evaluate_observed(
        approved=approved,
        observed=observed,
        scope=task.scope,
        budget=RuntimeBudget.controlled_write(
            max_changed_files=4,
            max_added_lines=100,
            max_deleted_lines=100,
        ),
    )
    assert decision.denial_code is MinimalChangeDenialCode.UNDECLARED_SCOPE_GROWTH


def test_observed_change_cannot_exceed_approved_line_estimate() -> None:
    task = _task()
    decision = MinimalChangePolicy().evaluate_observed(
        approved=ChangeEstimate(touched_paths=("src/a.py",), added_lines=10),
        observed=ChangeEstimate(touched_paths=("src/a.py",), added_lines=11),
        scope=task.scope,
        budget=RuntimeBudget.controlled_write(
            max_changed_files=2,
            max_added_lines=100,
            max_deleted_lines=100,
        ),
    )
    assert decision.denial_code is MinimalChangeDenialCode.UNDECLARED_LINE_GROWTH


def test_low_and_medium_risk_use_snapshot_isolation() -> None:
    policy = WorkspaceIsolationPolicy()
    change = ChangeEstimate(touched_paths=("src/a.py",), added_lines=1)
    for risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
        decision = policy.plan(
            task_contract=_task(risk=risk),
            change=change,
            worktree_available=False,
        )
        assert decision.allowed is True
        assert decision.mode is IsolationMode.SNAPSHOT
        assert decision.snapshot_required is True


def test_high_risk_requires_worktree_without_silent_downgrade() -> None:
    policy = WorkspaceIsolationPolicy()
    change = ChangeEstimate(touched_paths=("src/a.py",), added_lines=1)
    blocked = policy.plan(
        task_contract=_task(risk=RiskLevel.HIGH),
        change=change,
        worktree_available=False,
    )
    assert blocked.allowed is False
    assert blocked.mode is IsolationMode.WORKTREE
    assert blocked.worktree_required is True

    allowed = policy.plan(
        task_contract=_task(risk=RiskLevel.HIGH),
        change=change,
        worktree_available=True,
    )
    assert allowed.allowed is True
    assert allowed.mode is IsolationMode.WORKTREE
    assert allowed.clean_workspace_required is True


def test_read_only_operation_needs_no_workspace_isolation() -> None:
    decision = WorkspaceIsolationPolicy().plan(
        task_contract=_task(write_allowed=False),
        change=None,
        worktree_available=False,
    )
    assert decision.allowed is True
    assert decision.mode is IsolationMode.NONE
