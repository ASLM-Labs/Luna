"""Deterministic learning-integrity assessment for Luna Phase 19C."""

from __future__ import annotations

from luna.evaluation_governance import FrozenEvaluationSuite, ReleaseComparison
from luna.learning_integrity.models import (
    ClaimEvidenceReview,
    EvaluatorAgreementProbe,
    EvidenceOrigin,
    GeneralizationProfile,
    IntegrityEvidence,
    IntegritySeverity,
    LearningExposureRecord,
    LearningIntegrityFinding,
    LearningIntegrityPolicy,
    LearningIntegrityReport,
    LearningIntegrityRisk,
    LearningIntegrityStatus,
    ProxyMetricOutcome,
    ShortcutSliceProbe,
)


def assess_learning_integrity(
    *,
    policy: LearningIntegrityPolicy,
    evaluation_suite: FrozenEvaluationSuite,
    release_comparison: ReleaseComparison,
    generalization_profiles: tuple[GeneralizationProfile, ...] = (),
    shortcut_probes: tuple[ShortcutSliceProbe, ...] = (),
    evaluator_agreement_probes: tuple[EvaluatorAgreementProbe, ...] = (),
    learning_exposure: LearningExposureRecord | None = None,
    proxy_metrics: tuple[ProxyMetricOutcome, ...] = (),
    evidence_catalog: tuple[IntegrityEvidence, ...] = (),
    claim_reviews: tuple[ClaimEvidenceReview, ...] = (),
) -> LearningIntegrityReport:
    """Surface integrity risks without granting runtime or release-promotion authority."""
    findings: list[LearningIntegrityFinding] = []

    for profile in generalization_profiles:
        held_out_gap = profile.training_score - profile.held_out_score
        ood_gap = profile.training_score - profile.ood_score
        if held_out_gap > policy.max_train_held_out_gap + 1e-12:
            findings.append(
                LearningIntegrityFinding(
                    risk=LearningIntegrityRisk.OVERFITTING,
                    severity=IntegritySeverity.BLOCKING,
                    subject_id=profile.profile_id,
                    summary=(
                        "training-to-held-out gap exceeds the frozen integrity threshold"
                    ),
                    evidence_refs=profile.evidence_refs,
                )
            )
        if ood_gap > policy.max_train_ood_gap + 1e-12:
            findings.append(
                LearningIntegrityFinding(
                    risk=LearningIntegrityRisk.OVERFITTING,
                    severity=IntegritySeverity.BLOCKING,
                    subject_id=profile.profile_id,
                    summary="training-to-OOD gap exceeds the frozen integrity threshold",
                    evidence_refs=profile.evidence_refs,
                )
            )

    for shortcut_probe in shortcut_probes:
        if shortcut_probe.observed_gap > policy.max_shortcut_slice_gap + 1e-12:
            findings.append(
                LearningIntegrityFinding(
                    risk=LearningIntegrityRisk.SHORTCUT_LEARNING,
                    severity=IntegritySeverity.BLOCKING,
                    subject_id=shortcut_probe.probe_id,
                    summary=(
                        "matched observational slices show excessive shortcut-associated score gap"
                    ),
                    evidence_refs=shortcut_probe.evidence_refs,
                )
            )

    if learning_exposure is not None and policy.block_benchmark_identity_exposure:
        exposed_cases = sorted(
            set(learning_exposure.benchmark_case_ids) & set(evaluation_suite.case_ids)
        )
        for case_id in exposed_cases:
            findings.append(
                LearningIntegrityFinding(
                    risk=LearningIntegrityRisk.BENCHMARK_GAMING,
                    severity=IntegritySeverity.BLOCKING,
                    subject_id=case_id,
                    summary=(
                        "frozen evaluation case identity was exposed to the learning process"
                    ),
                    evidence_refs=learning_exposure.evidence_refs,
                )
            )
    if (
        learning_exposure is not None
        and policy.block_evaluator_identity_exposure
        and evaluation_suite.evaluator.fingerprint()
        in learning_exposure.evaluator_fingerprints
    ):
        findings.append(
            LearningIntegrityFinding(
                risk=LearningIntegrityRisk.EVALUATOR_GAMING,
                severity=IntegritySeverity.BLOCKING,
                subject_id=evaluation_suite.evaluator.evaluator_id,
                summary="governed evaluator identity was exposed to the learning process",
                evidence_refs=learning_exposure.evidence_refs,
            )
        )

    for evaluator_probe in evaluator_agreement_probes:
        if evaluator_probe.absolute_gap > policy.max_evaluator_disagreement + 1e-12:
            findings.append(
                LearningIntegrityFinding(
                    risk=LearningIntegrityRisk.EVALUATOR_GAMING,
                    severity=IntegritySeverity.BLOCKING,
                    subject_id=evaluator_probe.probe_id,
                    summary="primary and independent evaluator scores disagree beyond threshold",
                    evidence_refs=evaluator_probe.evidence_refs,
                )
            )

    improved_proxy_metrics = tuple(metric for metric in proxy_metrics if metric.improved)
    if improved_proxy_metrics and release_comparison.regressed_case_ids:
        proxy_severity = (
            IntegritySeverity.BLOCKING
            if (
                policy.critical_regression_zero_tolerance
                and release_comparison.critical_regressed_case_ids
            )
            else IntegritySeverity.WARNING
        )
        for metric in improved_proxy_metrics:
            findings.append(
                LearningIntegrityFinding(
                    risk=LearningIntegrityRisk.PROXY_SPECIFICATION_OPTIMIZATION,
                    severity=proxy_severity,
                    subject_id=metric.metric_id,
                    summary=(
                        "proxy metric improved while governed cognitive evaluation regressed"
                    ),
                    evidence_refs=metric.evidence_refs,
                )
            )

    evidence_by_id = {evidence.evidence_id: evidence for evidence in evidence_catalog}
    if len(evidence_by_id) != len(evidence_catalog):
        raise ValueError("integrity evidence IDs must be unique")

    for review in claim_reviews:
        referenced_ids = set(review.supporting_evidence_ids) | set(
            review.contradicting_evidence_ids
        )
        missing = referenced_ids - set(evidence_by_id)
        if missing:
            raise ValueError("claim review references unknown integrity evidence")

        ignored_contradictions = set(review.contradicting_evidence_ids) - set(
            review.considered_evidence_ids
        )
        if ignored_contradictions:
            findings.append(
                LearningIntegrityFinding(
                    risk=LearningIntegrityRisk.CONFIRMATION_BIAS,
                    severity=IntegritySeverity.BLOCKING,
                    subject_id=review.claim_id,
                    summary="contradictory evidence was present but not considered",
                    evidence_refs=tuple(sorted(ignored_contradictions)),
                )
            )

        supporting = tuple(evidence_by_id[item] for item in review.supporting_evidence_ids)
        independent_support = tuple(
            evidence
            for evidence in supporting
            if evidence.independent_from_candidate
            and evidence.origin is not EvidenceOrigin.CANDIDATE_OUTPUT
        )
        if policy.require_independent_claim_evidence and not independent_support:
            findings.append(
                LearningIntegrityFinding(
                    risk=LearningIntegrityRisk.SELF_CONFIRMATION,
                    severity=IntegritySeverity.BLOCKING,
                    subject_id=review.claim_id,
                    summary=(
                        "claim is supported only by non-independent or candidate-origin evidence"
                    ),
                    evidence_refs=review.supporting_evidence_ids,
                )
            )

    findings.sort(
        key=lambda finding: (
            finding.risk.value,
            finding.subject_id,
            finding.summary,
        )
    )
    status = (
        LearningIntegrityStatus.REJECT_CANDIDATE
        if any(finding.severity is IntegritySeverity.BLOCKING for finding in findings)
        else LearningIntegrityStatus.REVIEW_REQUIRED
        if findings
        else LearningIntegrityStatus.CLEAN
    )
    return LearningIntegrityReport(
        policy_sha256=policy.locked_sha256,
        findings=tuple(findings),
        status=status,
        promotion_authorized=False,
    )
