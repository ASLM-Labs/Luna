"""Frozen default policy for Luna Phase 19F."""

from __future__ import annotations

from luna.cognition import CognitiveDimension
from luna.improvement_gate.models import DimensionThreshold, ImprovementGatePolicy


def build_default_improvement_gate_policy() -> ImprovementGatePolicy:
    """Build conservative initial meaningful-change bounds for the first candidate gate."""

    thresholds = {
        dimension: DimensionThreshold(
            meaningful_improvement=0.01,
            regression_tolerance=0.01,
        )
        for dimension in CognitiveDimension
    }
    return ImprovementGatePolicy.freeze(
        revision="1.0.0",
        confidence_level=0.95,
        min_cases_per_slice=2,
        min_meaningful_improved_dimensions=1,
        dimension_thresholds=thresholds,
        require_clean_learning_integrity=True,
        require_held_out_and_ood=True,
        critical_regression_zero_tolerance=True,
        runtime_authority=False,
    )
