from __future__ import annotations

import pytest
from pydantic import ValidationError

from luna.cognition import CognitiveDimension, CognitiveScorecard
from luna.counterfactual import (
    CounterfactualAlternativeKind,
    CounterfactualCandidate,
    CounterfactualDisposition,
    CounterfactualEvidence,
    CounterfactualEvidenceOrigin,
    CounterfactualExperiment,
    ReplayEnvironment,
    ReplayObservation,
    assess_counterfactual,
    build_default_counterfactual_policy,
)


def _scorecard(case_id: str, value: float) -> CognitiveScorecard:
    return CognitiveScorecard(
        case_id=case_id,
        scores={dimension: value for dimension in CognitiveDimension},
        evidence_refs=(f"score:{case_id}:{value}",),
    )


def _evidence(
    evidence_id: str,
    *,
    origin: CounterfactualEvidenceOrigin = CounterfactualEvidenceOrigin.SANDBOX_HARNESS,
    independent: bool = True,
) -> CounterfactualEvidence:
    return CounterfactualEvidence(
        evidence_id=evidence_id,
        origin=origin,
        independent_from_candidate=independent,
        source_ref=f"evidence:{evidence_id}",
    )


def _observation(
    observation_id: str,
    decision_ref: str,
    evidence_id: str,
    *,
    score: float = 0.6,
    task_success: bool = True,
    verification_success: bool = True,
    action_count: int = 4,
    unnecessary_action_count: int = 1,
    cost_units: float = 4.0,
    critical_safety_regressions: int = 0,
    environment: ReplayEnvironment = ReplayEnvironment.SANDBOX,
) -> ReplayObservation:
    return ReplayObservation(
        observation_id=observation_id,
        case_id="case-001",
        source_revision="rev-001",
        decision_ref=decision_ref,
        environment=environment,
        scorecard=_scorecard("case-001", score),
        task_success=task_success,
        verification_success=verification_success,
        action_count=action_count,
        unnecessary_action_count=unnecessary_action_count,
        cost_units=cost_units,
        critical_safety_regressions=critical_safety_regressions,
        evidence_ids=(evidence_id,),
    )


def _candidate(
    kind: CounterfactualAlternativeKind = CounterfactualAlternativeKind.PLAN,
) -> CounterfactualCandidate:
    return CounterfactualCandidate(
        candidate_id="alt-001",
        source_case_id="case-001",
        source_revision="rev-001",
        alternative_kind=kind,
        baseline_decision_ref="decision:baseline",
        alternative_summary="Use the tested alternative path.",
        changed_basis=("new sandbox observation",),
        hypothesis_refs=("trace:decision-point",),
    )


def _experiment(
    *,
    alternative: ReplayObservation | None,
    evidence_catalog: tuple[CounterfactualEvidence, ...] | None = None,
    kind: CounterfactualAlternativeKind = CounterfactualAlternativeKind.PLAN,
) -> CounterfactualExperiment:
    catalog = evidence_catalog or (_evidence("base-e"), _evidence("alt-e"))
    return CounterfactualExperiment(
        experiment_id="experiment-001",
        candidate=_candidate(kind),
        baseline=_observation("base", "decision:baseline", "base-e"),
        alternative=alternative,
        evidence_catalog=catalog,
    )


def test_default_policy_is_locked_and_non_authoritative() -> None:
    policy = build_default_counterfactual_policy()

    assert policy.locked_sha256 == policy.computed_sha256()
    assert policy.promotion_authority is False
    assert policy.generalized_causal_claim_authority is False


def test_unexecuted_alternative_remains_hypothesis_only() -> None:
    result = assess_counterfactual(
        policy=build_default_counterfactual_policy(),
        experiment=_experiment(alternative=None),
    )

    assert result.disposition is CounterfactualDisposition.HYPOTHESIS_ONLY
    assert result.executed_counterfactual_evidence is False
    assert result.dimension_deltas == {}
    assert result.promotion_authorized is False


def test_controlled_replay_can_support_observed_better_path() -> None:
    alternative = _observation(
        "alt",
        "decision:alternative",
        "alt-e",
        score=0.7,
        action_count=3,
        unnecessary_action_count=0,
        cost_units=3.0,
    )
    result = assess_counterfactual(
        policy=build_default_counterfactual_policy(),
        experiment=_experiment(alternative=alternative),
    )

    assert result.disposition is CounterfactualDisposition.EVIDENCE_SUPPORTED
    assert set(result.improved_dimensions) == set(CognitiveDimension)
    assert result.action_count_delta == -1
    assert result.unnecessary_action_delta == -1
    assert result.cost_delta == pytest.approx(-1.0)
    assert result.executed_counterfactual_evidence is True
    assert result.generalized_causal_claim_authorized is False


def test_lower_cost_alone_can_be_observed_advantage() -> None:
    alternative = _observation(
        "alt",
        "decision:alternative",
        "alt-e",
        cost_units=2.5,
    )
    result = assess_counterfactual(
        policy=build_default_counterfactual_policy(),
        experiment=_experiment(alternative=alternative),
    )

    assert result.disposition is CounterfactualDisposition.EVIDENCE_SUPPORTED
    assert result.cost_delta == pytest.approx(-1.5)
    assert result.regressed_dimensions == ()


def test_cognitive_regression_is_not_called_an_advantage() -> None:
    alternative = _observation(
        "alt",
        "decision:alternative",
        "alt-e",
        score=0.5,
        action_count=2,
        cost_units=2.0,
    )
    result = assess_counterfactual(
        policy=build_default_counterfactual_policy(),
        experiment=_experiment(alternative=alternative),
    )

    assert result.disposition is CounterfactualDisposition.NO_ADVANTAGE
    assert set(result.regressed_dimensions) == set(CognitiveDimension)


def test_verification_regression_rejects_alternative() -> None:
    alternative = _observation(
        "alt",
        "decision:alternative",
        "alt-e",
        score=0.8,
        verification_success=False,
    )
    result = assess_counterfactual(
        policy=build_default_counterfactual_policy(),
        experiment=_experiment(alternative=alternative),
    )

    assert result.disposition is CounterfactualDisposition.REJECTED
    assert result.verified_success_preserved is False


def test_critical_safety_regression_is_zero_tolerance() -> None:
    alternative = _observation(
        "alt",
        "decision:alternative",
        "alt-e",
        score=0.8,
        critical_safety_regressions=1,
    )
    result = assess_counterfactual(
        policy=build_default_counterfactual_policy(),
        experiment=_experiment(alternative=alternative),
    )

    assert result.disposition is CounterfactualDisposition.REJECTED
    assert result.critical_safety_regression_count == 1


def test_non_independent_candidate_evidence_blocks_replay_claim() -> None:
    catalog = (
        _evidence("base-e"),
        _evidence(
            "alt-e",
            origin=CounterfactualEvidenceOrigin.CANDIDATE_OUTPUT,
            independent=False,
        ),
    )
    alternative = _observation("alt", "decision:alternative", "alt-e", score=0.8)
    result = assess_counterfactual(
        policy=build_default_counterfactual_policy(),
        experiment=_experiment(alternative=alternative, evidence_catalog=catalog),
    )

    assert result.disposition is CounterfactualDisposition.BLOCKED
    assert result.executed_counterfactual_evidence is False


def test_candidate_output_cannot_self_declare_independence() -> None:
    with pytest.raises(ValidationError, match="cannot declare itself independent"):
        _evidence(
            "candidate-self",
            origin=CounterfactualEvidenceOrigin.CANDIDATE_OUTPUT,
            independent=True,
        )


def test_unknown_evidence_reference_is_rejected() -> None:
    alternative = _observation("alt", "decision:alternative", "missing", score=0.8)
    with pytest.raises(ValueError, match="unknown counterfactual evidence"):
        assess_counterfactual(
            policy=build_default_counterfactual_policy(),
            experiment=_experiment(alternative=alternative),
        )


def test_same_case_revision_and_environment_are_required() -> None:
    alternative = _observation(
        "alt",
        "decision:alternative",
        "alt-e",
        environment=ReplayEnvironment.CONTROLLED_REPLAY,
    )
    with pytest.raises(ValidationError, match="same replay environment"):
        _experiment(alternative=alternative)


def test_alternative_must_change_tested_decision() -> None:
    alternative = _observation("alt", "decision:baseline", "alt-e")
    with pytest.raises(ValidationError, match="must change the tested decision"):
        _experiment(alternative=alternative)


@pytest.mark.parametrize("kind", list(CounterfactualAlternativeKind))
def test_all_counterfactual_alternative_families_are_representable(
    kind: CounterfactualAlternativeKind,
) -> None:
    experiment = _experiment(
        alternative=_observation("alt", "decision:alternative", "alt-e", score=0.7),
        kind=kind,
    )

    assert experiment.candidate.alternative_kind is kind
