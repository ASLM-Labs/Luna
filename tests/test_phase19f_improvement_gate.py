from __future__ import annotations

from hashlib import sha256

from luna.cognition import CognitiveDimension, CognitiveScorecard
from luna.evaluation_governance import (
    BenchmarkContaminationReport,
    ContaminationFinding,
    ContaminationReason,
    EvaluationCase,
    EvaluationPartition,
    EvaluatorKind,
    EvaluatorSpec,
    FrozenEvaluationSuite,
    build_release_snapshot,
    freeze_regression_suite,
)
from luna.improvement_gate import (
    EvaluationSlice,
    ImprovementGateDecision,
    MetricDisposition,
    build_default_improvement_gate_policy,
    evaluate_improvement_gate,
)
from luna.learning_integrity import (
    IntegritySeverity,
    LearningIntegrityFinding,
    LearningIntegrityReport,
    LearningIntegrityRisk,
    LearningIntegrityStatus,
)
from luna.sft import SFTTrainingReceipt, SFTTrainingSpec, register_training_receipt


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _cases() -> tuple[EvaluationCase, ...]:
    return tuple(
        EvaluationCase(
            case_id=case_id,
            source_trajectory_id=f"source-{case_id}",
            partition=partition,
            task_family=f"task-{case_id}",
            repository_family=f"repo-{case_id}",
            trajectory_family=f"trajectory-{case_id}",
            content_sha256=_digest(f"content-{case_id}"),
            evidence_refs=(f"fixture:{case_id}",),
        )
        for case_id, partition in (
            ("held-001", EvaluationPartition.HELD_OUT),
            ("held-002", EvaluationPartition.HELD_OUT),
            ("ood-001", EvaluationPartition.OOD),
            ("ood-002", EvaluationPartition.OOD),
        )
    )


def _suite(*, cases: tuple[EvaluationCase, ...] | None = None) -> FrozenEvaluationSuite:
    evaluator = EvaluatorSpec(
        evaluator_id="phase19f-deterministic-evaluator",
        revision="1.0.0",
        kind=EvaluatorKind.DETERMINISTIC,
        implementation_sha256=_digest("phase19f-evaluator-v1"),
        independent_from_candidate_artifacts=True,
        independent_from_training_data=True,
    )
    return FrozenEvaluationSuite.freeze(
        suite_name="phase19f-heldout-ood",
        revision="1.0.0",
        evaluator=evaluator,
        cases=cases or _cases(),
    )


def _scores(value: float = 0.5) -> dict[CognitiveDimension, float]:
    return {dimension: value for dimension in CognitiveDimension}


def _scorecards(
    *,
    cases: tuple[EvaluationCase, ...],
    adjustments: dict[CognitiveDimension, float] | None = None,
    critical_case_id: str | None = None,
) -> tuple[CognitiveScorecard, ...]:
    adjustments = adjustments or {}
    return tuple(
        CognitiveScorecard(
            case_id=case.case_id,
            scores={
                dimension: 0.5 + adjustments.get(dimension, 0.0)
                for dimension in CognitiveDimension
            },
            evidence_refs=(f"evaluation:{case.case_id}",),
            critical_regression=case.case_id == critical_case_id,
        )
        for case in cases
    )


def _candidate_chain():
    spec = SFTTrainingSpec.freeze(
        candidate_id="phase19f-candidate",
        base_model_id="fixture/base",
        base_model_revision="base-rev-001",
        trainer_id="fixture-trainer",
        trainer_revision="trainer-rev-001",
        corpus_sha256=_digest("corpus"),
        corpus_record_count=100,
        policy_sha256=_digest("phase19e-policy"),
        seed=19,
        epochs=1.0,
        learning_rate=2e-5,
        max_sequence_tokens=4096,
    )
    receipt = SFTTrainingReceipt(
        candidate_id=spec.candidate_id,
        training_spec_sha256=spec.locked_sha256,
        corpus_sha256=spec.corpus_sha256,
        base_model_revision=spec.base_model_revision,
        trainer_revision=spec.trainer_revision,
        training_executed=True,
        exit_code=0,
        artifact_sha256=_digest("trained-artifact"),
        artifact_size_bytes=1024,
        training_log_sha256=_digest("training-log"),
        held_out_used_during_training=False,
        runtime_authority_granted=False,
        evidence_refs=("fixture:external-training",),
    )
    artifact = register_training_receipt(spec=spec, receipt=receipt)
    return spec, receipt, artifact


def _clean_integrity() -> LearningIntegrityReport:
    return LearningIntegrityReport(
        policy_sha256=_digest("integrity-policy"),
        status=LearningIntegrityStatus.CLEAN,
    )


def _review_integrity() -> LearningIntegrityReport:
    return LearningIntegrityReport(
        policy_sha256=_digest("integrity-policy"),
        findings=(
            LearningIntegrityFinding(
                risk=LearningIntegrityRisk.PROXY_SPECIFICATION_OPTIMIZATION,
                severity=IntegritySeverity.WARNING,
                subject_id="proxy",
                summary="fixture warning",
                evidence_refs=("fixture:warning",),
            ),
        ),
        status=LearningIntegrityStatus.REVIEW_REQUIRED,
    )


def _blocking_integrity() -> LearningIntegrityReport:
    return LearningIntegrityReport(
        policy_sha256=_digest("integrity-policy"),
        findings=(
            LearningIntegrityFinding(
                risk=LearningIntegrityRisk.SELF_CONFIRMATION,
                severity=IntegritySeverity.BLOCKING,
                subject_id="claim",
                summary="fixture blocking integrity failure",
                evidence_refs=("fixture:blocking",),
            ),
        ),
        status=LearningIntegrityStatus.REJECT_CANDIDATE,
    )


def _bundle(
    *,
    adjustments: dict[CognitiveDimension, float] | None = None,
    critical_case_id: str | None = None,
):
    policy = build_default_improvement_gate_policy()
    suite = _suite()
    regression = freeze_regression_suite(
        revision="1.0.0",
        evaluation_suite=suite,
        critical_case_ids=("held-001",),
    )
    baseline = build_release_snapshot(
        release_id="baseline",
        candidate_model_id="base-model",
        evaluation_suite=suite,
        scorecards=_scorecards(cases=suite.cases),
    )
    candidate = build_release_snapshot(
        release_id="candidate",
        candidate_model_id="phase19f-candidate",
        evaluation_suite=suite,
        scorecards=_scorecards(
            cases=suite.cases,
            adjustments=adjustments,
            critical_case_id=critical_case_id,
        ),
    )
    spec, receipt, artifact = _candidate_chain()
    return {
        "policy": policy,
        "candidate_spec": spec,
        "candidate_receipt": receipt,
        "candidate_artifact": artifact,
        "evaluation_suite": suite,
        "regression_suite": regression,
        "baseline_snapshot": baseline,
        "candidate_snapshot": candidate,
        "contamination_report": BenchmarkContaminationReport(),
        "learning_integrity_report": _clean_integrity(),
    }


def test_default_improvement_gate_policy_is_frozen_and_has_no_runtime_authority() -> None:
    policy = build_default_improvement_gate_policy()

    assert policy.locked_sha256 == policy.computed_sha256()
    assert policy.runtime_authority is False
    assert set(policy.dimension_thresholds) == set(CognitiveDimension)


def test_missing_real_candidate_evidence_returns_insufficient_evidence() -> None:
    policy = build_default_improvement_gate_policy()

    report = evaluate_improvement_gate(policy=policy)

    assert report.decision is ImprovementGateDecision.INSUFFICIENT_EVIDENCE
    assert report.candidate_evidence_verified is False
    assert "verified real trained candidate evidence is missing" in report.blocked_reasons
    assert report.runtime_authority is False
    assert report.action_executed is False


def test_confidence_supported_improvement_can_recommend_promote_without_executing() -> None:
    bundle = _bundle(adjustments={CognitiveDimension.REASONING: 0.03})

    report = evaluate_improvement_gate(**bundle)

    assert report.decision is ImprovementGateDecision.PROMOTE
    assert report.meaningfully_improved_dimensions == (CognitiveDimension.REASONING,)
    assert report.meaningfully_regressed_dimensions == ()
    assert report.runtime_authority is False
    assert report.action_executed is False
    assert all(estimate.case_count >= 2 for estimate in report.estimates)


def test_small_noncritical_drop_inside_tolerance_does_not_force_reject() -> None:
    bundle = _bundle(
        adjustments={
            CognitiveDimension.REASONING: 0.03,
            CognitiveDimension.PLANNING: -0.005,
        }
    )

    candidate = bundle["candidate_snapshot"]
    cards = list(candidate.scorecards)
    critical = cards[0]
    critical_scores = dict(critical.scores)
    critical_scores[CognitiveDimension.PLANNING] = 0.5
    cards[0] = critical.model_copy(update={"scores": critical_scores})
    bundle["candidate_snapshot"] = candidate.model_copy(update={"scorecards": tuple(cards)})

    report = evaluate_improvement_gate(**bundle)

    assert report.decision is ImprovementGateDecision.PROMOTE
    planning = tuple(
        estimate
        for estimate in report.estimates
        if estimate.dimension is CognitiveDimension.PLANNING
        and estimate.evaluation_slice is EvaluationSlice.ALL
    )
    assert planning[0].disposition is MetricDisposition.NO_CLEAR_CHANGE


def test_meaningful_noncritical_regression_rejects_candidate() -> None:
    bundle = _bundle(
        adjustments={
            CognitiveDimension.REASONING: 0.03,
            CognitiveDimension.PLANNING: -0.03,
        }
    )

    candidate = bundle["candidate_snapshot"]
    cards = list(candidate.scorecards)
    critical = cards[0]
    critical_scores = dict(critical.scores)
    critical_scores[CognitiveDimension.PLANNING] = 0.5
    cards[0] = critical.model_copy(update={"scores": critical_scores})
    bundle["candidate_snapshot"] = candidate.model_copy(update={"scorecards": tuple(cards)})

    report = evaluate_improvement_gate(**bundle)

    assert report.decision is ImprovementGateDecision.REJECT
    assert CognitiveDimension.PLANNING in report.meaningfully_regressed_dimensions
    assert "meaningful non-critical regression exceeds frozen tolerance" in report.blocked_reasons


def test_critical_case_regression_is_zero_tolerance() -> None:
    bundle = _bundle(adjustments={CognitiveDimension.REASONING: 0.03})
    candidate = bundle["candidate_snapshot"]
    cards = list(candidate.scorecards)
    first = cards[0]
    scores = dict(first.scores)
    scores[CognitiveDimension.EVIDENCE_USAGE] -= 0.0001
    cards[0] = first.model_copy(update={"scores": scores})
    bundle["candidate_snapshot"] = candidate.model_copy(update={"scorecards": tuple(cards)})

    report = evaluate_improvement_gate(**bundle)

    assert report.decision is ImprovementGateDecision.REJECT
    assert report.critical_regressed_case_ids == ("held-001",)


def test_active_candidate_with_critical_regression_recommends_rollback() -> None:
    bundle = _bundle(
        adjustments={CognitiveDimension.REASONING: 0.03},
        critical_case_id="held-001",
    )

    report = evaluate_improvement_gate(**bundle, candidate_currently_active=True)

    assert report.decision is ImprovementGateDecision.ROLLBACK
    assert report.candidate_currently_active is True
    assert report.action_executed is False


def test_contamination_rejects_promotion_evidence() -> None:
    bundle = _bundle(adjustments={CognitiveDimension.REASONING: 0.03})
    bundle["contamination_report"] = BenchmarkContaminationReport(
        findings=(
            ContaminationFinding(
                case_id="held-001",
                exposure_source_trajectory_id="training-source",
                reason=ContaminationReason.TASK_FAMILY,
            ),
        )
    )

    report = evaluate_improvement_gate(**bundle)

    assert report.decision is ImprovementGateDecision.REJECT
    assert report.contamination_detected is True
    assert "benchmark contamination detected" in report.blocked_reasons


def test_learning_integrity_review_blocks_promotion_until_more_evidence() -> None:
    bundle = _bundle(adjustments={CognitiveDimension.REASONING: 0.03})
    bundle["learning_integrity_report"] = _review_integrity()

    report = evaluate_improvement_gate(**bundle)

    assert report.decision is ImprovementGateDecision.INSUFFICIENT_EVIDENCE
    assert report.learning_integrity_status is LearningIntegrityStatus.REVIEW_REQUIRED


def test_blocking_learning_integrity_rejects_candidate() -> None:
    bundle = _bundle(adjustments={CognitiveDimension.REASONING: 0.03})
    bundle["learning_integrity_report"] = _blocking_integrity()

    report = evaluate_improvement_gate(**bundle)

    assert report.decision is ImprovementGateDecision.REJECT
    assert "learning integrity contains blocking findings" in report.blocked_reasons


def test_evaluator_identity_drift_rejects_like_for_like_claim() -> None:
    bundle = _bundle(adjustments={CognitiveDimension.REASONING: 0.03})
    candidate = bundle["candidate_snapshot"]
    bundle["candidate_snapshot"] = candidate.model_copy(
        update={"evaluator_fingerprint": _digest("different-evaluator")}
    )

    report = evaluate_improvement_gate(**bundle)

    assert report.decision is ImprovementGateDecision.REJECT
    assert "candidate evaluator identity drift" in report.blocked_reasons


def test_candidate_snapshot_must_match_trained_artifact_identity() -> None:
    bundle = _bundle(adjustments={CognitiveDimension.REASONING: 0.03})
    candidate = bundle["candidate_snapshot"]
    bundle["candidate_snapshot"] = candidate.model_copy(
        update={"candidate_model_id": "different-candidate"}
    )

    report = evaluate_improvement_gate(**bundle)

    assert report.decision is ImprovementGateDecision.REJECT
    assert (
        "candidate snapshot model identity does not match trained artifact"
        in report.blocked_reasons
    )


def test_no_meaningful_improvement_is_not_promoted() -> None:
    bundle = _bundle()

    report = evaluate_improvement_gate(**bundle)

    assert report.decision is ImprovementGateDecision.INSUFFICIENT_EVIDENCE
    assert "candidate has no confidence-supported meaningful improvement" in report.blocked_reasons


def test_too_few_cases_per_partition_is_insufficient_evidence() -> None:
    small_cases = (_cases()[0], _cases()[2])
    suite = _suite(cases=small_cases)
    regression = freeze_regression_suite(revision="1.0.0", evaluation_suite=suite)
    baseline = build_release_snapshot(
        release_id="baseline",
        candidate_model_id="base-model",
        evaluation_suite=suite,
        scorecards=_scorecards(cases=small_cases),
    )
    candidate = build_release_snapshot(
        release_id="candidate",
        candidate_model_id="phase19f-candidate",
        evaluation_suite=suite,
        scorecards=_scorecards(
            cases=small_cases,
            adjustments={CognitiveDimension.REASONING: 0.03},
        ),
    )
    spec, receipt, artifact = _candidate_chain()

    report = evaluate_improvement_gate(
        policy=build_default_improvement_gate_policy(),
        candidate_spec=spec,
        candidate_receipt=receipt,
        candidate_artifact=artifact,
        evaluation_suite=suite,
        regression_suite=regression,
        baseline_snapshot=baseline,
        candidate_snapshot=candidate,
        contamination_report=BenchmarkContaminationReport(),
        learning_integrity_report=_clean_integrity(),
    )

    assert report.decision is ImprovementGateDecision.INSUFFICIENT_EVIDENCE
    assert "HELD_OUT" in report.blocked_reasons[0]
    assert "OOD" in report.blocked_reasons[0]
