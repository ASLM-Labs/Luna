"""Validated plan-step state transitions."""

from __future__ import annotations

from uuid import UUID

from luna.contracts.base import stable_payload, utc_now
from luna.contracts.enums import PlanStepStatus
from luna.contracts.plan import PlanStep
from luna.planning.models import PlanStatus, TaskPlan


class PlanLifecycle:
    """Apply immutable, validated transitions to task plans."""

    @staticmethod
    def _replace_step(
        plan: TaskPlan,
        *,
        step_id: UUID,
        status: PlanStepStatus,
        reason: str | None = None,
        plan_status: PlanStatus,
    ) -> TaskPlan:
        steps: list[PlanStep] = []
        found = False
        for step in plan.steps:
            if step.step_id != step_id:
                steps.append(step)
                continue
            found = True
            steps.append(
                PlanStep(
                    step_id=step.step_id,
                    sequence=step.sequence,
                    description=step.description,
                    status=status,
                    expectation=step.expectation,
                    depends_on=step.depends_on,
                    status_reason=reason,
                )
            )
        if not found:
            raise ValueError("plan step does not exist")
        payload = stable_payload(plan)
        payload.update(
            {
                "steps": [stable_payload(step) for step in steps],
                "status": plan_status,
                "updated_at": utc_now(),
            }
        )
        return TaskPlan.model_validate(payload)

    def activate(self, plan: TaskPlan, step_id: UUID) -> TaskPlan:
        if plan.status not in {PlanStatus.READY}:
            raise ValueError("only a READY plan can activate a step")
        candidate = next((step for step in plan.steps if step.step_id == step_id), None)
        if candidate is None:
            raise ValueError("plan step does not exist")
        if candidate.status is not PlanStepStatus.PENDING:
            raise ValueError("only a pending step can be activated")

        completed_ids = {
            step.step_id
            for step in plan.steps
            if step.status in {
                PlanStepStatus.COMPLETE,
                PlanStepStatus.SKIPPED_WITH_REASON,
            }
        }
        if not set(candidate.depends_on).issubset(completed_ids):
            raise ValueError("step dependencies are not complete")

        eligible = [
            step
            for step in plan.steps
            if step.status is PlanStepStatus.PENDING
            and set(step.depends_on).issubset(completed_ids)
        ]
        first_eligible = min(eligible, key=lambda step: step.sequence)
        if first_eligible.step_id != candidate.step_id:
            raise ValueError("an earlier eligible plan step must run first")
        return self._replace_step(
            plan,
            step_id=step_id,
            status=PlanStepStatus.ACTIVE,
            plan_status=PlanStatus.ACTIVE,
        )

    def complete(self, plan: TaskPlan, step_id: UUID) -> TaskPlan:
        step = next((item for item in plan.steps if item.step_id == step_id), None)
        if step is None or step.status is not PlanStepStatus.ACTIVE:
            raise ValueError("only the active step can be completed")

        remaining = [
            item
            for item in plan.steps
            if item.step_id != step_id
            and item.status in {
                PlanStepStatus.PENDING,
                PlanStepStatus.ACTIVE,
                PlanStepStatus.BLOCKED,
            }
        ]
        next_status = PlanStatus.READY if remaining else PlanStatus.COMPLETE
        return self._replace_step(
            plan,
            step_id=step_id,
            status=PlanStepStatus.COMPLETE,
            plan_status=next_status,
        )

    def fail(self, plan: TaskPlan, step_id: UUID, *, reason: str) -> TaskPlan:
        step = next((item for item in plan.steps if item.step_id == step_id), None)
        if step is None or step.status is not PlanStepStatus.ACTIVE:
            raise ValueError("only the active step can fail")
        return self._replace_step(
            plan,
            step_id=step_id,
            status=PlanStepStatus.FAILED,
            reason=reason,
            plan_status=PlanStatus.BLOCKED,
        )

    def block(self, plan: TaskPlan, step_id: UUID, *, reason: str) -> TaskPlan:
        step = next((item for item in plan.steps if item.step_id == step_id), None)
        if step is None or step.status not in {
            PlanStepStatus.PENDING,
            PlanStepStatus.ACTIVE,
        }:
            raise ValueError("only a pending or active step can be blocked")
        return self._replace_step(
            plan,
            step_id=step_id,
            status=PlanStepStatus.BLOCKED,
            reason=reason,
            plan_status=PlanStatus.BLOCKED,
        )

    def skip(self, plan: TaskPlan, step_id: UUID, *, reason: str) -> TaskPlan:
        step = next((item for item in plan.steps if item.step_id == step_id), None)
        if step is None or step.status is not PlanStepStatus.PENDING:
            raise ValueError("only a pending step can be skipped")
        remaining = [
            item
            for item in plan.steps
            if item.step_id != step_id
            and item.status in {
                PlanStepStatus.PENDING,
                PlanStepStatus.ACTIVE,
                PlanStepStatus.BLOCKED,
            }
        ]
        next_status = PlanStatus.READY if remaining else PlanStatus.COMPLETE
        return self._replace_step(
            plan,
            step_id=step_id,
            status=PlanStepStatus.SKIPPED_WITH_REASON,
            reason=reason,
            plan_status=next_status,
        )
