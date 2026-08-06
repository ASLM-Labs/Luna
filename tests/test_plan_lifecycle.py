from __future__ import annotations

import pytest

from luna.contracts.enums import PlanStepStatus
from luna.contracts.plan import PlanStep
from luna.planning import PlanLifecycle, PlanStatus, TaskComplexity, TaskPlan


def _plan() -> TaskPlan:
    first = PlanStep(sequence=1, description="Birinci adım")
    second = PlanStep(
        sequence=2,
        description="İkinci adım",
        depends_on=(first.step_id,),
    )
    return TaskPlan(
        task_id=__import__("uuid").uuid4(),
        objective="Test planı",
        complexity=TaskComplexity.SIMPLE,
        steps=(first, second),
    )


def test_out_of_order_activation_is_rejected() -> None:
    plan = _plan()
    with pytest.raises(ValueError, match=r"dependencies|earlier"):
        PlanLifecycle().activate(plan, plan.steps[1].step_id)


def test_step_lifecycle_reaches_complete() -> None:
    lifecycle = PlanLifecycle()
    plan = _plan()

    active_first = lifecycle.activate(plan, plan.steps[0].step_id)
    assert active_first.status is PlanStatus.ACTIVE
    assert active_first.steps[0].status is PlanStepStatus.ACTIVE

    after_first = lifecycle.complete(active_first, plan.steps[0].step_id)
    active_second = lifecycle.activate(after_first, plan.steps[1].step_id)
    complete = lifecycle.complete(active_second, plan.steps[1].step_id)

    assert complete.status is PlanStatus.COMPLETE
    assert all(step.status is PlanStepStatus.COMPLETE for step in complete.steps)
