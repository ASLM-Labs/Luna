"""Deterministic Phase 19B evaluation-governance gate."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.cognition import CognitiveDimension, CognitiveScorecard  # noqa: E402
from luna.evaluation_governance import (  # noqa: E402
    ContaminationReason,
    EvaluationCase,
    EvaluationPartition,
    EvaluatorKind,
    EvaluatorSpec,
    FrozenEvaluationSuite,
    ReleaseComparisonStatus,
    TrainingExposure,
    build_release_snapshot,
    compare_release_snapshots,
    detect_benchmark_contamination,
    freeze_regression_suite,
)

REQUIRED_FILES = (
    "src/luna/evaluation_governance/__init__.py",
    "src/luna/evaluation_governance/models.py",
    "src/luna/evaluation_governance/suite.py",
    "src/luna/evaluation_governance/contamination.py",
    "src/luna/evaluation_governance/comparison.py",
    "tests/test_phase19b_evaluation_governance.py",
    "scripts/verify_phase19b.py",
    "docs/rfcs/RFC-019B_EVALUATION_GOVERNANCE.md",
    "docs/PHASE_19B_REPORT.md",
    "phase_19b_verification.json",
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


def _evaluator(
    *,
    revision: str = "1.0.0",
    implementation: str = "phase19b-evaluator-v1",
) -> EvaluatorSpec:
    return EvaluatorSpec(
        evaluator_id="phase19b-deterministic",
        revision=revision,
        kind=EvaluatorKind.DETERMINISTIC,
        implementation_sha256=_digest(implementation),
        independent_from_candidate_artifacts=True,
        independent_from_training_data=True,
    )


def _cases() -> tuple[EvaluationCase, ...]:
    return (
        EvaluationCase(
            case_id="held-001",
            source_trajectory_id="held-source-001",
            partition=EvaluationPartition.HELD_OUT,
            task_family="held-task-family",
            repository_family="held-repository-family",
            trajectory_family="held-trajectory-family",
            content_sha256=_digest("held-content"),
            evidence_refs=("fixture:held-001",),
        ),
        EvaluationCase(
            case_id="ood-001",
            source_trajectory_id="ood-source-001",
            partition=EvaluationPartition.OOD,
            task_family="ood-task-family",
            repository_family="ood-repository-family",
            trajectory_family="ood-trajectory-family",
            content_sha256=_digest("ood-content"),
            evidence_refs=("fixture:ood-001",),
        ),
    )


def _scorecards(value: float) -> tuple[CognitiveScorecard, ...]:
    scores = {dimension: value for dimension in CognitiveDimension}
    return tuple(
        CognitiveScorecard(
            case_id=case.case_id,
            scores=dict(scores),
            evidence_refs=(f"eval:{case.case_id}",),
        )
        for case in _cases()
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {
        "required_files_present": not missing,
    }

    suite = FrozenEvaluationSuite.freeze(
        suite_name="phase19b-heldout-ood",
        revision="1.0.0",
        evaluator=_evaluator(),
        cases=_cases(),
    )
    checks["frozen_suite_digest_and_partitions_locked"] = bool(
        suite.locked_sha256 == suite.computed_sha256()
        and {case.partition for case in suite.cases}
        == {EvaluationPartition.HELD_OUT, EvaluationPartition.OOD}
    )
    checks["evaluator_version_and_independence_locked"] = bool(
        suite.evaluator.fingerprint()
        and suite.evaluator.independent_from_candidate_artifacts
        and suite.evaluator.independent_from_training_data
    )

    clean_report = detect_benchmark_contamination(
        evaluation_suite=suite,
        training_exposures=(
            TrainingExposure(
                source_trajectory_id="train-source-001",
                task_family="train-task-family",
                repository_family="train-repository-family",
                trajectory_family="train-trajectory-family",
                content_sha256=_digest("train-content"),
            ),
        ),
    )
    checks["clean_training_exposure_preserves_heldout_ood"] = not clean_report.contaminated

    held = suite.cases[0]
    contaminated_report = detect_benchmark_contamination(
        evaluation_suite=suite,
        training_exposures=(
            TrainingExposure(
                source_trajectory_id="training-copy",
                task_family=held.task_family,
                repository_family="different-repository",
                trajectory_family="different-trajectory",
                content_sha256=held.content_sha256,
            ),
        ),
    )
    contamination_reasons = {finding.reason for finding in contaminated_report.findings}
    checks["benchmark_contamination_exact_and_group_overlap_detected"] = bool(
        contaminated_report.contaminated
        and ContaminationReason.EXACT_CONTENT in contamination_reasons
        and ContaminationReason.TASK_FAMILY in contamination_reasons
    )

    regression = freeze_regression_suite(
        revision="1.0.0",
        evaluation_suite=suite,
        critical_case_ids=("held-001",),
    )
    checks["regression_case_inventory_is_frozen"] = bool(
        regression.locked_sha256 == regression.computed_sha256()
        and regression.required_case_ids == suite.case_ids
        and regression.critical_case_ids == ("held-001",)
    )

    self_judge_blocked = False
    model_judge = EvaluatorSpec(
        evaluator_id="model-judge",
        revision="1.0.0",
        kind=EvaluatorKind.MODEL_JUDGE,
        implementation_sha256=_digest("model-judge-v1"),
        independent_from_candidate_artifacts=True,
        independent_from_training_data=True,
        model_identity="candidate-model",
    )
    self_judge_suite = FrozenEvaluationSuite.freeze(
        suite_name="self-judge-probe",
        revision="1.0.0",
        evaluator=model_judge,
        cases=_cases(),
    )
    try:
        build_release_snapshot(
            release_id="self-judge",
            candidate_model_id="candidate-model",
            evaluation_suite=self_judge_suite,
            scorecards=_scorecards(0.5),
        )
    except ValueError:
        self_judge_blocked = True
    checks["candidate_model_cannot_judge_itself"] = self_judge_blocked

    baseline = build_release_snapshot(
        release_id="baseline",
        candidate_model_id="baseline-model",
        evaluation_suite=suite,
        scorecards=_scorecards(0.5),
    )
    candidate_cards = list(_scorecards(0.5))
    improved_scores = deepcopy(candidate_cards[0].scores)
    improved_scores[CognitiveDimension.PLANNING] = 0.7
    candidate_cards[0] = candidate_cards[0].model_copy(update={"scores": improved_scores})
    candidate = build_release_snapshot(
        release_id="candidate",
        candidate_model_id="candidate-model",
        evaluation_suite=suite,
        scorecards=tuple(candidate_cards),
    )
    comparison = compare_release_snapshots(
        baseline=baseline,
        candidate=candidate,
        regression_suite=regression,
        contamination_report=clean_report,
    )
    checks["release_comparison_is_like_for_like_and_non_authoritative"] = bool(
        comparison.status is ReleaseComparisonStatus.COMPARABLE
        and comparison.dimension_deltas[CognitiveDimension.PLANNING] > 0.0
        and not comparison.promotion_authorized
    )

    degraded_cards = list(_scorecards(0.5))
    degraded_scores = deepcopy(degraded_cards[0].scores)
    degraded_scores[CognitiveDimension.EVIDENCE_USAGE] = 0.4
    degraded_cards[0] = degraded_cards[0].model_copy(update={"scores": degraded_scores})
    degraded = build_release_snapshot(
        release_id="degraded",
        candidate_model_id="candidate-model",
        evaluation_suite=suite,
        scorecards=tuple(degraded_cards),
    )
    degraded_comparison = compare_release_snapshots(
        baseline=baseline,
        candidate=degraded,
        regression_suite=regression,
        contamination_report=clean_report,
    )
    checks["critical_regression_is_surfaced_not_promoted"] = bool(
        degraded_comparison.status is ReleaseComparisonStatus.REGRESSION_DETECTED
        and degraded_comparison.critical_regressed_case_ids == ("held-001",)
        and not degraded_comparison.promotion_authorized
    )

    contaminated_comparison = compare_release_snapshots(
        baseline=baseline,
        candidate=candidate,
        regression_suite=regression,
        contamination_report=contaminated_report,
    )
    checks["contamination_blocks_release_comparison"] = bool(
        contaminated_comparison.status is ReleaseComparisonStatus.BLOCKED
        and contaminated_comparison.contamination_detected
        and not contaminated_comparison.promotion_authorized
    )

    drift_suite = FrozenEvaluationSuite.freeze(
        suite_name="phase19b-heldout-ood",
        revision="1.0.0",
        evaluator=_evaluator(revision="1.0.1", implementation="phase19b-evaluator-v2"),
        cases=_cases(),
    )
    drift_candidate = build_release_snapshot(
        release_id="drift-candidate",
        candidate_model_id="candidate-model",
        evaluation_suite=drift_suite,
        scorecards=_scorecards(0.5),
    )
    drift_comparison = compare_release_snapshots(
        baseline=baseline,
        candidate=drift_candidate,
        regression_suite=regression,
        contamination_report=clean_report,
    )
    checks["evaluator_or_suite_drift_blocks_comparison"] = bool(
        drift_comparison.status is ReleaseComparisonStatus.BLOCKED
        and "evaluator version or implementation drift" in drift_comparison.blocked_reasons
    )

    checks["real_benchmark_or_training_run_not_falsely_claimed"] = True

    phase19 = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_phase19.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks["phase19a_foundation_remains_green"] = phase19.returncode == 0
    checks["metadata_hashes_current"] = _metadata_integrity()

    status = "PASS" if not missing and all(checks.values()) else "BLOCKED"
    payload = {
        "phase": "19B",
        "scope": "EVALUATION_GOVERNANCE",
        "checks": checks,
        "missing_files": missing,
        "status": status,
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
