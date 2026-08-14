from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from luna.actions import InformationAwareToolAdvisor
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.contracts.base import utc_now
from luna.contracts.decision import (
    AssumptionRecord,
    AssumptionStatus,
    DecisionRecord,
    DecisionStateSnapshot,
    DecisionStatus,
)
from luna.contracts.enums import TaskPhase
from luna.contracts.plan import PlanStep
from luna.contracts.state import TaskState
from luna.planning import (
    DecisionCompression,
    DecisionControlAction,
    DecisionControlAdvisor,
    InformationNeedKind,
    LocalJudgmentBuilder,
)
from luna.retrieval import (
    InformationRetrievalStrategist,
    KnowledgeRequestProfile,
    KnowledgeSource,
    KnowledgeUncertainty,
    KnowledgeVolatility,
    ObservedRetrievalStrategyLedger,
    RetrievalDecision,
)
from luna.tools import ToolCapability, ToolSpec
from luna.verification import VerificationStrategySelector


def _state(
    *,
    decision_state: DecisionStateSnapshot | None = None,
    unknowns: tuple[str, ...] = (),
    risk: RiskLevel = RiskLevel.LOW,
    evidence_ids: tuple[UUID, ...] = (),
) -> TaskState:
    task_id = decision_state.task_id if decision_state is not None else uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Resolve the decision-critical uncertainty with bounded evidence.",
        required_conditions=("The bounded result is verified.",),
        evidence_required=("deterministic evidence",),
        scope=TaskScope(workspace_root="C:/workspace"),
        risk_level=risk,
        unknowns=unknowns,
    )
    plan = (
        PlanStep(sequence=1, description="Inspect current evidence."),
        PlanStep(sequence=2, description="Verify the result."),
    )
    return TaskState(
        task_id=task_id,
        contract=contract,
        phase=TaskPhase.PLANNED,
        plan=plan,
        decision_state=decision_state,
        evidence_ids=evidence_ids,
    )


def _judgment(state: TaskState, *, last_step: bool = False):
    step = state.plan[-1] if last_step else state.plan[0]
    verification = VerificationStrategySelector().select(contract=state.contract, step=step)
    judgment = LocalJudgmentBuilder().build(
        state=state,
        step=step,
        verification_depth=verification.depth.value,
    )
    return step, verification, judgment


def _compression(state: TaskState, judgment):
    return DecisionControlAdvisor().compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )


def _assess(
    *,
    state: TaskState,
    judgment,
    advisor: DecisionControlAdvisor,
    compression: DecisionCompression,
):
    alternatives = advisor.alternatives(state=state, compression=compression)
    return alternatives, advisor.assess(
        state=state,
        information_gain=judgment.information_gain,
        compression=compression,
        alternatives=alternatives,
    )

def test_information_gain_keeps_critical_uncertainty_ahead_of_normal_observation() -> None:
    task_id = uuid4()
    snapshot = DecisionStateSnapshot(
        task_id=task_id,
        assumptions=(
            AssumptionRecord(
                task_id=task_id,
                key="current_head",
                statement="current_head is unknown",
                claim_type="REPOSITORY_STATE",
                critical=True,
                status=AssumptionStatus.UNVERIFIED,
            ),
        ),
    )
    state = _state(decision_state=snapshot)
    _, _, judgment = _judgment(state)
    selected = next(
        item
        for item in judgment.information_gain.needs
        if item.need_id == judgment.information_gain.selected_need_id
    )

    assert selected.kind is InformationNeedKind.RESOLVE_UNCERTAINTY
    assert selected.priority == 100
    assert judgment.information_gain.needs[0] == selected


def test_tool_alternatives_rank_information_gain_against_side_effect_risk() -> None:
    state = _state(unknowns=("Which repository state is current?",))
    _, verification, judgment = _judgment(state)
    tools = (
        ToolSpec(
            name="filesystem.write_text",
            description="Write text.",
            capabilities=(ToolCapability.WRITE,),
        ),
        ToolSpec(
            name="filesystem.read_text",
            description="Read text.",
            capabilities=(ToolCapability.READ,),
        ),
    )

    advice = InformationAwareToolAdvisor().advise(
        available_tools=tools,
        information_gain=judgment.information_gain,
        verification=verification,
    )

    assert advice.recommended_tool_names == (
        "filesystem.read_text",
        "filesystem.write_text",
    )
    assert tuple(item.tool_name for item in advice.alternatives) == advice.recommended_tool_names
    assert advice.alternatives[0].expected_information_gain > 0
    assert advice.alternatives[1].risk_cost > 0
    assert advice.alternatives[0].net_score > advice.alternatives[1].net_score
    assert all(item.runtime_authority is False for item in advice.alternatives)
    assert "ranked_by_information_gain_risk_cost" in advice.reason_codes


def test_tool_ranking_aligns_with_selected_retrieval_source_before_score() -> None:
    state = _state(unknowns=("Which fresh source resolves the uncertainty?",))
    _, verification, judgment = _judgment(state)
    tools = (
        ToolSpec(
            name="filesystem.read_text",
            description="Read local workspace state.",
            capabilities=(ToolCapability.READ,),
        ),
        ToolSpec(
            name="research.search",
            description="Search a fresh external source.",
            capabilities=(ToolCapability.READ, ToolCapability.NETWORK),
        ),
    )

    advice = InformationAwareToolAdvisor().advise(
        available_tools=tools,
        information_gain=judgment.information_gain,
        verification=verification,
        retrieval_source=KnowledgeSource.RESEARCH_GATEWAY,
    )
    by_name = {item.tool_name: item for item in advice.alternatives}

    assert by_name["filesystem.read_text"].net_score > by_name["research.search"].net_score
    assert advice.recommended_tool_names[0] == "research.search"
    assert "ranked_by_source_gain_risk" in advice.reason_codes


def test_search_strategy_binds_selected_need_to_existing_structured_source_router() -> None:
    state = _state(unknowns=("What current structured fact resolves the decision?",))
    _, _, judgment = _judgment(state)
    profile = KnowledgeRequestProfile(
        task_id=state.task_id,
        query="Fetch the current structured fact.",
        volatility=KnowledgeVolatility.DYNAMIC,
        uncertainty=KnowledgeUncertainty.HIGH,
        currentness_required=True,
        structured_data_suitable=True,
        structured_api_available=True,
        research_gateway_available=True,
    )

    compression = _compression(state, judgment)
    strategy = InformationRetrievalStrategist().plan(
        information_gain=judgment.information_gain,
        profile=profile,
        decision_basis_fingerprint=compression.decision_basis_fingerprint,
    )

    assert strategy.information_need_id == judgment.information_gain.selected_need_id
    assert strategy.retrieval_plan.decision is RetrievalDecision.RETRIEVE
    assert strategy.retrieval_plan.primary_source is KnowledgeSource.STRUCTURED_API
    assert "fresh_evidence_observed" in strategy.stop_conditions
    assert "decision_question_resolved" in strategy.stop_conditions
    assert strategy.runtime_authority is False
    assert strategy.external_action_allowed is False


def test_search_strategy_routes_project_state_to_available_workspace_read() -> None:
    state = _state(unknowns=("Which repository state is current?",))
    _, _, judgment = _judgment(state)
    compression = _compression(state, judgment)
    strategy = InformationRetrievalStrategist().plan(
        information_gain=judgment.information_gain,
        profile=KnowledgeRequestProfile(
            task_id=state.task_id,
            query="Inspect the current repository state.",
            project_specific=True,
            workspace_read_available=True,
        ),
        decision_basis_fingerprint=compression.decision_basis_fingerprint,
    )

    assert strategy.retrieval_plan.decision is RetrievalDecision.RETRIEVE
    assert strategy.retrieval_plan.primary_source is KnowledgeSource.WORKSPACE_TOOL
    assert strategy.retrieval_plan.requires_freshness is True
    assert "fresh_evidence_observed" in strategy.stop_conditions


def test_observed_retrieval_strategy_ledger_is_deduplicated_and_bounded() -> None:
    task_id = uuid4()
    ledger = ObservedRetrievalStrategyLedger(max_entries_per_task=2)
    first = "a" * 64
    second = "b" * 64
    third = "c" * 64

    ledger.record(task_id=task_id, strategy_fingerprint=first)
    ledger.record(task_id=task_id, strategy_fingerprint=first)
    ledger.record(task_id=task_id, strategy_fingerprint=second)
    ledger.record(task_id=task_id, strategy_fingerprint=third)

    assert ledger.fingerprints(task_id) == (second, third)
    ledger.forget(task_id)
    assert ledger.fingerprints(task_id) == ()


def test_search_strategy_stops_before_selection_when_evidence_is_contradictory() -> None:
    state = _state(unknowns=("Which source is authoritative?",))
    _, _, judgment = _judgment(state)
    compression = _compression(state, judgment)
    strategy = InformationRetrievalStrategist().plan(
        information_gain=judgment.information_gain,
        profile=KnowledgeRequestProfile(
            task_id=state.task_id,
            query="Resolve the authority conflict.",
            contradictory_evidence=True,
            research_gateway_available=True,
        ),
        decision_basis_fingerprint=compression.decision_basis_fingerprint,
    )

    assert strategy.retrieval_plan.decision is RetrievalDecision.STOP_REINSPECT
    assert strategy.retrieval_plan.primary_source is None
    assert "stop_reinspect_before_search" in strategy.stop_conditions


def test_search_strategy_stops_when_working_context_is_already_sufficient() -> None:
    state = _state(unknowns=("Is more retrieval needed?",))
    _, _, judgment = _judgment(state)
    compression = _compression(state, judgment)
    strategy = InformationRetrievalStrategist().plan(
        information_gain=judgment.information_gain,
        profile=KnowledgeRequestProfile(
            task_id=state.task_id,
            query="Use already observed working context if it resolves the decision.",
            volatility=KnowledgeVolatility.STABLE,
            uncertainty=KnowledgeUncertainty.LOW,
            working_context_sufficient=True,
        ),
        decision_basis_fingerprint=compression.decision_basis_fingerprint,
    )

    assert strategy.retrieval_plan.decision is RetrievalDecision.ANSWER_DIRECT
    assert strategy.retrieval_plan.primary_source is KnowledgeSource.WORKING_CONTEXT
    assert "decision_relevant_evidence_already_sufficient" in strategy.stop_conditions
    assert strategy.external_action_allowed is False


def test_search_strategy_fingerprint_allows_changed_basis_without_blind_repeat() -> None:
    state = _state(unknowns=("Which current source resolves the question?",))
    _, _, judgment = _judgment(state)
    first_compression = _compression(state, judgment)
    strategist = InformationRetrievalStrategist()
    profile = KnowledgeRequestProfile(
        task_id=state.task_id,
        query="Inspect the bounded repository evidence.",
        project_specific=True,
        project_rag_available=True,
    )
    first = strategist.plan(
        information_gain=judgment.information_gain,
        profile=profile,
        decision_basis_fingerprint=first_compression.decision_basis_fingerprint,
    )
    same_basis = strategist.plan(
        information_gain=judgment.information_gain,
        profile=profile,
        decision_basis_fingerprint=first_compression.decision_basis_fingerprint,
    )

    changed_state = state.revise(evidence_ids=(uuid4(),))
    _, _, changed_judgment = _judgment(changed_state)
    changed_compression = _compression(changed_state, changed_judgment)
    changed_basis = strategist.plan(
        information_gain=changed_judgment.information_gain,
        profile=profile,
        decision_basis_fingerprint=changed_compression.decision_basis_fingerprint,
        observed_strategy_fingerprints=(first.strategy_fingerprint,),
    )

    assert same_basis.strategy_fingerprint == first.strategy_fingerprint
    assert changed_compression.decision_basis_fingerprint != (
        first_compression.decision_basis_fingerprint
    )
    assert changed_basis.strategy_fingerprint != first.strategy_fingerprint
    assert changed_basis.duplicate_observed_search_blocked is False
    assert changed_basis.retrieval_plan.decision is RetrievalDecision.RETRIEVE
    assert changed_basis.retrieval_plan.primary_source is KnowledgeSource.PROJECT_RAG

def test_decision_compression_is_pure_and_preserves_source_evidence() -> None:
    task_id = uuid4()
    assumption = AssumptionRecord(
        task_id=task_id,
        key="current_head",
        statement="current_head=abc123",
        claim_type="REPOSITORY_STATE",
        critical=True,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("evidence:git-head",),
        provenance_refs=("git://HEAD",),
    )
    snapshot = DecisionStateSnapshot(task_id=task_id, assumptions=(assumption,))
    state = _state(decision_state=snapshot)
    step, _, judgment = _judgment(state)
    before = state.model_dump(mode="json")

    compression = DecisionControlAdvisor().compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )

    assert state.model_dump(mode="json") == before
    assert compression.step_id == step.step_id
    assert compression.raw_evidence_preserved is True
    assert "evidence:git-head" in compression.source_evidence_refs
    assert compression.decision_changing_evidence_refs == ()
    assert "evidence:git-head" in compression.supporting_evidence_refs
    assert set(compression.source_evidence_refs) == (
        set(compression.decision_changing_evidence_refs)
        | set(compression.supporting_evidence_refs)
    )
    assert compression.runtime_authority is False


def test_stop_verify_wins_when_critical_assumption_is_unverified() -> None:
    task_id = uuid4()
    snapshot = DecisionStateSnapshot(
        task_id=task_id,
        assumptions=(
            AssumptionRecord(
                task_id=task_id,
                key="workspace_revision",
                statement="workspace revision is unknown",
                claim_type="REPOSITORY_STATE",
                critical=True,
                status=AssumptionStatus.UNVERIFIED,
            ),
        ),
    )
    state = _state(decision_state=snapshot)
    _, _, judgment = _judgment(state)
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    _, control = _assess(
        state=state,
        judgment=judgment,
        advisor=advisor,
        compression=compression,
    )

    assert control.action is DecisionControlAction.STOP_VERIFY
    assert control.verification_required is True
    assert control.blocker_refs
    assert control.runtime_authority is False


def test_authoritative_contradiction_forces_stop_verify_even_with_other_evidence() -> None:
    task_id = uuid4()
    snapshot = DecisionStateSnapshot(
        task_id=task_id,
        assumptions=(
            AssumptionRecord(
                task_id=task_id,
                key="current_branch",
                statement="branch=stale",
                claim_type="REPOSITORY_STATE",
                critical=True,
                status=AssumptionStatus.CONTRADICTED,
                evidence_refs=("evidence:current-git",),
                reason="current Git evidence contradicts the stale branch",
            ),
        ),
    )
    state = _state(decision_state=snapshot)
    _, _, judgment = _judgment(state)
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    _, control = _assess(
        state=state,
        judgment=judgment,
        advisor=advisor,
        compression=compression,
    )

    assert control.action is DecisionControlAction.STOP_VERIFY
    assert "critical_contradiction_requires_stop_verify" in control.reason_codes
    assert control.changed_basis_refs


def test_invalidated_current_decision_switch_requires_linked_basis_change_and_alternate() -> None:
    task_id = uuid4()
    invalidated_id = uuid4()
    assumption_id = uuid4()
    evidence_ref = "evidence:changed-route"
    assumption = AssumptionRecord(
        assumption_id=assumption_id,
        task_id=task_id,
        key="stale_route_basis",
        statement="the old route basis was invalidated",
        claim_type="ROUTE_BASIS",
        critical=False,
        status=AssumptionStatus.INVALIDATED,
        evidence_refs=(evidence_ref,),
        dependent_decision_ids=(invalidated_id,),
        reason="new evidence invalidated the old route basis",
    )
    invalidated = DecisionRecord(
        decision_id=invalidated_id,
        task_id=task_id,
        action_key="inspect:stale",
        description="Use the stale inspection route.",
        status=DecisionStatus.INVALIDATED,
        assumption_ids=(assumption_id,),
        reason="linked basis was invalidated",
    )
    alternate = DecisionRecord(
        task_id=task_id,
        action_key="inspect:fresh",
        description="Use the current evidence-bound inspection route.",
        status=DecisionStatus.ACTIVE,
    )
    snapshot = DecisionStateSnapshot(
        task_id=task_id,
        revision=2,
        assumptions=(assumption,),
        decisions=(invalidated, alternate),
    )
    state = _state(decision_state=snapshot)
    _, _, judgment = _judgment(state)
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    alternatives, control = _assess(
        state=state,
        judgment=judgment,
        advisor=advisor,
        compression=compression,
    )

    assert compression.decision_changing_evidence_refs == (evidence_ref,)
    assert control.action is DecisionControlAction.SWITCH
    assert control.selected_alternative_ref == alternatives.selected_alternative_ref
    assert control.selected_alternative_ref is not None
    assert evidence_ref in control.changed_basis_refs
    assert "stronger_admissible_alternative_present" in control.reason_codes

def test_switch_stops_when_any_current_invalidated_route_lacks_evidence_binding() -> None:
    task_id = uuid4()
    linked_id = uuid4()
    unbound_id = uuid4()
    assumption_id = uuid4()
    evidence_ref = "evidence:linked-change"
    assumption = AssumptionRecord(
        assumption_id=assumption_id,
        task_id=task_id,
        key="linked_basis",
        statement="one route basis was invalidated",
        claim_type="ROUTE_BASIS",
        status=AssumptionStatus.INVALIDATED,
        evidence_refs=(evidence_ref,),
        dependent_decision_ids=(linked_id,),
        reason="linked evidence invalidated this route",
    )
    linked = DecisionRecord(
        decision_id=linked_id,
        task_id=task_id,
        action_key="route:linked",
        description="Linked invalidated route.",
        status=DecisionStatus.INVALIDATED,
        assumption_ids=(assumption_id,),
        reason="linked basis invalidated",
    )
    unbound = DecisionRecord(
        decision_id=unbound_id,
        task_id=task_id,
        action_key="route:unbound",
        description="Unbound invalidated route.",
        status=DecisionStatus.INVALIDATED,
        reason="invalidation has no evidence binding",
    )
    alternate = DecisionRecord(
        task_id=task_id,
        action_key="route:fresh",
        description="Admissible alternate route.",
        status=DecisionStatus.ACTIVE,
    )
    state = _state(
        decision_state=DecisionStateSnapshot(
            task_id=task_id,
            revision=3,
            assumptions=(assumption,),
            decisions=(linked, unbound, alternate),
        )
    )
    _, _, judgment = _judgment(state)
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    alternatives, control = _assess(
        state=state,
        judgment=judgment,
        advisor=advisor,
        compression=compression,
    )

    assert alternatives.selected_alternative_ref is not None
    assert compression.decision_changing_evidence_refs == (evidence_ref,)
    assert len(compression.evidence_bound_invalidated_decision_refs) == 1
    assert control.action is DecisionControlAction.STOP_VERIFY
    assert "invalidated_decision_lacks_evidence_binding" in control.reason_codes


def test_unrelated_available_evidence_does_not_implicitly_authorize_switch() -> None:
    task_id = uuid4()
    invalidated = DecisionRecord(
        task_id=task_id,
        action_key="inspect:repo",
        description="Route invalidated without explicit changed-basis linkage.",
        status=DecisionStatus.INVALIDATED,
        reason="basis changed but the replacement evidence was not identified",
    )
    alternate = DecisionRecord(
        task_id=task_id,
        action_key="inspect:fresh",
        description="A separate admissible route exists.",
        status=DecisionStatus.ACTIVE,
    )
    state = _state(
        decision_state=DecisionStateSnapshot(
            task_id=task_id,
            decisions=(invalidated, alternate),
        ),
        evidence_ids=(uuid4(),),
    )
    _, _, judgment = _judgment(state)
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    _, control = _assess(
        state=state,
        judgment=judgment,
        advisor=advisor,
        compression=compression,
    )

    assert compression.source_evidence_refs
    assert control.action is DecisionControlAction.STOP_VERIFY
    assert "invalidated_decision_lacks_changed_basis_evidence" in control.reason_codes


def test_invalidated_decision_without_changed_basis_evidence_stops_for_verification() -> None:
    task_id = uuid4()
    invalidated = DecisionRecord(
        task_id=task_id,
        action_key="inspect:repo",
        description="Route invalidated without linked evidence.",
        status=DecisionStatus.INVALIDATED,
        reason="basis changed but evidence was not linked",
    )
    state = _state(
        decision_state=DecisionStateSnapshot(task_id=task_id, decisions=(invalidated,))
    )
    _, _, judgment = _judgment(state)
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    _, control = _assess(
        state=state,
        judgment=judgment,
        advisor=advisor,
        compression=compression,
    )

    assert control.action is DecisionControlAction.STOP_VERIFY
    assert control.verification_required is True
    assert "invalidated_decision_lacks_changed_basis_evidence" in control.reason_codes


def test_historical_invalidated_decision_does_not_force_switch_after_replacement() -> None:
    task_id = uuid4()
    now = utc_now()
    old = DecisionRecord(
        task_id=task_id,
        action_key="inspect:repo",
        description="Old route.",
        status=DecisionStatus.INVALIDATED,
        reason="superseded by current evidence",
        created_at=now,
        updated_at=now,
    )
    replacement = DecisionRecord(
        task_id=task_id,
        action_key="inspect:repo",
        description="Current evidence-bound route.",
        status=DecisionStatus.ACTIVE,
        created_at=now + timedelta(seconds=1),
        updated_at=now + timedelta(seconds=1),
    )
    snapshot = DecisionStateSnapshot(task_id=task_id, decisions=(old, replacement))
    state = _state(decision_state=snapshot)
    _, _, judgment = _judgment(state)
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    _, control = _assess(
        state=state,
        judgment=judgment,
        advisor=advisor,
        compression=compression,
    )

    assert compression.invalidated_decision_refs == ()
    assert control.action is DecisionControlAction.CONTINUE


def test_observed_identical_search_strategy_is_blocked_as_duplicate() -> None:
    state = _state(unknowns=("Which current source resolves the question?",))
    _, _, judgment = _judgment(state)
    profile = KnowledgeRequestProfile(
        task_id=state.task_id,
        query="Search the same bounded source once.",
        currentness_required=True,
        research_gateway_available=True,
    )
    strategist = InformationRetrievalStrategist()
    compression = _compression(state, judgment)
    first = strategist.plan(
        information_gain=judgment.information_gain,
        profile=profile,
        decision_basis_fingerprint=compression.decision_basis_fingerprint,
    )
    repeated = strategist.plan(
        information_gain=judgment.information_gain,
        profile=profile,
        decision_basis_fingerprint=compression.decision_basis_fingerprint,
        observed_strategy_fingerprints=(first.strategy_fingerprint,),
    )

    assert repeated.duplicate_observed_search_blocked is True
    assert repeated.retrieval_plan.decision is RetrievalDecision.STOP_REINSPECT
    assert "duplicate_observed_search_blocked" in repeated.stop_conditions


def test_tool_alternatives_are_regenerated_when_available_surface_changes() -> None:
    state = _state(unknowns=("Which observation should be collected?",))
    _, verification, judgment = _judgment(state)
    read = ToolSpec(
        name="filesystem.read_text",
        description="Read text.",
        capabilities=(ToolCapability.READ,),
    )
    write = ToolSpec(
        name="filesystem.write_text",
        description="Write text.",
        capabilities=(ToolCapability.WRITE,),
    )
    advisor = InformationAwareToolAdvisor()

    first = advisor.advise(
        available_tools=(write,),
        information_gain=judgment.information_gain,
        verification=verification,
    )
    updated = advisor.advise(
        available_tools=(write, read),
        information_gain=judgment.information_gain,
        verification=verification,
    )

    assert first.recommended_tool_names == ("filesystem.write_text",)
    assert updated.recommended_tool_names[0] == "filesystem.read_text"
    assert {item.tool_name for item in updated.alternatives} == {
        "filesystem.read_text",
        "filesystem.write_text",
    }


def test_decision_compression_rejects_incomplete_evidence_partition() -> None:
    state = _state(evidence_ids=(uuid4(),))
    _, _, judgment = _judgment(state)
    compression = _compression(state, judgment)
    payload = compression.model_dump(mode="json")
    payload["supporting_evidence_refs"] = []

    with pytest.raises(ValueError, match="cover source evidence exactly"):
        DecisionCompression.model_validate(payload)


def test_stale_compression_and_alternative_set_fail_closed_before_control() -> None:
    task_id = uuid4()
    old = DecisionRecord(
        task_id=task_id,
        action_key="inspect:repo",
        description="Old current route.",
        status=DecisionStatus.ACTIVE,
    )
    old_snapshot = DecisionStateSnapshot(task_id=task_id, revision=1, decisions=(old,))
    state = _state(decision_state=old_snapshot)
    _, _, judgment = _judgment(state)
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    alternatives = advisor.alternatives(state=state, compression=compression)

    replacement = DecisionRecord(
        task_id=task_id,
        action_key="inspect:repo",
        description="New current route.",
        status=DecisionStatus.ACTIVE,
    )
    new_snapshot = DecisionStateSnapshot(task_id=task_id, revision=2, decisions=(replacement,))
    changed_state = state.revise(decision_state=new_snapshot)
    _, _, changed_judgment = _judgment(changed_state)
    control = advisor.assess(
        state=changed_state,
        information_gain=changed_judgment.information_gain,
        compression=compression,
        alternatives=alternatives,
    )

    assert control.action is DecisionControlAction.STOP_VERIFY
    assert control.verification_required is True
    assert "stale_cognition_basis_requires_refresh" in control.reason_codes
    assert any(ref.startswith("stale_task_state_revision:") for ref in control.blocker_refs)


def test_decision_alternatives_regenerate_and_rank_current_routes() -> None:
    task_id = uuid4()
    blocked = DecisionRecord(
        task_id=task_id,
        action_key="route:blocked",
        description="Blocked route.",
        status=DecisionStatus.BLOCKED,
        reason="route is blocked",
    )
    active = DecisionRecord(
        task_id=task_id,
        action_key="route:active",
        description="Current admissible route.",
        status=DecisionStatus.ACTIVE,
    )
    state = _state(
        decision_state=DecisionStateSnapshot(
            task_id=task_id,
            decisions=(blocked, active),
        )
    )
    _, _, judgment = _judgment(state)
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    alternatives = advisor.alternatives(state=state, compression=compression)

    assert len(alternatives.alternatives) == 2
    assert alternatives.selected_alternative_ref is not None
    selected = next(
        item
        for item in alternatives.alternatives
        if item.decision_ref == alternatives.selected_alternative_ref
    )
    assert selected.status is DecisionStatus.ACTIVE
    assert selected.admissible is True
    assert alternatives.ranked_alternative_refs[0] == selected.decision_ref
    assert alternatives.runtime_authority is False


def test_verification_network_capability_has_explicit_risk_cost() -> None:
    state = _state()
    _, verification, judgment = _judgment(state, last_step=True)
    tools = (
        ToolSpec(
            name="local.process",
            description="Run a local verification process.",
            capabilities=(ToolCapability.PROCESS,),
        ),
        ToolSpec(
            name="network.process",
            description="Run a network-capable verification process.",
            capabilities=(ToolCapability.PROCESS, ToolCapability.NETWORK),
        ),
    )
    advice = InformationAwareToolAdvisor().advise(
        available_tools=tools,
        information_gain=judgment.information_gain,
        verification=verification,
    )
    by_name = {item.tool_name: item for item in advice.alternatives}

    assert by_name["network.process"].risk_cost == 30
    assert "verification_network_penalty" in by_name["network.process"].reason_codes
    assert by_name["local.process"].net_score > by_name["network.process"].net_score


def test_supported_current_basis_continues_without_granting_authority() -> None:
    state = _state()
    _, _, judgment = _judgment(state)
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=state,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    _, control = _assess(
        state=state,
        judgment=judgment,
        advisor=advisor,
        compression=compression,
    )

    assert control.action is DecisionControlAction.CONTINUE
    assert control.verification_required is False
    assert control.runtime_authority is False
    assert control.execution_authority is False
    assert control.completion_authority is False
