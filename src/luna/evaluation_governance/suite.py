"""Frozen evaluation and regression suite helpers for Phase 19B."""

from __future__ import annotations

from luna.cognition import CognitiveScorecard
from luna.evaluation_governance.models import (
    FrozenEvaluationSuite,
    FrozenRegressionSuite,
    ReleaseEvaluationSnapshot,
)


def build_release_snapshot(
    *,
    release_id: str,
    candidate_model_id: str,
    evaluation_suite: FrozenEvaluationSuite,
    scorecards: tuple[CognitiveScorecard, ...],
) -> ReleaseEvaluationSnapshot:
    """Bind a complete scorecard set to one frozen suite and evaluator revision."""
    evaluation_suite.evaluator.assert_independent_for_candidate(candidate_model_id)
    scorecard_ids = {card.case_id for card in scorecards}
    if scorecard_ids != set(evaluation_suite.case_ids):
        raise ValueError("release snapshot must contain exactly the frozen evaluation case IDs")
    return ReleaseEvaluationSnapshot(
        release_id=release_id,
        candidate_model_id=candidate_model_id,
        evaluation_suite_sha256=evaluation_suite.locked_sha256,
        evaluator_fingerprint=evaluation_suite.evaluator.fingerprint(),
        scorecards=scorecards,
    )


def freeze_regression_suite(
    *,
    revision: str,
    evaluation_suite: FrozenEvaluationSuite,
    critical_case_ids: tuple[str, ...] = (),
) -> FrozenRegressionSuite:
    """Lock the repeatable case inventory independently from promotion policy."""
    return FrozenRegressionSuite.freeze(
        revision=revision,
        evaluation_suite=evaluation_suite,
        critical_case_ids=critical_case_ids,
    )
