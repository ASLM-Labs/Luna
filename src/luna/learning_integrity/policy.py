"""Frozen default learning-integrity policy for Luna Phase 19C."""

from __future__ import annotations

from luna.learning_integrity.models import LearningIntegrityPolicy


def build_default_learning_integrity_policy() -> LearningIntegrityPolicy:
    """Return the revision-locked Phase 19C policy with conservative starter thresholds."""
    return LearningIntegrityPolicy.freeze(
        revision="1.0.0",
        max_train_held_out_gap=0.15,
        max_train_ood_gap=0.20,
        max_shortcut_slice_gap=0.20,
        max_evaluator_disagreement=0.15,
        block_benchmark_identity_exposure=True,
        block_evaluator_identity_exposure=True,
        require_independent_claim_evidence=True,
        critical_regression_zero_tolerance=True,
    )
