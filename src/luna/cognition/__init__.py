"""Phase 19 cognitive-quality contracts and deterministic comparison helpers."""

from luna.cognition.evaluator import assess_uncertainty, compare_to_baseline
from luna.cognition.models import (
    CognitiveComparison,
    CognitiveComparisonVerdict,
    CognitiveDimension,
    CognitiveScorecard,
    ConfidenceBand,
    EvidenceState,
    FailureLabel,
    FrozenCognitiveBaseline,
    SelfCorrectionAssessment,
    UncertaintyAssessment,
    UncertaintyDirective,
)

__all__ = [
    "CognitiveComparison",
    "CognitiveComparisonVerdict",
    "CognitiveDimension",
    "CognitiveScorecard",
    "ConfidenceBand",
    "EvidenceState",
    "FailureLabel",
    "FrozenCognitiveBaseline",
    "SelfCorrectionAssessment",
    "UncertaintyAssessment",
    "UncertaintyDirective",
    "assess_uncertainty",
    "compare_to_baseline",
]
