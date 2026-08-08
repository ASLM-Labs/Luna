"""Confidence-aware improvement and release recommendation gate for Phase 19F."""

from __future__ import annotations

from collections.abc import Iterable
from math import sqrt
from statistics import NormalDist, fmean, stdev

from luna.cognition import CognitiveDimension, CognitiveScorecard
from luna.evaluation_governance import (
    BenchmarkContaminationReport,
    EvaluationPartition,
    FrozenEvaluationSuite,
    FrozenRegressionSuite,
    ReleaseEvaluationSnapshot,
)
from luna.improvement_gate.models import (
    DimensionEstimate,
    EvaluationSlice,
    ImprovementGateDecision,
    ImprovementGatePolicy,
    ImprovementGateReport,
    MetricDisposition,
)
from luna.learning_integrity import LearningIntegrityReport, LearningIntegrityStatus
from luna.sft import (
    SFTCandidateArtifact,
    SFTTrainingReceipt,
    SFTTrainingSpec,
    register_training_receipt,
)

_EPSILON = 1e-12


def _unique_reasons(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _candidate_chain_verified(
    *,
    spec: SFTTrainingSpec | None,
    receipt: SFTTrainingReceipt | None,
    artifact: SFTCandidateArtifact | None,
) -> bool:
    if spec is None or receipt is None or artifact is None:
        return False
    try:
        expected = register_training_receipt(spec=spec, receipt=receipt)
    except ValueError:
        return False
    return expected == artifact


def _scorecards_for_slice(
    *,
    snapshot: ReleaseEvaluationSnapshot,
    evaluation_suite: FrozenEvaluationSuite,
    evaluation_slice: EvaluationSlice,
) -> tuple[CognitiveScorecard, ...]:
    if evaluation_slice is EvaluationSlice.ALL:
        return snapshot.scorecards
    partition = EvaluationPartition(evaluation_slice.value)
    selected_ids = {
        case.case_id for case in evaluation_suite.cases if case.partition is partition
    }
    return tuple(card for card in snapshot.scorecards if card.case_id in selected_ids)


def _estimate_dimension(
    *,
    dimension: CognitiveDimension,
    evaluation_slice: EvaluationSlice,
    baseline_cards: tuple[CognitiveScorecard, ...],
    candidate_cards: tuple[CognitiveScorecard, ...],
    policy: ImprovementGatePolicy,
) -> DimensionEstimate:
    threshold = policy.dimension_thresholds[dimension]
    baseline_by_id = {card.case_id: card for card in baseline_cards}
    candidate_by_id = {card.case_id: card for card in candidate_cards}
    common_ids = tuple(sorted(set(baseline_by_id) & set(candidate_by_id)))
    deltas = tuple(
        candidate_by_id[case_id].scores[dimension] - baseline_by_id[case_id].scores[dimension]
        for case_id in common_ids
    )
    mean_delta = fmean(deltas) if deltas else 0.0
    if len(deltas) < policy.min_cases_per_slice:
        return DimensionEstimate(
            dimension=dimension,
            evaluation_slice=evaluation_slice,
            case_count=len(deltas),
            mean_delta=mean_delta,
            confidence_level=policy.confidence_level,
            meaningful_improvement=threshold.meaningful_improvement,
            regression_tolerance=threshold.regression_tolerance,
            disposition=MetricDisposition.INSUFFICIENT_EVIDENCE,
        )

    sample_std = stdev(deltas)
    z_score = NormalDist().inv_cdf(0.5 + policy.confidence_level / 2.0)
    half_width = z_score * sample_std / sqrt(len(deltas))
    ci_lower = mean_delta - half_width
    ci_upper = mean_delta + half_width

    if ci_upper < -threshold.regression_tolerance - _EPSILON:
        disposition = MetricDisposition.MEANINGFUL_REGRESSION
    elif ci_lower > threshold.meaningful_improvement - _EPSILON:
        disposition = MetricDisposition.MEANINGFUL_IMPROVEMENT
    else:
        disposition = MetricDisposition.NO_CLEAR_CHANGE

    return DimensionEstimate(
        dimension=dimension,
        evaluation_slice=evaluation_slice,
        case_count=len(deltas),
        mean_delta=mean_delta,
        confidence_level=policy.confidence_level,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        meaningful_improvement=threshold.meaningful_improvement,
        regression_tolerance=threshold.regression_tolerance,
        disposition=disposition,
    )


def _blocking_decision(
    *,
    candidate_currently_active: bool,
    rollback_worthy: bool,
) -> ImprovementGateDecision:
    if candidate_currently_active and rollback_worthy:
        return ImprovementGateDecision.ROLLBACK
    return ImprovementGateDecision.REJECT


def evaluate_improvement_gate(
    *,
    policy: ImprovementGatePolicy,
    candidate_spec: SFTTrainingSpec | None = None,
    candidate_receipt: SFTTrainingReceipt | None = None,
    candidate_artifact: SFTCandidateArtifact | None = None,
    evaluation_suite: FrozenEvaluationSuite | None = None,
    regression_suite: FrozenRegressionSuite | None = None,
    baseline_snapshot: ReleaseEvaluationSnapshot | None = None,
    candidate_snapshot: ReleaseEvaluationSnapshot | None = None,
    contamination_report: BenchmarkContaminationReport | None = None,
    learning_integrity_report: LearningIntegrityReport | None = None,
    candidate_currently_active: bool = False,
) -> ImprovementGateReport:
    """Evaluate a trained candidate without directly mutating runtime release state."""

    if policy.locked_sha256 != policy.computed_sha256():
        raise ValueError("improvement gate policy is not revision locked")

    candidate_verified = _candidate_chain_verified(
        spec=candidate_spec,
        receipt=candidate_receipt,
        artifact=candidate_artifact,
    )
    candidate_id = candidate_artifact.candidate_id if candidate_artifact is not None else None

    missing_reasons: list[str] = []
    if not candidate_verified:
        missing_reasons.append("verified real trained candidate evidence is missing")
    if evaluation_suite is None:
        missing_reasons.append("frozen evaluation suite is missing")
    if regression_suite is None:
        missing_reasons.append("frozen regression suite is missing")
    if baseline_snapshot is None:
        missing_reasons.append("baseline evaluation snapshot is missing")
    if candidate_snapshot is None:
        missing_reasons.append("candidate evaluation snapshot is missing")
    if contamination_report is None:
        missing_reasons.append("benchmark contamination report is missing")
    if learning_integrity_report is None:
        missing_reasons.append("learning integrity report is missing")
    if missing_reasons:
        return ImprovementGateReport(
            policy_sha256=policy.locked_sha256,
            decision=ImprovementGateDecision.INSUFFICIENT_EVIDENCE,
            candidate_id=candidate_id,
            candidate_evidence_verified=candidate_verified,
            candidate_currently_active=candidate_currently_active,
            blocked_reasons=_unique_reasons(missing_reasons),
        )

    assert candidate_artifact is not None
    assert evaluation_suite is not None
    assert regression_suite is not None
    assert baseline_snapshot is not None
    assert candidate_snapshot is not None
    assert contamination_report is not None
    assert learning_integrity_report is not None

    blocked_reasons: list[str] = []
    rollback_worthy = False

    if regression_suite.evaluation_suite_sha256 != evaluation_suite.locked_sha256:
        blocked_reasons.append("regression suite does not bind the frozen evaluation suite")
    if baseline_snapshot.evaluation_suite_sha256 != evaluation_suite.locked_sha256:
        blocked_reasons.append("baseline snapshot evaluation suite drift")
    if candidate_snapshot.evaluation_suite_sha256 != evaluation_suite.locked_sha256:
        blocked_reasons.append("candidate snapshot evaluation suite drift")

    evaluator_fingerprint = evaluation_suite.evaluator.fingerprint()
    if baseline_snapshot.evaluator_fingerprint != evaluator_fingerprint:
        blocked_reasons.append("baseline evaluator identity drift")
    if candidate_snapshot.evaluator_fingerprint != evaluator_fingerprint:
        blocked_reasons.append("candidate evaluator identity drift")
    try:
        evaluation_suite.evaluator.assert_independent_for_candidate(candidate_artifact.candidate_id)
    except ValueError:
        blocked_reasons.append("candidate evaluator independence failure")

    if candidate_snapshot.candidate_model_id != candidate_artifact.candidate_id:
        blocked_reasons.append("candidate snapshot model identity does not match trained artifact")

    required_ids = set(regression_suite.required_case_ids)
    baseline_ids = {card.case_id for card in baseline_snapshot.scorecards}
    candidate_ids = {card.case_id for card in candidate_snapshot.scorecards}
    if baseline_ids != required_ids or candidate_ids != required_ids:
        blocked_reasons.append("evaluation snapshots do not match frozen regression case inventory")

    if contamination_report.contaminated:
        blocked_reasons.append("benchmark contamination detected")

    if learning_integrity_report.status is LearningIntegrityStatus.REJECT_CANDIDATE:
        blocked_reasons.append("learning integrity contains blocking findings")
        rollback_worthy = True
    elif (
        policy.require_clean_learning_integrity
        and learning_integrity_report.status is LearningIntegrityStatus.REVIEW_REQUIRED
    ):
        return ImprovementGateReport(
            policy_sha256=policy.locked_sha256,
            decision=ImprovementGateDecision.INSUFFICIENT_EVIDENCE,
            candidate_id=candidate_artifact.candidate_id,
            candidate_evidence_verified=True,
            candidate_currently_active=candidate_currently_active,
            evaluation_suite_sha256=evaluation_suite.locked_sha256,
            evaluator_fingerprint=evaluator_fingerprint,
            learning_integrity_status=learning_integrity_report.status,
            contamination_detected=contamination_report.contaminated,
            blocked_reasons=("learning integrity review is required before promotion",),
        )

    if blocked_reasons:
        return ImprovementGateReport(
            policy_sha256=policy.locked_sha256,
            decision=_blocking_decision(
                candidate_currently_active=candidate_currently_active,
                rollback_worthy=rollback_worthy,
            ),
            candidate_id=candidate_artifact.candidate_id,
            candidate_evidence_verified=True,
            candidate_currently_active=candidate_currently_active,
            evaluation_suite_sha256=evaluation_suite.locked_sha256,
            evaluator_fingerprint=evaluator_fingerprint,
            learning_integrity_status=learning_integrity_report.status,
            contamination_detected=contamination_report.contaminated,
            blocked_reasons=_unique_reasons(blocked_reasons),
        )

    baseline_by_id = {card.case_id: card for card in baseline_snapshot.scorecards}
    candidate_by_id = {card.case_id: card for card in candidate_snapshot.scorecards}
    critical_ids = set(regression_suite.critical_case_ids)
    critical_regressed: list[str] = []
    for case_id in regression_suite.required_case_ids:
        candidate_card = candidate_by_id[case_id]
        baseline_card = baseline_by_id[case_id]
        score_regressed = any(
            candidate_card.scores[dimension] < baseline_card.scores[dimension] - _EPSILON
            for dimension in CognitiveDimension
        )
        if candidate_card.critical_regression or (case_id in critical_ids and score_regressed):
            critical_regressed.append(case_id)

    if policy.critical_regression_zero_tolerance and critical_regressed:
        return ImprovementGateReport(
            policy_sha256=policy.locked_sha256,
            decision=_blocking_decision(
                candidate_currently_active=candidate_currently_active,
                rollback_worthy=True,
            ),
            candidate_id=candidate_artifact.candidate_id,
            candidate_evidence_verified=True,
            candidate_currently_active=candidate_currently_active,
            evaluation_suite_sha256=evaluation_suite.locked_sha256,
            evaluator_fingerprint=evaluator_fingerprint,
            learning_integrity_status=learning_integrity_report.status,
            contamination_detected=False,
            critical_regressed_case_ids=tuple(critical_regressed),
            blocked_reasons=("critical regression detected with zero tolerance",),
        )

    slices = [EvaluationSlice.ALL]
    if policy.require_held_out_and_ood:
        slices.extend((EvaluationSlice.HELD_OUT, EvaluationSlice.OOD))

    estimates: list[DimensionEstimate] = []
    for evaluation_slice in slices:
        baseline_cards = _scorecards_for_slice(
            snapshot=baseline_snapshot,
            evaluation_suite=evaluation_suite,
            evaluation_slice=evaluation_slice,
        )
        candidate_cards = _scorecards_for_slice(
            snapshot=candidate_snapshot,
            evaluation_suite=evaluation_suite,
            evaluation_slice=evaluation_slice,
        )
        for dimension in CognitiveDimension:
            estimates.append(
                _estimate_dimension(
                    dimension=dimension,
                    evaluation_slice=evaluation_slice,
                    baseline_cards=baseline_cards,
                    candidate_cards=candidate_cards,
                    policy=policy,
                )
            )

    insufficient = tuple(
        estimate
        for estimate in estimates
        if estimate.disposition is MetricDisposition.INSUFFICIENT_EVIDENCE
    )
    if insufficient:
        slices_missing = sorted({estimate.evaluation_slice.value for estimate in insufficient})
        return ImprovementGateReport(
            policy_sha256=policy.locked_sha256,
            decision=ImprovementGateDecision.INSUFFICIENT_EVIDENCE,
            candidate_id=candidate_artifact.candidate_id,
            candidate_evidence_verified=True,
            candidate_currently_active=candidate_currently_active,
            evaluation_suite_sha256=evaluation_suite.locked_sha256,
            evaluator_fingerprint=evaluator_fingerprint,
            learning_integrity_status=learning_integrity_report.status,
            contamination_detected=False,
            estimates=tuple(estimates),
            blocked_reasons=(
                "insufficient paired cases for required evaluation slices: "
                + ", ".join(slices_missing),
            ),
        )

    regressed_dimensions = tuple(
        dimension
        for dimension in CognitiveDimension
        if any(
            estimate.dimension is dimension
            and estimate.disposition is MetricDisposition.MEANINGFUL_REGRESSION
            for estimate in estimates
        )
    )
    if regressed_dimensions:
        return ImprovementGateReport(
            policy_sha256=policy.locked_sha256,
            decision=_blocking_decision(
                candidate_currently_active=candidate_currently_active,
                rollback_worthy=True,
            ),
            candidate_id=candidate_artifact.candidate_id,
            candidate_evidence_verified=True,
            candidate_currently_active=candidate_currently_active,
            evaluation_suite_sha256=evaluation_suite.locked_sha256,
            evaluator_fingerprint=evaluator_fingerprint,
            learning_integrity_status=learning_integrity_report.status,
            contamination_detected=False,
            estimates=tuple(estimates),
            meaningfully_regressed_dimensions=regressed_dimensions,
            blocked_reasons=("meaningful non-critical regression exceeds frozen tolerance",),
        )

    improved_dimensions = tuple(
        dimension
        for dimension in CognitiveDimension
        if any(
            estimate.dimension is dimension
            and estimate.evaluation_slice is EvaluationSlice.ALL
            and estimate.disposition is MetricDisposition.MEANINGFUL_IMPROVEMENT
            for estimate in estimates
        )
    )
    if len(improved_dimensions) < policy.min_meaningful_improved_dimensions:
        return ImprovementGateReport(
            policy_sha256=policy.locked_sha256,
            decision=ImprovementGateDecision.INSUFFICIENT_EVIDENCE,
            candidate_id=candidate_artifact.candidate_id,
            candidate_evidence_verified=True,
            candidate_currently_active=candidate_currently_active,
            evaluation_suite_sha256=evaluation_suite.locked_sha256,
            evaluator_fingerprint=evaluator_fingerprint,
            learning_integrity_status=learning_integrity_report.status,
            contamination_detected=False,
            estimates=tuple(estimates),
            blocked_reasons=("candidate has no confidence-supported meaningful improvement",),
        )

    return ImprovementGateReport(
        policy_sha256=policy.locked_sha256,
        decision=ImprovementGateDecision.PROMOTE,
        candidate_id=candidate_artifact.candidate_id,
        candidate_evidence_verified=True,
        candidate_currently_active=candidate_currently_active,
        evaluation_suite_sha256=evaluation_suite.locked_sha256,
        evaluator_fingerprint=evaluator_fingerprint,
        learning_integrity_status=learning_integrity_report.status,
        contamination_detected=False,
        estimates=tuple(estimates),
        meaningfully_improved_dimensions=improved_dimensions,
        runtime_authority=False,
        action_executed=False,
    )
