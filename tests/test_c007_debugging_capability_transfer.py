from __future__ import annotations

import pytest
from pydantic import ValidationError

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
from luna.experience import (
    DistillationDisposition,
    DistilledExperienceCandidate,
    EvidenceOrigin,
    GeneralizationScope,
    LessonKind,
)
from luna.trajectories import DatasetSplit

STAGES = (
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
)


def _lesson() -> DistilledExperienceCandidate:
    return DistilledExperienceCandidate(
        lesson_id="c007.verify-root-cause-before-repair",
        statement="Localize the failure and falsify the broken assumption before repairing it.",
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


def _binding() -> ControlledLessonTransferBinding:
    return ControlledLessonTransferBinding(
        lesson_id=_lesson().lesson_id,
        reviewer_ref="human-review:c007",
        approval_scope=("held-out debugging evaluation",),
    )


def _assessments(
    *,
    prefix: str,
    score: float,
    initial_repair_failed: bool,
) -> tuple[DebuggingStageAssessment, ...]:
    stages = STAGES
    if initial_repair_failed:
        stages = (*stages, DebuggingStage.CHANGED_BASIS_REPLAN)
    stages = (*stages, DebuggingStage.PREVENTION_PROCESS_LESSON)
    return tuple(
        DebuggingStageAssessment(
            stage=stage,
            score=score,
            evidence_refs=(f"{prefix}:{stage.value}",),
            observation_summary=f"Observed {stage.value} behavior.",
        )
        for stage in stages
    )


def _case(
    case_id: str,
    *,
    score: float,
    diagnosis_correct: bool,
    repair_succeeded: bool,
    lesson_applied: bool,
    initial_repair_failed: bool = False,
    split: DatasetSplit = DatasetSplit.HELD_OUT,
    split_group_key: str | None = None,
    critical_regression: bool = False,
) -> DebuggingEvaluationCase:
    lesson_ids = (_lesson().lesson_id,) if lesson_applied else ()
    return DebuggingEvaluationCase(
        case_id=case_id,
        task_family="heldout-debugging-family",
        split_group_key=split_group_key or f"heldout-group:{case_id}",
        dataset_split=split,
        stage_assessments=_assessments(
            prefix=f"ev:{case_id}:{'after' if lesson_applied else 'before'}",
            score=score,
            initial_repair_failed=initial_repair_failed,
        ),
        diagnosis_correct=diagnosis_correct,
        repair_succeeded=repair_succeeded,
        initial_repair_failed=initial_repair_failed,
        applied_lesson_ids=lesson_ids,
        evaluator_ref="deterministic-evaluator:c007",
        evidence_origin=EvidenceOrigin.DETERMINISTIC_VERIFIER,
        critical_regression=critical_regression,
    )


def _paired_cases() -> tuple[
    tuple[DebuggingEvaluationCase, ...],
    tuple[DebuggingEvaluationCase, ...],
]:
    baseline = (
        _case(
            "debug-a",
            score=0.40,
            diagnosis_correct=False,
            repair_succeeded=False,
            lesson_applied=False,
            initial_repair_failed=True,
        ),
        _case(
            "debug-b",
            score=0.55,
            diagnosis_correct=True,
            repair_succeeded=True,
            lesson_applied=False,
        ),
    )
    transfer = (
        _case(
            "debug-a",
            score=0.80,
            diagnosis_correct=True,
            repair_succeeded=True,
            lesson_applied=True,
            initial_repair_failed=True,
        ),
        _case(
            "debug-b",
            score=0.85,
            diagnosis_correct=True,
            repair_succeeded=True,
            lesson_applied=True,
        ),
    )
    return baseline, transfer


def test_debugging_case_requires_canonical_stage_order() -> None:
    assessments = list(_assessments(prefix="ev", score=0.5, initial_repair_failed=False))
    assessments[0], assessments[1] = assessments[1], assessments[0]
    with pytest.raises(ValidationError, match="canonical observable stage order"):
        DebuggingEvaluationCase(
            case_id="bad-order",
            task_family="heldout-debugging-family",
            split_group_key="heldout-group:bad-order",
            dataset_split=DatasetSplit.HELD_OUT,
            stage_assessments=tuple(assessments),
            diagnosis_correct=False,
            repair_succeeded=False,
            evaluator_ref="deterministic-evaluator:c007",
            evidence_origin=EvidenceOrigin.DETERMINISTIC_VERIFIER,
        )


def test_changed_basis_stage_is_required_after_failed_initial_repair() -> None:
    assessments = _assessments(prefix="ev", score=0.5, initial_repair_failed=False)
    with pytest.raises(ValidationError, match="canonical observable stage order"):
        DebuggingEvaluationCase(
            case_id="missing-replan",
            task_family="heldout-debugging-family",
            split_group_key="heldout-group:missing-replan",
            dataset_split=DatasetSplit.HELD_OUT,
            stage_assessments=assessments,
            diagnosis_correct=False,
            repair_succeeded=False,
            initial_repair_failed=True,
            evaluator_ref="deterministic-evaluator:c007",
            evidence_origin=EvidenceOrigin.DETERMINISTIC_VERIFIER,
        )


def test_model_self_report_cannot_score_transfer() -> None:
    with pytest.raises(ValidationError, match="model self-report"):
        DebuggingEvaluationCase(
            case_id="self-report",
            task_family="heldout-debugging-family",
            split_group_key="heldout-group:self-report",
            dataset_split=DatasetSplit.HELD_OUT,
            stage_assessments=_assessments(
                prefix="ev",
                score=0.5,
                initial_repair_failed=False,
            ),
            diagnosis_correct=True,
            repair_succeeded=True,
            evaluator_ref="model:self",
            evidence_origin=EvidenceOrigin.MODEL_SELF_REPORT,
        )


def test_supported_transfer_uses_paired_unseen_heldout_cases() -> None:
    baseline, transfer = _paired_cases()
    result = DebuggingTransferEvaluator().evaluate(
        lesson=_lesson(),
        binding=_binding(),
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=baseline,
        transfer_cases=transfer,
    )

    assert result.verdict is DebuggingTransferVerdict.SUPPORTED
    assert result.held_out_case_ids == ("debug-a", "debug-b")
    assert DebuggingMetric.REPAIR_SUCCESS in result.meaningfully_improved_metrics
    assert DebuggingMetric.DIAGNOSIS_QUALITY in result.meaningfully_improved_metrics
    assert result.regressed_metrics == ()
    assert result.runtime_authority is False
    assert result.training_authority is False
    assert result.promotion_authority is False
    assert result.automatic_memory_commit_allowed is False
    assert result.action_executed is False


def test_transfer_rejects_training_split_group_reuse() -> None:
    baseline, transfer = _paired_cases()
    contaminated_before = baseline[0].model_copy(update={"split_group_key": "train-group-a"})
    contaminated_after = transfer[0].model_copy(update={"split_group_key": "train-group-a"})
    result = DebuggingTransferEvaluator().evaluate(
        lesson=_lesson(),
        binding=_binding(),
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=(contaminated_before, baseline[1]),
        transfer_cases=(contaminated_after, transfer[1]),
    )

    assert result.verdict is DebuggingTransferVerdict.INSUFFICIENT_EVIDENCE
    assert "training_group_reused_in_transfer_eval:debug-a" in result.blocked_reasons


def test_transfer_requires_heldout_evaluation() -> None:
    baseline, transfer = _paired_cases()
    validation_before = baseline[0].model_copy(update={"dataset_split": DatasetSplit.VALIDATION})
    validation_after = transfer[0].model_copy(update={"dataset_split": DatasetSplit.VALIDATION})
    result = DebuggingTransferEvaluator().evaluate(
        lesson=_lesson(),
        binding=_binding(),
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=(validation_before, baseline[1]),
        transfer_cases=(validation_after, transfer[1]),
    )

    assert result.verdict is DebuggingTransferVerdict.INSUFFICIENT_EVIDENCE
    assert "baseline_case_not_held_out:debug-a" in result.blocked_reasons
    assert "transfer_case_not_held_out:debug-a" in result.blocked_reasons


def test_transfer_case_must_explicitly_apply_reviewed_lesson() -> None:
    baseline, transfer = _paired_cases()
    missing = transfer[0].model_copy(update={"applied_lesson_ids": ()})
    result = DebuggingTransferEvaluator().evaluate(
        lesson=_lesson(),
        binding=_binding(),
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=baseline,
        transfer_cases=(missing, transfer[1]),
    )

    assert result.verdict is DebuggingTransferVerdict.INSUFFICIENT_EVIDENCE
    assert "transfer_case_missing_lesson_binding:debug-a" in result.blocked_reasons


def test_baseline_must_not_already_use_lesson() -> None:
    baseline, transfer = _paired_cases()
    contaminated = baseline[0].model_copy(update={"applied_lesson_ids": (_lesson().lesson_id,)})
    result = DebuggingTransferEvaluator().evaluate(
        lesson=_lesson(),
        binding=_binding(),
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=(contaminated, baseline[1]),
        transfer_cases=transfer,
    )

    assert result.verdict is DebuggingTransferVerdict.INSUFFICIENT_EVIDENCE
    assert "baseline_case_has_lesson_confound:debug-a" in result.blocked_reasons



def test_controlled_binding_requires_human_review_origin() -> None:
    with pytest.raises(ValidationError, match="explicit human review"):
        ControlledLessonTransferBinding(
            lesson_id=_lesson().lesson_id,
            reviewer_ref="model:self",
            review_origin=EvidenceOrigin.MODEL_SELF_REPORT,
            approval_scope=("held-out debugging evaluation",),
        )


def test_transfer_rejects_additional_lesson_confounds() -> None:
    baseline, transfer = _paired_cases()
    confounded = transfer[0].model_copy(
        update={"applied_lesson_ids": (_lesson().lesson_id, "other-lesson")}
    )
    result = DebuggingTransferEvaluator().evaluate(
        lesson=_lesson(),
        binding=_binding(),
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=baseline,
        transfer_cases=(confounded, transfer[1]),
    )

    assert result.verdict is DebuggingTransferVerdict.INSUFFICIENT_EVIDENCE
    assert "transfer_case_has_lesson_confound:debug-a" in result.blocked_reasons

def test_transfer_binding_must_match_c003_candidate() -> None:
    baseline, transfer = _paired_cases()
    wrong_binding = ControlledLessonTransferBinding(
        lesson_id="different-lesson",
        reviewer_ref="human-review:c007",
        approval_scope=("held-out debugging evaluation",),
    )
    result = DebuggingTransferEvaluator().evaluate(
        lesson=_lesson(),
        binding=wrong_binding,
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=baseline,
        transfer_cases=transfer,
    )

    assert result.verdict is DebuggingTransferVerdict.INSUFFICIENT_EVIDENCE
    assert "controlled_transfer_binding_lesson_mismatch" in result.blocked_reasons


def test_single_heldout_case_is_insufficient_evidence() -> None:
    baseline, transfer = _paired_cases()
    result = DebuggingTransferEvaluator().evaluate(
        lesson=_lesson(),
        binding=_binding(),
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=(baseline[0],),
        transfer_cases=(transfer[0],),
    )

    assert result.verdict is DebuggingTransferVerdict.INSUFFICIENT_EVIDENCE
    assert "insufficient_held_out_case_count" in result.blocked_reasons


def test_metric_regression_blocks_transfer_support() -> None:
    baseline, transfer = _paired_cases()
    degraded = _case(
        "debug-b",
        score=0.00,
        diagnosis_correct=False,
        repair_succeeded=False,
        lesson_applied=True,
    )
    result = DebuggingTransferEvaluator().evaluate(
        lesson=_lesson(),
        binding=_binding(),
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=baseline,
        transfer_cases=(transfer[0], degraded),
    )

    assert result.verdict is DebuggingTransferVerdict.NOT_SUPPORTED
    assert result.regressed_metrics
    assert "debugging_metric_regression_detected" in result.blocked_reasons


def test_critical_regression_blocks_transfer_support() -> None:
    baseline, transfer = _paired_cases()
    critical = transfer[1].model_copy(update={"critical_regression": True})
    result = DebuggingTransferEvaluator().evaluate(
        lesson=_lesson(),
        binding=_binding(),
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=baseline,
        transfer_cases=(transfer[0], critical),
    )

    assert result.verdict is DebuggingTransferVerdict.NOT_SUPPORTED
    assert result.critical_regression_case_ids == ("debug-b",)
    assert "critical_debugging_regression_detected" in result.blocked_reasons


def test_policy_is_frozen_and_requires_repair_and_diagnosis_metrics() -> None:
    policy = build_default_debugging_transfer_policy()
    assert policy.locked_sha256 == policy.computed_sha256()
    assert DebuggingMetric.REPAIR_SUCCESS in policy.required_outcome_metrics
    assert DebuggingMetric.DIAGNOSIS_QUALITY in policy.required_outcome_metrics
