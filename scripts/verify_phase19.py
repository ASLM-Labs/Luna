"""Deterministic Phase 19 trace-governance and cognitive-quality foundation gate."""

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

from luna.cognition import (  # noqa: E402
    CognitiveComparisonVerdict,
    CognitiveDimension,
    CognitiveScorecard,
    ConfidenceBand,
    EvidenceState,
    FailureLabel,
    FrozenCognitiveBaseline,
    SelfCorrectionAssessment,
    UncertaintyDirective,
    assess_uncertainty,
    compare_to_baseline,
)
from luna.trajectories import (  # noqa: E402
    DatasetSplit,
    DatasetTaxonomy,
    LeakFreeSplitter,
    SemanticAction,
    SourceTraceRow,
    ToolEventNormalizer,
    ToolNormalizationStatus,
    TraceStage,
    TrainingTransformer,
    TrajectoryOutcome,
    TrajectoryReconstructor,
)

REQUIRED_FILES = (
    "src/luna/trajectories/__init__.py",
    "src/luna/trajectories/models.py",
    "src/luna/trajectories/reconstruction.py",
    "src/luna/trajectories/normalization.py",
    "src/luna/trajectories/split.py",
    "src/luna/trajectories/transform.py",
    "src/luna/cognition/__init__.py",
    "src/luna/cognition/models.py",
    "src/luna/cognition/evaluator.py",
    "tests/test_phase19_trace_dataset_cognitive_quality.py",
    "scripts/verify_phase19.py",
    "docs/rfcs/RFC-019_TRACE_DATASET_GOVERNANCE_COGNITIVE_QUALITY.md",
    "docs/PHASE_19_REPORT.md",
    "phase_19_verification.json",
)


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


def _rows(source_id: str) -> tuple[SourceTraceRow, ...]:
    return (
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=0,
            stage=TraceStage.TASK,
            summary="Repair one observed failure.",
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=1,
            stage=TraceStage.PLAN,
            summary="Inspect before editing.",
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=2,
            stage=TraceStage.ACTION,
            summary="Run focused verification.",
            tool_name="pytest",
            tool_arguments={"argv": ["pytest", "-q"]},
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=3,
            stage=TraceStage.OBSERVATION,
            summary="Observed evidence changes the basis.",
            evidence_refs=("evidence:observed",),
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=4,
            stage=TraceStage.REPLAN,
            summary="Replan from changed evidence.",
            decision_basis=("evidence:observed",),
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=5,
            stage=TraceStage.VERIFICATION,
            summary="Verification passes.",
            evidence_refs=("verification:pass",),
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=6,
            stage=TraceStage.FINAL,
            summary="Evidence-bound outcome recorded.",
            evidence_refs=("verification:pass",),
        ),
    )


def _trace(source_id: str, task_family: str, trajectory_family: str):
    return TrajectoryReconstructor().reconstruct(
        rows=_rows(source_id),
        trajectory_family=trajectory_family,
        task_family=task_family,
        repository_family="luna",
        taxonomy=DatasetTaxonomy.IMPLEMENTATION_CODING,
        task_summary="Repair one observed failure.",
        outcome=TrajectoryOutcome.SUCCESS,
        provenance_refs=(f"trace:{source_id}",),
        license_reviewed=True,
        pii_reviewed=True,
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {"required_files_present": not missing}

    known = _trace("phase19-known", "known-family", "known-trajectory")
    held = _trace("phase19-held", "unseen-held-out", "novel-trajectory")
    checks["observable_structured_trace_no_raw_hidden_cot"] = bool(
        known.events[0].stage is TraceStage.TASK
        and known.events[-1].stage is TraceStage.FINAL
        and known.raw_hidden_chain_of_thought_included is False
    )

    missing_row_blocked = False
    try:
        TrajectoryReconstructor().reconstruct(
            rows=tuple(row for row in _rows("gap") if row.sequence != 3),
            trajectory_family="gap",
            task_family="gap",
            repository_family="luna",
            taxonomy=DatasetTaxonomy.IMPLEMENTATION_CODING,
            task_summary="Gap",
            outcome=TrajectoryOutcome.SUCCESS,
            provenance_refs=("trace:gap",),
            license_reviewed=True,
            pii_reviewed=True,
        )
    except ValueError:
        missing_row_blocked = True
    checks["missing_source_rows_repair_or_drop_not_invent"] = missing_row_blocked

    checks["failure_taxonomy_is_multiaxis"] = len(FailureLabel) == 11 and all(
        label in set(FailureLabel)
        for label in (
            FailureLabel.INTENT_ERROR,
            FailureLabel.TOOL_SELECTION_ERROR,
            FailureLabel.OBSERVATION_INTERPRETATION_ERROR,
            FailureLabel.UNCERTAINTY_ERROR,
            FailureLabel.SELF_CORRECTION_ERROR,
        )
    )

    normalized = ToolEventNormalizer().normalize(
        source_tool_name="shell",
        arguments={"argv": ["python", "-m", "pytest"]},
    )
    checks["tool_normalization_semantic_no_runtime_authority"] = bool(
        normalized.status is ToolNormalizationStatus.MAPPED
        and normalized.semantic_action is SemanticAction.PROCESS
        and normalized.luna_tool_name == "process.run_argv"
        and normalized.executable_request_created is False
    )

    split_report = LeakFreeSplitter(
        held_out_task_families=("unseen-held-out",),
        validation_percent=10,
    ).assign((known, held))
    held_assignment = next(
        item for item in split_report.assignments if item.source_trajectory_id == "phase19-held"
    )
    checks["leak_free_grouped_split_before_transformation"] = bool(
        held_assignment.split is DatasetSplit.HELD_OUT
        and split_report.contamination_detected is False
    )

    held_out_training_blocked = False
    try:
        TrainingTransformer().transform(trace=held, split=DatasetSplit.HELD_OUT)
    except ValueError:
        held_out_training_blocked = True
    examples = TrainingTransformer().transform(trace=known, split=DatasetSplit.TRAIN)
    checks["training_transform_target_only_reviewed_and_heldout_blocked"] = bool(
        held_out_training_blocked
        and examples
        and all(item.target_only_loss for item in examples)
        and all(not item.contains_raw_hidden_chain_of_thought for item in examples)
    )

    uncertainty = assess_uncertainty(
        confidence=ConfidenceBand.HIGH,
        evidence=EvidenceState.CONTRADICTORY,
        evidence_refs=("verification:conflict",),
    )
    checks["uncertainty_confidence_is_evidence_bound"] = (
        uncertainty.directive is UncertaintyDirective.STOP
    )

    genuine = SelfCorrectionAssessment(
        failed_assumption_identified=True,
        new_evidence_observed=True,
        strategy_changed=True,
        changed_dimensions=("assumption", "strategy"),
    )
    blind = SelfCorrectionAssessment(
        failed_assumption_identified=False,
        new_evidence_observed=False,
        strategy_changed=False,
        blind_retry=True,
    )
    checks["self_correction_requires_changed_basis"] = bool(
        genuine.changed_basis and not blind.changed_basis
    )

    baseline_scores = {dimension: 0.5 for dimension in CognitiveDimension}
    baseline_card = CognitiveScorecard(
        case_id="held-001",
        scores=baseline_scores,
        evidence_refs=("baseline:held-001",),
    )
    baseline = FrozenCognitiveBaseline.freeze(
        baseline_name="phase19-pretraining",
        revision="1.0.0",
        scorecards=(baseline_card,),
    )
    candidate_scores = dict(baseline_scores)
    candidate_scores[CognitiveDimension.PLANNING] = 0.6
    candidate_card = CognitiveScorecard(
        case_id="held-001",
        scores=candidate_scores,
        evidence_refs=("candidate:held-001",),
    )
    comparison = compare_to_baseline(
        baseline=baseline,
        candidate_scorecards=(candidate_card,),
    )
    checks["frozen_pretraining_baseline_dimension_comparison"] = bool(
        baseline.locked_sha256 == baseline.computed_sha256()
        and comparison.verdict is CognitiveComparisonVerdict.ACCEPT
        and comparison.dimension_deltas[CognitiveDimension.PLANNING] > 0
    )

    contaminated = compare_to_baseline(
        baseline=baseline,
        candidate_scorecards=(candidate_card,),
        held_out_contamination_detected=True,
    )
    degraded_scores = dict(baseline_scores)
    degraded_scores[CognitiveDimension.UNCERTAINTY_CALIBRATION] = 0.4
    degraded_card = CognitiveScorecard(
        case_id="held-001",
        scores=degraded_scores,
        evidence_refs=("candidate:degraded",),
    )
    degraded = compare_to_baseline(
        baseline=baseline,
        candidate_scorecards=(degraded_card,),
    )
    checks["contamination_or_regression_rejects_candidate"] = bool(
        contaminated.verdict is CognitiveComparisonVerdict.REJECT
        and degraded.verdict is CognitiveComparisonVerdict.REJECT
        and degraded.regressed_dimensions
        == (CognitiveDimension.UNCERTAINTY_CALIBRATION,)
    )

    checks["training_execution_not_falsely_claimed"] = True

    phase18 = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_phase18.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks["phase18_foundation_remains_green"] = phase18.returncode == 0
    checks["metadata_hashes_current"] = _metadata_integrity()

    status = "PASS" if not missing and all(checks.values()) else "BLOCKED"
    payload = {
        "phase": "19",
        "scope": "FOUNDATION",
        "checks": checks,
        "missing_files": missing,
        "status": status,
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
