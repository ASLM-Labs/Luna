from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

from luna.contracts.enums import ObservationStatus, PlanStepStatus
from luna.contracts.observation import Observation
from luna.contracts.plan import ExpectedObservation, PlanStep
from luna.planning import (
    AdaptiveReplanner,
    AttemptBasis,
    PlanLifecycle,
    ReplanAction,
    RetryReason,
    TaskComplexity,
    TaskPlan,
)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _active_plan() -> TaskPlan:
    expectation = ExpectedObservation(
        summary="Komut başarıyla tamamlanmalı",
        expected_status=ObservationStatus.SUCCESS,
        expected_exit_codes=(0,),
        failure_signals=("test_failure",),
        verification_method="exit code ve test özeti",
        high_impact=True,
    )
    step = PlanStep(
        sequence=1,
        description="Önemli eylemi uygula",
        expectation=expectation,
    )
    plan = TaskPlan(
        task_id=uuid4(),
        objective="Replan testi",
        complexity=TaskComplexity.STANDARD,
        steps=(step,),
        significant_step_ids=(step.step_id,),
    )
    return PlanLifecycle().activate(plan, step.step_id)


def _basis() -> AttemptBasis:
    return AttemptBasis(
        action_key="execute:verification",
        context_fingerprint=_digest("context"),
        execution_strategy="run_once",
        verification_strategy="exit_code",
        scope_fingerprint=_digest("scope"),
    )


def test_matching_observation_completes_without_replan() -> None:
    plan = _active_plan()
    observation = Observation(
        trace_id=uuid4(),
        status=ObservationStatus.SUCCESS,
        exit_code=0,
    )

    outcome = AdaptiveReplanner().reconcile(
        plan=plan,
        step_id=plan.steps[0].step_id,
        observation=observation,
        attempt_basis=_basis(),
    )

    assert outcome.action is ReplanAction.CONTINUE
    assert outcome.plan.steps[0].status is PlanStepStatus.COMPLETE


def test_mismatch_records_failed_assumption_and_changes_plan() -> None:
    plan = _active_plan()
    observation = Observation(
        trace_id=uuid4(),
        status=ObservationStatus.FAILURE,
        exit_code=1,
        errors=("test_failure",),
    )

    outcome = AdaptiveReplanner().reconcile(
        plan=plan,
        step_id=plan.steps[0].step_id,
        observation=observation,
        attempt_basis=_basis(),
    )

    assert outcome.action is ReplanAction.REPLAN
    assert outcome.plan.version == 2
    assert outcome.plan.supersedes_plan_id == plan.plan_id
    assert len(outcome.plan.failed_assumptions) == 1
    assert outcome.plan.steps[0].status is PlanStepStatus.FAILED
    assert outcome.plan.steps[1].status is PlanStepStatus.PENDING
    assert outcome.retry_decision is not None
    assert outcome.retry_decision.allowed


def test_explicit_same_basis_retry_is_blocked() -> None:
    plan = _active_plan()
    observation = Observation(
        trace_id=uuid4(),
        status=ObservationStatus.FAILURE,
        exit_code=1,
        errors=("test_failure",),
    )
    basis = _basis()

    outcome = AdaptiveReplanner().reconcile(
        plan=plan,
        step_id=plan.steps[0].step_id,
        observation=observation,
        attempt_basis=basis,
        proposed_basis=basis,
    )

    assert outcome.action is ReplanAction.BLOCK
    assert outcome.retry_decision is not None
    assert outcome.retry_decision.reason is RetryReason.BLIND_RETRY_BLOCKED
    assert outcome.plan.steps[0].status is PlanStepStatus.BLOCKED
