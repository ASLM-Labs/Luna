from __future__ import annotations

from luna.context import ContextBudget, ContextCandidate, ContextSource, ContextSourceKind
from luna.contracts import RiskLevel, TaskScope
from luna.planning import AdaptivePlanner, TaskComplexity
from luna.preparation import TaskPreparer


def _preparation(
    request: str,
    *,
    write_allowed: bool = False,
    risk: RiskLevel = RiskLevel.LOW,
):
    allowed_paths = ("README.md",) if "README.md" in request else ()
    return TaskPreparer().prepare(
        request=request,
        scope=TaskScope(
            workspace_root="C:/workspace",
            allowed_paths=allowed_paths,
            write_allowed=write_allowed,
        ),
        context_candidates=[
            ContextCandidate(
                source=ContextSource.from_text(
                    kind=ContextSourceKind.USER_MESSAGE,
                    locator="user:request",
                    text=request,
                    verified=True,
                ),
                required=True,
                priority=100,
            )
        ],
        context_budget=ContextBudget(),
        required_conditions=("İstek kapsam içinde karşılanmalı",),
        evidence_required=("Yapısal doğrulama",),
        risk_level=risk,
    )


def test_simple_task_does_not_create_a_long_plan() -> None:
    preparation = _preparation("README.md dosyasını incele")
    planner = AdaptivePlanner()

    first = planner.plan(preparation)
    second = planner.plan(preparation)

    assert first.complexity is TaskComplexity.SIMPLE
    assert len(first.steps) == 1
    assert first.semantic_outline() == second.semantic_outline()


def test_write_plan_records_expectation_before_change() -> None:
    plan = AdaptivePlanner().plan(
        _preparation("README.md dosyasını düzelt", write_allowed=True)
    )

    assert plan.complexity is TaskComplexity.STANDARD
    assert len(plan.steps) == 3
    assert len(plan.significant_step_ids) == 1
    significant = next(
        step for step in plan.steps if step.step_id in plan.significant_step_ids
    )
    assert significant.expectation is not None
    assert significant.expectation.high_impact


def test_high_risk_plan_is_complex_but_remains_short() -> None:
    plan = AdaptivePlanner().plan(
        _preparation(
            "README.md dosyasını düzelt",
            write_allowed=True,
            risk=RiskLevel.HIGH,
        )
    )

    assert plan.complexity is TaskComplexity.COMPLEX
    assert len(plan.steps) == 4
    assert len(plan.steps) <= 5
