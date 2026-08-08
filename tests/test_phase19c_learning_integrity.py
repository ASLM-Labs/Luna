from __future__ import annotations

from hashlib import sha256

import pytest
from pydantic import ValidationError

from luna.cognition import CognitiveDimension, CognitiveScorecard
from luna.evaluation_governance import (
    BenchmarkContaminationReport,
    EvaluationCase,
    EvaluationPartition,
    EvaluatorKind,
    EvaluatorSpec,
    FrozenEvaluationSuite,
    ReleaseComparison,
    ReleaseComparisonStatus,
    build_release_snapshot,
    compare_release_snapshots,
    freeze_regression_suite,
)
from luna.learning_integrity import (
    ClaimEvidenceReview,
    EvaluatorAgreementProbe,
    EvidenceOrigin,
    GeneralizationProfile,
    IntegrityEvidence,
    LearningExposureRecord,
    LearningIntegrityPolicy,
    LearningIntegrityRisk,
    LearningIntegrityStatus,
    ProxyMetricOutcome,
    ShortcutSliceProbe,
    assess_learning_integrity,
    build_default_learning_integrity_policy,
)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _suite() -> FrozenEvaluationSuite:
    evaluator = EvaluatorSpec(
        evaluator_id="phase19c-primary",
        revision="1.0.0",
        kind=EvaluatorKind.DETERMINISTIC,
        implementation_sha256=_digest("phase19c-primary-v1"),
        independent_from_candidate_artifacts=True,
        independent_from_training_data=True,
    )
    return FrozenEvaluationSuite.freeze(
        suite_name="phase19c-heldout-ood",
        revision="1.0.0",
        evaluator=evaluator,
        cases=(
            EvaluationCase(
                case_id="held-001",
                source_trajectory_id="held-source-001",
                partition=EvaluationPartition.HELD_OUT,
                task_family="held-task",
                repository_family="held-repository",
                trajectory_family="held-trajectory",
                content_sha256=_digest("held-content"),
                evidence_refs=("fixture:held",),
            ),
            EvaluationCase(
                case_id="ood-001",
                source_trajectory_id="ood-source-001",
                partition=EvaluationPartition.OOD,
                task_family="ood-task",
                repository_family="ood-repository",
                trajectory_family="ood-trajectory",
                content_sha256=_digest("ood-content"),
                evidence_refs=("fixture:ood",),
            ),
        ),
    )


def _scorecards(value: float) -> tuple[CognitiveScorecard, ...]:
    return tuple(
        CognitiveScorecard(
            case_id=case_id,
            scores={dimension: value for dimension in CognitiveDimension},
            evidence_refs=(f"eval:{case_id}",),
        )
        for case_id in ("held-001", "ood-001")
    )


def _comparison(*, critical_regression: bool = False) -> ReleaseComparison:
    suite = _suite()
    regression = freeze_regression_suite(
        revision="1.0.0",
        evaluation_suite=suite,
        critical_case_ids=("held-001",),
    )
    baseline = build_release_snapshot(
        release_id="baseline",
        candidate_model_id="baseline-model",
        evaluation_suite=suite,
        scorecards=_scorecards(0.6),
    )
    candidate_cards = list(_scorecards(0.6))
    if critical_regression:
        scores = dict(candidate_cards[0].scores)
        scores[CognitiveDimension.EVIDENCE_USAGE] = 0.4
        candidate_cards[0] = candidate_cards[0].model_copy(update={"scores": scores})
    candidate = build_release_snapshot(
        release_id="candidate",
        candidate_model_id="candidate-model",
        evaluation_suite=suite,
        scorecards=tuple(candidate_cards),
    )
    return compare_release_snapshots(
        baseline=baseline,
        candidate=candidate,
        regression_suite=regression,
        contamination_report=BenchmarkContaminationReport(),
    )


def test_default_policy_is_revision_locked() -> None:
    policy = build_default_learning_integrity_policy()

    assert policy.revision == "1.0.0"
    assert policy.locked_sha256 == policy.computed_sha256()
    assert policy.critical_regression_zero_tolerance is True


def test_tampered_policy_digest_is_rejected() -> None:
    policy = build_default_learning_integrity_policy()
    payload = policy.model_dump()
    payload["locked_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="policy digest mismatch"):
        LearningIntegrityPolicy.model_validate(payload)


def test_clean_integrity_profile_stays_clean_without_promotion_authority() -> None:
    policy = build_default_learning_integrity_policy()
    suite = _suite()
    report = assess_learning_integrity(
        policy=policy,
        evaluation_suite=suite,
        release_comparison=_comparison(),
        generalization_profiles=(
            GeneralizationProfile(
                profile_id="clean-generalization",
                training_score=0.80,
                validation_score=0.78,
                held_out_score=0.74,
                ood_score=0.68,
                evidence_refs=("eval:generalization",),
            ),
        ),
        shortcut_probes=(
            ShortcutSliceProbe(
                probe_id="clean-shortcut",
                shortcut_present_score=0.75,
                shortcut_absent_score=0.68,
                evidence_refs=("eval:shortcut",),
            ),
        ),
        evaluator_agreement_probes=(
            EvaluatorAgreementProbe(
                probe_id="clean-agreement",
                primary_evaluator_fingerprint=suite.evaluator.fingerprint(),
                independent_evaluator_fingerprint=_digest("independent-evaluator"),
                primary_score=0.72,
                independent_score=0.68,
                independent_evaluator_verified=True,
                evidence_refs=("eval:agreement",),
            ),
        ),
        learning_exposure=LearningExposureRecord(
            benchmark_case_ids=("train-case-001",),
            evaluator_fingerprints=(_digest("training-evaluator"),),
            optimization_metric_ids=("training-loss",),
            evidence_refs=("lineage:training",),
        ),
        evidence_catalog=(
            IntegrityEvidence(
                evidence_id="independent-1",
                origin=EvidenceOrigin.DETERMINISTIC_VERIFIER,
                independent_from_candidate=True,
            ),
        ),
        claim_reviews=(
            ClaimEvidenceReview(
                claim_id="claim-clean",
                supporting_evidence_ids=("independent-1",),
                considered_evidence_ids=("independent-1",),
            ),
        ),
    )

    assert report.status is LearningIntegrityStatus.CLEAN
    assert report.findings == ()
    assert report.promotion_authorized is False


def test_overfitting_is_detected_from_frozen_generalization_gaps() -> None:
    report = assess_learning_integrity(
        policy=build_default_learning_integrity_policy(),
        evaluation_suite=_suite(),
        release_comparison=_comparison(),
        generalization_profiles=(
            GeneralizationProfile(
                profile_id="overfit-profile",
                training_score=0.95,
                validation_score=0.88,
                held_out_score=0.60,
                ood_score=0.50,
                evidence_refs=("eval:generalization",),
            ),
        ),
    )

    assert report.status is LearningIntegrityStatus.REJECT_CANDIDATE
    assert LearningIntegrityRisk.OVERFITTING in report.risk_set


def test_shortcut_dependency_risk_uses_matched_observational_slices() -> None:
    report = assess_learning_integrity(
        policy=build_default_learning_integrity_policy(),
        evaluation_suite=_suite(),
        release_comparison=_comparison(),
        shortcut_probes=(
            ShortcutSliceProbe(
                probe_id="shortcut-probe",
                shortcut_present_score=0.92,
                shortcut_absent_score=0.55,
                evidence_refs=("eval:shortcut-slices",),
            ),
        ),
    )

    assert LearningIntegrityRisk.SHORTCUT_LEARNING in report.risk_set


def test_unmatched_shortcut_slices_are_rejected_as_invalid_evidence() -> None:
    with pytest.raises(ValidationError, match="matched observational slices"):
        ShortcutSliceProbe(
            probe_id="bad-probe",
            shortcut_present_score=0.90,
            shortcut_absent_score=0.40,
            matched_observational_slices=False,
            evidence_refs=("eval:bad",),
        )


def test_frozen_benchmark_and_evaluator_identity_exposure_is_blocking() -> None:
    suite = _suite()
    report = assess_learning_integrity(
        policy=build_default_learning_integrity_policy(),
        evaluation_suite=suite,
        release_comparison=_comparison(),
        learning_exposure=LearningExposureRecord(
            benchmark_case_ids=("held-001",),
            evaluator_fingerprints=(suite.evaluator.fingerprint(),),
            optimization_metric_ids=("training-loss",),
            evidence_refs=("lineage:training-config",),
        ),
    )

    assert LearningIntegrityRisk.BENCHMARK_GAMING in report.risk_set
    assert LearningIntegrityRisk.EVALUATOR_GAMING in report.risk_set
    assert report.status is LearningIntegrityStatus.REJECT_CANDIDATE


def test_independent_evaluator_disagreement_is_detected() -> None:
    suite = _suite()
    report = assess_learning_integrity(
        policy=build_default_learning_integrity_policy(),
        evaluation_suite=suite,
        release_comparison=_comparison(),
        evaluator_agreement_probes=(
            EvaluatorAgreementProbe(
                probe_id="agreement-risk",
                primary_evaluator_fingerprint=suite.evaluator.fingerprint(),
                independent_evaluator_fingerprint=_digest("shadow-evaluator"),
                primary_score=0.90,
                independent_score=0.55,
                independent_evaluator_verified=True,
                evidence_refs=("eval:agreement-risk",),
            ),
        ),
    )

    assert LearningIntegrityRisk.EVALUATOR_GAMING in report.risk_set


def test_same_evaluator_cannot_be_used_as_independent_agreement_probe() -> None:
    fingerprint = _digest("same-evaluator")
    with pytest.raises(ValidationError, match="distinct independent evaluator"):
        EvaluatorAgreementProbe(
            probe_id="invalid-agreement",
            primary_evaluator_fingerprint=fingerprint,
            independent_evaluator_fingerprint=fingerprint,
            primary_score=0.7,
            independent_score=0.7,
            independent_evaluator_verified=True,
            evidence_refs=("eval:invalid",),
        )


def test_proxy_improvement_with_governed_regression_is_blocking() -> None:
    comparison = _comparison(critical_regression=True)
    assert comparison.status is ReleaseComparisonStatus.REGRESSION_DETECTED

    report = assess_learning_integrity(
        policy=build_default_learning_integrity_policy(),
        evaluation_suite=_suite(),
        release_comparison=comparison,
        proxy_metrics=(
            ProxyMetricOutcome(
                metric_id="training-objective",
                baseline_value=0.5,
                candidate_value=0.8,
                evidence_refs=("metric:training-objective",),
            ),
        ),
    )

    assert LearningIntegrityRisk.PROXY_SPECIFICATION_OPTIMIZATION in report.risk_set


def test_ignored_contradiction_is_confirmation_bias() -> None:
    report = assess_learning_integrity(
        policy=build_default_learning_integrity_policy(),
        evaluation_suite=_suite(),
        release_comparison=_comparison(),
        evidence_catalog=(
            IntegrityEvidence(
                evidence_id="support",
                origin=EvidenceOrigin.DETERMINISTIC_VERIFIER,
                independent_from_candidate=True,
            ),
            IntegrityEvidence(
                evidence_id="contradiction",
                origin=EvidenceOrigin.EXTERNAL_OBSERVATION,
                independent_from_candidate=True,
            ),
        ),
        claim_reviews=(
            ClaimEvidenceReview(
                claim_id="claim-biased",
                supporting_evidence_ids=("support",),
                contradicting_evidence_ids=("contradiction",),
                considered_evidence_ids=("support",),
            ),
        ),
    )

    assert LearningIntegrityRisk.CONFIRMATION_BIAS in report.risk_set


def test_candidate_output_alone_is_self_confirmation_not_independent_verification() -> None:
    report = assess_learning_integrity(
        policy=build_default_learning_integrity_policy(),
        evaluation_suite=_suite(),
        release_comparison=_comparison(),
        evidence_catalog=(
            IntegrityEvidence(
                evidence_id="candidate-self",
                origin=EvidenceOrigin.CANDIDATE_OUTPUT,
                independent_from_candidate=False,
            ),
        ),
        claim_reviews=(
            ClaimEvidenceReview(
                claim_id="claim-self-confirmed",
                supporting_evidence_ids=("candidate-self",),
                considered_evidence_ids=("candidate-self",),
            ),
        ),
    )

    assert LearningIntegrityRisk.SELF_CONFIRMATION in report.risk_set
    assert report.promotion_authorized is False


def test_candidate_output_cannot_mark_itself_independent() -> None:
    with pytest.raises(ValidationError, match="cannot be independent evidence"):
        IntegrityEvidence(
            evidence_id="bad-self-evidence",
            origin=EvidenceOrigin.CANDIDATE_OUTPUT,
            independent_from_candidate=True,
        )


def test_unknown_claim_evidence_is_rejected_instead_of_invented() -> None:
    with pytest.raises(ValueError, match="unknown integrity evidence"):
        assess_learning_integrity(
            policy=build_default_learning_integrity_policy(),
            evaluation_suite=_suite(),
            release_comparison=_comparison(),
            claim_reviews=(
                ClaimEvidenceReview(
                    claim_id="claim-missing-evidence",
                    supporting_evidence_ids=("missing",),
                    considered_evidence_ids=("missing",),
                ),
            ),
        )
