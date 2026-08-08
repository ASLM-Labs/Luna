"""Release-to-release evaluation comparison for Phase 19B."""

from __future__ import annotations

from luna.cognition import CognitiveDimension
from luna.evaluation_governance.models import (
    BenchmarkContaminationReport,
    FrozenRegressionSuite,
    ReleaseComparison,
    ReleaseComparisonStatus,
    ReleaseEvaluationSnapshot,
)


def compare_release_snapshots(
    *,
    baseline: ReleaseEvaluationSnapshot,
    candidate: ReleaseEvaluationSnapshot,
    regression_suite: FrozenRegressionSuite,
    contamination_report: BenchmarkContaminationReport,
) -> ReleaseComparison:
    """Compare matching snapshots and surface regressions without authorizing promotion."""
    blocked_reasons: list[str] = []
    if baseline.evaluation_suite_sha256 != candidate.evaluation_suite_sha256:
        blocked_reasons.append("evaluation suite drift")
    if baseline.evaluator_fingerprint != candidate.evaluator_fingerprint:
        blocked_reasons.append("evaluator version or implementation drift")
    if baseline.evaluation_suite_sha256 != regression_suite.evaluation_suite_sha256:
        blocked_reasons.append("regression suite does not bind the evaluation suite")

    baseline_by_id = {card.case_id: card for card in baseline.scorecards}
    candidate_by_id = {card.case_id: card for card in candidate.scorecards}
    required_ids = set(regression_suite.required_case_ids)
    if set(baseline_by_id) != required_ids or set(candidate_by_id) != required_ids:
        blocked_reasons.append("release snapshots do not match required regression cases")
    if contamination_report.contaminated:
        blocked_reasons.append("benchmark contamination detected")

    zero_deltas = {dimension: 0.0 for dimension in CognitiveDimension}
    if blocked_reasons:
        return ReleaseComparison(
            baseline_release_id=baseline.release_id,
            candidate_release_id=candidate.release_id,
            evaluation_suite_sha256=regression_suite.evaluation_suite_sha256,
            evaluator_fingerprint=candidate.evaluator_fingerprint,
            dimension_deltas=zero_deltas,
            contamination_detected=contamination_report.contaminated,
            blocked_reasons=tuple(blocked_reasons),
            status=ReleaseComparisonStatus.BLOCKED,
        )

    dimension_deltas: dict[CognitiveDimension, float] = {}
    for dimension in CognitiveDimension:
        baseline_mean = sum(card.scores[dimension] for card in baseline.scorecards) / len(
            baseline.scorecards
        )
        candidate_mean = sum(card.scores[dimension] for card in candidate.scorecards) / len(
            candidate.scorecards
        )
        dimension_deltas[dimension] = candidate_mean - baseline_mean

    regressed_case_ids: list[str] = []
    for case_id in regression_suite.required_case_ids:
        baseline_card = baseline_by_id[case_id]
        candidate_card = candidate_by_id[case_id]
        if any(
            candidate_card.scores[dimension] < baseline_card.scores[dimension] - 1e-12
            for dimension in CognitiveDimension
        ):
            regressed_case_ids.append(case_id)

    critical_ids = set(regression_suite.critical_case_ids)
    critical_regressed = tuple(
        case_id for case_id in regressed_case_ids if case_id in critical_ids
    )
    status = (
        ReleaseComparisonStatus.REGRESSION_DETECTED
        if regressed_case_ids
        else ReleaseComparisonStatus.COMPARABLE
    )
    return ReleaseComparison(
        baseline_release_id=baseline.release_id,
        candidate_release_id=candidate.release_id,
        evaluation_suite_sha256=regression_suite.evaluation_suite_sha256,
        evaluator_fingerprint=candidate.evaluator_fingerprint,
        dimension_deltas=dimension_deltas,
        regressed_case_ids=tuple(regressed_case_ids),
        critical_regressed_case_ids=critical_regressed,
        contamination_detected=False,
        status=status,
    )
