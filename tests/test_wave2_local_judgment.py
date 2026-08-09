from __future__ import annotations

from uuid import uuid4

from luna.actions import InformationAwareToolAdvisor
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.contracts.decision import AssumptionRecord, AssumptionStatus, DecisionStateSnapshot
from luna.contracts.enums import TaskPhase
from luna.contracts.plan import PlanStep
from luna.contracts.state import TaskState
from luna.planning import InformationNeedKind, LocalJudgmentBuilder
from luna.tools import ToolCapability, ToolSpec
from luna.verification import (
    EvidenceStrength,
    VerificationDepth,
    VerificationStrategySelector,
)


def _state(*, risk: RiskLevel = RiskLevel.LOW, with_critical_gap: bool = False) -> TaskState:
    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Inspect the bounded target and prove the requested result.",
        required_conditions=("Requested result is satisfied.",),
        forbidden_outcomes=("Protected state changes.",),
        evidence_required=("deterministic test result",),
        scope=TaskScope(
            workspace_root="C:/workspace",
            allowed_paths=("README.md",),
            write_allowed=risk is not RiskLevel.LOW,
        ),
        risk_level=risk,
    )
    steps = (
        PlanStep(sequence=1, description="Inspect current state."),
        PlanStep(sequence=2, description="Verify acceptance evidence.", depends_on=()),
    )
    decision_state = None
    if with_critical_gap:
        decision_state = DecisionStateSnapshot(
            task_id=task_id,
            assumptions=(
                AssumptionRecord(
                    task_id=task_id,
                    key="current_baseline",
                    statement="The observed baseline is current.",
                    claim_type="REPOSITORY_STATE",
                    critical=True,
                    status=AssumptionStatus.UNVERIFIED,
                ),
            ),
        )
    return TaskState(
        task_id=task_id,
        contract=contract,
        phase=TaskPhase.PLANNED,
        plan=steps,
        decision_state=decision_state,
    )


def test_acceptance_backchain_is_deterministic_and_contract_bound() -> None:
    state = _state()
    builder = LocalJudgmentBuilder()

    first = builder.acceptance_backchain(state)
    second = builder.acceptance_backchain(state)

    assert first == second
    assert len(first.targets) == 3
    assert {item.text for item in first.targets} == {
        "Requested result is satisfied.",
        "Protected state changes.",
        "deterministic test result",
    }
    assert all(item.evidence_requirements for item in first.targets)


def test_information_gain_prioritizes_critical_uncertainty_before_action() -> None:
    state = _state(with_critical_gap=True)
    builder = LocalJudgmentBuilder()
    verification = VerificationStrategySelector().select(
        contract=state.contract,
        step=state.plan[0],
    )

    judgment = builder.build(
        state=state,
        step=state.plan[0],
        verification_depth=verification.depth.value,
    )
    selected = next(
        item
        for item in judgment.information_gain.needs
        if item.need_id == judgment.information_gain.selected_need_id
    )

    assert selected.kind is InformationNeedKind.RESOLVE_UNCERTAINTY
    assert "critical_uncertainty_present" in judgment.information_gain.reason_codes
    assert any("UNVERIFIED" in item for item in judgment.decision_basis.blocker_refs)


def test_verification_strategy_can_strengthen_but_not_weaken_default_floor() -> None:
    low = _state(risk=RiskLevel.LOW)
    high = _state(risk=RiskLevel.HIGH)
    selector = VerificationStrategySelector()

    low_strategy = selector.select(contract=low.contract, step=low.plan[0])
    high_strategy = selector.select(contract=high.contract, step=high.plan[0])

    assert low_strategy.depth is VerificationDepth.TARGETED
    assert low_strategy.minimum_strength_floor is EvidenceStrength.STRONG
    assert high_strategy.depth is VerificationDepth.REGRESSION
    assert high_strategy.minimum_strength_floor is EvidenceStrength.DETERMINISTIC


def test_tool_advice_reorders_only_the_already_available_set() -> None:
    state = _state()
    builder = LocalJudgmentBuilder()
    strategy = VerificationStrategySelector().select(
        contract=state.contract,
        step=state.plan[0],
    )
    judgment = builder.build(
        state=state,
        step=state.plan[0],
        verification_depth=strategy.depth.value,
    )
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
    advisor = InformationAwareToolAdvisor()

    advice = advisor.advise(
        available_tools=tools,
        information_gain=judgment.information_gain,
        verification=strategy,
    )
    ordered = advisor.ordered_specs(available_tools=tools, advice=advice)

    assert set(advice.recommended_tool_names) == {item.name for item in tools}
    assert ordered[0].name == "filesystem.read_text"
    assert "advisory_only_no_authority" in advice.reason_codes


def test_final_step_targets_acceptance_evidence() -> None:
    state = _state()
    builder = LocalJudgmentBuilder()
    strategy = VerificationStrategySelector().select(
        contract=state.contract,
        step=state.plan[-1],
    )
    judgment = builder.build(
        state=state,
        step=state.plan[-1],
        verification_depth=strategy.depth.value,
    )
    selected = next(
        item
        for item in judgment.information_gain.needs
        if item.need_id == judgment.information_gain.selected_need_id
    )

    assert selected.kind is InformationNeedKind.VERIFY_ACCEPTANCE
