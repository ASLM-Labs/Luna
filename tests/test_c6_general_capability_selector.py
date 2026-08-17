from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.planning import (
    CapabilityDisposition,
    CapabilityKind,
    CapabilitySelectionEntry,
    CapabilitySelectionPlan,
    DecisionControlAction,
    GeneralCapabilitySelector,
)
from luna.retrieval import RetrievalDecision
from luna.runtime import PolicyTurn, PolicyTurnStatus
from luna.verification import VerificationDepth


def _select(
    *,
    retrieval_decision: RetrievalDecision = RetrievalDecision.RETRIEVE,
    considered_tool_names: tuple[str, ...] = ("filesystem.read_text",),
    decision_control_action: DecisionControlAction = DecisionControlAction.CONTINUE,
):
    return GeneralCapabilitySelector().select(
        task_id=uuid4(),
        step_id=uuid4(),
        specification_basis_fingerprint="1" * 64,
        acceptance_basis_fingerprint="2" * 64,
        decision_basis_fingerprint="3" * 64,
        retrieval_strategy_fingerprint="4" * 64,
        decision_control_action=decision_control_action.value,
        retrieval_decision=retrieval_decision.value,
        verification_depth=VerificationDepth.TARGETED.value,
        considered_tool_names=considered_tool_names,
    )


def test_c6_same_inputs_produce_same_selection_basis() -> None:
    task_id = uuid4()
    step_id = uuid4()
    selector = GeneralCapabilitySelector()
    kwargs = {
        "task_id": task_id,
        "step_id": step_id,
        "specification_basis_fingerprint": "1" * 64,
        "acceptance_basis_fingerprint": "2" * 64,
        "decision_basis_fingerprint": "3" * 64,
        "retrieval_strategy_fingerprint": "4" * 64,
        "decision_control_action": DecisionControlAction.CONTINUE.value,
        "retrieval_decision": RetrievalDecision.RETRIEVE.value,
        "verification_depth": VerificationDepth.TARGETED.value,
        "considered_tool_names": ("filesystem.read_text",),
    }

    first = selector.select(**kwargs)
    second = selector.select(**kwargs)

    assert first == second
    assert first.selection_basis_fingerprint == second.selection_basis_fingerprint


def test_c6_retrieve_selects_retrieval_without_granting_authority() -> None:
    plan = _select()

    assert plan.selected_capabilities() == (
        CapabilityKind.SPECIFICATION,
        CapabilityKind.ACCEPTANCE_JUDGMENT,
        CapabilityKind.DECISION_CONTROL,
        CapabilityKind.VERIFICATION,
        CapabilityKind.RETRIEVAL,
        CapabilityKind.TOOL_ADVICE,
    )
    assert plan.skipped_capabilities() == ()
    assert plan.runtime_authority is False
    assert plan.execution_authority is False
    assert plan.completion_authority is False
    assert "c4:specification_basis:" + "1" * 64 in plan.provenance_refs
    assert "c5:acceptance_basis:" + "2" * 64 in plan.provenance_refs


def test_c6_answer_direct_skips_retrieval_but_keeps_allowed_tool_advice() -> None:
    plan = _select(retrieval_decision=RetrievalDecision.ANSWER_DIRECT)
    by_kind = {item.capability: item for item in plan.entries}

    assert by_kind[CapabilityKind.RETRIEVAL].disposition is CapabilityDisposition.SKIPPED
    assert "decision_relevant_evidence_already_sufficient" in (
        by_kind[CapabilityKind.RETRIEVAL].reason_codes
    )
    assert by_kind[CapabilityKind.TOOL_ADVICE].disposition is CapabilityDisposition.SELECTED
    assert "tool_policy_remains_outer_bound" in by_kind[CapabilityKind.TOOL_ADVICE].reason_codes


def test_c6_stop_reinspect_and_empty_tool_surface_skip_downstream_activation() -> None:
    plan = _select(
        retrieval_decision=RetrievalDecision.STOP_REINSPECT,
        considered_tool_names=(),
        decision_control_action=DecisionControlAction.STOP_VERIFY,
    )
    by_kind = {item.capability: item for item in plan.entries}

    assert by_kind[CapabilityKind.RETRIEVAL].disposition is CapabilityDisposition.SKIPPED
    assert "stop_reinspect_preserved" in by_kind[CapabilityKind.RETRIEVAL].reason_codes
    assert by_kind[CapabilityKind.TOOL_ADVICE].disposition is CapabilityDisposition.SKIPPED
    assert "no_already_allowed_tools_available" in by_kind[CapabilityKind.TOOL_ADVICE].reason_codes


def test_c6_changed_owner_decision_changes_selection_basis() -> None:
    task_id = uuid4()
    step_id = uuid4()
    selector = GeneralCapabilitySelector()
    common = {
        "task_id": task_id,
        "step_id": step_id,
        "specification_basis_fingerprint": "1" * 64,
        "acceptance_basis_fingerprint": "2" * 64,
        "decision_basis_fingerprint": "3" * 64,
        "retrieval_strategy_fingerprint": "4" * 64,
        "decision_control_action": DecisionControlAction.CONTINUE.value,
        "verification_depth": VerificationDepth.TARGETED.value,
        "considered_tool_names": ("filesystem.read_text",),
    }

    retrieve = selector.select(
        **common,
        retrieval_decision=RetrievalDecision.RETRIEVE.value,
    )
    direct = selector.select(
        **common,
        retrieval_decision=RetrievalDecision.ANSWER_DIRECT.value,
    )

    assert retrieve.selection_basis_fingerprint != direct.selection_basis_fingerprint
    assert CapabilityKind.RETRIEVAL in retrieve.selected_capabilities()
    assert CapabilityKind.RETRIEVAL in direct.skipped_capabilities()


def test_c6_rejects_selected_capability_with_skipped_dependency() -> None:
    entries = (
        CapabilitySelectionEntry(
            capability=CapabilityKind.SPECIFICATION,
            disposition=CapabilityDisposition.SKIPPED,
            reason_codes=("fixture",),
        ),
        CapabilitySelectionEntry(
            capability=CapabilityKind.ACCEPTANCE_JUDGMENT,
            disposition=CapabilityDisposition.SELECTED,
            depends_on=(CapabilityKind.SPECIFICATION,),
            reason_codes=("fixture",),
        ),
        CapabilitySelectionEntry(
            capability=CapabilityKind.DECISION_CONTROL,
            disposition=CapabilityDisposition.SELECTED,
            depends_on=(CapabilityKind.ACCEPTANCE_JUDGMENT,),
            reason_codes=("fixture",),
        ),
        CapabilitySelectionEntry(
            capability=CapabilityKind.VERIFICATION,
            disposition=CapabilityDisposition.SELECTED,
            depends_on=(CapabilityKind.ACCEPTANCE_JUDGMENT,),
            reason_codes=("fixture",),
        ),
        CapabilitySelectionEntry(
            capability=CapabilityKind.RETRIEVAL,
            disposition=CapabilityDisposition.SKIPPED,
            depends_on=(CapabilityKind.DECISION_CONTROL,),
            reason_codes=("fixture",),
        ),
        CapabilitySelectionEntry(
            capability=CapabilityKind.TOOL_ADVICE,
            disposition=CapabilityDisposition.SELECTED,
            depends_on=(CapabilityKind.DECISION_CONTROL, CapabilityKind.VERIFICATION),
            reason_codes=("fixture",),
        ),
    )

    with pytest.raises(ValidationError, match="selected capability cannot depend on a skipped"):
        CapabilitySelectionPlan(
            task_id=uuid4(),
            step_id=uuid4(),
            specification_basis_fingerprint="1" * 64,
            acceptance_basis_fingerprint="2" * 64,
            decision_basis_fingerprint="3" * 64,
            retrieval_strategy_fingerprint="4" * 64,
            selection_basis_fingerprint="5" * 64,
            entries=entries,
            provenance_refs=("a", "b", "c", "d"),
        )


def test_c6_policy_turn_carries_observable_selection_without_model_projection() -> None:
    plan = _select()
    turn = PolicyTurn(
        task_id=plan.task_id,
        trace_id=uuid4(),
        status=PolicyTurnStatus.YIELD,
        model_request_id=uuid4(),
        model_request_fingerprint="5" * 64,
        model_response_id=uuid4(),
        capability_selection=plan,
    )

    assert turn.capability_selection == plan
    assert turn.capability_selection.runtime_authority is False
    assert turn.capability_selection.execution_authority is False
    assert turn.capability_selection.completion_authority is False


def test_c6_policy_turn_rejects_selection_from_another_task() -> None:
    plan = _select()

    with pytest.raises(ValidationError, match="capability selection task must match"):
        PolicyTurn(
            task_id=uuid4(),
            trace_id=uuid4(),
            status=PolicyTurnStatus.YIELD,
            model_request_id=uuid4(),
            model_request_fingerprint="5" * 64,
            model_response_id=uuid4(),
            capability_selection=plan,
        )
