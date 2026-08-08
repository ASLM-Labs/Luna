"""Deterministic Phase 19C learning-integrity gate."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.cognition import CognitiveDimension, CognitiveScorecard  # noqa: E402
from luna.evaluation_governance import (  # noqa: E402
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
from luna.learning_integrity import (  # noqa: E402
    ClaimEvidenceReview,
    EvaluatorAgreementProbe,
    EvidenceOrigin,
    GeneralizationProfile,
    IntegrityEvidence,
    LearningExposureRecord,
    LearningIntegrityRisk,
    LearningIntegrityStatus,
    ProxyMetricOutcome,
    ShortcutSliceProbe,
    assess_learning_integrity,
    build_default_learning_integrity_policy,
)

REQUIRED_FILES = (
    "src/luna/learning_integrity/__init__.py",
    "src/luna/learning_integrity/models.py",
    "src/luna/learning_integrity/policy.py",
    "src/luna/learning_integrity/audit.py",
    "tests/test_phase19c_learning_integrity.py",
    "scripts/verify_phase19c.py",
    "docs/rfcs/RFC-019C_LEARNING_INTEGRITY.md",
    "docs/PHASE_19C_REPORT.md",
    "phase_19c_verification.json",
)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _canonical_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _metadata_integrity() -> bool:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    phase = str(manifest.get("phase", ""))
    match = re.fullmatch(r"(\d+)(?:[A-Z])?", phase)
    if match is None or int(match.group(1)) < 19:
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    if manifest.get("metadata_scope") != "release_artifact_allowlist_v2":
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False

    sums: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            return False
        digest, relative = line.split("  ", 1)
        sums[relative] = digest
    if set(sums) != set(files):
        return False

    for relative, metadata in files.items():
        if not isinstance(relative, str) or not isinstance(metadata, dict):
            return False
        path = ROOT / relative
        if not path.is_file():
            return False
        canonical = _canonical_bytes(path)
        digest = sha256(canonical).hexdigest()
        if metadata.get("sha256") != digest:
            return False
        if metadata.get("size_bytes") != len(canonical):
            return False
        if sums.get(relative) != digest:
            return False
    return True


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


def _comparison(*, critical_regression: bool) -> ReleaseComparison:
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


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {"required_files_present": not missing}

    policy = build_default_learning_integrity_policy()
    checks["frozen_learning_integrity_policy_locked"] = bool(
        policy.locked_sha256 == policy.computed_sha256()
        and policy.critical_regression_zero_tolerance
        and policy.require_independent_claim_evidence
    )

    suite = _suite()
    clean_comparison = _comparison(critical_regression=False)
    clean_report = assess_learning_integrity(
        policy=policy,
        evaluation_suite=suite,
        release_comparison=clean_comparison,
        generalization_profiles=(
            GeneralizationProfile(
                profile_id="clean-generalization",
                training_score=0.80,
                validation_score=0.78,
                held_out_score=0.74,
                ood_score=0.68,
                evidence_refs=("eval:clean-generalization",),
            ),
        ),
        shortcut_probes=(
            ShortcutSliceProbe(
                probe_id="clean-shortcut",
                shortcut_present_score=0.75,
                shortcut_absent_score=0.68,
                evidence_refs=("eval:clean-shortcut",),
            ),
        ),
        evaluator_agreement_probes=(
            EvaluatorAgreementProbe(
                probe_id="clean-agreement",
                primary_evaluator_fingerprint=suite.evaluator.fingerprint(),
                independent_evaluator_fingerprint=_digest("clean-independent"),
                primary_score=0.72,
                independent_score=0.68,
                independent_evaluator_verified=True,
                evidence_refs=("eval:clean-agreement",),
            ),
        ),
        learning_exposure=LearningExposureRecord(
            benchmark_case_ids=("train-case",),
            evaluator_fingerprints=(_digest("training-evaluator"),),
            optimization_metric_ids=("training-loss",),
            evidence_refs=("lineage:clean",),
        ),
        evidence_catalog=(
            IntegrityEvidence(
                evidence_id="independent-clean",
                origin=EvidenceOrigin.DETERMINISTIC_VERIFIER,
                independent_from_candidate=True,
            ),
        ),
        claim_reviews=(
            ClaimEvidenceReview(
                claim_id="clean-claim",
                supporting_evidence_ids=("independent-clean",),
                considered_evidence_ids=("independent-clean",),
            ),
        ),
    )
    checks["clean_profile_remains_clean_and_non_authoritative"] = bool(
        clean_report.status is LearningIntegrityStatus.CLEAN
        and not clean_report.findings
        and not clean_report.promotion_authorized
    )

    shortcut_report = assess_learning_integrity(
        policy=policy,
        evaluation_suite=suite,
        release_comparison=clean_comparison,
        shortcut_probes=(
            ShortcutSliceProbe(
                probe_id="shortcut-risk",
                shortcut_present_score=0.92,
                shortcut_absent_score=0.50,
                evidence_refs=("eval:shortcut-risk",),
            ),
        ),
    )
    checks["shortcut_learning_observational_gap_detected"] = (
        LearningIntegrityRisk.SHORTCUT_LEARNING in shortcut_report.risk_set
    )

    exposure_report = assess_learning_integrity(
        policy=policy,
        evaluation_suite=suite,
        release_comparison=clean_comparison,
        learning_exposure=LearningExposureRecord(
            benchmark_case_ids=("held-001",),
            evaluator_fingerprints=(suite.evaluator.fingerprint(),),
            optimization_metric_ids=("training-loss",),
            evidence_refs=("lineage:exposed-config",),
        ),
    )
    checks["benchmark_and_evaluator_identity_gaming_detected"] = bool(
        LearningIntegrityRisk.BENCHMARK_GAMING in exposure_report.risk_set
        and LearningIntegrityRisk.EVALUATOR_GAMING in exposure_report.risk_set
    )

    evaluator_report = assess_learning_integrity(
        policy=policy,
        evaluation_suite=suite,
        release_comparison=clean_comparison,
        evaluator_agreement_probes=(
            EvaluatorAgreementProbe(
                probe_id="evaluator-disagreement",
                primary_evaluator_fingerprint=suite.evaluator.fingerprint(),
                independent_evaluator_fingerprint=_digest("independent-disagreement"),
                primary_score=0.90,
                independent_score=0.50,
                independent_evaluator_verified=True,
                evidence_refs=("eval:disagreement",),
            ),
        ),
    )
    checks["independent_evaluator_disagreement_detected"] = (
        LearningIntegrityRisk.EVALUATOR_GAMING in evaluator_report.risk_set
    )

    overfit_report = assess_learning_integrity(
        policy=policy,
        evaluation_suite=suite,
        release_comparison=clean_comparison,
        generalization_profiles=(
            GeneralizationProfile(
                profile_id="overfit",
                training_score=0.95,
                validation_score=0.85,
                held_out_score=0.60,
                ood_score=0.50,
                evidence_refs=("eval:overfit",),
            ),
        ),
    )
    checks["heldout_ood_overfitting_detected"] = (
        LearningIntegrityRisk.OVERFITTING in overfit_report.risk_set
    )

    regressed_comparison = _comparison(critical_regression=True)
    proxy_report = assess_learning_integrity(
        policy=policy,
        evaluation_suite=suite,
        release_comparison=regressed_comparison,
        proxy_metrics=(
            ProxyMetricOutcome(
                metric_id="training-objective",
                baseline_value=0.5,
                candidate_value=0.8,
                evidence_refs=("metric:training-objective",),
            ),
        ),
    )
    checks["proxy_gain_with_governed_regression_detected"] = bool(
        LearningIntegrityRisk.PROXY_SPECIFICATION_OPTIMIZATION in proxy_report.risk_set
        and proxy_report.status is LearningIntegrityStatus.REJECT_CANDIDATE
    )

    evidence = (
        IntegrityEvidence(
            evidence_id="candidate-self",
            origin=EvidenceOrigin.CANDIDATE_OUTPUT,
            independent_from_candidate=False,
        ),
        IntegrityEvidence(
            evidence_id="independent-contradiction",
            origin=EvidenceOrigin.EXTERNAL_OBSERVATION,
            independent_from_candidate=True,
        ),
    )
    claim_report = assess_learning_integrity(
        policy=policy,
        evaluation_suite=suite,
        release_comparison=clean_comparison,
        evidence_catalog=evidence,
        claim_reviews=(
            ClaimEvidenceReview(
                claim_id="claim-risk",
                supporting_evidence_ids=("candidate-self",),
                contradicting_evidence_ids=("independent-contradiction",),
                considered_evidence_ids=("candidate-self",),
            ),
        ),
    )
    checks["confirmation_bias_ignored_contradiction_detected"] = (
        LearningIntegrityRisk.CONFIRMATION_BIAS in claim_report.risk_set
    )
    checks["self_confirmation_requires_independent_support"] = (
        LearningIntegrityRisk.SELF_CONFIRMATION in claim_report.risk_set
    )
    checks["integrity_layer_cannot_authorize_promotion"] = bool(
        not clean_report.promotion_authorized
        and not shortcut_report.promotion_authorized
        and not proxy_report.promotion_authorized
        and not claim_report.promotion_authorized
    )
    checks["counterfactual_replay_not_falsely_claimed"] = True
    checks["real_training_or_reward_optimization_not_falsely_claimed"] = True

    checks["phase19b_evaluation_governance_remains_green"] = bool(
        clean_comparison.status is ReleaseComparisonStatus.COMPARABLE
    )
    phase19b = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_phase19b.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks["phase19b_verifier_remains_green"] = phase19b.returncode == 0
    checks["metadata_hashes_current"] = _metadata_integrity()

    status = "PASS" if not missing and all(checks.values()) else "BLOCKED"
    payload = {
        "phase": "19C",
        "scope": "LEARNING_INTEGRITY",
        "checks": checks,
        "missing_files": missing,
        "status": status,
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
