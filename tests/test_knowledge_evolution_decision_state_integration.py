from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

import luna.decision_state as package
from luna.contracts import (
    AssumptionRecord,
    AssumptionStatus,
    DecisionRecord,
    DecisionStateSnapshot,
    DecisionStatus,
)
from luna.decision_state import (
    DecisionStateKnowledgeEvolutionAdapter,
    DecisionStateService,
    KnowledgeDecisionStateBinding,
    KnowledgeDecisionStateIntegrationDisposition,
    KnowledgeDecisionStateIntegrationResult,
)
from luna.knowledge_evolution import (
    KnowledgeApplicabilitySignal,
    KnowledgeApplicabilitySignalState,
    KnowledgeOptionSpaceChangeSignal,
    KnowledgeReevaluationAdvisory,
    KnowledgeValiditySignal,
    KnowledgeValiditySignalState,
    project_knowledge_reevaluation_advisory,
)

KNOWLEDGE_REF = "memory://record/a"


def _advisory(
    *,
    validity: KnowledgeValiditySignalState,
    applicability: KnowledgeApplicabilitySignalState,
    material_change: bool,
) -> KnowledgeReevaluationAdvisory:
    validity_signal = KnowledgeValiditySignal(
        knowledge_ref=KNOWLEDGE_REF,
        state=validity,
        source_ref="verification://validity",
        evidence_refs=(
            ()
            if validity
            is KnowledgeValiditySignalState.UNRESOLVED
            else ("evidence://validity",)
        ),
        provenance_refs=("owner://verification",),
    )

    applicability_signal = KnowledgeApplicabilitySignal(
        knowledge_ref=KNOWLEDGE_REF,
        state=applicability,
        source_ref="context://applicability",
        condition_refs=("constraint://windows",),
        evidence_refs=(
            ()
            if applicability
            is KnowledgeApplicabilitySignalState.UNRESOLVED
            else ("evidence://applicability",)
        ),
        provenance_refs=("owner://context",),
    )

    option_space = KnowledgeOptionSpaceChangeSignal(
        knowledge_ref=KNOWLEDGE_REF,
        material_change=material_change,
        source_ref="planner://option-space",
        evidence_refs=(
            ("evidence://option-space",)
            if material_change
            else ()
        ),
        provenance_refs=("owner://planner",),
    )

    advisory = project_knowledge_reevaluation_advisory(
        validity=validity_signal,
        applicability=applicability_signal,
        option_space_change=option_space,
    )

    assert advisory is not None
    return advisory


def _decision_fixture():
    task_id = uuid4()
    service = DecisionStateService()
    snapshot = DecisionStateSnapshot.empty(task_id)

    assumption = AssumptionRecord(
        task_id=task_id,
        key="knowledge-record-a",
        statement="record a remains semantically valid",
        claim_type="KNOWLEDGE_VALIDITY",
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("evidence://old",),
        provenance_refs=("owner://decision-state",),
    )

    snapshot = service.record_assumption(
        snapshot,
        assumption,
    )

    active = DecisionRecord(
        task_id=task_id,
        action_key="use-record-a",
        description="Use record A for the current route.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(assumption.assumption_id,),
    )

    completed = DecisionRecord(
        task_id=task_id,
        action_key="historical-record-a",
        description="Historical work already completed.",
        status=DecisionStatus.COMPLETED,
        assumption_ids=(assumption.assumption_id,),
    )

    unrelated = DecisionRecord(
        task_id=task_id,
        action_key="unrelated-route",
        description="Independent current route.",
        status=DecisionStatus.ACTIVE,
    )

    snapshot = service.record_decision(
        snapshot,
        active,
    )
    snapshot = service.record_decision(
        snapshot,
        completed,
    )
    snapshot = service.record_decision(
        snapshot,
        unrelated,
    )

    binding = KnowledgeDecisionStateBinding(
        task_id=task_id,
        knowledge_ref=KNOWLEDGE_REF,
        assumption_id=assumption.assumption_id,
        provenance_refs=("binding://knowledge-to-assumption",),
    )

    return (
        service,
        snapshot,
        assumption,
        active,
        completed,
        unrelated,
        binding,
    )


def test_ke_f4_surface_is_publicly_exported() -> None:
    assert (
        package.DecisionStateKnowledgeEvolutionAdapter
        is DecisionStateKnowledgeEvolutionAdapter
    )
    assert (
        package.KnowledgeDecisionStateBinding
        is KnowledgeDecisionStateBinding
    )
    assert (
        package.KnowledgeDecisionStateIntegrationDisposition
        is KnowledgeDecisionStateIntegrationDisposition
    )
    assert (
        package.KnowledgeDecisionStateIntegrationResult
        is KnowledgeDecisionStateIntegrationResult
    )


def test_invalidation_candidate_is_applied_only_by_decisionstate_owner() -> None:
    (
        _,
        snapshot,
        assumption,
        active,
        completed,
        unrelated,
        binding,
    ) = _decision_fixture()

    advisory = _advisory(
        validity=KnowledgeValiditySignalState.CONTRADICTED,
        applicability=KnowledgeApplicabilitySignalState.APPLICABLE,
        material_change=False,
    )

    result, revised = (
        DecisionStateKnowledgeEvolutionAdapter().integrate(
            snapshot=snapshot,
            advisory=advisory,
            binding=binding,
        )
    )

    assert (
        result.disposition
        is KnowledgeDecisionStateIntegrationDisposition.CONTRADICTION_APPLIED
    )
    assert result.mutation_applied is True
    assert revised.revision == snapshot.revision + 1
    assert result.affected_decision_ids == (
        active.decision_id,
    )

    by_assumption_id = {
        item.assumption_id: item
        for item in revised.assumptions
    }
    updated = by_assumption_id[
        assumption.assumption_id
    ]

    assert updated.status is AssumptionStatus.CONTRADICTED
    assert {
        "evidence://old",
        "evidence://validity",
        "evidence://applicability",
    }.issubset(set(updated.evidence_refs))

    assert (
        "binding://knowledge-to-assumption"
        in updated.provenance_refs
    )

    by_decision_id = {
        item.decision_id: item
        for item in revised.decisions
    }

    assert (
        by_decision_id[active.decision_id].status
        is DecisionStatus.INVALIDATED
    )
    assert (
        by_decision_id[completed.decision_id].status
        is DecisionStatus.COMPLETED
    )
    assert (
        by_decision_id[unrelated.decision_id].status
        is DecisionStatus.ACTIVE
    )

    assert result.truth_authority is False
    assert result.verification_authority is False
    assert result.ranking_authority is False
    assert result.invalidation_authority is False
    assert result.stop_authority is False
    assert result.decision_mutation_authority is False
    assert result.runtime_authority is False


def test_repeated_contradiction_does_not_create_revision_churn() -> None:
    (
        _,
        snapshot,
        _,
        _,
        _,
        _,
        binding,
    ) = _decision_fixture()

    advisory = _advisory(
        validity=KnowledgeValiditySignalState.CONTRADICTED,
        applicability=KnowledgeApplicabilitySignalState.APPLICABLE,
        material_change=False,
    )

    adapter = DecisionStateKnowledgeEvolutionAdapter()

    _, revised = adapter.integrate(
        snapshot=snapshot,
        advisory=advisory,
        binding=binding,
    )

    result, same = adapter.integrate(
        snapshot=revised,
        advisory=advisory,
        binding=binding,
    )

    assert same is revised
    assert (
        result.disposition
        is KnowledgeDecisionStateIntegrationDisposition
        .CONTRADICTION_ALREADY_REFLECTED
    )
    assert result.mutation_applied is False
    assert result.input_revision == result.output_revision
    assert result.affected_decision_ids == ()


def test_verify_stop_candidate_is_deferred_without_mutation() -> None:
    (
        _,
        snapshot,
        _,
        active,
        _,
        _,
        binding,
    ) = _decision_fixture()

    advisory = _advisory(
        validity=KnowledgeValiditySignalState.UNRESOLVED,
        applicability=KnowledgeApplicabilitySignalState.APPLICABLE,
        material_change=False,
    )

    result, same = (
        DecisionStateKnowledgeEvolutionAdapter().integrate(
            snapshot=snapshot,
            advisory=advisory,
            binding=binding,
        )
    )

    assert same is snapshot
    assert (
        result.disposition
        is KnowledgeDecisionStateIntegrationDisposition
        .VERIFY_STOP_DEFERRED
    )
    assert result.mutation_applied is False
    assert result.verify_stop_candidate is True
    assert result.stop_authority is False

    decision = next(
        item
        for item in same.decisions
        if item.decision_id == active.decision_id
    )
    assert decision.status is DecisionStatus.ACTIVE


def test_reevaluation_candidate_is_deferred_without_mutation() -> None:
    (
        _,
        snapshot,
        _,
        active,
        _,
        _,
        binding,
    ) = _decision_fixture()

    advisory = _advisory(
        validity=KnowledgeValiditySignalState.SUPPORTED,
        applicability=KnowledgeApplicabilitySignalState.APPLICABLE,
        material_change=True,
    )

    result, same = (
        DecisionStateKnowledgeEvolutionAdapter().integrate(
            snapshot=snapshot,
            advisory=advisory,
            binding=binding,
        )
    )

    assert same is snapshot
    assert (
        result.disposition
        is KnowledgeDecisionStateIntegrationDisposition
        .REEVALUATION_DEFERRED
    )
    assert result.mutation_applied is False
    assert result.reevaluation_candidate is True
    assert result.ranking_authority is False

    decision = next(
        item
        for item in same.decisions
        if item.decision_id == active.decision_id
    )
    assert decision.status is DecisionStatus.ACTIVE


def test_cross_task_binding_is_rejected() -> None:
    (
        _,
        snapshot,
        assumption,
        _,
        _,
        _,
        _,
    ) = _decision_fixture()

    binding = KnowledgeDecisionStateBinding(
        task_id=uuid4(),
        knowledge_ref=KNOWLEDGE_REF,
        assumption_id=assumption.assumption_id,
        provenance_refs=("binding://wrong-task",),
    )

    advisory = _advisory(
        validity=KnowledgeValiditySignalState.CONTRADICTED,
        applicability=KnowledgeApplicabilitySignalState.APPLICABLE,
        material_change=False,
    )

    with pytest.raises(
        ValueError,
        match="binding task",
    ):
        DecisionStateKnowledgeEvolutionAdapter().integrate(
            snapshot=snapshot,
            advisory=advisory,
            binding=binding,
        )


def test_cross_knowledge_binding_is_rejected() -> None:
    (
        _,
        snapshot,
        assumption,
        _,
        _,
        _,
        _,
    ) = _decision_fixture()

    binding = KnowledgeDecisionStateBinding(
        task_id=snapshot.task_id,
        knowledge_ref="memory://record/b",
        assumption_id=assumption.assumption_id,
        provenance_refs=("binding://wrong-record",),
    )

    advisory = _advisory(
        validity=KnowledgeValiditySignalState.CONTRADICTED,
        applicability=KnowledgeApplicabilitySignalState.APPLICABLE,
        material_change=False,
    )

    with pytest.raises(
        ValueError,
        match="knowledge ref",
    ):
        DecisionStateKnowledgeEvolutionAdapter().integrate(
            snapshot=snapshot,
            advisory=advisory,
            binding=binding,
        )


def test_unknown_assumption_binding_is_rejected() -> None:
    (
        _,
        snapshot,
        _,
        _,
        _,
        _,
        _,
    ) = _decision_fixture()

    binding = KnowledgeDecisionStateBinding(
        task_id=snapshot.task_id,
        knowledge_ref=KNOWLEDGE_REF,
        assumption_id=uuid4(),
        provenance_refs=("binding://missing",),
    )

    advisory = _advisory(
        validity=KnowledgeValiditySignalState.CONTRADICTED,
        applicability=KnowledgeApplicabilitySignalState.APPLICABLE,
        material_change=False,
    )

    with pytest.raises(
        ValueError,
        match="unknown DecisionState assumption",
    ):
        DecisionStateKnowledgeEvolutionAdapter().integrate(
            snapshot=snapshot,
            advisory=advisory,
            binding=binding,
        )


def test_historical_assumption_binding_is_rejected() -> None:
    (
        service,
        snapshot,
        assumption,
        _,
        _,
        _,
        binding,
    ) = _decision_fixture()

    current_assumption = next(
        item
        for item in snapshot.assumptions
        if item.assumption_id == assumption.assumption_id
    )

    replacement = AssumptionRecord(
        task_id=snapshot.task_id,
        key=current_assumption.key,
        statement="record a has a newer current basis",
        claim_type=current_assumption.claim_type,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("evidence://replacement",),
        provenance_refs=("owner://replacement",),
    )

    superseded = service.supersede_and_record(
        snapshot,
        previous=current_assumption,
        replacement=replacement,
        reason="new current knowledge basis",
    )

    advisory = _advisory(
        validity=KnowledgeValiditySignalState.CONTRADICTED,
        applicability=KnowledgeApplicabilitySignalState.APPLICABLE,
        material_change=False,
    )

    with pytest.raises(
        ValueError,
        match="must target current",
    ):
        DecisionStateKnowledgeEvolutionAdapter().integrate(
            snapshot=superseded,
            advisory=advisory,
            binding=binding,
        )


def test_forged_invalidation_kind_cannot_bypass_external_state() -> None:
    (
        _,
        snapshot,
        _,
        _,
        _,
        _,
        binding,
    ) = _decision_fixture()

    advisory = _advisory(
        validity=KnowledgeValiditySignalState.CONTRADICTED,
        applicability=KnowledgeApplicabilitySignalState.APPLICABLE,
        material_change=False,
    )

    forged = advisory.model_copy(
        update={
            "validity_state": (
                KnowledgeValiditySignalState.SUPPORTED
            )
        }
    )

    with pytest.raises(
        ValueError,
        match="requires CONTRADICTED",
    ):
        DecisionStateKnowledgeEvolutionAdapter().integrate(
            snapshot=snapshot,
            advisory=forged,
            binding=binding,
        )


def test_forged_reevaluation_kind_cannot_bypass_material_change() -> None:
    (
        _,
        snapshot,
        _,
        _,
        _,
        _,
        binding,
    ) = _decision_fixture()

    advisory = _advisory(
        validity=KnowledgeValiditySignalState.SUPPORTED,
        applicability=KnowledgeApplicabilitySignalState.APPLICABLE,
        material_change=True,
    )

    forged = advisory.model_copy(
        update={
            "material_option_space_change": False,
        }
    )

    with pytest.raises(
        ValueError,
        match="material change",
    ):
        DecisionStateKnowledgeEvolutionAdapter().integrate(
            snapshot=snapshot,
            advisory=forged,
            binding=binding,
        )


@pytest.mark.parametrize(
    "field",
    (
        "truth_authority",
        "verification_authority",
        "ranking_authority",
        "decision_mutation_authority",
        "runtime_authority",
    ),
)
def test_binding_cannot_escalate_authority(
    field: str,
) -> None:
    (
        _,
        snapshot,
        assumption,
        _,
        _,
        _,
        _,
    ) = _decision_fixture()

    payload = {
        "task_id": snapshot.task_id,
        "knowledge_ref": KNOWLEDGE_REF,
        "assumption_id": assumption.assumption_id,
        "provenance_refs": ("binding://fixture",),
        field: True,
    }

    with pytest.raises(ValidationError):
        KnowledgeDecisionStateBinding.model_validate(
            payload
        )
