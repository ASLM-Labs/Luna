from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from luna.context import (
    ContextAuthorityRole,
    ContextClaim,
    ContextClaimType,
    ContextIntegrityGate,
    ContextRequirement,
    ContextSourceKind,
    LayeredContextComposer,
)
from luna.contracts import (
    AssumptionRecord,
    AssumptionStatus,
    CompletionStatus,
    DecisionRecord,
    DecisionStateSnapshot,
    DecisionStatus,
    InvalidationControlAction,
    InvalidationLayer,
    PlanStep,
    PlanStepStatus,
    RiskLevel,
    TaskContract,
    TaskPhase,
    TaskScope,
    TaskState,
)
from luna.decision_state import DecisionStateService
from luna.planning import (
    DecisionCompression,
    DecisionControlAction,
    DecisionControlAdvisor,
    LocalJudgmentBuilder,
    TargetedInvalidationCoordinator,
)


def _state(task_id: UUID, *, plan: tuple[PlanStep, ...] = ()) -> TaskState:
    return TaskState(
        task_id=task_id,
        contract=TaskContract(
            task_id=task_id,
            objective="Exercise targeted cross-layer invalidation.",
            required_conditions=("Only dependent cognition is invalidated.",),
            evidence_required=("Changed-basis evidence is preserved.",),
            scope=TaskScope(workspace_root="C:/repo"),
            risk_level=RiskLevel.LOW,
        ),
        plan=plan,
        decision_state=DecisionStateSnapshot.empty(task_id),
    )


def _supported_assumption(
    *,
    task_id: UUID,
    key: str,
    evidence: str,
    critical: bool = False,
) -> AssumptionRecord:
    return AssumptionRecord(
        task_id=task_id,
        key=key,
        statement=f"{key}=old",
        claim_type=ContextClaimType.REPOSITORY_STATE.value,
        critical=critical,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=(evidence,),
        provenance_refs=(f"source:{key}:old",),
    )


def _seed_decision_state(
    *,
    state: TaskState,
    assumption: AssumptionRecord,
    decision: DecisionRecord,
    other_assumption: AssumptionRecord | None = None,
    other_decision: DecisionRecord | None = None,
) -> TaskState:
    service = DecisionStateService()
    assert state.decision_state is not None
    snapshot = service.record_assumption(state.decision_state, assumption)
    if other_assumption is not None:
        snapshot = service.record_assumption(snapshot, other_assumption)
    snapshot = service.record_decision(snapshot, decision)
    if other_decision is not None:
        snapshot = service.record_decision(snapshot, other_decision)
    return state.revise(decision_state=snapshot)


def _transition_assumption(
    *,
    state: TaskState,
    assumption_id: UUID,
    status: AssumptionStatus,
    reason: str,
) -> TaskState:
    service = DecisionStateService()
    assert state.decision_state is not None
    snapshot = service.transition_assumption(
        state.decision_state,
        assumption_id=assumption_id,
        status=status,
        reason=reason,
    )
    return state.revise(decision_state=snapshot)


def _impact_refs(report) -> set[str]:
    return {item.target_ref for item in report.impacts}


def test_assumption_invalidation_propagates_only_to_dependent_decision() -> None:
    task_id = uuid4()
    state = _state(task_id)
    affected_assumption = _supported_assumption(
        task_id=task_id,
        key="current_head",
        evidence="git:head:old",
    )
    other_assumption = _supported_assumption(
        task_id=task_id,
        key="artifact_path",
        evidence="path:desktop",
    )
    affected_decision = DecisionRecord(
        task_id=task_id,
        action_key="use-current-head",
        description="Use the current verified HEAD.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(affected_assumption.assumption_id,),
    )
    other_decision = DecisionRecord(
        task_id=task_id,
        action_key="use-artifact-path",
        description="Use the verified artifact path.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(other_assumption.assumption_id,),
    )
    previous = _seed_decision_state(
        state=state,
        assumption=affected_assumption,
        decision=affected_decision,
        other_assumption=other_assumption,
        other_decision=other_decision,
    )
    current = _transition_assumption(
        state=previous,
        assumption_id=affected_assumption.assumption_id,
        status=AssumptionStatus.CONTRADICTED,
        reason="fresh Git evidence contradicts the old HEAD",
    )

    report, revised = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=current,
        evidence_refs=("git:head:new",),
        provenance_refs=("git://head/new",),
    )

    affected_assumption_ref = f"assumption:{affected_assumption.assumption_id}"
    affected_decision_ref = f"decision:{affected_decision.decision_id}"
    other_assumption_ref = f"assumption:{other_assumption.assumption_id}"
    other_decision_ref = f"decision:{other_decision.decision_id}"
    assert report.control_action is InvalidationControlAction.REPLAN
    assert _impact_refs(report) == {affected_assumption_ref, affected_decision_ref}
    assert {other_assumption_ref, other_decision_ref}.issubset(report.preserved_refs)
    assert revised.invalidation_state is not None
    assert revised.invalidation_state.latest_report == report


def test_critical_assumption_invalidation_requires_stop_verify() -> None:
    task_id = uuid4()
    assumption = _supported_assumption(
        task_id=task_id,
        key="workspace_identity",
        evidence="workspace:old",
        critical=True,
    )
    decision = DecisionRecord(
        task_id=task_id,
        action_key="write-workspace",
        description="Write to the verified workspace.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(assumption.assumption_id,),
    )
    previous = _seed_decision_state(
        state=_state(task_id),
        assumption=assumption,
        decision=decision,
    )
    current = _transition_assumption(
        state=previous,
        assumption_id=assumption.assumption_id,
        status=AssumptionStatus.CONTRADICTED,
        reason="workspace identity changed",
    )

    report, _ = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=current,
        evidence_refs=("workspace:new",),
        provenance_refs=("runtime://workspace",),
    )

    assert report.control_action is InvalidationControlAction.STOP_VERIFY
    assert "critical_basis_requires_verification" in report.reason_codes
    assert report.changed_basis_required is True
    assert report.runtime_authority is False
    assert report.completion_authority is False


def test_plan_dependency_invalidation_blocks_only_transitive_dependents() -> None:
    task_id = uuid4()
    first = PlanStep(sequence=1, description="Inspect the repository.")
    second = PlanStep(
        sequence=2,
        description="Patch the repository.",
        depends_on=(first.step_id,),
    )
    third = PlanStep(
        sequence=3,
        description="Verify the patch.",
        depends_on=(second.step_id,),
    )
    independent = PlanStep(sequence=4, description="Prepare an unrelated note.")
    previous = _state(task_id, plan=(first, second, third, independent))
    failed_first = first.model_copy(
        update={"status": PlanStepStatus.FAILED, "status_reason": "inspection failed"}
    )
    current = previous.revise(plan=(failed_first, second, third, independent))

    report, revised = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=current,
        evidence_refs=("observation:inspection-failed",),
        provenance_refs=("tool://filesystem.read",),
    )

    by_id = {item.step_id: item for item in revised.plan}
    assert by_id[first.step_id].status is PlanStepStatus.FAILED
    assert by_id[second.step_id].status is PlanStepStatus.BLOCKED
    assert by_id[third.step_id].status is PlanStepStatus.BLOCKED
    assert by_id[independent.step_id].status is PlanStepStatus.PENDING
    assert f"plan_step:{independent.step_id}" in report.preserved_refs


def test_explicit_decision_subject_binding_invalidates_its_plan_step() -> None:
    task_id = uuid4()
    target_step = PlanStep(sequence=1, description="Apply the selected route.")
    unrelated = PlanStep(sequence=2, description="Independent documentation.")
    assumption = _supported_assumption(
        task_id=task_id,
        key="route_available",
        evidence="route:old",
    )
    decision = DecisionRecord(
        task_id=task_id,
        action_key="selected-route",
        description="Use route A.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(assumption.assumption_id,),
        subject_ref=f"plan_step:{target_step.step_id}",
    )
    previous = _seed_decision_state(
        state=_state(task_id, plan=(target_step, unrelated)),
        assumption=assumption,
        decision=decision,
    )
    current = _transition_assumption(
        state=previous,
        assumption_id=assumption.assumption_id,
        status=AssumptionStatus.SUPERSEDED,
        reason="route A was superseded",
    )

    report, revised = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=current,
        evidence_refs=("route:new",),
        provenance_refs=("router://selection",),
    )

    by_id = {item.step_id: item for item in revised.plan}
    assert by_id[target_step.step_id].status is PlanStepStatus.BLOCKED
    assert by_id[unrelated.step_id].status is PlanStepStatus.PENDING
    assert f"plan_step:{target_step.step_id}" in _impact_refs(report)


def test_c2_ephemeral_artifacts_are_invalidated_through_explicit_dependencies() -> None:
    task_id = uuid4()
    assumption = _supported_assumption(
        task_id=task_id,
        key="branch",
        evidence="branch:old",
    )
    decision = DecisionRecord(
        task_id=task_id,
        action_key="branch-route",
        description="Operate on the old branch.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(assumption.assumption_id,),
    )
    previous = _seed_decision_state(
        state=_state(task_id),
        assumption=assumption,
        decision=decision,
    )
    current = _transition_assumption(
        state=previous,
        assumption_id=assumption.assumption_id,
        status=AssumptionStatus.CONTRADICTED,
        reason="fresh branch evidence disagrees",
    )
    fingerprint = "a" * 64
    compression = DecisionCompression(
        task_id=task_id,
        step_id=uuid4(),
        source_task_state_revision=previous.revision,
        source_decision_state_revision=previous.decision_state.revision,  # type: ignore[union-attr]
        decision_basis_fingerprint=fingerprint,
        selected_information_need_id="information:sha256:" + "b" * 64,
        decision_question="Which route remains valid?",
        current_assumption_refs=(
            f"assumption:{assumption.assumption_id}:{AssumptionStatus.SUPPORTED.value}",
        ),
        current_decision_refs=(
            f"decision:{decision.decision_id}:{DecisionStatus.ACTIVE.value}",
        ),
        reason_codes=("fixture",),
    )
    alternatives = SimpleNamespace(decision_basis_fingerprint=fingerprint)
    retrieval = SimpleNamespace(
        strategy_fingerprint="c" * 64,
        decision_basis_fingerprint=fingerprint,
    )

    report, _ = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=current,
        evidence_refs=("branch:new",),
        provenance_refs=("git://branch",),
        compression=compression,
        alternatives=alternatives,
        retrieval_strategy=retrieval,
    )

    layers = {item.layer for item in report.impacts}
    assert InvalidationLayer.DECISION_COMPRESSION in layers
    assert InvalidationLayer.DECISION_ALTERNATIVES in layers
    assert InvalidationLayer.RETRIEVAL_STRATEGY in layers


def test_context_supersede_carries_new_evidence_into_c2_changed_basis() -> None:
    task_id = uuid4()
    service = DecisionStateService()
    old_assumption = _supported_assumption(
        task_id=task_id,
        key="current_head",
        evidence="git:head:old",
    )
    old_decision = DecisionRecord(
        task_id=task_id,
        action_key="use-old-head",
        description="Continue from the old HEAD.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(old_assumption.assumption_id,),
    )
    alternate = DecisionRecord(
        task_id=task_id,
        action_key="use-new-head",
        description="Use the refreshed HEAD.",
        status=DecisionStatus.PENDING,
    )
    state = _state(task_id)
    assert state.decision_state is not None
    snapshot = service.record_assumption(state.decision_state, old_assumption)
    snapshot = service.record_decision(snapshot, old_decision)
    snapshot = service.record_decision(snapshot, alternate)
    previous = state.revise(decision_state=snapshot)
    claim = ContextClaim(
        task_id=task_id,
        key="current_head",
        value="new",
        claim_type=ContextClaimType.REPOSITORY_STATE,
        source_kind=ContextSourceKind.COMMAND_OUTPUT,
        source_ref="git://head/new",
        authority_role=ContextAuthorityRole.CURRENT_OBSERVATION,
        observed_at=datetime(2026, 8, 14, 20, 0, tzinfo=UTC),
        verified=True,
        evidence_refs=("git:head:new",),
    )
    _, reconciled = ContextIntegrityGate(decision_state=service).evaluate(
        state=previous,
        bundle=LayeredContextComposer().compose(task_id=task_id, candidates=()),
        claims=(claim,),
        requirements=(
            ContextRequirement(
                key="current_head",
                claim_type=ContextClaimType.REPOSITORY_STATE,
                critical=False,
            ),
        ),
    )
    report, current = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=reconciled,
        evidence_refs=claim.evidence_refs,
        provenance_refs=(claim.source_ref,),
    )
    assert "git:head:new" in report.changed_basis_evidence_refs
    assert "git:head:old" not in report.changed_basis_evidence_refs

    step = PlanStep(sequence=1, description="Choose the current HEAD route.")
    current = current.revise(plan=(step,))
    judgment = LocalJudgmentBuilder().build(
        state=current,
        step=step,
        verification_depth="TARGETED",
    )
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=current,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    alternatives = advisor.alternatives(state=current, compression=compression)
    control = advisor.assess(
        state=current,
        information_gain=judgment.information_gain,
        compression=compression,
        alternatives=alternatives,
    )

    assert "git:head:new" in compression.decision_changing_evidence_refs
    assert compression.evidence_bound_invalidated_decision_refs
    assert "c3_changed_basis_evidence_applied" in compression.reason_codes
    assert control.action is DecisionControlAction.SWITCH


def test_completion_claim_is_marked_stale_without_granting_completion_authority() -> None:
    task_id = uuid4()
    step = PlanStep(
        sequence=1,
        description="Previously verified work.",
        status=PlanStepStatus.COMPLETE,
    )
    previous = _state(task_id, plan=(step,)).model_copy(
        update={
            "phase": TaskPhase.REPORTING,
            "completion_status": CompletionStatus.VERIFIED_COMPLETE,
        }
    )
    failed_step = step.model_copy(
        update={"status": PlanStepStatus.FAILED, "status_reason": "new evidence failed"}
    )
    current = previous.revise(plan=(failed_step,))

    report, revised = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=current,
        evidence_refs=("verification:new-failure",),
        provenance_refs=("verification://rerun",),
    )

    assert report.completion_claim_stale is True
    assert report.control_action is InvalidationControlAction.STOP_VERIFY
    assert report.completion_authority is False
    assert revised.completion_status is CompletionStatus.VERIFIED_COMPLETE
    assert any(
        item.layer is InvalidationLayer.COMPLETION_CLAIM for item in report.impacts
    )


def test_no_new_invalidation_preserves_state_revision_and_does_not_persist_report() -> None:
    task_id = uuid4()
    state = _state(task_id)

    report, same = TargetedInvalidationCoordinator().reconcile(
        previous_state=state,
        current_state=state,
    )

    assert report.control_action is InvalidationControlAction.NONE
    assert report.impacts == ()
    assert same is state
    assert same.invalidation_state is None


def test_stale_state_delta_is_rejected_before_invalidation() -> None:
    task_id = uuid4()
    old = _state(task_id)
    newer = old.revise()

    with pytest.raises(ValueError, match="stale task-state revision"):
        TargetedInvalidationCoordinator().reconcile(
            previous_state=newer,
            current_state=old,
            provenance_refs=("fixture://stale",),
        )


def test_invalidation_requires_evidence_or_provenance() -> None:
    task_id = uuid4()
    step = PlanStep(sequence=1, description="Fail without evidence.")
    previous = _state(task_id, plan=(step,))
    current = previous.revise(
        plan=(
            step.model_copy(
                update={"status": PlanStepStatus.FAILED, "status_reason": "failed"}
            ),
        )
    )

    with pytest.raises(ValueError, match="requires evidence or provenance"):
        TargetedInvalidationCoordinator().reconcile(
            previous_state=previous,
            current_state=current,
        )


def test_unrelated_completed_plan_step_survives_other_branch_invalidation() -> None:
    task_id = uuid4()
    root_a = PlanStep(sequence=1, description="Branch A root.")
    child_a = PlanStep(sequence=2, description="Branch A child.", depends_on=(root_a.step_id,))
    root_b = PlanStep(
        sequence=3,
        description="Independent branch B.",
        status=PlanStepStatus.COMPLETE,
    )
    previous = _state(task_id, plan=(root_a, child_a, root_b))
    current = previous.revise(
        plan=(
            root_a.model_copy(
                update={"status": PlanStepStatus.FAILED, "status_reason": "branch A failed"}
            ),
            child_a,
            root_b,
        )
    )

    report, revised = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=current,
        evidence_refs=("observation:branch-a-failed",),
        provenance_refs=("tool://branch-a",),
    )

    by_id = {item.step_id: item for item in revised.plan}
    assert by_id[child_a.step_id].status is PlanStepStatus.BLOCKED
    assert by_id[root_b.step_id].status is PlanStepStatus.COMPLETE
    assert f"plan_step:{root_b.step_id}" in report.preserved_refs


def test_persisted_old_report_is_not_reemitted_as_new_invalidation() -> None:
    task_id = uuid4()
    root = PlanStep(sequence=1, description="Root basis.")
    child = PlanStep(sequence=2, description="Dependent work.", depends_on=(root.step_id,))
    previous = _state(task_id, plan=(root, child))
    current = previous.revise(
        plan=(
            root.model_copy(
                update={"status": PlanStepStatus.FAILED, "status_reason": "observed failure"}
            ),
            child,
        )
    )
    first_report, revised = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=current,
        evidence_refs=("observation:root-failed",),
        provenance_refs=("tool://root",),
    )
    assert first_report.control_action is InvalidationControlAction.REPLAN
    assert revised.invalidation_state is not None

    no_op_report, same = TargetedInvalidationCoordinator().reconcile(
        previous_state=revised,
        current_state=revised,
    )

    assert no_op_report.control_action is InvalidationControlAction.NONE
    assert no_op_report.impacts == ()
    assert no_op_report.trigger_refs == ()
    assert same is revised
    assert same.invalidation_state is revised.invalidation_state
    assert same.invalidation_state.latest_report == first_report


def test_evidence_alone_cannot_invalidate_unchanged_newer_basis() -> None:
    task_id = uuid4()
    assumption = _supported_assumption(
        task_id=task_id,
        key="current_head",
        evidence="git:head:new",
    )
    decision = DecisionRecord(
        task_id=task_id,
        action_key="build",
        description="Build from the newer verified HEAD.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(assumption.assumption_id,),
    )
    state = _seed_decision_state(
        state=_state(task_id),
        assumption=assumption,
        decision=decision,
    )

    report, same = TargetedInvalidationCoordinator().reconcile(
        previous_state=state,
        current_state=state,
        evidence_refs=("git:head:stale",),
        provenance_refs=("fixture://stale-observation",),
    )

    assert report.control_action is InvalidationControlAction.NONE
    assert report.impacts == ()
    assert same is state
    assert same.decision_state is not None
    assert same.decision_state.decisions[0].status is DecisionStatus.ACTIVE


def test_task_state_rejects_invalidation_report_from_future_revision() -> None:
    task_id = uuid4()
    root = PlanStep(sequence=1, description="Root basis.")
    previous = _state(task_id, plan=(root,))
    current = previous.revise(
        plan=(
            root.model_copy(
                update={"status": PlanStepStatus.FAILED, "status_reason": "observed failure"}
            ),
        )
    )
    _, revised = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=current,
        evidence_refs=("observation:root-failed",),
        provenance_refs=("tool://root",),
    )
    assert revised.invalidation_state is not None

    stale_payload = previous.model_dump(mode="json")
    stale_payload["invalidation_state"] = revised.invalidation_state.model_dump(mode="json")
    with pytest.raises(ValueError, match="future task revision"):
        TaskState.model_validate(stale_payload)


def test_c3_binds_changed_evidence_only_to_the_impacted_decision_basis() -> None:
    task_id = uuid4()
    service = DecisionStateService()
    head = _supported_assumption(
        task_id=task_id,
        key="current_head",
        evidence="git:head:old",
    )
    artifact = _supported_assumption(
        task_id=task_id,
        key="artifact_path",
        evidence="path:old",
    )
    decision = DecisionRecord(
        task_id=task_id,
        action_key="use-old-head",
        description="Continue from the old HEAD.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(head.assumption_id,),
    )
    alternate = DecisionRecord(
        task_id=task_id,
        action_key="use-new-head",
        description="Use the refreshed HEAD.",
        status=DecisionStatus.PENDING,
    )
    state = _state(task_id)
    assert state.decision_state is not None
    snapshot = service.record_assumption(state.decision_state, head)
    snapshot = service.record_assumption(snapshot, artifact)
    snapshot = service.record_decision(snapshot, decision)
    snapshot = service.record_decision(snapshot, alternate)
    previous = state.revise(decision_state=snapshot)

    head_claim = ContextClaim(
        task_id=task_id,
        key="current_head",
        value="new",
        claim_type=ContextClaimType.REPOSITORY_STATE,
        source_kind=ContextSourceKind.COMMAND_OUTPUT,
        source_ref="git://head/new",
        authority_role=ContextAuthorityRole.CURRENT_OBSERVATION,
        observed_at=datetime(2026, 8, 14, 20, 0, tzinfo=UTC),
        verified=True,
        evidence_refs=("git:head:new",),
    )
    artifact_claim = ContextClaim(
        task_id=task_id,
        key="artifact_path",
        value="desktop",
        claim_type=ContextClaimType.REPOSITORY_STATE,
        source_kind=ContextSourceKind.COMMAND_OUTPUT,
        source_ref="path://desktop/new",
        authority_role=ContextAuthorityRole.CURRENT_OBSERVATION,
        observed_at=datetime(2026, 8, 14, 20, 0, tzinfo=UTC),
        verified=True,
        evidence_refs=("path:desktop:new",),
    )
    claims = (head_claim, artifact_claim)
    _, reconciled = ContextIntegrityGate(decision_state=service).evaluate(
        state=previous,
        bundle=LayeredContextComposer().compose(task_id=task_id, candidates=()),
        claims=claims,
        requirements=(
            ContextRequirement(
                key="current_head",
                claim_type=ContextClaimType.REPOSITORY_STATE,
                critical=False,
            ),
            ContextRequirement(
                key="artifact_path",
                claim_type=ContextClaimType.REPOSITORY_STATE,
                critical=False,
            ),
        ),
    )
    report, current = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=reconciled,
        evidence_refs=tuple(ref for claim in claims for ref in claim.evidence_refs),
        provenance_refs=tuple(claim.source_ref for claim in claims),
    )
    decision_ref = TargetedInvalidationCoordinator.decision_ref(decision.decision_id)
    decision_impact = next(item for item in report.impacts if item.target_ref == decision_ref)
    assert "git:head:new" in decision_impact.changed_basis_evidence_refs
    assert "path:desktop:new" not in decision_impact.changed_basis_evidence_refs
    assert f"context:{artifact_claim.claim_id}" not in decision_impact.changed_basis_evidence_refs

    step = PlanStep(sequence=1, description="Choose the current HEAD route.")
    current = current.revise(plan=(step,))
    judgment = LocalJudgmentBuilder().build(
        state=current,
        step=step,
        verification_depth="TARGETED",
    )
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=current,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    assert "git:head:new" in compression.decision_changing_evidence_refs
    assert "path:desktop:new" not in compression.decision_changing_evidence_refs
    assert f"context:{artifact_claim.claim_id}" not in compression.decision_changing_evidence_refs


def test_unrelated_evidence_or_observation_is_not_promoted_to_changed_basis() -> None:
    task_id = uuid4()
    assumption = _supported_assumption(
        task_id=task_id,
        key="current_head",
        evidence="git:head:old",
    )
    decision = DecisionRecord(
        task_id=task_id,
        action_key="use-old-head",
        description="Continue from the old HEAD.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(assumption.assumption_id,),
    )
    alternate = DecisionRecord(
        task_id=task_id,
        action_key="use-new-head",
        description="Use another route.",
        status=DecisionStatus.PENDING,
    )
    state = _state(task_id)
    previous = _seed_decision_state(
        state=state,
        assumption=assumption,
        decision=decision,
        other_decision=alternate,
    )
    invalidated = _transition_assumption(
        state=previous,
        assumption_id=assumption.assumption_id,
        status=AssumptionStatus.INVALIDATED,
        reason="The basis is no longer admissible.",
    )
    unrelated_observation = uuid4()
    invalidated = invalidated.revise(observation_ids=(unrelated_observation,))
    report, current = TargetedInvalidationCoordinator().reconcile(
        previous_state=previous,
        current_state=invalidated,
        evidence_refs=("evidence:unrelated",),
        provenance_refs=("runtime:unrelated",),
    )
    assert report.changed_basis_evidence_refs == ()
    decision_ref = TargetedInvalidationCoordinator.decision_ref(decision.decision_id)
    decision_impact = next(item for item in report.impacts if item.target_ref == decision_ref)
    assert decision_impact.changed_basis_evidence_refs == ()

    step = PlanStep(sequence=1, description="Choose a route after invalidation.")
    current = current.revise(plan=(step,))
    judgment = LocalJudgmentBuilder().build(
        state=current,
        step=step,
        verification_depth="TARGETED",
    )
    advisor = DecisionControlAdvisor()
    compression = advisor.compress(
        state=current,
        information_gain=judgment.information_gain,
        decision_basis=judgment.decision_basis,
    )
    alternatives = advisor.alternatives(state=current, compression=compression)
    control = advisor.assess(
        state=current,
        information_gain=judgment.information_gain,
        compression=compression,
        alternatives=alternatives,
    )
    assert compression.decision_changing_evidence_refs == ()
    assert control.action is DecisionControlAction.STOP_VERIFY
    assert "invalidated_decision_lacks_changed_basis_evidence" in control.reason_codes
