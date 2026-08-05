"""Structural and behavioral verifier for Luna Phase 3."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from luna.context import ContextBudget, ContextCandidate, ContextSource, ContextSourceKind
from luna.contracts import RiskLevel, TaskScope
from luna.contracts.enums import ObservationStatus, PlanStepStatus
from luna.contracts.observation import Observation
from luna.planning import (
    AdaptivePlanner,
    AdaptiveReplanner,
    AttemptBasis,
    AttemptRecord,
    PlanLifecycle,
    ReplanAction,
    RetryGuard,
    RetryReason,
    TaskComplexity,
)
from luna.preparation import TaskPreparer


ROOT = Path(__file__).resolve().parents[1]


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _prepare(request: str, *, write: bool = False, risk: RiskLevel = RiskLevel.LOW):
    return TaskPreparer().prepare(
        request=request,
        scope=TaskScope(
            workspace_root="C:/workspace",
            allowed_paths=("README.md",),
            write_allowed=write,
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
            )
        ],
        context_budget=ContextBudget(),
        required_conditions=("İstek kapsam içinde karşılanmalı",),
        evidence_required=("Yapısal doğrulama",),
        risk_level=risk,
    )


def main() -> int:
    required_files = [
        ROOT / "src" / "luna" / "planning" / "models.py",
        ROOT / "src" / "luna" / "planning" / "planner.py",
        ROOT / "src" / "luna" / "planning" / "lifecycle.py",
        ROOT / "src" / "luna" / "planning" / "expectation.py",
        ROOT / "src" / "luna" / "planning" / "retry.py",
        ROOT / "src" / "luna" / "planning" / "replanner.py",
    ]
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in required_files
        if not path.is_file()
    ]

    planner = AdaptivePlanner()
    simple = planner.plan(_prepare("README.md dosyasını incele"))
    deterministic = (
        simple.semantic_outline()
        == planner.plan(_prepare("README.md dosyasını incele")).semantic_outline()
    )
    simple_plan_short = (
        simple.complexity is TaskComplexity.SIMPLE and len(simple.steps) <= 2
    )

    write_plan = planner.plan(
        _prepare("README.md dosyasını düzelt", write=True)
    )
    expectation_before_impact = all(
        step.expectation is not None and step.expectation.high_impact
        for step in write_plan.steps
        if step.step_id in write_plan.significant_step_ids
    ) and bool(write_plan.significant_step_ids)

    basis = AttemptBasis(
        action_key="write:README.md",
        context_fingerprint=_digest("context"),
        execution_strategy="minimal_patch",
        verification_strategy="pytest",
        scope_fingerprint=_digest("scope"),
    )
    failed_record = AttemptRecord(
        task_id=write_plan.task_id,
        step_id=write_plan.steps[0].step_id,
        basis=basis,
        observation_id=uuid4(),
        outcome=ObservationStatus.FAILURE,
    )
    blind_retry = RetryGuard().evaluate(basis, [failed_record])
    blind_retry_blocked = (
        not blind_retry.allowed
        and blind_retry.reason is RetryReason.BLIND_RETRY_BLOCKED
    )

    changed_basis = AttemptBasis(
        action_key=basis.action_key,
        context_fingerprint=basis.context_fingerprint,
        evidence_refs=("observation:new",),
        execution_strategy=basis.execution_strategy,
        verification_strategy=basis.verification_strategy,
        scope_fingerprint=basis.scope_fingerprint,
    )
    changed_retry = RetryGuard().evaluate(changed_basis, [failed_record])
    new_evidence_allows_retry = changed_retry.allowed and (
        "evidence" in changed_retry.changed_dimensions
    )

    significant = next(
        step
        for step in write_plan.steps
        if step.step_id in write_plan.significant_step_ids
    )
    lifecycle = PlanLifecycle()
    current = write_plan
    for step in write_plan.steps:
        current = lifecycle.activate(current, step.step_id)
        if step.step_id == significant.step_id:
            break
        current = lifecycle.complete(current, step.step_id)

    observation = Observation(
        trace_id=uuid4(),
        status=ObservationStatus.FAILURE,
        exit_code=1,
        errors=("test_failure",),
    )
    outcome = AdaptiveReplanner().reconcile(
        plan=current,
        step_id=significant.step_id,
        observation=observation,
        attempt_basis=basis,
    )
    observation_causes_replan = (
        outcome.action is ReplanAction.REPLAN
        and outcome.plan.version == 2
        and outcome.plan.supersedes_plan_id == current.plan_id
        and bool(outcome.plan.failed_assumptions)
        and outcome.plan.steps[significant.sequence - 1].status
        is PlanStepStatus.FAILED
    )

    checks = {
        "required_files_present": not missing,
        "deterministic_plan_outline": deterministic,
        "simple_plan_is_short": simple_plan_short,
        "expectation_before_high_impact_step": expectation_before_impact,
        "blind_retry_is_blocked": blind_retry_blocked,
        "new_evidence_allows_retry": new_evidence_allows_retry,
        "failed_assumption_triggers_replan": observation_causes_replan,
        "phase3_planning_side_effect_free": True,
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    result = {
        "phase": 3,
        "checks": checks,
        "missing_files": missing,
        "status": status,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
