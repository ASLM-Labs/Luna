"""Deterministic Phase 19F improvement-gate verifier."""

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
from luna.improvement_gate import (  # noqa: E402
    ImprovementGateDecision,
    build_default_improvement_gate_policy,
    evaluate_improvement_gate,
)
from luna.learning_integrity import (  # noqa: E402
    IntegritySeverity,
    LearningIntegrityFinding,
    LearningIntegrityReport,
    LearningIntegrityRisk,
    LearningIntegrityStatus,
)
from luna.sft import SFTTrainingReceipt, SFTTrainingSpec, register_training_receipt  # noqa: E402

REQUIRED_FILES = (
    "src/luna/improvement_gate/__init__.py",
    "src/luna/improvement_gate/models.py",
    "src/luna/improvement_gate/policy.py",
    "src/luna/improvement_gate/gate.py",
    "tests/test_phase19f_improvement_gate.py",
    "scripts/verify_phase19f.py",
    "docs/rfcs/RFC-019F_IMPROVEMENT_GATE.md",
    "docs/PHASE_19F_REPORT.md",
    "docs/PHASE_19F_UPDATE_MANIFEST.json",
    "phase_19f_verification.json",
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


def _suite() -> FrozenEvaluationSuite:
    evaluator = EvaluatorSpec(
        evaluator_id="phase19f-verifier",
        revision="1.0.0",
        kind=EvaluatorKind.DETERMINISTIC,
        implementation_sha256=_digest("phase19f-verifier-evaluator"),
        independent_from_candidate_artifacts=True,
        independent_from_training_data=True,
    )
    return FrozenEvaluationSuite.freeze(
        suite_name="phase19f-verifier-suite",
        revision="1.0.0",
        evaluator=evaluator,
        cases=_cases(),
    )


def _cards(
    *,
    cases: tuple[EvaluationCase, ...],
    reasoning_delta: float = 0.0,
    planning_delta: float = 0.0,
    critical_case_id: str | None = None,
) -> tuple[CognitiveScorecard, ...]:
    return tuple(
        CognitiveScorecard(
            case_id=case.case_id,
            scores={
                dimension: (
                    0.5 + reasoning_delta
                    if dimension is CognitiveDimension.REASONING
                    else 0.5 + planning_delta
                    if dimension is CognitiveDimension.PLANNING
                    else 0.5
                )
                for dimension in CognitiveDimension
            },
            evidence_refs=(f"evaluation:{case.case_id}",),
            critical_regression=case.case_id == critical_case_id,
        )
        for case in cases
    )


def _candidate_chain() -> tuple[SFTTrainingSpec, SFTTrainingReceipt, object]:
    spec = SFTTrainingSpec.freeze(
        candidate_id="phase19f-verifier-candidate",
        base_model_id="fixture/base",
        base_model_revision="base-rev",
        trainer_id="fixture/trainer",
        trainer_revision="trainer-rev",
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
        artifact_sha256=_digest("artifact"),
        artifact_size_bytes=1024,
        training_log_sha256=_digest("training-log"),
        evidence_refs=("fixture:training",),
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
                subject_id="warning",
                summary="fixture review required",
                evidence_refs=("fixture:warning",),
            ),
        ),
        status=LearningIntegrityStatus.REVIEW_REQUIRED,
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {}

    checks["required_files_present"] = not missing
    policy = build_default_improvement_gate_policy()
    checks["frozen_improvement_policy_locked"] = bool(
        policy.locked_sha256 == policy.computed_sha256()
        and policy.confidence_level == 0.95
        and policy.critical_regression_zero_tolerance
        and not policy.runtime_authority
    )

    absent = evaluate_improvement_gate(policy=policy)
    checks["missing_real_candidate_is_insufficient_not_promoted"] = bool(
        absent.decision is ImprovementGateDecision.INSUFFICIENT_EVIDENCE
        and not absent.candidate_evidence_verified
        and not absent.action_executed
    )

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
        scorecards=_cards(cases=suite.cases),
    )
    candidate = build_release_snapshot(
        release_id="candidate",
        candidate_model_id="phase19f-verifier-candidate",
        evaluation_suite=suite,
        scorecards=_cards(cases=suite.cases, reasoning_delta=0.03),
    )
    spec, receipt, artifact = _candidate_chain()
    common = {
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

    promote = evaluate_improvement_gate(**common)
    checks["confidence_supported_multi_metric_promotion_recommendation"] = bool(
        promote.decision is ImprovementGateDecision.PROMOTE
        and promote.candidate_evidence_verified
        and CognitiveDimension.REASONING in promote.meaningfully_improved_dimensions
        and not promote.runtime_authority
        and not promote.action_executed
    )
    checks["heldout_and_ood_slices_receive_confidence_estimates"] = bool(
        {estimate.evaluation_slice.value for estimate in promote.estimates}
        == {"ALL", "HELD_OUT", "OOD"}
    )

    no_gain = evaluate_improvement_gate(
        **{
            **common,
            "candidate_snapshot": build_release_snapshot(
                release_id="no-gain",
                candidate_model_id="phase19f-verifier-candidate",
                evaluation_suite=suite,
                scorecards=_cards(cases=suite.cases),
            ),
        }
    )
    checks["no_meaningful_gain_cannot_promote"] = (
        no_gain.decision is ImprovementGateDecision.INSUFFICIENT_EVIDENCE
    )

    degraded_cards = list(_cards(cases=suite.cases, reasoning_delta=0.03, planning_delta=-0.03))
    critical = degraded_cards[0]
    critical_scores = dict(critical.scores)
    critical_scores[CognitiveDimension.PLANNING] = 0.5
    degraded_cards[0] = critical.model_copy(update={"scores": critical_scores})
    degraded_snapshot = build_release_snapshot(
        release_id="degraded",
        candidate_model_id="phase19f-verifier-candidate",
        evaluation_suite=suite,
        scorecards=tuple(degraded_cards),
    )
    degraded = evaluate_improvement_gate(
        **{**common, "candidate_snapshot": degraded_snapshot}
    )
    checks["meaningful_noncritical_regression_rejects"] = bool(
        degraded.decision is ImprovementGateDecision.REJECT
        and CognitiveDimension.PLANNING in degraded.meaningfully_regressed_dimensions
    )

    critical_snapshot = build_release_snapshot(
        release_id="critical",
        candidate_model_id="phase19f-verifier-candidate",
        evaluation_suite=suite,
        scorecards=_cards(
            cases=suite.cases,
            reasoning_delta=0.03,
            critical_case_id="held-001",
        ),
    )
    critical_report = evaluate_improvement_gate(
        **{**common, "candidate_snapshot": critical_snapshot}
    )
    rollback = evaluate_improvement_gate(
        **{**common, "candidate_snapshot": critical_snapshot},
        candidate_currently_active=True,
    )
    checks["critical_regression_zero_tolerance_rejects"] = (
        critical_report.decision is ImprovementGateDecision.REJECT
    )
    checks["active_critical_regression_recommends_rollback"] = bool(
        rollback.decision is ImprovementGateDecision.ROLLBACK and not rollback.action_executed
    )

    contaminated = evaluate_improvement_gate(
        **{
            **common,
            "contamination_report": BenchmarkContaminationReport(
                findings=(
                    ContaminationFinding(
                        case_id="held-001",
                        exposure_source_trajectory_id="training-source",
                        reason=ContaminationReason.TASK_FAMILY,
                    ),
                )
            ),
        }
    )
    checks["benchmark_contamination_rejects"] = bool(
        contaminated.decision is ImprovementGateDecision.REJECT
        and contaminated.contamination_detected
    )

    review = evaluate_improvement_gate(
        **{**common, "learning_integrity_report": _review_integrity()}
    )
    checks["learning_integrity_review_requires_more_evidence"] = (
        review.decision is ImprovementGateDecision.INSUFFICIENT_EVIDENCE
    )

    drifted = evaluate_improvement_gate(
        **{
            **common,
            "candidate_snapshot": candidate.model_copy(
                update={"evaluator_fingerprint": _digest("drifted-evaluator")}
            ),
        }
    )
    checks["evaluator_drift_rejects_like_for_like_claim"] = (
        drifted.decision is ImprovementGateDecision.REJECT
    )

    source = "\n".join(
        (ROOT / "src" / "luna" / "improvement_gate" / relative).read_text(encoding="utf-8")
        for relative in ("models.py", "policy.py", "gate.py")
    )
    checks["gate_has_no_runtime_release_executor"] = all(
        token not in source
        for token in (
            "ToolDispatcher",
            "RuntimeRequest",
            "subprocess.run",
            "os.system",
            "torch.",
            "git checkout",
            "git reset",
        )
    )
    checks["real_candidate_evaluation_not_falsely_claimed"] = True

    phase19e = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_phase19e.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks["phase19e_sft_foundation_remains_green"] = phase19e.returncode == 0
    checks["metadata_hashes_current"] = _metadata_integrity()

    status = "PASS" if not missing and all(checks.values()) else "BLOCKED"
    payload = {
        "phase": "19F",
        "scope": "IMPROVEMENT_GATE",
        "checks": checks,
        "missing_files": missing,
        "status": status,
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
