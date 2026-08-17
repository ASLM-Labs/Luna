"""KE-F1 relation-contract foundation tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

import luna.knowledge_evolution as package
from luna.knowledge_evolution import (
    KnowledgeApplicabilitySignal,
    KnowledgeApplicabilitySignalState,
    KnowledgeEvolutionProjection,
    KnowledgeEvolutionRelation,
    KnowledgeEvolutionRelationKind,
    KnowledgeOptionSpaceChangeSignal,
    KnowledgeReevaluationAdvisory,
    KnowledgeReevaluationAdvisoryKind,
    KnowledgeValiditySignal,
    KnowledgeValiditySignalState,
    project_knowledge_reevaluation_advisory,
)


def _relation(
    *,
    source: str = "knowledge://a",
    target: str = "knowledge://b",
    kind: KnowledgeEvolutionRelationKind = (
        KnowledgeEvolutionRelationKind.ALTERNATIVE_TO
    ),
    applicability: tuple[str, ...] = (),
) -> KnowledgeEvolutionRelation:
    return KnowledgeEvolutionRelation(
        source_ref=source,
        target_ref=target,
        relation_kind=kind,
        applicability_refs=applicability,
        evidence_refs=("evidence://observed",),
        provenance_refs=("owner://canonical",),
        observed_at=datetime(
            2026,
            1,
            1,
            tzinfo=UTC,
        ),
    )


def test_ke_foundation_is_publicly_exported() -> None:
    assert (
        package.KnowledgeEvolutionRelation
        is KnowledgeEvolutionRelation
    )
    assert (
        package.KnowledgeEvolutionProjection
        is KnowledgeEvolutionProjection
    )
    assert (
        package.KnowledgeEvolutionRelationKind
        is KnowledgeEvolutionRelationKind
    )


def test_relation_kind_set_is_exactly_boundary_frozen() -> None:
    assert {
        item.value
        for item in KnowledgeEvolutionRelationKind
    } == {
        "ALTERNATIVE_TO",
        "EXTENDS",
        "COEXISTS_WITH",
        "REPLACES_UNDER",
        "INCOMPATIBLE_WITH",
        "DERIVED_FROM",
    }


def test_relation_carries_no_truth_ranking_or_runtime_authority() -> None:
    relation = _relation()

    assert relation.truth_authority is False
    assert relation.verification_authority is False
    assert relation.ranking_authority is False
    assert relation.execution_authority is False
    assert relation.runtime_authority is False


@pytest.mark.parametrize(
    "field",
    (
        "truth_authority",
        "verification_authority",
        "ranking_authority",
        "execution_authority",
        "runtime_authority",
    ),
)
def test_relation_authority_cannot_be_escalated(
    field: str,
) -> None:
    payload = {
        "source_ref": "knowledge://a",
        "target_ref": "knowledge://b",
        "relation_kind": "ALTERNATIVE_TO",
        "evidence_refs": ("evidence://observed",),
        "provenance_refs": ("owner://canonical",),
        field: True,
    }

    with pytest.raises(ValidationError):
        KnowledgeEvolutionRelation.model_validate(
            payload
        )


def test_relation_requires_external_evidence_and_provenance() -> None:
    with pytest.raises(ValidationError):
        KnowledgeEvolutionRelation(
            source_ref="knowledge://a",
            target_ref="knowledge://b",
            relation_kind=(
                KnowledgeEvolutionRelationKind.EXTENDS
            ),
            evidence_refs=(),
            provenance_refs=("owner://canonical",),
        )

    with pytest.raises(ValidationError):
        KnowledgeEvolutionRelation(
            source_ref="knowledge://a",
            target_ref="knowledge://b",
            relation_kind=(
                KnowledgeEvolutionRelationKind.EXTENDS
            ),
            evidence_refs=("evidence://observed",),
            provenance_refs=(),
        )


def test_relation_cannot_self_reference() -> None:
    with pytest.raises(
        ValidationError,
        match="cannot self-reference",
    ):
        _relation(
            source="knowledge://same",
            target="knowledge://same",
        )


def test_replaces_under_requires_explicit_applicability() -> None:
    with pytest.raises(
        ValidationError,
        match="requires explicit applicability",
    ):
        _relation(
            kind=(
                KnowledgeEvolutionRelationKind.REPLACES_UNDER
            )
        )

    relation = _relation(
        kind=(
            KnowledgeEvolutionRelationKind.REPLACES_UNDER
        ),
        applicability=(
            "constraint://runtime/windows",
        ),
    )

    assert relation.applicability_refs == (
        "constraint://runtime/windows",
    )


def test_relation_refs_are_normalized_without_ranking() -> None:
    relation = KnowledgeEvolutionRelation(
        source_ref=" knowledge://a ",
        target_ref=" knowledge://b ",
        relation_kind=(
            KnowledgeEvolutionRelationKind.EXTENDS
        ),
        applicability_refs=(
            "constraint://z",
            "constraint://a",
        ),
        evidence_refs=(
            "evidence://z",
            "evidence://a",
        ),
        provenance_refs=(
            "owner://z",
            "owner://a",
        ),
    )

    assert relation.source_ref == "knowledge://a"
    assert relation.target_ref == "knowledge://b"

    assert relation.applicability_refs == (
        "constraint://a",
        "constraint://z",
    )

    assert relation.evidence_refs == (
        "evidence://a",
        "evidence://z",
    )

    assert relation.provenance_refs == (
        "owner://a",
        "owner://z",
    )


def test_projection_has_no_authority() -> None:
    projection = KnowledgeEvolutionProjection(
        task_id=uuid4(),
        source_task_state_revision=4,
        relations=(_relation(),),
    )

    assert projection.truth_authority is False
    assert projection.verification_authority is False
    assert projection.ranking_authority is False
    assert projection.execution_authority is False
    assert projection.runtime_authority is False


def test_symmetric_relation_reverse_is_duplicate_semantics() -> None:
    first = _relation(
        source="knowledge://a",
        target="knowledge://b",
        kind=(
            KnowledgeEvolutionRelationKind.ALTERNATIVE_TO
        ),
    )

    reverse = _relation(
        source="knowledge://b",
        target="knowledge://a",
        kind=(
            KnowledgeEvolutionRelationKind.ALTERNATIVE_TO
        ),
    )

    with pytest.raises(
        ValidationError,
        match="duplicate semantic relations",
    ):
        KnowledgeEvolutionProjection(
            task_id=uuid4(),
            source_task_state_revision=1,
            relations=(
                first,
                reverse,
            ),
        )


def test_directional_reverse_relations_remain_distinct() -> None:
    forward = _relation(
        source="knowledge://a",
        target="knowledge://b",
        kind=KnowledgeEvolutionRelationKind.EXTENDS,
    )

    reverse = _relation(
        source="knowledge://b",
        target="knowledge://a",
        kind=KnowledgeEvolutionRelationKind.EXTENDS,
    )

    projection = KnowledgeEvolutionProjection(
        task_id=uuid4(),
        source_task_state_revision=2,
        relations=(
            forward,
            reverse,
        ),
    )

    assert projection.relations == (
        forward,
        reverse,
    )


def test_same_relation_with_different_evidence_is_one_semantic_relation() -> None:
    first = _relation()

    second = first.model_copy(
        update={
            "evidence_refs": (
                "evidence://independent-second",
            ),
            "provenance_refs": (
                "owner://second",
            ),
        }
    )

    with pytest.raises(
        ValidationError,
        match="duplicate semantic relations",
    ):
        KnowledgeEvolutionProjection(
            task_id=uuid4(),
            source_task_state_revision=3,
            relations=(
                first,
                second,
            ),
        )



def test_ke_f2_signal_types_are_publicly_exported() -> None:
    assert (
        package.KnowledgeValiditySignal
        is KnowledgeValiditySignal
    )
    assert (
        package.KnowledgeValiditySignalState
        is KnowledgeValiditySignalState
    )
    assert (
        package.KnowledgeApplicabilitySignal
        is KnowledgeApplicabilitySignal
    )
    assert (
        package.KnowledgeApplicabilitySignalState
        is KnowledgeApplicabilitySignalState
    )


def test_validity_signal_state_set_is_boundary_frozen() -> None:
    assert {
        item.value
        for item in KnowledgeValiditySignalState
    } == {
        "SUPPORTED",
        "CONTRADICTED",
        "UNRESOLVED",
    }


def test_applicability_signal_state_set_is_boundary_frozen() -> None:
    assert {
        item.value
        for item in KnowledgeApplicabilitySignalState
    } == {
        "APPLICABLE",
        "INAPPLICABLE",
        "UNRESOLVED",
    }


@pytest.mark.parametrize(
    "state",
    (
        KnowledgeValiditySignalState.SUPPORTED,
        KnowledgeValiditySignalState.CONTRADICTED,
    ),
)
def test_resolved_validity_signal_requires_external_evidence(
    state: KnowledgeValiditySignalState,
) -> None:
    with pytest.raises(
        ValidationError,
        match="requires external evidence",
    ):
        KnowledgeValiditySignal(
            knowledge_ref="memory://record/a",
            state=state,
            source_ref="verification://validity",
            evidence_refs=(),
            provenance_refs=("owner://memory",),
        )


def test_unresolved_validity_does_not_invent_missing_evidence() -> None:
    signal = KnowledgeValiditySignal(
        knowledge_ref="memory://record/a",
        state=KnowledgeValiditySignalState.UNRESOLVED,
        source_ref="verification://validity",
        evidence_refs=(),
        provenance_refs=("owner://memory",),
    )

    assert signal.evidence_refs == ()
    assert signal.truth_authority is False
    assert signal.verification_authority is False
    assert signal.ranking_authority is False


@pytest.mark.parametrize(
    "state",
    (
        KnowledgeApplicabilitySignalState.APPLICABLE,
        KnowledgeApplicabilitySignalState.INAPPLICABLE,
    ),
)
def test_resolved_applicability_requires_external_evidence(
    state: KnowledgeApplicabilitySignalState,
) -> None:
    with pytest.raises(
        ValidationError,
        match="requires external evidence",
    ):
        KnowledgeApplicabilitySignal(
            knowledge_ref="memory://record/a",
            state=state,
            source_ref="context://applicability",
            condition_refs=("constraint://windows",),
            evidence_refs=(),
            provenance_refs=("owner://context",),
        )


def test_applicability_always_requires_explicit_conditions() -> None:
    with pytest.raises(ValidationError):
        KnowledgeApplicabilitySignal(
            knowledge_ref="memory://record/a",
            state=(
                KnowledgeApplicabilitySignalState.UNRESOLVED
            ),
            source_ref="context://applicability",
            condition_refs=(),
            evidence_refs=(),
            provenance_refs=("owner://context",),
        )


def test_unresolved_applicability_is_not_selection_authority() -> None:
    signal = KnowledgeApplicabilitySignal(
        knowledge_ref="memory://record/a",
        state=(
            KnowledgeApplicabilitySignalState.UNRESOLVED
        ),
        source_ref="context://applicability",
        condition_refs=(
            "constraint://runtime/windows",
        ),
        evidence_refs=(),
        provenance_refs=("owner://context",),
    )

    assert signal.evidence_refs == ()
    assert signal.ranking_authority is False
    assert signal.execution_authority is False
    assert signal.runtime_authority is False


def test_signal_refs_are_normalized_deterministically() -> None:
    validity = KnowledgeValiditySignal(
        knowledge_ref=" memory://record/a ",
        state=KnowledgeValiditySignalState.SUPPORTED,
        source_ref=" verification://validity ",
        evidence_refs=(
            "evidence://z",
            "evidence://a",
        ),
        provenance_refs=(
            "owner://z",
            "owner://a",
        ),
    )

    applicability = KnowledgeApplicabilitySignal(
        knowledge_ref=" memory://record/a ",
        state=(
            KnowledgeApplicabilitySignalState.APPLICABLE
        ),
        source_ref=" context://applicability ",
        condition_refs=(
            "constraint://z",
            "constraint://a",
        ),
        evidence_refs=(
            "evidence://z",
            "evidence://a",
        ),
        provenance_refs=(
            "owner://z",
            "owner://a",
        ),
    )

    assert validity.knowledge_ref == "memory://record/a"
    assert validity.source_ref == "verification://validity"
    assert validity.evidence_refs == (
        "evidence://a",
        "evidence://z",
    )
    assert validity.provenance_refs == (
        "owner://a",
        "owner://z",
    )

    assert applicability.knowledge_ref == "memory://record/a"
    assert applicability.source_ref == "context://applicability"
    assert applicability.condition_refs == (
        "constraint://a",
        "constraint://z",
    )


@pytest.mark.parametrize(
    "field",
    (
        "truth_authority",
        "verification_authority",
        "ranking_authority",
        "execution_authority",
        "runtime_authority",
    ),
)
def test_external_signals_cannot_escalate_authority(
    field: str,
) -> None:
    validity_payload = {
        "knowledge_ref": "memory://record/a",
        "state": "SUPPORTED",
        "source_ref": "verification://validity",
        "evidence_refs": ("evidence://a",),
        "provenance_refs": ("owner://memory",),
        field: True,
    }

    applicability_payload = {
        "knowledge_ref": "memory://record/a",
        "state": "APPLICABLE",
        "source_ref": "context://applicability",
        "condition_refs": ("constraint://windows",),
        "evidence_refs": ("evidence://a",),
        "provenance_refs": ("owner://context",),
        field: True,
    }

    with pytest.raises(ValidationError):
        KnowledgeValiditySignal.model_validate(
            validity_payload
        )

    with pytest.raises(ValidationError):
        KnowledgeApplicabilitySignal.model_validate(
            applicability_payload
        )



def _ke_f3_validity(
    state: KnowledgeValiditySignalState,
) -> KnowledgeValiditySignal:
    evidence_refs = (
        ()
        if state is KnowledgeValiditySignalState.UNRESOLVED
        else ("evidence://validity",)
    )

    return KnowledgeValiditySignal(
        knowledge_ref="memory://record/a",
        state=state,
        source_ref="verification://validity",
        evidence_refs=evidence_refs,
        provenance_refs=("owner://verification",),
    )


def _ke_f3_applicability(
    state: KnowledgeApplicabilitySignalState,
) -> KnowledgeApplicabilitySignal:
    evidence_refs = (
        ()
        if state is KnowledgeApplicabilitySignalState.UNRESOLVED
        else ("evidence://applicability",)
    )

    return KnowledgeApplicabilitySignal(
        knowledge_ref="memory://record/a",
        state=state,
        source_ref="context://applicability",
        condition_refs=("constraint://windows",),
        evidence_refs=evidence_refs,
        provenance_refs=("owner://context",),
    )


def _ke_f3_option_space(
    *,
    material_change: bool,
) -> KnowledgeOptionSpaceChangeSignal:
    return KnowledgeOptionSpaceChangeSignal(
        knowledge_ref="memory://record/a",
        material_change=material_change,
        source_ref="planner://option-space",
        evidence_refs=(
            ("evidence://option-space",)
            if material_change
            else ()
        ),
        provenance_refs=("owner://planner",),
    )


def test_ke_f3_surface_is_publicly_exported() -> None:
    assert (
        package.KnowledgeOptionSpaceChangeSignal
        is KnowledgeOptionSpaceChangeSignal
    )
    assert (
        package.KnowledgeReevaluationAdvisory
        is KnowledgeReevaluationAdvisory
    )
    assert (
        package.KnowledgeReevaluationAdvisoryKind
        is KnowledgeReevaluationAdvisoryKind
    )
    assert (
        package.project_knowledge_reevaluation_advisory
        is project_knowledge_reevaluation_advisory
    )


def test_ke_f3_advisory_kind_set_is_boundary_frozen() -> None:
    assert {
        item.value
        for item in KnowledgeReevaluationAdvisoryKind
    } == {
        "INVALIDATION_CANDIDATE",
        "VERIFY_STOP_CANDIDATE",
        "REEVALUATION_CANDIDATE",
    }


def test_material_option_space_change_requires_external_evidence() -> None:
    with pytest.raises(
        ValidationError,
        match="requires external evidence",
    ):
        KnowledgeOptionSpaceChangeSignal(
            knowledge_ref="memory://record/a",
            material_change=True,
            source_ref="planner://option-space",
            evidence_refs=(),
            provenance_refs=("owner://planner",),
        )


def test_nonmaterial_option_space_change_does_not_invent_evidence() -> None:
    signal = _ke_f3_option_space(
        material_change=False,
    )

    assert signal.evidence_refs == ()
    assert signal.truth_authority is False
    assert signal.verification_authority is False
    assert signal.ranking_authority is False
    assert signal.execution_authority is False
    assert signal.runtime_authority is False


def test_contradicted_becomes_invalidation_candidate() -> None:
    advisory = project_knowledge_reevaluation_advisory(
        validity=_ke_f3_validity(
            KnowledgeValiditySignalState.CONTRADICTED
        ),
        applicability=_ke_f3_applicability(
            KnowledgeApplicabilitySignalState.APPLICABLE
        ),
        option_space_change=_ke_f3_option_space(
            material_change=False
        ),
    )

    assert advisory is not None
    assert (
        advisory.kind
        is KnowledgeReevaluationAdvisoryKind.INVALIDATION_CANDIDATE
    )
    assert advisory.invalidation_authority is False
    assert advisory.decision_mutation_authority is False


def test_unresolved_validity_becomes_verify_stop_candidate() -> None:
    advisory = project_knowledge_reevaluation_advisory(
        validity=_ke_f3_validity(
            KnowledgeValiditySignalState.UNRESOLVED
        ),
        applicability=_ke_f3_applicability(
            KnowledgeApplicabilitySignalState.APPLICABLE
        ),
        option_space_change=_ke_f3_option_space(
            material_change=False
        ),
    )

    assert advisory is not None
    assert (
        advisory.kind
        is KnowledgeReevaluationAdvisoryKind.VERIFY_STOP_CANDIDATE
    )
    assert advisory.stop_authority is False
    assert advisory.verification_authority is False


def test_unresolved_applicability_becomes_verify_stop_candidate() -> None:
    advisory = project_knowledge_reevaluation_advisory(
        validity=_ke_f3_validity(
            KnowledgeValiditySignalState.SUPPORTED
        ),
        applicability=_ke_f3_applicability(
            KnowledgeApplicabilitySignalState.UNRESOLVED
        ),
        option_space_change=_ke_f3_option_space(
            material_change=False
        ),
    )

    assert advisory is not None
    assert (
        advisory.kind
        is KnowledgeReevaluationAdvisoryKind.VERIFY_STOP_CANDIDATE
    )


def test_contradiction_precedes_unresolved_candidate_projection() -> None:
    advisory = project_knowledge_reevaluation_advisory(
        validity=_ke_f3_validity(
            KnowledgeValiditySignalState.CONTRADICTED
        ),
        applicability=_ke_f3_applicability(
            KnowledgeApplicabilitySignalState.UNRESOLVED
        ),
        option_space_change=_ke_f3_option_space(
            material_change=False
        ),
    )

    assert advisory is not None
    assert (
        advisory.kind
        is KnowledgeReevaluationAdvisoryKind.INVALIDATION_CANDIDATE
    )


def test_supported_applicable_material_change_becomes_reevaluation_candidate() -> None:
    advisory = project_knowledge_reevaluation_advisory(
        validity=_ke_f3_validity(
            KnowledgeValiditySignalState.SUPPORTED
        ),
        applicability=_ke_f3_applicability(
            KnowledgeApplicabilitySignalState.APPLICABLE
        ),
        option_space_change=_ke_f3_option_space(
            material_change=True
        ),
    )

    assert advisory is not None
    assert (
        advisory.kind
        is KnowledgeReevaluationAdvisoryKind.REEVALUATION_CANDIDATE
    )
    assert advisory.material_option_space_change is True
    assert advisory.ranking_authority is False


def test_supported_applicable_without_material_change_has_no_advisory() -> None:
    advisory = project_knowledge_reevaluation_advisory(
        validity=_ke_f3_validity(
            KnowledgeValiditySignalState.SUPPORTED
        ),
        applicability=_ke_f3_applicability(
            KnowledgeApplicabilitySignalState.APPLICABLE
        ),
        option_space_change=_ke_f3_option_space(
            material_change=False
        ),
    )

    assert advisory is None


def test_inapplicable_material_change_does_not_become_reevaluation_candidate() -> None:
    advisory = project_knowledge_reevaluation_advisory(
        validity=_ke_f3_validity(
            KnowledgeValiditySignalState.SUPPORTED
        ),
        applicability=_ke_f3_applicability(
            KnowledgeApplicabilitySignalState.INAPPLICABLE
        ),
        option_space_change=_ke_f3_option_space(
            material_change=True
        ),
    )

    assert advisory is None


def test_ke_f3_rejects_cross_knowledge_signal_binding() -> None:
    applicability = _ke_f3_applicability(
        KnowledgeApplicabilitySignalState.APPLICABLE
    ).model_copy(
        update={
            "knowledge_ref": "memory://record/b",
        }
    )

    with pytest.raises(
        ValueError,
        match="same knowledge ref",
    ):
        project_knowledge_reevaluation_advisory(
            validity=_ke_f3_validity(
                KnowledgeValiditySignalState.SUPPORTED
            ),
            applicability=applicability,
            option_space_change=_ke_f3_option_space(
                material_change=True
            ),
        )


def test_ke_f3_advisory_preserves_external_basis_deterministically() -> None:
    validity = KnowledgeValiditySignal(
        knowledge_ref="memory://record/a",
        state=KnowledgeValiditySignalState.SUPPORTED,
        source_ref="verification://validity",
        evidence_refs=(
            "evidence://z",
            "evidence://a",
        ),
        provenance_refs=(
            "owner://z",
            "owner://a",
        ),
    )

    applicability = KnowledgeApplicabilitySignal(
        knowledge_ref="memory://record/a",
        state=KnowledgeApplicabilitySignalState.APPLICABLE,
        source_ref="context://applicability",
        condition_refs=(
            "constraint://z",
            "constraint://a",
        ),
        evidence_refs=(
            "evidence://b",
            "evidence://a",
        ),
        provenance_refs=(
            "owner://context",
            "owner://a",
        ),
    )

    option_space = KnowledgeOptionSpaceChangeSignal(
        knowledge_ref="memory://record/a",
        material_change=True,
        source_ref="planner://option-space",
        evidence_refs=(
            "evidence://option-space",
            "evidence://b",
        ),
        provenance_refs=(
            "owner://planner",
            "owner://context",
        ),
    )

    advisory = project_knowledge_reevaluation_advisory(
        validity=validity,
        applicability=applicability,
        option_space_change=option_space,
    )

    assert advisory is not None
    assert advisory.condition_refs == (
        "constraint://a",
        "constraint://z",
    )
    assert advisory.evidence_refs == (
        "evidence://a",
        "evidence://b",
        "evidence://option-space",
        "evidence://z",
    )
    assert advisory.provenance_refs == (
        "owner://a",
        "owner://context",
        "owner://planner",
        "owner://z",
    )


@pytest.mark.parametrize(
    "field",
    (
        "truth_authority",
        "verification_authority",
        "ranking_authority",
        "invalidation_authority",
        "stop_authority",
        "decision_mutation_authority",
        "memory_mutation_authority",
        "execution_authority",
        "runtime_authority",
    ),
)
def test_ke_f3_advisory_cannot_escalate_authority(
    field: str,
) -> None:
    advisory = project_knowledge_reevaluation_advisory(
        validity=_ke_f3_validity(
            KnowledgeValiditySignalState.CONTRADICTED
        ),
        applicability=_ke_f3_applicability(
            KnowledgeApplicabilitySignalState.APPLICABLE
        ),
        option_space_change=_ke_f3_option_space(
            material_change=False
        ),
    )

    assert advisory is not None

    payload = advisory.model_dump(
        mode="python"
    )
    payload[field] = True

    with pytest.raises(ValidationError):
        KnowledgeReevaluationAdvisory.model_validate(
            payload
        )
