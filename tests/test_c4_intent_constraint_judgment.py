from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.autonomy import AutonomyPolicy
from luna.context import (
    ContextBudget,
    ContextCandidate,
    ContextClaimType,
    ContextSource,
    ContextSourceKind,
)
from luna.contracts import (
    AssumptionRecord,
    AssumptionStatus,
    ConstraintKind,
    ConstraintStrength,
    DecisionStateSnapshot,
    IntentConstraintJudgment,
    RiskLevel,
    SpecificationControlAction,
    TaskContract,
    TaskScope,
    TaskState,
)
from luna.contracts.enums import TaskPhase
from luna.contracts.plan import PlanStep
from luna.intent import DeterministicIntentResolver, IntentConstraintJudge
from luna.planning import AdaptivePlanner, DecisionControlAction, DecisionControlAdvisor
from luna.planning.judgment import LocalJudgmentBuilder
from luna.preparation import PreparationStatus, TaskPreparer
from luna.runtime import RuntimeRequest, build_task_fingerprint
from luna.runtime.identity_context import RequestSource, RuntimeActor
from luna.verification import VerificationStrategySelector


def _context(request: str) -> tuple[ContextCandidate, ...]:
    return (
        ContextCandidate(
            source=ContextSource.from_text(
                kind=ContextSourceKind.USER_MESSAGE,
                locator="user:request",
                text=request,
                verified=True,
            ),
            required=True,
            priority=100,
        ),
    )


def _prepare(
    request: str,
    *,
    required: tuple[str, ...] = ("Requested result is satisfied.",),
    forbidden: tuple[str, ...] = (),
    preferences: tuple[str, ...] = (),
    write_allowed: bool = False,
) -> object:
    return TaskPreparer().prepare(
        request=request,
        scope=TaskScope(
            workspace_root="C:/workspace",
            allowed_paths=("src/luna/example.py",) if write_allowed else (),
            write_allowed=write_allowed,
        ),
        context_candidates=_context(request),
        context_budget=ContextBudget(),
        required_conditions=required,
        forbidden_outcomes=forbidden,
        evidence_required=("Deterministic verification evidence.",),
        soft_preferences=preferences,
        risk_level=RiskLevel.LOW,
    )


def test_solution_shaped_request_reconstructs_to_explicit_outcome() -> None:
    preparation = _prepare(
        "Refactor src/luna/example.py to fix the bounded behavior.",
        required=("The bounded behavior is fixed.",),
        write_allowed=True,
    )
    judgment = preparation.specification_judgment

    assert preparation.status is PreparationStatus.READY_FOR_PLANNING
    assert judgment.action is SpecificationControlAction.RECONSTRUCT
    assert judgment.literal_objective.startswith("Refactor src/luna/example.py")
    assert judgment.reconstructed_objective == "The bounded behavior is fixed."
    assert judgment.solution_shaped_request
    assert judgment.raw_request_preserved
    assert not judgment.runtime_authority
    assert not judgment.execution_authority
    assert not judgment.completion_authority


def test_literal_request_remains_literal_when_no_solution_signal_exists() -> None:
    preparation = _prepare("Inspect the bounded runtime state.")
    judgment = preparation.specification_judgment

    assert judgment.action is SpecificationControlAction.ACCEPT_LITERAL
    assert judgment.reconstructed_objective == judgment.literal_objective
    assert not judgment.solution_shaped_request


def test_all_hard_constraints_keep_provenance_and_cannot_be_traded() -> None:
    preparation = _prepare(
        "Inspect the bounded runtime state.",
        forbidden=("Protected state changes.",),
        preferences=("Prefer concise output.",),
    )
    judgment = preparation.specification_judgment
    hard = tuple(
        item for item in judgment.constraints if item.strength is ConstraintStrength.HARD
    )
    assert hard
    assert set(judgment.preserved_hard_constraint_refs) == {
        item.constraint_id for item in hard
    }
    assert all(item.provenance_refs for item in hard)
    assert all(item.kind is not ConstraintKind.PREFERENCE for item in hard)


def test_soft_preference_conflicting_with_prohibition_is_traded_off() -> None:
    preparation = _prepare(
        "Inspect the bounded runtime state.",
        forbidden=("Modify README.md",),
        preferences=("Modify README.md", "Prefer concise output."),
    )
    judgment = preparation.specification_judgment
    constraints = {item.constraint_id: item for item in judgment.constraints}

    assert judgment.action is SpecificationControlAction.TRADE_OFF
    assert {constraints[ref].statement for ref in judgment.traded_off_preference_refs} == {
        "Modify README.md"
    }
    assert {constraints[ref].statement for ref in judgment.accepted_preference_refs} == {
        "Prefer concise output."
    }
    assert any(not conflict.hard_conflict for conflict in judgment.conflicts)
    assert not judgment.blocker_refs


def test_soft_preference_cannot_widen_runtime_authority() -> None:
    preparation = _prepare(
        "Inspect the bounded runtime state.",
        preferences=("write_allowed:true",),
    )
    judgment = preparation.specification_judgment

    assert judgment.action is SpecificationControlAction.TRADE_OFF
    assert judgment.traded_off_preference_refs
    assert "hard_constraint_wins_over_preference" in judgment.reason_codes


def test_soft_preferences_remain_advisory_and_outside_task_contract() -> None:
    preparation = _prepare(
        "Inspect the bounded runtime state.",
        preferences=("Prefer concise output.",),
    )

    assert preparation.contract is not None
    assert "soft_preferences" not in preparation.contract.model_dump(mode="json")
    assert preparation.specification_judgment.accepted_preference_refs


def test_hard_required_forbidden_conflict_stops_before_planning() -> None:
    request = "Inspect README.md."
    preparation = TaskPreparer().prepare(
        request=request,
        scope=TaskScope(workspace_root="C:/workspace"),
        context_candidates=_context(request),
        context_budget=ContextBudget(),
        required_conditions=("README must change.",),
        forbidden_outcomes=("README must change.",),
        evidence_required=("diff",),
    )

    assert preparation.status is PreparationStatus.NEEDS_CLARIFICATION
    assert preparation.contract is None
    assert preparation.specification_judgment.action is SpecificationControlAction.STOP_VERIFY
    assert preparation.specification_judgment.blocker_refs
    assert any(conflict.hard_conflict for conflict in preparation.specification_judgment.conflicts)


def test_critical_ambiguity_is_not_silently_invented() -> None:
    preparation = _prepare(
        "kodu refactor",
        required=("Bug is fixed.",),
        write_allowed=False,
    )

    assert preparation.status is PreparationStatus.NEEDS_CLARIFICATION
    assert preparation.contract is None
    assert preparation.specification_judgment.action is SpecificationControlAction.STOP_VERIFY
    assert any("write_scope" in ref for ref in preparation.specification_judgment.blocker_refs)


def test_planner_uses_reconstructed_objective_but_contract_stays_literal() -> None:
    preparation = _prepare(
        "Rewrite src/luna/example.py to restore bounded behavior.",
        required=("Bounded behavior is restored.",),
        write_allowed=True,
    )
    plan = AdaptivePlanner().plan(preparation)

    assert preparation.contract is not None
    assert preparation.contract.objective.startswith("Rewrite src/luna/example.py")
    assert plan.objective == "Bounded behavior is restored."


def test_task_state_rejects_specification_for_a_different_literal_objective() -> None:
    preparation = _prepare("Inspect the bounded runtime state.")
    assert preparation.contract is not None
    base = preparation.specification_judgment
    wrong_literal = "Different objective"
    wrong_fingerprint = IntentConstraintJudgment.compute_basis_fingerprint(
        task_id=base.task_id,
        request_fingerprint=base.request_fingerprint,
        literal_objective=wrong_literal,
        reconstructed_objective=wrong_literal,
        constraints=base.constraints,
        conflicts=base.conflicts,
        unresolved_ambiguities=base.unresolved_ambiguities,
    )
    wrong = IntentConstraintJudgment.model_validate(
        {
            **base.model_dump(mode="json"),
            "specification_basis_fingerprint": wrong_fingerprint,
            "literal_objective": wrong_literal,
            "reconstructed_objective": wrong_literal,
        }
    )

    with pytest.raises(ValidationError, match="literal objective"):
        TaskState(
            task_id=preparation.task_id,
            contract=preparation.contract,
            phase=TaskPhase.CONTRACTED,
            specification_judgment=wrong,
        )


def test_c4_basis_flows_into_c2_decision_basis() -> None:
    preparation = _prepare(
        "Refactor src/luna/example.py to fix bounded behavior.",
        required=("Bounded behavior is fixed.",),
        write_allowed=True,
    )
    assert preparation.contract is not None
    step = PlanStep(sequence=1, description="Inspect current state.")
    state = TaskState(
        task_id=preparation.task_id,
        contract=preparation.contract,
        phase=TaskPhase.PLANNED,
        plan=(step,),
        specification_judgment=preparation.specification_judgment,
    )
    verification = VerificationStrategySelector().select(
        contract=state.contract,
        step=step,
    )
    judgment = LocalJudgmentBuilder().build(
        state=state,
        step=step,
        verification_depth=verification.depth.value,
    )

    assert judgment.decision_basis.objective == "Bounded behavior is fixed."
    assert "risk_level:LOW" in judgment.decision_basis.hard_constraints
    assert "write_allowed:true" in judgment.decision_basis.hard_constraints
    assert "c4_specification_bound" in judgment.decision_basis.reason_codes


def test_c4_stop_verify_blocker_forces_c2_stop_verify() -> None:
    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Inspect the bounded target.",
        required_conditions=("Target is inspected.",),
        evidence_required=("Structured observation.",),
        scope=TaskScope(workspace_root="C:/workspace"),
    )
    base = IntentConstraintJudge().from_contract(
        raw_request=contract.objective,
        contract=contract,
    )
    unresolved = ("critical_goal",)
    fingerprint = IntentConstraintJudgment.compute_basis_fingerprint(
        task_id=base.task_id,
        request_fingerprint=base.request_fingerprint,
        literal_objective=base.literal_objective,
        reconstructed_objective=base.reconstructed_objective,
        constraints=base.constraints,
        conflicts=base.conflicts,
        unresolved_ambiguities=unresolved,
    )
    blocked = IntentConstraintJudgment.model_validate(
        {
            **base.model_dump(mode="json"),
            "specification_basis_fingerprint": fingerprint,
            "action": SpecificationControlAction.STOP_VERIFY.value,
            "unresolved_ambiguities": unresolved,
            "blocker_refs": ("c4:ambiguity:critical_goal",),
            "reason_codes": (
                "hard_constraints_preserved",
                "critical_specification_issue_requires_stop_verify",
            ),
        }
    )
    step = PlanStep(sequence=1, description="Inspect current state.")
    state = TaskState(
        task_id=task_id,
        contract=contract,
        phase=TaskPhase.PLANNED,
        plan=(step,),
        specification_judgment=blocked,
    )
    verification = VerificationStrategySelector().select(contract=contract, step=step)
    local = LocalJudgmentBuilder().build(
        state=state,
        step=step,
        verification_depth=verification.depth.value,
    )
    control = DecisionControlAdvisor()
    compression = control.compress(
        state=state,
        information_gain=local.information_gain,
        decision_basis=local.decision_basis,
    )
    alternatives = control.alternatives(state=state, compression=compression)
    assessment = control.assess(
        state=state,
        information_gain=local.information_gain,
        compression=compression,
        alternatives=alternatives,
    )

    assert assessment.action is DecisionControlAction.STOP_VERIFY
    assert "c4_specification_requires_stop_verify" in assessment.reason_codes


def test_soft_preferences_are_part_of_runtime_task_identity(tmp_path) -> None:
    task_id = uuid4()
    actor = RuntimeActor.verified_owner("owner")
    common = dict(
        task_id=task_id,
        raw_request="Inspect the bounded target.",
        source=RequestSource.TEST,
        actor=actor,
        scope=TaskScope(workspace_root=str(tmp_path)),
        autonomy=AutonomyPolicy(task_id=task_id),
        required_conditions=("Target is inspected.",),
        evidence_required=("Structured observation.",),
    )
    first = RuntimeRequest(**common, soft_preferences=("Prefer concise output.",))
    second = RuntimeRequest(**common, soft_preferences=("Prefer detailed output.",))

    assert build_task_fingerprint(first).digest != build_task_fingerprint(second).digest


def test_specification_basis_fingerprint_rejects_tampering() -> None:
    intent = DeterministicIntentResolver().resolve("Inspect the bounded target.")
    preparation = _prepare(intent.raw_request)
    judgment = preparation.specification_judgment

    payload = judgment.model_dump(mode="json")
    payload["specification_basis_fingerprint"] = sha256(b"tampered").hexdigest()
    with pytest.raises(ValidationError, match="basis fingerprint"):
        IntentConstraintJudgment.model_validate(payload)

def _state_with_assumptions(preparation, *assumptions: AssumptionRecord) -> TaskState:
    assert preparation.contract is not None
    return TaskState(
        task_id=preparation.task_id,
        contract=preparation.contract,
        phase=TaskPhase.CONTRACTED,
        decision_state=DecisionStateSnapshot(
            task_id=preparation.task_id,
            assumptions=assumptions,
        ),
        specification_judgment=preparation.specification_judgment,
    )


def test_verified_project_policy_becomes_hard_c4_constraint_with_provenance() -> None:
    preparation = _prepare("Inspect the bounded runtime state.")
    policy = AssumptionRecord(
        task_id=preparation.task_id,
        key="generated_files_policy",
        statement="Do not modify generated files.",
        claim_type=ContextClaimType.PROJECT_POLICY.value,
        critical=True,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("evidence:project-policy",),
        provenance_refs=("repo:CONTRIBUTING.md",),
    )
    state = _state_with_assumptions(preparation, policy)

    refined = IntentConstraintJudge().refine_from_state(
        base=preparation.specification_judgment,
        state=state,
    )
    project_constraints = tuple(
        item for item in refined.constraints if item.kind is ConstraintKind.PROJECT_POLICY
    )

    assert len(project_constraints) == 1
    project = project_constraints[0]
    assert project.strength is ConstraintStrength.HARD
    assert project.statement == "Do not modify generated files."
    assert "evidence:project-policy" in project.provenance_refs
    assert "repo:CONTRIBUTING.md" in project.provenance_refs
    assert project.constraint_id in refined.preserved_hard_constraint_refs
    assert f"c1:assumption:{policy.assumption_id}" in refined.context_basis_refs
    assert refined.specification_basis_fingerprint != (
        preparation.specification_judgment.specification_basis_fingerprint
    )
    assert "verified_project_policy_bound" in refined.reason_codes


def test_supported_repository_state_changes_basis_without_becoming_hard_constraint() -> None:
    preparation = _prepare("Inspect the bounded runtime state.")
    repository_state = AssumptionRecord(
        task_id=preparation.task_id,
        key="current_branch",
        statement="Current branch is cognition/c4-intent-constraint-judgment.",
        claim_type=ContextClaimType.REPOSITORY_STATE.value,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("git:branch:c4",),
        provenance_refs=("git:branch",),
    )
    state = _state_with_assumptions(preparation, repository_state)

    refined = IntentConstraintJudge().refine_from_state(
        base=preparation.specification_judgment,
        state=state,
    )

    assert f"c1:assumption:{repository_state.assumption_id}" in refined.context_basis_refs
    assert not any(
        item.kind is ConstraintKind.PROJECT_POLICY for item in refined.constraints
    )
    assert refined.specification_basis_fingerprint != (
        preparation.specification_judgment.specification_basis_fingerprint
    )
    assert refined.action is SpecificationControlAction.ACCEPT_LITERAL


def test_noncurrent_or_unsupported_project_policy_never_becomes_c4_authority() -> None:
    preparation = _prepare("Inspect the bounded runtime state.")
    historical = AssumptionRecord(
        task_id=preparation.task_id,
        key="project_policy",
        statement="Historical policy must not survive contradiction.",
        claim_type=ContextClaimType.PROJECT_POLICY.value,
        critical=True,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("evidence:old-policy",),
    )
    contradicted = AssumptionRecord(
        task_id=preparation.task_id,
        key="project_policy",
        statement="Historical policy must not survive contradiction.",
        claim_type=ContextClaimType.PROJECT_POLICY.value,
        critical=True,
        status=AssumptionStatus.CONTRADICTED,
        evidence_refs=("evidence:new-policy",),
        reason="authoritative policy evidence contradicted the previous basis",
    )
    unverified = AssumptionRecord(
        task_id=preparation.task_id,
        key="unverified_policy",
        statement="Unverified policy must not become a hard constraint.",
        claim_type=ContextClaimType.PROJECT_POLICY.value,
        critical=True,
        status=AssumptionStatus.UNVERIFIED,
    )
    state = _state_with_assumptions(
        preparation,
        historical,
        contradicted,
        unverified,
    )

    refined = IntentConstraintJudge().refine_from_state(
        base=preparation.specification_judgment,
        state=state,
    )

    assert not any(
        item.kind is ConstraintKind.PROJECT_POLICY for item in refined.constraints
    )
    assert not refined.context_basis_refs
    assert refined.specification_basis_fingerprint == (
        preparation.specification_judgment.specification_basis_fingerprint
    )



def test_verified_project_policy_cannot_widen_runtime_authority() -> None:
    preparation = _prepare("Inspect the bounded runtime state.")
    policy = AssumptionRecord(
        task_id=preparation.task_id,
        key="write_policy",
        statement="write_allowed:true",
        claim_type=ContextClaimType.PROJECT_POLICY.value,
        critical=True,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("evidence:write-policy",),
    )
    state = _state_with_assumptions(preparation, policy)

    refined = IntentConstraintJudge().refine_from_state(
        base=preparation.specification_judgment,
        state=state,
    )

    assert refined.action is SpecificationControlAction.STOP_VERIFY
    assert refined.blocker_refs
    assert any(
        conflict.hard_conflict
        and conflict.reason_code == "project_policy_cannot_widen_authority_boundary"
        for conflict in refined.conflicts
    )


def test_soft_preference_is_traded_against_verified_project_policy() -> None:
    preparation = _prepare(
        "Inspect the bounded runtime state.",
        preferences=("write_allowed:true",),
        write_allowed=True,
    )
    policy = AssumptionRecord(
        task_id=preparation.task_id,
        key="write_policy",
        statement="write_allowed:false",
        claim_type=ContextClaimType.PROJECT_POLICY.value,
        critical=True,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("evidence:write-policy",),
    )
    state = _state_with_assumptions(preparation, policy)

    refined = IntentConstraintJudge().refine_from_state(
        base=preparation.specification_judgment,
        state=state,
    )

    assert refined.action is SpecificationControlAction.TRADE_OFF
    assert refined.traded_off_preference_refs
    assert any(
        not conflict.hard_conflict
        and conflict.reason_code == "soft_preference_conflicts_with_project_policy"
        for conflict in refined.conflicts
    )
