"""Frozen default policy for Luna Phase 19D counterfactual analysis."""

from luna.counterfactual.models import CounterfactualPolicy


def build_default_counterfactual_policy() -> CounterfactualPolicy:
    """Return the revision-locked exploratory Phase 19D policy."""
    return CounterfactualPolicy.freeze(revision="1.0.0")
