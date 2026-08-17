from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from luna.context import ContextBudget, ContextCandidate, ContextSource, ContextSourceKind
from luna.contracts import TaskScope, TaskState
from luna.planning import AcceptanceBackchain, AdaptivePlanner, LocalJudgmentBuilder
from luna.preparation import TaskPreparation, TaskPreparer


def _preparation(
    request: str,
    *,
    task_id: UUID,
    soft_preferences: tuple[str, ...] = (),
):
    return TaskPreparer().prepare(
        request=request,
        scope=TaskScope(workspace_root="C:/workspace"),
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
        required_conditions=("Required behavior is satisfied.",),
        forbidden_outcomes=("Forbidden behavior occurs.",),
        evidence_required=("Deterministic verification result",),
        soft_preferences=soft_preferences,
        task_id=task_id,
    )


def _basis(preparation: TaskPreparation) -> AcceptanceBackchain:
    assert preparation.contract is not None
    specification = preparation.specification_judgment
    return LocalJudgmentBuilder().acceptance_from_basis(
        contract=preparation.contract,
        specification=specification,
    )


def test_c5_same_contract_and_c4_basis_produce_same_acceptance_basis() -> None:
    task_id = uuid4()
    preparation = _preparation("Inspect the current task.", task_id=task_id)

    first = _basis(preparation)
    second = _basis(preparation)

    assert first.acceptance_basis_fingerprint == second.acceptance_basis_fingerprint
    assert tuple(item.target_id for item in first.targets) == tuple(
        item.target_id for item in second.targets
    )


def test_c5_changed_c4_basis_preserves_semantic_targets_but_changes_basis() -> None:
    task_id = uuid4()
    first_preparation = _preparation(
        "Inspect the current task.",
        task_id=task_id,
        soft_preferences=("Prefer concise output.",),
    )
    second_preparation = _preparation(
        "Inspect the current task.",
        task_id=task_id,
        soft_preferences=("Prefer detailed output.",),
    )

    assert first_preparation.contract is not None
    assert second_preparation.contract is not None
    assert (
        first_preparation.specification_judgment.specification_basis_fingerprint
        != second_preparation.specification_judgment.specification_basis_fingerprint
    )

    first = _basis(first_preparation)
    second = _basis(second_preparation)

    assert tuple(item.target_id for item in first.targets) == tuple(
        item.target_id for item in second.targets
    )
    assert first.acceptance_basis_fingerprint != second.acceptance_basis_fingerprint
    assert all("Prefer concise output." not in item.text for item in first.targets)
    assert all("Prefer detailed output." not in item.text for item in second.targets)


def test_c5_basis_bound_targets_expose_provenance_without_authority() -> None:
    preparation = _preparation("Inspect the current task.", task_id=uuid4())
    backchain = _basis(preparation)

    assert backchain.specification_basis_fingerprint is not None
    assert backchain.acceptance_basis_fingerprint is not None
    assert backchain.provenance_refs
    assert all(item.source_refs for item in backchain.targets)
    assert backchain.runtime_authority is False
    assert backchain.execution_authority is False
    assert backchain.completion_authority is False


def test_c5_rejects_specification_from_another_task() -> None:
    first = _preparation("Inspect the current task.", task_id=uuid4())
    second = _preparation("Inspect the current task.", task_id=uuid4())
    assert first.contract is not None

    with pytest.raises(ValueError, match="must match the authoritative task contract"):
        LocalJudgmentBuilder().acceptance_from_basis(
            contract=first.contract,
            specification=second.specification_judgment,
        )


def test_c5_planner_and_task_state_preserve_same_acceptance_binding() -> None:
    preparation = _preparation("Inspect the current task.", task_id=uuid4())
    assert preparation.contract is not None
    backchain = _basis(preparation)
    plan = AdaptivePlanner().plan(preparation)
    target_ids = tuple(item.target_id for item in backchain.targets)

    assert plan.acceptance_target_ids == target_ids
    assert backchain.acceptance_basis_fingerprint is not None

    state = TaskState(
        task_id=preparation.contract.task_id,
        contract=preparation.contract,
        plan=plan.steps,
        specification_judgment=preparation.specification_judgment,
        acceptance_target_ids=target_ids,
        acceptance_basis_fingerprint=backchain.acceptance_basis_fingerprint,
    )

    assert state.acceptance_target_ids == plan.acceptance_target_ids
    assert state.acceptance_basis_fingerprint == backchain.acceptance_basis_fingerprint


def test_c5_task_state_requires_target_and_basis_binding_together() -> None:
    preparation = _preparation("Inspect the current task.", task_id=uuid4())
    assert preparation.contract is not None
    plan = AdaptivePlanner().plan(preparation)

    with pytest.raises(ValueError, match="must be stored together"):
        TaskState(
            task_id=preparation.contract.task_id,
            contract=preparation.contract,
            plan=plan.steps,
            specification_judgment=preparation.specification_judgment,
            acceptance_target_ids=plan.acceptance_target_ids,
        )
def test_c5_revising_c4_basis_clears_stale_acceptance_binding() -> None:
    task_id = uuid4()
    first_preparation = _preparation(
        "Inspect the current task.",
        task_id=task_id,
        soft_preferences=("Prefer concise output.",),
    )
    second_preparation = _preparation(
        "Inspect the current task.",
        task_id=task_id,
        soft_preferences=("Prefer detailed output.",),
    )
    assert first_preparation.contract is not None
    first_backchain = _basis(first_preparation)
    plan = AdaptivePlanner().plan(first_preparation)
    assert first_backchain.acceptance_basis_fingerprint is not None

    state = TaskState(
        task_id=task_id,
        contract=first_preparation.contract,
        plan=plan.steps,
        specification_judgment=first_preparation.specification_judgment,
        acceptance_target_ids=plan.acceptance_target_ids,
        acceptance_basis_fingerprint=first_backchain.acceptance_basis_fingerprint,
    )
    revised = state.revise(
        specification_judgment=second_preparation.specification_judgment,
    )

    assert (
        revised.specification_judgment.specification_basis_fingerprint
        != state.specification_judgment.specification_basis_fingerprint
    )
    assert revised.acceptance_target_ids == ()
    assert revised.acceptance_basis_fingerprint is None


def test_c5_task_state_rejects_partial_acceptance_binding_revision() -> None:
    preparation = _preparation("Inspect the current task.", task_id=uuid4())
    assert preparation.contract is not None
    backchain = _basis(preparation)
    plan = AdaptivePlanner().plan(preparation)
    assert backchain.acceptance_basis_fingerprint is not None

    state = TaskState(
        task_id=preparation.contract.task_id,
        contract=preparation.contract,
        plan=plan.steps,
        specification_judgment=preparation.specification_judgment,
        acceptance_target_ids=plan.acceptance_target_ids,
        acceptance_basis_fingerprint=backchain.acceptance_basis_fingerprint,
    )

    with pytest.raises(ValueError, match="must be revised together"):
        state.revise(acceptance_target_ids=plan.acceptance_target_ids)
