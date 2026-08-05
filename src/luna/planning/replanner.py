"""Observation-driven replanning with failed-assumption tracking."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from luna.contracts.base import utc_now
from luna.contracts.enums import ObservationStatus, PlanStepStatus
from luna.contracts.observation import Observation
from luna.contracts.plan import ExpectedObservation, PlanStep
from luna.planning.expectation import ExpectationEvaluator
from luna.planning.lifecycle import PlanLifecycle
from luna.planning.models import (
    AttemptBasis,
    AttemptRecord,
    FailedAssumption,
    PlanStatus,
    ReplanAction,
    ReplanOutcome,
    TaskPlan,
)
from luna.planning.retry import RetryGuard


class AdaptiveReplanner:
    """Reconcile observations and revise a plan only with a changed basis."""

    def __init__(
        self,
        *,
        evaluator: ExpectationEvaluator | None = None,
        lifecycle: PlanLifecycle | None = None,
        retry_guard: RetryGuard | None = None,
    ) -> None:
        self._evaluator = evaluator or ExpectationEvaluator()
        self._lifecycle = lifecycle or PlanLifecycle()
        self._retry_guard = retry_guard or RetryGuard()

    @staticmethod
    def _find_active_step(plan: TaskPlan, step_id: UUID) -> PlanStep:
        step = next((item for item in plan.steps if item.step_id == step_id), None)
        if step is None:
            raise ValueError("plan step does not exist")
        if step.status is not PlanStepStatus.ACTIVE:
            raise ValueError("replanning requires the active step")
        if step.expectation is None:
            raise ValueError("replanning requires a recorded expectation")
        return step

    @staticmethod
    def _failed_assumption(
        step: PlanStep,
        observation: Observation,
        mismatches: tuple[str, ...],
    ) -> FailedAssumption:
        expectation = step.expectation
        if expectation is None:
            raise ValueError("step expectation is required")
        return FailedAssumption(
            statement=(
                f"Expectation failed for step {step.sequence}: {expectation.summary}; "
                + "; ".join(mismatches)
            ),
            step_id=step.step_id,
            observation_id=observation.observation_id,
        )

    @staticmethod
    def _default_recovery_basis(
        previous: AttemptBasis,
        observation: Observation,
    ) -> AttemptBasis:
        return AttemptBasis(
            action_key=f"diagnose:{previous.action_key}",
            context_fingerprint=previous.context_fingerprint,
            evidence_refs=tuple(
                dict.fromkeys(
                    (*previous.evidence_refs, str(observation.observation_id))
                )
            ),
            assumption_revision=previous.assumption_revision + 1,
            execution_strategy="diagnose_expectation_mismatch",
            verification_strategy=previous.verification_strategy,
            scope_fingerprint=previous.scope_fingerprint,
        )

    @staticmethod
    def _blocked_plan(
        plan: TaskPlan,
        step: PlanStep,
        failed_assumption: FailedAssumption,
        reason: str,
    ) -> TaskPlan:
        steps = tuple(
            PlanStep(
                step_id=item.step_id,
                sequence=item.sequence,
                description=item.description,
                status=(
                    PlanStepStatus.BLOCKED
                    if item.step_id == step.step_id
                    else item.status
                ),
                expectation=item.expectation,
                depends_on=item.depends_on,
                status_reason=reason if item.step_id == step.step_id else item.status_reason,
            )
            for item in plan.steps
        )
        return TaskPlan(
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            version=plan.version,
            objective=plan.objective,
            complexity=plan.complexity,
            steps=steps,
            significant_step_ids=plan.significant_step_ids,
            assumptions=plan.assumptions,
            failed_assumptions=(*plan.failed_assumptions, failed_assumption),
            status=PlanStatus.BLOCKED,
            supersedes_plan_id=plan.supersedes_plan_id,
            replan_reason=plan.replan_reason,
            created_at=plan.created_at,
            updated_at=utc_now(),
        )

    @staticmethod
    def _replanned_plan(
        plan: TaskPlan,
        step: PlanStep,
        failed_assumption: FailedAssumption,
        candidate_basis: AttemptBasis,
        reason: str,
        recovery_description: str | None,
    ) -> TaskPlan:
        same_action_retry = not candidate_basis.action_key.startswith("diagnose:")
        recovery_expectation = (
            step.expectation
            if same_action_retry
            else ExpectedObservation(
                summary="Recovery diagnosis should produce a new evidence basis.",
                expected_status=ObservationStatus.SUCCESS,
                failure_signals=("no_new_evidence",),
                verification_method=(
                    "Compare observation references and the retry-basis fingerprint."
                ),
                high_impact=False,
            )
        )
        description = recovery_description or (
            "Diagnose the expectation mismatch using the new observation before "
            "choosing another action."
        )
        recovery_step = PlanStep(
            sequence=step.sequence + 1,
            description=description,
            expectation=recovery_expectation,
            depends_on=step.depends_on,
        )

        new_steps: list[PlanStep] = []
        for item in plan.steps:
            if item.step_id == step.step_id:
                new_steps.append(
                    PlanStep(
                        step_id=item.step_id,
                        sequence=item.sequence,
                        description=item.description,
                        status=PlanStepStatus.FAILED,
                        expectation=item.expectation,
                        depends_on=item.depends_on,
                        status_reason=reason,
                    )
                )
                new_steps.append(recovery_step)
                continue

            sequence = item.sequence + 1 if item.sequence > step.sequence else item.sequence
            dependencies = tuple(
                recovery_step.step_id if value == step.step_id else value
                for value in item.depends_on
            )
            new_steps.append(
                PlanStep(
                    step_id=item.step_id,
                    sequence=sequence,
                    description=item.description,
                    status=item.status,
                    expectation=item.expectation,
                    depends_on=dependencies,
                    status_reason=item.status_reason,
                )
            )

        significant_ids = list(plan.significant_step_ids)
        if recovery_expectation.high_impact:
            significant_ids.append(recovery_step.step_id)

        return TaskPlan(
            task_id=plan.task_id,
            version=plan.version + 1,
            objective=plan.objective,
            complexity=plan.complexity,
            steps=tuple(new_steps),
            significant_step_ids=tuple(dict.fromkeys(significant_ids)),
            assumptions=plan.assumptions,
            failed_assumptions=(*plan.failed_assumptions, failed_assumption),
            status=PlanStatus.READY,
            supersedes_plan_id=plan.plan_id,
            replan_reason=reason,
        )

    def reconcile(
        self,
        *,
        plan: TaskPlan,
        step_id: UUID,
        observation: Observation,
        attempt_basis: AttemptBasis,
        history: Iterable[AttemptRecord] = (),
        proposed_basis: AttemptBasis | None = None,
        recovery_description: str | None = None,
    ) -> ReplanOutcome:
        step = self._find_active_step(plan, step_id)
        expectation = step.expectation
        if expectation is None:
            raise ValueError("step expectation is required")
        assessment = self._evaluator.assess(expectation, observation)

        if assessment.matched:
            completed = self._lifecycle.complete(plan, step_id)
            return ReplanOutcome(
                action=ReplanAction.CONTINUE,
                plan=completed,
                assessment=assessment,
                reason="observation matched the recorded expectation",
            )

        failed_assumption = self._failed_assumption(
            step,
            observation,
            assessment.mismatches,
        )
        current_attempt = AttemptRecord(
            task_id=plan.task_id,
            step_id=step.step_id,
            basis=attempt_basis,
            observation_id=observation.observation_id,
            outcome=observation.status,
        )
        history_with_current = (*tuple(history), current_attempt)
        candidate = proposed_basis or self._default_recovery_basis(
            attempt_basis,
            observation,
        )
        retry_decision = self._retry_guard.evaluate(
            candidate,
            history_with_current,
        )
        reason = "expectation mismatch: " + "; ".join(assessment.mismatches)

        if not retry_decision.allowed:
            blocked = self._blocked_plan(
                plan,
                step,
                failed_assumption,
                reason,
            )
            return ReplanOutcome(
                action=ReplanAction.BLOCK,
                plan=blocked,
                assessment=assessment,
                reason=reason,
                retry_decision=retry_decision,
                failed_assumption=failed_assumption,
            )

        replanned = self._replanned_plan(
            plan,
            step,
            failed_assumption,
            candidate,
            reason,
            recovery_description,
        )
        return ReplanOutcome(
            action=ReplanAction.REPLAN,
            plan=replanned,
            assessment=assessment,
            reason=reason,
            retry_decision=retry_decision,
            failed_assumption=failed_assumption,
        )
