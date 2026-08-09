from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.experience import (
    CaseRelation,
    DistillationDisposition,
    EvidenceOrigin,
    ExperienceDistiller,
    ExperienceLessonProposal,
    GeneralizationScope,
    LessonCaseEvidence,
    LessonKind,
)
from luna.trajectories import (
    DatasetSplit,
    DatasetTaxonomy,
    LeakFreeSplitReport,
    ObservableDecisionEvent,
    SplitAssignment,
    StructuredDecisionTrace,
    TraceStage,
    TrajectoryOutcome,
)


def _trace(
    *,
    source_id: str,
    trajectory_family: str,
    task_family: str,
    evidence_ref: str,
    license_reviewed: bool = True,
    pii_reviewed: bool = True,
) -> StructuredDecisionTrace:
    return StructuredDecisionTrace(
        source_trajectory_id=source_id,
        trajectory_family=trajectory_family,
        task_family=task_family,
        repository_family="repo-luna",
        taxonomy=DatasetTaxonomy.IMPLEMENTATION_CODING,
        task_summary="Verify a reusable observable process lesson.",
        events=(
            ObservableDecisionEvent(
                sequence=0,
                stage=TraceStage.TASK,
                summary="Perform a bounded implementation task.",
            ),
            ObservableDecisionEvent(
                sequence=1,
                stage=TraceStage.ACTION,
                summary="Apply the candidate action.",
            ),
            ObservableDecisionEvent(
                sequence=2,
                stage=TraceStage.EVIDENCE,
                summary="Record observable task evidence.",
                evidence_refs=(evidence_ref,),
            ),
            ObservableDecisionEvent(
                sequence=3,
                stage=TraceStage.VERIFICATION,
                summary="Verify the resulting behavior.",
                evidence_refs=(evidence_ref,),
            ),
            ObservableDecisionEvent(
                sequence=4,
                stage=TraceStage.FINAL,
                summary="Report only the verified result.",
            ),
        ),
        outcome=TrajectoryOutcome.SUCCESS,
        provenance_refs=(f"source:{source_id}",),
        license_reviewed=license_reviewed,
        pii_reviewed=pii_reviewed,
    )


def _split_report(
    *traces: StructuredDecisionTrace,
    override_split: DatasetSplit = DatasetSplit.TRAIN,
) -> LeakFreeSplitReport:
    held_out = (
        (traces[0].task_family,)
        if override_split is DatasetSplit.HELD_OUT
        else ("reserved-heldout-family",)
    )
    return LeakFreeSplitReport(
        assignments=tuple(
            SplitAssignment(
                trajectory_id=str(trace.trajectory_id),
                source_trajectory_id=trace.source_trajectory_id,
                split_group_key=trace.split_group_key,
                task_family=trace.task_family,
                split=override_split,
            )
            for trace in traces
        ),
        held_out_task_families=held_out,
    )


def _case(
    trace: StructuredDecisionTrace,
    *,
    evidence_ref: str,
    relation: CaseRelation = CaseRelation.SUPPORTS,
    origin: EvidenceOrigin = EvidenceOrigin.DETERMINISTIC_VERIFIER,
) -> LessonCaseEvidence:
    return LessonCaseEvidence(
        source_trajectory_id=trace.source_trajectory_id,
        relation=relation,
        evidence_refs=(evidence_ref,),
        evidence_origin=origin,
        evaluator_ref="verifier:c003-fixture",
        observation_summary="The cited observable evidence supports this scoped relation.",
    )


def _proposal(*cases: LessonCaseEvidence) -> ExperienceLessonProposal:
    return ExperienceLessonProposal(
        lesson_id="lesson.verify-before-done",
        statement="Do not claim completion until observable verification evidence exists.",
        kind=LessonKind.INVARIANT,
        applicability_scope=("bounded implementation tasks",),
        cases=cases,
    )


def test_two_independent_groups_create_review_required_candidate() -> None:
    first = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )
    second = _trace(
        source_id="source-b",
        trajectory_family="family-b",
        task_family="debugging",
        evidence_ref="ev:b",
    )

    result = ExperienceDistiller().distill(
        proposal=_proposal(
            _case(first, evidence_ref="ev:a"),
            _case(second, evidence_ref="ev:b"),
        ),
        traces=(first, second),
        split_report=_split_report(first, second),
    )

    assert result.disposition is DistillationDisposition.REVIEW_REQUIRED_CANDIDATE
    assert result.generalization_test_passed is True
    assert result.generalization_scope is GeneralizationScope.WITHIN_TASK_FAMILY
    assert len(result.supporting_split_groups) == 2
    assert result.review_required is True
    assert result.automatic_memory_commit_allowed is False
    assert result.runtime_authority is False
    assert result.training_authority is False
    assert result.promotion_authority is False


def test_cross_task_support_is_scoped_as_cross_task_not_universal() -> None:
    first = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )
    second = _trace(
        source_id="source-b",
        trajectory_family="family-b",
        task_family="retrieval",
        evidence_ref="ev:b",
    )

    result = ExperienceDistiller().distill(
        proposal=_proposal(
            _case(first, evidence_ref="ev:a"),
            _case(second, evidence_ref="ev:b"),
        ),
        traces=(first, second),
        split_report=_split_report(first, second),
    )

    assert result.generalization_scope is GeneralizationScope.CROSS_TASK_FAMILY
    assert set(result.supporting_task_families) == {"debugging", "retrieval"}


def test_single_support_group_is_insufficient_evidence() -> None:
    trace = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )

    result = ExperienceDistiller().distill(
        proposal=_proposal(_case(trace, evidence_ref="ev:a")),
        traces=(trace,),
        split_report=_split_report(trace),
    )

    assert result.disposition is DistillationDisposition.INSUFFICIENT_EVIDENCE
    assert result.generalization_test_passed is False
    assert result.generalization_scope is GeneralizationScope.NONE


def test_observable_contradiction_rejects_candidate() -> None:
    first = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )
    second = _trace(
        source_id="source-b",
        trajectory_family="family-b",
        task_family="debugging",
        evidence_ref="ev:b",
    )

    result = ExperienceDistiller().distill(
        proposal=_proposal(
            _case(first, evidence_ref="ev:a"),
            _case(
                second,
                evidence_ref="ev:b",
                relation=CaseRelation.CONTRADICTS,
            ),
        ),
        traces=(first, second),
        split_report=_split_report(first, second),
    )

    assert result.disposition is DistillationDisposition.REJECTED_CONTRADICTION
    assert result.generalization_test_passed is False
    assert result.contradicting_source_trajectories == ("source-b",)


def test_model_self_report_cannot_establish_case_evidence() -> None:
    trace = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )

    with pytest.raises(ValidationError):
        _case(
            trace,
            evidence_ref="ev:a",
            origin=EvidenceOrigin.MODEL_SELF_REPORT,
        )


def test_unobserved_evidence_reference_is_rejected() -> None:
    trace = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )

    with pytest.raises(ValueError, match="not observed"):
        ExperienceDistiller().distill(
            proposal=_proposal(_case(trace, evidence_ref="ev:missing")),
            traces=(trace,),
            split_report=_split_report(trace),
        )


def test_validation_and_heldout_cases_cannot_enter_distillation() -> None:
    trace = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )
    proposal = _proposal(_case(trace, evidence_ref="ev:a"))
    distiller = ExperienceDistiller()

    with pytest.raises(ValueError, match="TRAIN experience only"):
        distiller.distill(
            proposal=proposal,
            traces=(trace,),
            split_report=_split_report(trace, override_split=DatasetSplit.VALIDATION),
        )

    with pytest.raises(ValueError, match="TRAIN experience only"):
        distiller.distill(
            proposal=proposal,
            traces=(trace,),
            split_report=_split_report(trace, override_split=DatasetSplit.HELD_OUT),
        )


def test_privacy_or_license_unreviewed_trace_is_rejected() -> None:
    trace = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
        pii_reviewed=False,
    )

    with pytest.raises(ValueError, match="PII-reviewed"):
        ExperienceDistiller().distill(
            proposal=_proposal(_case(trace, evidence_ref="ev:a")),
            traces=(trace,),
            split_report=_split_report(trace),
        )


def test_unknown_trajectory_and_missing_assignment_are_rejected() -> None:
    trace = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )
    unknown_case = LessonCaseEvidence(
        source_trajectory_id="source-missing",
        relation=CaseRelation.SUPPORTS,
        evidence_refs=("ev:a",),
        evidence_origin=EvidenceOrigin.HUMAN_REVIEW,
        evaluator_ref="review:human",
        observation_summary="Explicit reviewed claim.",
    )

    with pytest.raises(ValueError, match="unknown trajectory"):
        ExperienceDistiller().distill(
            proposal=_proposal(unknown_case),
            traces=(trace,),
            split_report=_split_report(trace),
        )

    empty_for_trace = _trace(
        source_id="source-b",
        trajectory_family="family-b",
        task_family="debugging",
        evidence_ref="ev:b",
    )
    with pytest.raises(ValueError, match="no governed split assignment"):
        ExperienceDistiller().distill(
            proposal=_proposal(_case(trace, evidence_ref="ev:a")),
            traces=(trace,),
            split_report=_split_report(empty_for_trace),
        )


def test_split_lineage_mismatch_is_rejected() -> None:
    trace = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )
    report = LeakFreeSplitReport(
        assignments=(
            SplitAssignment(
                trajectory_id=str(uuid4()),
                source_trajectory_id=trace.source_trajectory_id,
                split_group_key="wrong::group::key",
                task_family=trace.task_family,
                split=DatasetSplit.TRAIN,
            ),
        ),
        held_out_task_families=("reserved-heldout-family",),
    )

    with pytest.raises(ValueError, match="group lineage"):
        ExperienceDistiller().distill(
            proposal=_proposal(_case(trace, evidence_ref="ev:a")),
            traces=(trace,),
            split_report=report,
        )


def test_duplicate_source_judgment_is_rejected() -> None:
    trace = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )

    with pytest.raises(ValidationError, match="only once"):
        _proposal(
            _case(trace, evidence_ref="ev:a"),
            _case(trace, evidence_ref="ev:a"),
        )


def test_distillation_is_deterministic_for_same_inputs() -> None:
    first = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )
    second = _trace(
        source_id="source-b",
        trajectory_family="family-b",
        task_family="debugging",
        evidence_ref="ev:b",
    )
    proposal = _proposal(
        _case(first, evidence_ref="ev:a"),
        _case(second, evidence_ref="ev:b"),
    )
    report = _split_report(first, second)
    distiller = ExperienceDistiller()

    assert distiller.distill(
        proposal=proposal,
        traces=(first, second),
        split_report=report,
    ) == distiller.distill(
        proposal=proposal,
        traces=(first, second),
        split_report=report,
    )


def test_authority_flags_cannot_be_escalated_by_assignment() -> None:
    first = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )
    second = _trace(
        source_id="source-b",
        trajectory_family="family-b",
        task_family="debugging",
        evidence_ref="ev:b",
    )
    result = ExperienceDistiller().distill(
        proposal=_proposal(
            _case(first, evidence_ref="ev:a"),
            _case(second, evidence_ref="ev:b"),
        ),
        traces=(first, second),
        split_report=_split_report(first, second),
    )

    with pytest.raises(ValidationError):
        result.runtime_authority = True  # type: ignore[assignment]
