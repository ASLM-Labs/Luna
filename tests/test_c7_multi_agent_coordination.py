from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.contracts.plan import PlanStep
from luna.contracts.task import TaskContract, TaskScope
from luna.planning.coordination import (
    CoordinationMode,
    CoordinationPlan,
    GeneralCoordinationPlanner,
    WorkerAssignment,
    WorkerRole,
)

_C6_BASIS = "a" * 64


def _contract(*, write_allowed: bool = True) -> TaskContract:
    return TaskContract(
        objective="Implement bounded C7 coordination.",
        required_conditions=("coordination remains bounded",),
        evidence_required=("tests pass",),
        scope=TaskScope(
            workspace_root=".",
            allowed_paths=("src/luna", "tests"),
            write_allowed=write_allowed,
        ),
    )


def _steps() -> tuple[PlanStep, PlanStep, PlanStep]:
    first = PlanStep(
        sequence=1,
        description="Inspect coordination contracts.",
    )
    second = PlanStep(
        sequence=2,
        description="Implement coordination model.",
    )
    third = PlanStep(
        sequence=3,
        description="Verify coordination behavior.",
    )
    return first, second, third


def test_c7_defaults_to_solo_without_independent_work() -> None:
    contract = _contract()
    steps = _steps()

    plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=7,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        worker_capacity=4,
    )

    assert plan.mode is CoordinationMode.SOLO
    assert plan.assignments == ()
    assert "solo_default_preserved" in plan.reason_codes
    assert plan.runtime_authority is False
    assert plan.execution_authority is False
    assert plan.completion_authority is False


def test_c7_worker_capacity_one_preserves_solo() -> None:
    contract = _contract()
    steps = _steps()

    plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=7,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=1,
    )

    assert plan.mode is CoordinationMode.SOLO
    assert plan.assignments == ()
    assert "worker_capacity_insufficient_for_parallel_workers" in plan.reason_codes


def test_c7_selects_parallel_workers_for_independent_steps() -> None:
    contract = _contract()
    steps = _steps()

    plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=8,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        acceptance_target_refs=("acceptance:one",),
        allowed_path_refs=("src/luna",),
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=2,
    )

    assert plan.mode is CoordinationMode.PARALLEL_WORKERS
    assert len(plan.assignments) == 2
    assert tuple(item.role for item in plan.assignments) == (
        WorkerRole.PARALLEL,
        WorkerRole.PARALLEL,
    )
    assert tuple(item.source_step_ids for item in plan.assignments) == (
        (steps[0].step_id,),
        (steps[1].step_id,),
    )
    assert all(item.allowed_path_refs == ("src/luna",) for item in plan.assignments)
    assert all(item.runtime_authority is False for item in plan.assignments)
    assert all(item.execution_authority is False for item in plan.assignments)
    assert all(item.completion_authority is False for item in plan.assignments)


def test_c7_parallel_selection_respects_worker_capacity() -> None:
    contract = _contract()
    steps = _steps()

    plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=8,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        parallelizable_step_ids=tuple(step.step_id for step in steps),
        worker_capacity=2,
    )

    assert plan.mode is CoordinationMode.PARALLEL_WORKERS
    assert len(plan.assignments) == 2
    assert tuple(
        item.source_step_ids[0] for item in plan.assignments
    ) == (
        steps[0].step_id,
        steps[1].step_id,
    )


def test_c7_independent_review_precedes_parallel_selection() -> None:
    contract = _contract()
    steps = _steps()

    plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=9,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        independent_review_required=True,
        independent_review_step_id=steps[2].step_id,
        worker_capacity=3,
    )

    assert plan.mode is CoordinationMode.INDEPENDENT_REVIEW
    assert len(plan.assignments) == 1
    reviewer = plan.assignments[0]
    assert reviewer.role is WorkerRole.INDEPENDENT_REVIEWER
    assert reviewer.source_step_ids == (steps[2].step_id,)
    assert reviewer.objective == steps[2].description
    assert (
        "main_conclusion_not_required_by_reviewer_assignment"
        in plan.reason_codes
    )


def test_c7_independent_review_requires_extra_capacity() -> None:
    contract = _contract()
    steps = _steps()

    plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=9,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        independent_review_required=True,
        independent_review_step_id=steps[2].step_id,
        worker_capacity=1,
    )

    assert plan.mode is CoordinationMode.SOLO
    assert plan.assignments == ()
    assert (
        "worker_capacity_insufficient_for_independent_review"
        in plan.reason_codes
    )


def test_c7_rejects_worker_path_scope_widening() -> None:
    contract = _contract()
    steps = _steps()

    with pytest.raises(
        ValueError,
        match="C7 worker path bounds must remain within TaskContract scope",
    ):
        GeneralCoordinationPlanner().plan(
            task_contract=contract,
            source_task_revision=1,
            steps=steps,
            capability_selection_basis_fingerprint=_C6_BASIS,
            allowed_path_refs=("outside/task/scope",),
        )


def test_c7_rejects_parallel_steps_that_depend_on_one_another() -> None:
    contract = _contract()
    first = PlanStep(
        sequence=1,
        description="First step.",
    )
    second = PlanStep(
        sequence=2,
        description="Second step.",
        depends_on=(first.step_id,),
    )

    with pytest.raises(
        ValueError,
        match="parallelizable steps cannot depend on one another",
    ):
        GeneralCoordinationPlanner().plan(
            task_contract=contract,
            source_task_revision=2,
            steps=(first, second),
            capability_selection_basis_fingerprint=_C6_BASIS,
            parallelizable_step_ids=(first.step_id, second.step_id),
            worker_capacity=2,
        )


def test_c7_assignment_semantic_basis_is_revision_independent() -> None:
    contract = _contract()
    steps = _steps()
    planner = GeneralCoordinationPlanner()

    first = planner.plan(
        task_contract=contract,
        source_task_revision=20,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=2,
    )
    second = planner.plan(
        task_contract=contract,
        source_task_revision=21,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=2,
    )

    assert first.source_task_revision == 20
    assert second.source_task_revision == 21
    assert tuple(
        item.assignment_basis_fingerprint for item in first.assignments
    ) == tuple(
        item.assignment_basis_fingerprint for item in second.assignments
    )
    assert tuple(item.assignment_id for item in first.assignments) == tuple(
        item.assignment_id for item in second.assignments
    )


def test_c7_assignment_basis_changes_when_semantic_input_changes() -> None:
    contract = _contract()
    steps = _steps()
    planner = GeneralCoordinationPlanner()

    first = planner.plan(
        task_contract=contract,
        source_task_revision=20,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        acceptance_target_refs=("acceptance:old",),
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=2,
    )
    second = planner.plan(
        task_contract=contract,
        source_task_revision=20,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        acceptance_target_refs=("acceptance:new",),
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=2,
    )

    assert first.assignments[0].assignment_basis_fingerprint != (
        second.assignments[0].assignment_basis_fingerprint
    )


def test_c7_plan_is_deterministic_for_same_inputs() -> None:
    contract = _contract()
    steps = _steps()
    planner = GeneralCoordinationPlanner()

    kwargs = dict(
        task_contract=contract,
        source_task_revision=12,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        acceptance_target_refs=("acceptance:one",),
        allowed_path_refs=("tests",),
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=2,
    )

    first = planner.plan(**kwargs)
    second = planner.plan(**kwargs)

    assert first == second
    assert first.coordination_basis_fingerprint == (
        second.coordination_basis_fingerprint
    )


def test_c7_contract_rejects_authority_escalation() -> None:
    contract = _contract()
    steps = _steps()

    plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=3,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
    )

    payload = plan.model_dump(mode="python")
    payload["execution_authority"] = True

    with pytest.raises(ValidationError):
        CoordinationPlan.model_validate(payload)


def test_c7_assignment_id_must_match_basis() -> None:
    with pytest.raises(
        ValidationError,
        match="worker assignment ID must derive from its basis fingerprint",
    ):
        WorkerAssignment(
            assignment_id=f"assignment:sha256:{'b' * 64}",
            task_id=uuid4(),
            role=WorkerRole.PARALLEL,
            objective="Bounded work.",
            source_task_revision=1,
            source_step_ids=(uuid4(),),
            assignment_basis_fingerprint="c" * 64,
            provenance_refs=("test",),
        )


def test_c7_rejects_transitively_dependent_parallel_steps() -> None:
    contract = _contract()

    first = PlanStep(
        sequence=1,
        description="First step.",
    )
    second = PlanStep(
        sequence=2,
        description="Second step.",
        depends_on=(first.step_id,),
    )
    third = PlanStep(
        sequence=3,
        description="Third step.",
        depends_on=(second.step_id,),
    )

    with pytest.raises(
        ValueError,
        match="parallelizable steps cannot depend on one another",
    ):
        GeneralCoordinationPlanner().plan(
            task_contract=contract,
            source_task_revision=2,
            steps=(first, second, third),
            capability_selection_basis_fingerprint=_C6_BASIS,
            parallelizable_step_ids=(first.step_id, third.step_id),
            worker_capacity=2,
        )


def test_c7_parallel_assignment_order_follows_plan_sequence() -> None:
    contract = _contract()
    steps = _steps()

    plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=4,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        parallelizable_step_ids=(steps[1].step_id, steps[0].step_id),
        worker_capacity=2,
    )

    assert plan.mode is CoordinationMode.PARALLEL_WORKERS
    assert tuple(item.source_step_ids[0] for item in plan.assignments) == (
        steps[0].step_id,
        steps[1].step_id,
    )


def test_c7_patch1_plan_rejects_assignment_dependencies() -> None:
    contract = _contract()
    steps = _steps()

    plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=5,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=2,
    )

    payload = plan.model_dump(mode="python")
    payload["assignments"][1]["depends_on"] = (
        plan.assignments[0].assignment_id,
    )

    with pytest.raises(
        ValidationError,
        match="C7 Patch1 worker assignments must remain dependency-free",
    ):
        CoordinationPlan.model_validate(payload)

def test_c7_coordination_plan_rejects_duplicate_assignment_identity() -> None:
    contract = _contract()
    steps = _steps()

    valid_plan = GeneralCoordinationPlanner().plan(
        task_contract=contract,
        source_task_revision=11,
        steps=steps,
        capability_selection_basis_fingerprint=_C6_BASIS,
        parallelizable_step_ids=(steps[0].step_id, steps[1].step_id),
        worker_capacity=2,
    )

    duplicate = valid_plan.assignments[0]

    with pytest.raises(ValidationError):
        CoordinationPlan(
            task_id=valid_plan.task_id,
            source_task_revision=valid_plan.source_task_revision,
            capability_selection_basis_fingerprint=(
                valid_plan.capability_selection_basis_fingerprint
            ),
            mode=CoordinationMode.PARALLEL_WORKERS,
            assignments=(duplicate, duplicate),
            coordination_basis_fingerprint=valid_plan.coordination_basis_fingerprint,
            reason_codes=valid_plan.reason_codes,
            provenance_refs=valid_plan.provenance_refs,
        )
