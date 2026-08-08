from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

import pytest
from pydantic import ValidationError

from luna.cognition import CognitiveDimension, CognitiveScorecard
from luna.evaluation_governance import (
    ContaminationReason,
    EvaluationCase,
    EvaluationPartition,
    EvaluatorKind,
    EvaluatorSpec,
    FrozenEvaluationSuite,
    ReleaseComparisonStatus,
    TrainingExposure,
    build_release_snapshot,
    compare_release_snapshots,
    detect_benchmark_contamination,
    freeze_regression_suite,
)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _evaluator(
    *,
    kind: EvaluatorKind = EvaluatorKind.DETERMINISTIC,
    model_identity: str | None = None,
    revision: str = "1.0.0",
    implementation: str = "deterministic-evaluator-v1",
) -> EvaluatorSpec:
    return EvaluatorSpec(
        evaluator_id="phase19b-evaluator",
        revision=revision,
        kind=kind,
        implementation_sha256=_digest(implementation),
        independent_from_candidate_artifacts=True,
        independent_from_training_data=True,
        model_identity=model_identity,
    )


def _cases() -> tuple[EvaluationCase, ...]:
    return (
        EvaluationCase(
            case_id="held-001",
            source_trajectory_id="source-held-001",
            partition=EvaluationPartition.HELD_OUT,
            task_family="held-task-family",
            repository_family="held-repository-family",
            trajectory_family="held-trajectory-family",
            content_sha256=_digest("held-content"),
            evidence_refs=("fixture:held-001",),
        ),
        EvaluationCase(
            case_id="ood-001",
            source_trajectory_id="source-ood-001",
            partition=EvaluationPartition.OOD,
            task_family="ood-task-family",
            repository_family="ood-repository-family",
            trajectory_family="ood-trajectory-family",
            content_sha256=_digest("ood-content"),
            evidence_refs=("fixture:ood-001",),
        ),
    )


def _suite(*, evaluator: EvaluatorSpec | None = None) -> FrozenEvaluationSuite:
    return FrozenEvaluationSuite.freeze(
        suite_name="phase19b-heldout-ood",
        revision="1.0.0",
        evaluator=evaluator or _evaluator(),
        cases=_cases(),
    )


def _scores(value: float) -> dict[CognitiveDimension, float]:
    return {dimension: value for dimension in CognitiveDimension}


def _scorecards(value: float = 0.5) -> tuple[CognitiveScorecard, ...]:
    return tuple(
        CognitiveScorecard(
            case_id=case.case_id,
            scores=_scores(value),
            evidence_refs=(f"evaluation:{case.case_id}",),
        )
        for case in _cases()
    )


def test_frozen_evaluation_suite_requires_held_out_and_ood_and_is_deterministic() -> None:
    first = _suite()
    second = _suite()

    assert first.locked_sha256 == second.locked_sha256
    assert first.computed_sha256() == first.locked_sha256
    assert {case.partition for case in first.cases} == {
        EvaluationPartition.HELD_OUT,
        EvaluationPartition.OOD,
    }


def test_evaluation_group_cannot_span_held_out_and_ood() -> None:
    held, ood = _cases()
    conflicting = ood.model_copy(
        update={
            "task_family": held.task_family,
            "repository_family": held.repository_family,
            "trajectory_family": held.trajectory_family,
        }
    )

    with pytest.raises(ValidationError, match="cannot span held-out and OOD"):
        FrozenEvaluationSuite.freeze(
            suite_name="bad-suite",
            revision="1.0.0",
            evaluator=_evaluator(),
            cases=(held, conflicting),
        )


def test_evaluator_independence_is_mandatory_and_versioned() -> None:
    with pytest.raises(ValidationError, match="independent from candidate artifacts"):
        EvaluatorSpec(
            evaluator_id="coupled",
            revision="1.0.0",
            kind=EvaluatorKind.DETERMINISTIC,
            implementation_sha256=_digest("coupled"),
            independent_from_candidate_artifacts=False,
            independent_from_training_data=True,
        )

    first = _evaluator()
    second = _evaluator(revision="1.0.1")
    assert first.fingerprint() != second.fingerprint()


def test_model_judge_cannot_evaluate_itself() -> None:
    evaluator = _evaluator(
        kind=EvaluatorKind.MODEL_JUDGE,
        model_identity="judge-model",
    )
    suite = _suite(evaluator=evaluator)

    with pytest.raises(ValueError, match="cannot judge itself"):
        build_release_snapshot(
            release_id="candidate",
            candidate_model_id="judge-model",
            evaluation_suite=suite,
            scorecards=_scorecards(),
        )


def test_benchmark_contamination_detects_exact_and_group_overlap() -> None:
    suite = _suite()
    held = suite.cases[0]
    exposures = (
        TrainingExposure(
            source_trajectory_id="training-copy",
            task_family=held.task_family,
            repository_family="different-repo",
            trajectory_family="different-trajectory",
            content_sha256=held.content_sha256,
        ),
    )

    report = detect_benchmark_contamination(
        evaluation_suite=suite,
        training_exposures=exposures,
    )
    reasons = {finding.reason for finding in report.findings}

    assert report.contaminated is True
    assert ContaminationReason.EXACT_CONTENT in reasons
    assert ContaminationReason.TASK_FAMILY in reasons


def test_clean_training_exposure_does_not_contaminate_evaluation_suite() -> None:
    report = detect_benchmark_contamination(
        evaluation_suite=_suite(),
        training_exposures=(
            TrainingExposure(
                source_trajectory_id="train-001",
                task_family="train-task",
                repository_family="train-repo",
                trajectory_family="train-trajectory",
                content_sha256=_digest("train-content"),
            ),
        ),
    )

    assert report.contaminated is False
    assert report.findings == ()


def test_regression_suite_locks_case_inventory_and_critical_subset() -> None:
    suite = _suite()
    regression = freeze_regression_suite(
        revision="1.0.0",
        evaluation_suite=suite,
        critical_case_ids=("held-001",),
    )

    assert regression.required_case_ids == suite.case_ids
    assert regression.critical_case_ids == ("held-001",)
    assert regression.computed_sha256() == regression.locked_sha256


def test_release_snapshot_requires_exact_frozen_case_inventory() -> None:
    suite = _suite()

    with pytest.raises(ValueError, match="exactly the frozen evaluation case IDs"):
        build_release_snapshot(
            release_id="candidate",
            candidate_model_id="candidate-model",
            evaluation_suite=suite,
            scorecards=(_scorecards()[0],),
        )


def test_release_comparison_is_like_for_like_and_has_no_promotion_authority() -> None:
    suite = _suite()
    regression = freeze_regression_suite(
        revision="1.0.0",
        evaluation_suite=suite,
        critical_case_ids=("held-001",),
    )
    baseline = build_release_snapshot(
        release_id="baseline",
        candidate_model_id="baseline-model",
        evaluation_suite=suite,
        scorecards=_scorecards(0.5),
    )
    candidate_cards = list(_scorecards(0.5))
    improved_scores = deepcopy(candidate_cards[0].scores)
    improved_scores[CognitiveDimension.PLANNING] = 0.7
    candidate_cards[0] = candidate_cards[0].model_copy(update={"scores": improved_scores})
    candidate = build_release_snapshot(
        release_id="candidate",
        candidate_model_id="candidate-model",
        evaluation_suite=suite,
        scorecards=tuple(candidate_cards),
    )
    contamination = detect_benchmark_contamination(
        evaluation_suite=suite,
        training_exposures=(),
    )

    comparison = compare_release_snapshots(
        baseline=baseline,
        candidate=candidate,
        regression_suite=regression,
        contamination_report=contamination,
    )

    assert comparison.status is ReleaseComparisonStatus.COMPARABLE
    assert comparison.dimension_deltas[CognitiveDimension.PLANNING] == pytest.approx(0.1)
    assert comparison.promotion_authorized is False


def test_release_comparison_surfaces_noncritical_and_critical_regressions() -> None:
    suite = _suite()
    regression = freeze_regression_suite(
        revision="1.0.0",
        evaluation_suite=suite,
        critical_case_ids=("held-001",),
    )
    baseline_cards = _scorecards(0.5)
    baseline = build_release_snapshot(
        release_id="baseline",
        candidate_model_id="baseline-model",
        evaluation_suite=suite,
        scorecards=baseline_cards,
    )

    degraded = list(_scorecards(0.5))
    degraded_scores = deepcopy(degraded[0].scores)
    degraded_scores[CognitiveDimension.EVIDENCE_USAGE] = 0.4
    degraded[0] = degraded[0].model_copy(update={"scores": degraded_scores})
    candidate = build_release_snapshot(
        release_id="candidate",
        candidate_model_id="candidate-model",
        evaluation_suite=suite,
        scorecards=tuple(degraded),
    )

    comparison = compare_release_snapshots(
        baseline=baseline,
        candidate=candidate,
        regression_suite=regression,
        contamination_report=detect_benchmark_contamination(
            evaluation_suite=suite,
            training_exposures=(),
        ),
    )

    assert comparison.status is ReleaseComparisonStatus.REGRESSION_DETECTED
    assert comparison.regressed_case_ids == ("held-001",)
    assert comparison.critical_regressed_case_ids == ("held-001",)
    assert comparison.promotion_authorized is False


def test_contamination_blocks_release_comparison() -> None:
    suite = _suite()
    regression = freeze_regression_suite(
        revision="1.0.0",
        evaluation_suite=suite,
    )
    baseline = build_release_snapshot(
        release_id="baseline",
        candidate_model_id="baseline-model",
        evaluation_suite=suite,
        scorecards=_scorecards(),
    )
    candidate = build_release_snapshot(
        release_id="candidate",
        candidate_model_id="candidate-model",
        evaluation_suite=suite,
        scorecards=_scorecards(),
    )
    held = suite.cases[0]
    contamination = detect_benchmark_contamination(
        evaluation_suite=suite,
        training_exposures=(
            TrainingExposure(
                source_trajectory_id=held.source_trajectory_id,
                task_family="different-task",
                repository_family="different-repo",
                trajectory_family="different-trajectory",
                content_sha256=_digest("different-content"),
            ),
        ),
    )

    comparison = compare_release_snapshots(
        baseline=baseline,
        candidate=candidate,
        regression_suite=regression,
        contamination_report=contamination,
    )

    assert comparison.status is ReleaseComparisonStatus.BLOCKED
    assert comparison.contamination_detected is True
    assert "benchmark contamination detected" in comparison.blocked_reasons
    assert comparison.promotion_authorized is False


def test_evaluator_drift_blocks_release_comparison() -> None:
    baseline_suite = _suite()
    candidate_suite = _suite(
        evaluator=_evaluator(
            revision="1.0.1",
            implementation="deterministic-evaluator-v2",
        )
    )
    regression = freeze_regression_suite(
        revision="1.0.0",
        evaluation_suite=baseline_suite,
    )
    baseline = build_release_snapshot(
        release_id="baseline",
        candidate_model_id="baseline-model",
        evaluation_suite=baseline_suite,
        scorecards=_scorecards(),
    )
    candidate = build_release_snapshot(
        release_id="candidate",
        candidate_model_id="candidate-model",
        evaluation_suite=candidate_suite,
        scorecards=_scorecards(),
    )

    comparison = compare_release_snapshots(
        baseline=baseline,
        candidate=candidate,
        regression_suite=regression,
        contamination_report=detect_benchmark_contamination(
            evaluation_suite=baseline_suite,
            training_exposures=(),
        ),
    )

    assert comparison.status is ReleaseComparisonStatus.BLOCKED
    assert "evaluation suite drift" in comparison.blocked_reasons
    assert "evaluator version or implementation drift" in comparison.blocked_reasons
