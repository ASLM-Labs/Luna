from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

import luna.planning as package
from luna.contracts import (
    DecisionStateSnapshot,
    PlanStep,
    RiskLevel,
    TaskContract,
    TaskScope,
    TaskState,
)
from luna.decision_state import (
    KnowledgeDecisionStateIntegrationDisposition,
    KnowledgeDecisionStateIntegrationResult,
)
from luna.knowledge_evolution import (
    KnowledgeReevaluationAdvisoryKind,
)
from luna.planning import (
    InformationGainPlan,
    InformationNeed,
    InformationNeedKind,
    KnowledgeInformationGainRefresh,
    KnowledgeInformationGainRefresher,
)

KNOWLEDGE_REF = "memory://record/a"


def _state():
    task_id = uuid4()
    step = PlanStep(
        sequence=1,
        description="Inspect the current decision basis.",
    )

    state = TaskState(
        task_id=task_id,
        contract=TaskContract(
            task_id=task_id,
            objective="Refresh information gain safely.",
            required_conditions=(
                "Knowledge signals remain non-authoritative.",
            ),
            evidence_required=(
                "Owner-validated signal provenance is preserved.",
            ),
            scope=TaskScope(
                workspace_root="C:/repo",
            ),
            risk_level=RiskLevel.LOW,
        ),
        plan=(step,),
        decision_state=DecisionStateSnapshot.empty(
            task_id
        ),
    )

    return state, step


def _need(
    *,
    suffix: str,
    kind: InformationNeedKind,
    priority: int,
) -> InformationNeed:
    return InformationNeed(
        need_id=(
            "information:sha256:"
            + suffix * 64
        ),
        kind=kind,
        description=f"fixture information need {suffix}",
        acceptance_target_ids=(
            "acceptance://fixture",
        ),
        priority=priority,
    )


def _plan(
    *,
    state: TaskState,
    step: PlanStep,
    priority: int = 80,
    kind: InformationNeedKind = (
        InformationNeedKind.OBSERVE_STATE
    ),
) -> InformationGainPlan:
    need = _need(
        suffix="1",
        kind=kind,
        priority=priority,
    )

    return InformationGainPlan(
        task_id=state.task_id,
        step_id=step.step_id,
        needs=(need,),
        selected_need_id=need.need_id,
        reason_codes=("fixture_base_plan",),
    )


def _integration(
    *,
    state: TaskState,
    disposition: (
        KnowledgeDecisionStateIntegrationDisposition
    ),
) -> KnowledgeDecisionStateIntegrationResult:
    assert state.decision_state is not None

    if (
        disposition
        is KnowledgeDecisionStateIntegrationDisposition
        .VERIFY_STOP_DEFERRED
    ):
        advisory_kind = (
            KnowledgeReevaluationAdvisoryKind
            .VERIFY_STOP_CANDIDATE
        )
        verify = True
        reevaluation = False
        mutation = False
    elif (
        disposition
        is KnowledgeDecisionStateIntegrationDisposition
        .REEVALUATION_DEFERRED
    ):
        advisory_kind = (
            KnowledgeReevaluationAdvisoryKind
            .REEVALUATION_CANDIDATE
        )
        verify = False
        reevaluation = True
        mutation = False
    else:
        advisory_kind = (
            KnowledgeReevaluationAdvisoryKind
            .INVALIDATION_CANDIDATE
        )
        verify = False
        reevaluation = False
        mutation = (
            disposition
            is KnowledgeDecisionStateIntegrationDisposition
            .CONTRADICTION_APPLIED
        )

    revision = state.decision_state.revision

    if mutation:
        raise AssertionError(
            "fixture uses non-mutating contradiction disposition"
        )

    return KnowledgeDecisionStateIntegrationResult(
        task_id=state.task_id,
        knowledge_ref=KNOWLEDGE_REF,
        assumption_id=uuid4(),
        advisory_kind=advisory_kind,
        disposition=disposition,
        input_revision=revision,
        output_revision=revision,
        affected_decision_ids=(),
        evidence_refs=(
            ("evidence://ke",)
            if reevaluation
            else ()
        ),
        provenance_refs=(
            "owner://decision-state-ke-adapter",
        ),
        mutation_applied=False,
        verify_stop_candidate=verify,
        reevaluation_candidate=reevaluation,
    )


def test_f2_refresh_surface_is_publicly_exported() -> None:
    assert (
        package.KnowledgeInformationGainRefresh
        is KnowledgeInformationGainRefresh
    )
    assert (
        package.KnowledgeInformationGainRefresher
        is KnowledgeInformationGainRefresher
    )


def test_verify_stop_deferred_adds_priority_100_uncertainty_need() -> None:
    state, step = _state()
    plan = _plan(
        state=state,
        step=step,
    )

    integration = _integration(
        state=state,
        disposition=(
            KnowledgeDecisionStateIntegrationDisposition
            .VERIFY_STOP_DEFERRED
        ),
    )

    refresh = KnowledgeInformationGainRefresher().refresh(
        state=state,
        plan=plan,
        integration=integration,
    )

    selected = next(
        item
        for item in refresh.refreshed_plan.needs
        if (
            item.need_id
            == refresh.refreshed_plan.selected_need_id
        )
    )

    assert refresh.information_need_present is True
    assert refresh.plan_changed is True
    assert refresh.selected_need_changed is True
    assert (
        selected.kind
        is InformationNeedKind.RESOLVE_UNCERTAINTY
    )
    assert selected.priority == 100
    assert (
        "ke_verify_stop_candidate_prioritized"
        in refresh.refreshed_plan.reason_codes
    )
    assert refresh.verification_authority is False
    assert refresh.decision_control_authority is False


def test_existing_priority_100_uncertainty_is_not_displaced_by_equal_ke_need() -> None:
    state, step = _state()

    plan = _plan(
        state=state,
        step=step,
        priority=100,
        kind=InformationNeedKind.RESOLVE_UNCERTAINTY,
    )

    integration = _integration(
        state=state,
        disposition=(
            KnowledgeDecisionStateIntegrationDisposition
            .VERIFY_STOP_DEFERRED
        ),
    )

    refresh = KnowledgeInformationGainRefresher().refresh(
        state=state,
        plan=plan,
        integration=integration,
    )

    assert (
        refresh.refreshed_plan.selected_need_id
        == plan.selected_need_id
    )
    assert refresh.selected_need_changed is False
    assert len(refresh.refreshed_plan.needs) == 2


def test_reevaluation_deferred_adds_priority_95_observation_need() -> None:
    state, step = _state()
    plan = _plan(
        state=state,
        step=step,
    )

    integration = _integration(
        state=state,
        disposition=(
            KnowledgeDecisionStateIntegrationDisposition
            .REEVALUATION_DEFERRED
        ),
    )

    refresh = KnowledgeInformationGainRefresher().refresh(
        state=state,
        plan=plan,
        integration=integration,
    )

    selected = next(
        item
        for item in refresh.refreshed_plan.needs
        if (
            item.need_id
            == refresh.refreshed_plan.selected_need_id
        )
    )

    assert selected.kind is InformationNeedKind.OBSERVE_STATE
    assert selected.priority == 95
    assert refresh.selected_need_changed is True
    assert refresh.evidence_refs == (
        "evidence://ke",
    )
    assert (
        "ke_reevaluation_candidate_prioritized"
        in refresh.refreshed_plan.reason_codes
    )


def test_priority_100_critical_need_stays_ahead_of_reevaluation() -> None:
    state, step = _state()

    plan = _plan(
        state=state,
        step=step,
        priority=100,
        kind=InformationNeedKind.RESOLVE_UNCERTAINTY,
    )

    integration = _integration(
        state=state,
        disposition=(
            KnowledgeDecisionStateIntegrationDisposition
            .REEVALUATION_DEFERRED
        ),
    )

    refresh = KnowledgeInformationGainRefresher().refresh(
        state=state,
        plan=plan,
        integration=integration,
    )

    assert (
        refresh.refreshed_plan.selected_need_id
        == plan.selected_need_id
    )
    assert refresh.selected_need_changed is False


def test_refresh_is_idempotent_for_same_owner_signal() -> None:
    state, step = _state()
    plan = _plan(
        state=state,
        step=step,
    )

    integration = _integration(
        state=state,
        disposition=(
            KnowledgeDecisionStateIntegrationDisposition
            .REEVALUATION_DEFERRED
        ),
    )

    first = KnowledgeInformationGainRefresher().refresh(
        state=state,
        plan=plan,
        integration=integration,
    )

    second = KnowledgeInformationGainRefresher().refresh(
        state=state,
        plan=first.refreshed_plan,
        integration=integration,
    )

    assert (
        second.refreshed_plan
        == first.refreshed_plan
    )
    assert second.plan_changed is False
    assert second.selected_need_changed is False


def test_non_deferred_contradiction_result_does_not_duplicate_state_logic() -> None:
    state, step = _state()
    plan = _plan(
        state=state,
        step=step,
    )

    integration = _integration(
        state=state,
        disposition=(
            KnowledgeDecisionStateIntegrationDisposition
            .CONTRADICTION_ALREADY_REFLECTED
        ),
    )

    refresh = KnowledgeInformationGainRefresher().refresh(
        state=state,
        plan=plan,
        integration=integration,
    )

    assert refresh.refreshed_plan is plan
    assert refresh.information_need_present is False
    assert refresh.plan_changed is False
    assert refresh.selected_need_changed is False


def test_stale_f4_result_is_rejected() -> None:
    state, step = _state()
    plan = _plan(
        state=state,
        step=step,
    )

    integration = _integration(
        state=state,
        disposition=(
            KnowledgeDecisionStateIntegrationDisposition
            .VERIFY_STOP_DEFERRED
        ),
    ).model_copy(
        update={
            "output_revision": 99,
            "input_revision": 99,
        }
    )

    with pytest.raises(
        ValueError,
        match="stale KE-F4 integration result",
    ):
        KnowledgeInformationGainRefresher().refresh(
            state=state,
            plan=plan,
            integration=integration,
        )


def test_cross_task_owner_output_is_rejected() -> None:
    state, step = _state()
    plan = _plan(
        state=state,
        step=step,
    )

    integration = _integration(
        state=state,
        disposition=(
            KnowledgeDecisionStateIntegrationDisposition
            .VERIFY_STOP_DEFERRED
        ),
    ).model_copy(
        update={
            "task_id": uuid4(),
        }
    )

    with pytest.raises(
        ValueError,
        match="owner-output task mismatch",
    ):
        KnowledgeInformationGainRefresher().refresh(
            state=state,
            plan=plan,
            integration=integration,
        )


def test_forged_owner_output_kind_is_rejected() -> None:
    state, step = _state()
    plan = _plan(
        state=state,
        step=step,
    )

    integration = _integration(
        state=state,
        disposition=(
            KnowledgeDecisionStateIntegrationDisposition
            .VERIFY_STOP_DEFERRED
        ),
    ).model_copy(
        update={
            "advisory_kind": (
                KnowledgeReevaluationAdvisoryKind
                .REEVALUATION_CANDIDATE
            ),
        }
    )

    with pytest.raises(
        ValueError,
        match="inconsistent advisory kind",
    ):
        KnowledgeInformationGainRefresher().refresh(
            state=state,
            plan=plan,
            integration=integration,
        )


@pytest.mark.parametrize(
    "field",
    (
        "truth_authority",
        "verification_authority",
        "planning_authority",
        "decision_control_authority",
        "ranking_authority",
        "decision_mutation_authority",
        "memory_mutation_authority",
        "execution_authority",
        "runtime_authority",
    ),
)
def test_f2_refresh_cannot_escalate_authority(
    field: str,
) -> None:
    state, step = _state()
    plan = _plan(
        state=state,
        step=step,
    )

    integration = _integration(
        state=state,
        disposition=(
            KnowledgeDecisionStateIntegrationDisposition
            .REEVALUATION_DEFERRED
        ),
    )

    refresh = KnowledgeInformationGainRefresher().refresh(
        state=state,
        plan=plan,
        integration=integration,
    )

    payload = refresh.model_dump(
        mode="python"
    )
    payload[field] = True

    with pytest.raises(ValidationError):
        KnowledgeInformationGainRefresh.model_validate(
            payload
        )
