"""Deterministic Wave 2 local-judgment foundation gate."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from luna.actions import InformationAwareToolAdvisor
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.contracts.decision import AssumptionRecord, AssumptionStatus, DecisionStateSnapshot
from luna.contracts.enums import TaskPhase
from luna.contracts.plan import PlanStep
from luna.contracts.state import TaskState
from luna.planning import InformationNeedKind, LocalJudgmentBuilder
from luna.tools import ToolCapability, ToolSpec
from luna.verification import EvidenceStrength, VerificationDepth, VerificationStrategySelector

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "src/luna/planning/judgment.py",
    "src/luna/actions/advisory.py",
    "src/luna/verification/strategy.py",
    "tests/test_wave2_local_judgment.py",
    "scripts/verify_wave2.py",
)


def _state(*, risk: RiskLevel, critical_gap: bool) -> TaskState:
    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Use observable evidence to complete the bounded task.",
        required_conditions=("The requested result is satisfied.",),
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
        PlanStep(sequence=2, description="Verify acceptance evidence."),
    )
    decision_state = None
    if critical_gap:
        decision_state = DecisionStateSnapshot(
            task_id=task_id,
            assumptions=(
                AssumptionRecord(
                    task_id=task_id,
                    key="current_state",
                    statement="Current state is known.",
                    claim_type="CURRENT_STATE",
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


def main() -> int:
    checks: dict[str, bool] = {}
    checks["required_files_present"] = all(
        (PROJECT_ROOT / item).is_file() for item in REQUIRED_FILES
    )

    low = _state(risk=RiskLevel.LOW, critical_gap=True)
    high = _state(risk=RiskLevel.HIGH, critical_gap=False)
    builder = LocalJudgmentBuilder()
    selector = VerificationStrategySelector()

    low_strategy = selector.select(contract=low.contract, step=low.plan[0])
    high_strategy = selector.select(contract=high.contract, step=high.plan[0])
    low_judgment = builder.build(
        state=low,
        step=low.plan[0],
        verification_depth=low_strategy.depth.value,
    )
    selected = next(
        item
        for item in low_judgment.information_gain.needs
        if item.need_id == low_judgment.information_gain.selected_need_id
    )

    checks["acceptance_backchain_present"] = len(low_judgment.acceptance.targets) == 3
    checks["critical_uncertainty_precedes_action"] = (
        selected.kind is InformationNeedKind.RESOLVE_UNCERTAINTY
    )
    checks["decision_basis_evidence_bound"] = (
        low_judgment.decision_basis.objective == low.contract.objective
        and bool(low_judgment.decision_basis.acceptance_target_ids)
        and bool(low_judgment.decision_basis.hard_constraints)
    )
    checks["critical_gap_visible_as_blocker"] = any(
        "UNVERIFIED" in item for item in low_judgment.decision_basis.blocker_refs
    )
    checks["high_risk_strengthens_verification"] = (
        high_strategy.depth is VerificationDepth.REGRESSION
        and high_strategy.minimum_strength_floor is EvidenceStrength.DETERMINISTIC
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
        information_gain=low_judgment.information_gain,
        verification=low_strategy,
    )
    checks["tool_advice_does_not_expand_authority"] = (
        set(advice.recommended_tool_names) == {item.name for item in tools}
        and "advisory_only_no_authority" in advice.reason_codes
    )
    checks["observe_before_infer_tool_order"] = advice.recommended_tool_names[0] == (
        "filesystem.read_text"
    )

    policy_source = (PROJECT_ROOT / "src/luna/runtime/policy_agent.py").read_text(encoding="utf-8")
    loop_source = (PROJECT_ROOT / "src/luna/runtime/loop.py").read_text(encoding="utf-8")
    checks["policy_model_receives_structured_advisory_context"] = (
        'name="local_judgment"' in policy_source
        and "advisory context" in policy_source
        and "Prefer direct observation over inference" in policy_source
    )
    checks["completion_policy_only_strengthened"] = (
        "minimum_strength=strategy.minimum_strength_floor" in loop_source
    )
    checks["no_runtime_authority_expansion"] = all(
        token not in (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        for rel in (
            "src/luna/planning/judgment.py",
            "src/luna/actions/advisory.py",
            "src/luna/verification/strategy.py",
        )
        for token in ("ToolDispatcher(", "CompletionGate(", "memory_service", "training")
    )

    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"{name}: {'PASS' if passed else 'FAIL'}")
    if failed:
        print("[REJECT] Wave 2 local-judgment foundation failed: " + ", ".join(failed))
        return 1
    print("[PASS] Wave 2 local-judgment foundation verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
