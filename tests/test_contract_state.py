from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.contracts import (
    CompletionStatus,
    PlanStep,
    TaskContract,
    TaskPhase,
    TaskScope,
    TaskState,
)


def make_contract() -> TaskContract:
    return TaskContract(
        objective="Implement Phase 1 contracts",
        required_conditions=("Contracts validate",),
        forbidden_outcomes=("Runtime capabilities activate",),
        evidence_required=("Tests pass",),
        scope=TaskScope(workspace_root="C:/workspace/luna"),
    )


def test_legal_task_transition_increments_revision() -> None:
    contract = make_contract()
    state = TaskState(task_id=contract.task_id, contract=contract)
    contracted = state.transition_to(TaskPhase.CONTRACTED)

    assert contracted.phase is TaskPhase.CONTRACTED
    assert contracted.revision == 1
    assert state.phase is TaskPhase.CREATED


def test_illegal_task_transition_is_rejected() -> None:
    contract = make_contract()
    state = TaskState(task_id=contract.task_id, contract=contract)

    with pytest.raises(ValueError, match="invalid task transition"):
        state.transition_to(TaskPhase.ACTING)


def test_task_state_rejects_mismatched_contract_id() -> None:
    contract = make_contract()
    with pytest.raises(ValidationError, match="must match"):
        TaskState(task_id=uuid4(), contract=contract)


def test_plan_sequences_must_be_contiguous() -> None:
    contract = make_contract()
    with pytest.raises(ValidationError, match="contiguous"):
        TaskState(
            task_id=contract.task_id,
            contract=contract,
            plan=(PlanStep(sequence=2, description="Second"),),
        )


def test_closed_task_requires_completion_status() -> None:
    contract = make_contract()
    with pytest.raises(ValidationError, match="requires completion_status"):
        TaskState(
            task_id=contract.task_id,
            contract=contract,
            phase=TaskPhase.CLOSED,
        )


def test_full_happy_path_to_verified_closed() -> None:
    contract = make_contract()
    state = TaskState(task_id=contract.task_id, contract=contract)
    for phase in (
        TaskPhase.CONTRACTED,
        TaskPhase.CONTEXT_READY,
        TaskPhase.PLANNED,
        TaskPhase.ACTING,
        TaskPhase.OBSERVING,
        TaskPhase.VERIFYING,
    ):
        state = state.transition_to(phase)

    state = state.transition_to(
        TaskPhase.REPORTING,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
    )
    state = state.transition_to(
        TaskPhase.CLOSED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
    )

    assert state.phase is TaskPhase.CLOSED
    assert state.completion_status is CompletionStatus.VERIFIED_COMPLETE
    assert state.revision == 8


def test_task_state_round_trip() -> None:
    contract = make_contract()
    state = TaskState(task_id=contract.task_id, contract=contract)
    assert TaskState.from_json(state.to_json()) == state
