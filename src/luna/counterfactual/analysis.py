"""Deterministic controlled-replay comparison for Luna Phase 19D."""

from __future__ import annotations

from luna.cognition import CognitiveDimension
from luna.counterfactual.models import (
    CounterfactualAssessment,
    CounterfactualDisposition,
    CounterfactualEvidence,
    CounterfactualEvidenceOrigin,
    CounterfactualExperiment,
    CounterfactualPolicy,
    ReplayObservation,
)


def _independent_refs(
    *,
    observation: ReplayObservation,
    evidence_by_id: dict[str, CounterfactualEvidence],
) -> tuple[str, ...]:
    refs: list[str] = []
    for evidence_id in observation.evidence_ids:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            raise ValueError("replay observation references unknown counterfactual evidence")
        if (
            evidence.independent_from_candidate
            and evidence.origin is not CounterfactualEvidenceOrigin.CANDIDATE_OUTPUT
        ):
            refs.append(evidence.source_ref)
    return tuple(sorted(set(refs)))


def assess_counterfactual(
    *,
    policy: CounterfactualPolicy,
    experiment: CounterfactualExperiment,
) -> CounterfactualAssessment:
    """Compare only actually observed, like-for-like controlled replay outcomes."""
    if experiment.alternative is None:
        return CounterfactualAssessment(
            policy_sha256=policy.locked_sha256,
            experiment_id=experiment.experiment_id,
            disposition=CounterfactualDisposition.HYPOTHESIS_ONLY,
        )

    baseline = experiment.baseline
    alternative = experiment.alternative
    if policy.require_same_environment and baseline.environment is not alternative.environment:
        raise ValueError("counterfactual policy requires the same replay environment")
    if (
        policy.require_same_source_revision
        and baseline.source_revision != alternative.source_revision
    ):
        raise ValueError("counterfactual policy requires the same source revision")

    evidence_by_id = {item.evidence_id: item for item in experiment.evidence_catalog}
    baseline_refs = _independent_refs(
        observation=baseline,
        evidence_by_id=evidence_by_id,
    )
    alternative_refs = _independent_refs(
        observation=alternative,
        evidence_by_id=evidence_by_id,
    )
    evidence_refs = tuple(sorted(set(baseline_refs + alternative_refs)))
    if policy.require_independent_observation_evidence and (
        not baseline_refs or not alternative_refs
    ):
        return CounterfactualAssessment(
            policy_sha256=policy.locked_sha256,
            experiment_id=experiment.experiment_id,
            disposition=CounterfactualDisposition.BLOCKED,
        )

    dimension_deltas = {
        dimension: alternative.scorecard.scores[dimension]
        - baseline.scorecard.scores[dimension]
        for dimension in CognitiveDimension
    }
    improved_dimensions = tuple(
        dimension for dimension, delta in dimension_deltas.items() if delta > 1e-12
    )
    regressed_dimensions = tuple(
        dimension for dimension, delta in dimension_deltas.items() if delta < -1e-12
    )
    critical_regression_count = max(
        0,
        alternative.critical_safety_regressions - baseline.critical_safety_regressions,
    )
    action_count_delta = alternative.action_count - baseline.action_count
    unnecessary_action_delta = (
        alternative.unnecessary_action_count - baseline.unnecessary_action_count
    )
    cost_delta = alternative.cost_units - baseline.cost_units
    verified_success_preserved = bool(
        (not baseline.task_success or alternative.task_success)
        and (not baseline.verification_success or alternative.verification_success)
    )

    if (
        (policy.critical_safety_zero_tolerance and critical_regression_count > 0)
        or not verified_success_preserved
    ):
        disposition = CounterfactualDisposition.REJECTED
    elif regressed_dimensions:
        disposition = CounterfactualDisposition.NO_ADVANTAGE
    elif (
        improved_dimensions
        or action_count_delta < 0
        or unnecessary_action_delta < 0
        or cost_delta < -1e-12
    ):
        disposition = CounterfactualDisposition.EVIDENCE_SUPPORTED
    else:
        disposition = CounterfactualDisposition.NO_ADVANTAGE

    return CounterfactualAssessment(
        policy_sha256=policy.locked_sha256,
        experiment_id=experiment.experiment_id,
        disposition=disposition,
        dimension_deltas=dimension_deltas,
        improved_dimensions=improved_dimensions,
        regressed_dimensions=regressed_dimensions,
        action_count_delta=action_count_delta,
        unnecessary_action_delta=unnecessary_action_delta,
        cost_delta=cost_delta,
        verified_success_preserved=verified_success_preserved,
        critical_safety_regression_count=critical_regression_count,
        evidence_refs=evidence_refs,
        executed_counterfactual_evidence=True,
        generalized_causal_claim_authorized=False,
        promotion_authorized=False,
    )
