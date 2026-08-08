"""Deterministic cognitive-quality helpers for Phase 19."""

from __future__ import annotations

from luna.cognition.models import (
    CognitiveComparison,
    CognitiveComparisonVerdict,
    CognitiveDimension,
    CognitiveScorecard,
    ConfidenceBand,
    EvidenceState,
    FrozenCognitiveBaseline,
    UncertaintyAssessment,
    UncertaintyDirective,
)


def assess_uncertainty(
    *,
    confidence: ConfidenceBand,
    evidence: EvidenceState,
    evidence_refs: tuple[str, ...] = (),
) -> UncertaintyAssessment:
    """Apply evidence-bound uncertainty policy without model self-asserted authority."""
    if evidence is EvidenceState.CONTRADICTORY:
        directive = UncertaintyDirective.STOP
    elif evidence is EvidenceState.INSUFFICIENT or confidence is ConfidenceBand.LOW:
        directive = UncertaintyDirective.INSPECT
    else:
        directive = UncertaintyDirective.PROCEED
    return UncertaintyAssessment(
        confidence=confidence,
        evidence=evidence,
        directive=directive,
        evidence_refs=evidence_refs,
    )


def compare_to_baseline(
    *,
    baseline: FrozenCognitiveBaseline,
    candidate_scorecards: tuple[CognitiveScorecard, ...],
    held_out_contamination_detected: bool = False,
) -> CognitiveComparison:
    """Compare like-for-like cases against the frozen pre-training baseline."""
    baseline_by_id = {card.case_id: card for card in baseline.scorecards}
    candidate_by_id = {card.case_id: card for card in candidate_scorecards}
    if set(baseline_by_id) != set(candidate_by_id):
        raise ValueError("candidate scorecards must match frozen baseline case IDs")

    deltas: dict[CognitiveDimension, float] = {}
    for dimension in CognitiveDimension:
        before = sum(card.scores[dimension] for card in baseline.scorecards) / len(
            baseline.scorecards
        )
        after = sum(card.scores[dimension] for card in candidate_scorecards) / len(
            candidate_scorecards
        )
        deltas[dimension] = after - before

    regressed_dimensions = tuple(
        dimension for dimension, delta in deltas.items() if delta < -1e-12
    )
    critical_regressions = sum(card.critical_regression for card in candidate_scorecards)
    verdict = (
        CognitiveComparisonVerdict.REJECT
        if regressed_dimensions or critical_regressions or held_out_contamination_detected
        else CognitiveComparisonVerdict.ACCEPT
    )
    return CognitiveComparison(
        baseline_sha256=baseline.locked_sha256,
        dimension_deltas=deltas,
        regressed_dimensions=regressed_dimensions,
        critical_regression_count=critical_regressions,
        held_out_contamination_detected=held_out_contamination_detected,
        verdict=verdict,
    )
