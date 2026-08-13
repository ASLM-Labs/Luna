"""Capabilities Luna diagnostic scenarios."""

from __future__ import annotations

from luna.debugging import (
    ControlledLessonTransferBinding,
    DebuggingEvaluationCase,
    DebuggingMetric,
    DebuggingStage,
    DebuggingStageAssessment,
    DebuggingTransferEvaluator,
    DebuggingTransferVerdict,
    build_default_debugging_transfer_policy,
)
from luna.diagnostics.models import SmokeReport, legacy_contract_report
from luna.experience import (
    CaseRelation,
    DistillationDisposition,
    DistilledExperienceCandidate,
    ExperienceDistiller,
    ExperienceLessonProposal,
    GeneralizationScope,
    LessonCaseEvidence,
    LessonKind,
)
from luna.experience import EvidenceOrigin as ExperienceEvidenceOrigin
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


def run_c003() -> SmokeReport:

    def trace(
        *, source_id: str, trajectory_family: str, task_family: str, evidence_ref: str
    ) -> StructuredDecisionTrace:
        return StructuredDecisionTrace(
            source_trajectory_id=source_id,
            trajectory_family=trajectory_family,
            task_family=task_family,
            repository_family="repo-luna",
            taxonomy=DatasetTaxonomy.IMPLEMENTATION_CODING,
            task_summary="C-003 smoke fixture",
            events=(
                ObservableDecisionEvent(
                    sequence=0, stage=TraceStage.TASK, summary="Perform a bounded task."
                ),
                ObservableDecisionEvent(
                    sequence=1,
                    stage=TraceStage.EVIDENCE,
                    summary="Record observable evidence.",
                    evidence_refs=(evidence_ref,),
                ),
                ObservableDecisionEvent(
                    sequence=2,
                    stage=TraceStage.VERIFICATION,
                    summary="Verify the observed result.",
                    evidence_refs=(evidence_ref,),
                ),
                ObservableDecisionEvent(
                    sequence=3, stage=TraceStage.FINAL, summary="Report the verified result."
                ),
            ),
            outcome=TrajectoryOutcome.SUCCESS,
            provenance_refs=(f"source:{source_id}",),
            license_reviewed=True,
            pii_reviewed=True,
        )

    first = trace(
        source_id="c003-smoke-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )
    second = trace(
        source_id="c003-smoke-b",
        trajectory_family="family-b",
        task_family="debugging",
        evidence_ref="ev:b",
    )
    split_report = LeakFreeSplitReport(
        assignments=tuple(
            SplitAssignment(
                trajectory_id=str(item.trajectory_id),
                source_trajectory_id=item.source_trajectory_id,
                split_group_key=item.split_group_key,
                task_family=item.task_family,
                split=DatasetSplit.TRAIN,
            )
            for item in (first, second)
        ),
        held_out_task_families=("reserved-heldout-family",),
    )
    proposal = ExperienceLessonProposal(
        lesson_id="c003.smoke.verify-before-done",
        statement="Completion claims require observable verification evidence.",
        kind=LessonKind.INVARIANT,
        applicability_scope=("bounded implementation tasks",),
        cases=(
            LessonCaseEvidence(
                source_trajectory_id=first.source_trajectory_id,
                relation=CaseRelation.SUPPORTS,
                evidence_refs=("ev:a",),
                evidence_origin=ExperienceEvidenceOrigin.DETERMINISTIC_VERIFIER,
                evaluator_ref="verifier:c003-smoke",
                observation_summary="First independent observable support case.",
            ),
            LessonCaseEvidence(
                source_trajectory_id=second.source_trajectory_id,
                relation=CaseRelation.SUPPORTS,
                evidence_refs=("ev:b",),
                evidence_origin=ExperienceEvidenceOrigin.DETERMINISTIC_VERIFIER,
                evaluator_ref="verifier:c003-smoke",
                observation_summary="Second independent observable support case.",
            ),
        ),
    )
    result = ExperienceDistiller().distill(
        proposal=proposal, traces=(first, second), split_report=split_report
    )
    payload = {
        "disposition": result.disposition.value,
        "generalization_scope": result.generalization_scope.value,
        "generalization_test_passed": result.generalization_test_passed,
        "support_group_count": len(result.supporting_split_groups),
        "review_required": result.review_required,
        "automatic_memory_commit_allowed": result.automatic_memory_commit_allowed,
        "runtime_authority": result.runtime_authority,
        "training_authority": result.training_authority,
        "promotion_authority": result.promotion_authority,
    }
    return legacy_contract_report(
        "c003",
        payload,
        all(
            (
                result.disposition is DistillationDisposition.REVIEW_REQUIRED_CANDIDATE,
                result.generalization_scope is GeneralizationScope.WITHIN_TASK_FAMILY,
                result.generalization_test_passed is True,
                len(result.supporting_split_groups) == 2,
                result.review_required is True,
                result.automatic_memory_commit_allowed is False,
                result.runtime_authority is False,
                result.training_authority is False,
                result.promotion_authority is False,
            )
        ),
    )


def run_c007() -> SmokeReport:
    lesson = DistilledExperienceCandidate(
        lesson_id="c007.smoke.root-cause-first",
        statement="Localize and falsify the broken assumption before repair.",
        kind=LessonKind.STRATEGY,
        applicability_scope=("debugging tasks",),
        disposition=DistillationDisposition.REVIEW_REQUIRED_CANDIDATE,
        generalization_scope=GeneralizationScope.WITHIN_TASK_FAMILY,
        generalization_test_passed=True,
        supporting_source_trajectories=("train-a", "train-b"),
        supporting_split_groups=("train-group-a", "train-group-b"),
        supporting_task_families=("debugging",),
        evidence_refs=("train:ev:a", "train:ev:b"),
        provenance_refs=("source:train-a", "source:train-b"),
        decision_basis=("independent_support_groups_satisfied",),
    )
    binding = ControlledLessonTransferBinding(
        lesson_id=lesson.lesson_id,
        reviewer_ref="human-review:c007-smoke",
        approval_scope=("held-out debugging evaluation",),
    )
    base_stages = (
        DebuggingStage.ERROR_OBSERVATION,
        DebuggingStage.FAILURE_LOCALIZATION,
        DebuggingStage.HYPOTHESIS_GENERATION_RANKING,
        DebuggingStage.BROKEN_ASSUMPTION_DETECTION,
        DebuggingStage.STATE_CONTEXT_INSPECTION,
        DebuggingStage.MINIMAL_REPAIR_PLANNING,
        DebuggingStage.TOOL_SELECTION,
        DebuggingStage.PATCH_ACTION,
        DebuggingStage.TARGETED_VERIFICATION,
        DebuggingStage.FULL_REGRESSION_VERIFICATION,
        DebuggingStage.PREVENTION_PROCESS_LESSON,
    )

    def case(
        case_id: str, *, score: float, diagnosis: bool, repair: bool, applied: bool
    ) -> DebuggingEvaluationCase:
        assessments = tuple(
            DebuggingStageAssessment(
                stage=stage,
                score=score,
                evidence_refs=(f"ev:{case_id}:{('after' if applied else 'before')}:{stage.value}",),
                observation_summary=f"Observed {stage.value} behavior.",
            )
            for stage in base_stages
        )
        return DebuggingEvaluationCase(
            case_id=case_id,
            task_family="heldout-debugging-family",
            split_group_key=f"heldout-group:{case_id}",
            dataset_split=DatasetSplit.HELD_OUT,
            stage_assessments=assessments,
            diagnosis_correct=diagnosis,
            repair_succeeded=repair,
            applied_lesson_ids=(lesson.lesson_id,) if applied else (),
            evaluator_ref="deterministic-evaluator:c007-smoke",
            evidence_origin=ExperienceEvidenceOrigin.DETERMINISTIC_VERIFIER,
        )

    baseline = (
        case("debug-a", score=0.4, diagnosis=False, repair=False, applied=False),
        case("debug-b", score=0.55, diagnosis=True, repair=True, applied=False),
    )
    transfer = (
        case("debug-a", score=0.8, diagnosis=True, repair=True, applied=True),
        case("debug-b", score=0.85, diagnosis=True, repair=True, applied=True),
    )
    result = DebuggingTransferEvaluator().evaluate(
        lesson=lesson,
        binding=binding,
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=baseline,
        transfer_cases=transfer,
    )
    payload = {
        "verdict": result.verdict.value,
        "held_out_case_count": len(result.held_out_case_ids),
        "repair_improved": DebuggingMetric.REPAIR_SUCCESS in result.meaningfully_improved_metrics,
        "diagnosis_improved": DebuggingMetric.DIAGNOSIS_QUALITY
        in result.meaningfully_improved_metrics,
        "regressed_metrics": [metric.value for metric in result.regressed_metrics],
        "review_required": result.review_required,
        "automatic_memory_commit_allowed": result.automatic_memory_commit_allowed,
        "runtime_authority": result.runtime_authority,
        "training_authority": result.training_authority,
        "promotion_authority": result.promotion_authority,
        "action_executed": result.action_executed,
    }
    return legacy_contract_report(
        "c007",
        payload,
        all(
            (
                result.verdict is DebuggingTransferVerdict.SUPPORTED,
                len(result.held_out_case_ids) == 2,
                DebuggingMetric.REPAIR_SUCCESS in result.meaningfully_improved_metrics,
                DebuggingMetric.DIAGNOSIS_QUALITY in result.meaningfully_improved_metrics,
                not result.regressed_metrics,
                result.review_required is True,
                result.automatic_memory_commit_allowed is False,
                result.runtime_authority is False,
                result.training_authority is False,
                result.promotion_authority is False,
                result.action_executed is False,
            )
        ),
    )
