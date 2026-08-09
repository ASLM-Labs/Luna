"""Deterministic C-007 Debugging Capability Decomposition & Transfer gate."""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.capabilities import (  # noqa: E402
    CapabilityStatus,
    EvidenceFreshness,
    build_canonical_capability_registry,
)
from luna.debugging import (  # noqa: E402
    ControlledLessonTransferBinding,
    DebuggingEvaluationCase,
    DebuggingMetric,
    DebuggingStage,
    DebuggingStageAssessment,
    DebuggingTransferEvaluator,
    DebuggingTransferVerdict,
    build_default_debugging_transfer_policy,
)
from luna.experience import (  # noqa: E402
    DistillationDisposition,
    DistilledExperienceCandidate,
    EvidenceOrigin,
    GeneralizationScope,
    LessonKind,
)
from luna.trajectories import DatasetSplit  # noqa: E402

REQUIRED_FILES = (
    "src/luna/debugging/__init__.py",
    "src/luna/debugging/models.py",
    "src/luna/debugging/evaluator.py",
    "tests/test_c007_debugging_capability_transfer.py",
    "scripts/verify_c007.py",
    "docs/rfcs/RFC-C007_DEBUGGING_CAPABILITY_DECOMPOSITION_TRANSFER.md",
    "docs/C007_DEBUGGING_CAPABILITY_TRANSFER_REPORT.md",
    "docs/C007_UPDATE_MANIFEST.json",
    "c007_verification.json",
)

_BASE_STAGES = (
    DebuggingStage.ERROR_OBSERVATION,
    DebuggingStage.FAILURE_LOCALIZATION,
    DebuggingStage.HYPOTHESIS_GENERATION_RANKING,
    DebuggingStage.BROKEN_ASSUMPTION_DETECTION,
    DebuggingStage.STATE_CONTEXT_INSPECTION,
    DebuggingStage.MINIMAL_REPAIR_PLANNING,
    DebuggingStage.TOOL_SELECTION,
    DebuggingStage.PATCH_ACTION,
    DebuggingStage.TARGETED_VERIFICATION,
    DebuggingStage.FULL_REGRESSION_VERIFICATION,
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
    if manifest.get("phase") != "19F":
        return False
    if manifest.get("capability") != "C-007":
        return False
    if manifest.get("capability_status") != "IMPLEMENTED_UNVERIFIED":
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
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            return False
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


def _lesson() -> DistilledExperienceCandidate:
    return DistilledExperienceCandidate(
        lesson_id="c007.verify-root-cause-before-repair",
        statement="Localize the failure and falsify the broken assumption before repair.",
        kind=LessonKind.STRATEGY,
        applicability_scope=("debugging tasks",),
        disposition=DistillationDisposition.REVIEW_REQUIRED_CANDIDATE,
        generalization_scope=GeneralizationScope.WITHIN_TASK_FAMILY,
        generalization_test_passed=True,
        supporting_source_trajectories=("train-a", "train-b"),
        supporting_split_groups=("train-group-a", "train-group-b"),
        supporting_task_families=("debugging",),
        evidence_refs=("train:ev:a", "train:ev:b"),
        provenance_refs=("source:train-a", "source:train-b"),
        decision_basis=("independent_support_groups_satisfied",),
    )


def _assessments(
    *,
    prefix: str,
    score: float,
    initial_repair_failed: bool,
) -> tuple[DebuggingStageAssessment, ...]:
    stages = _BASE_STAGES
    if initial_repair_failed:
        stages = (*stages, DebuggingStage.CHANGED_BASIS_REPLAN)
    stages = (*stages, DebuggingStage.PREVENTION_PROCESS_LESSON)
    return tuple(
        DebuggingStageAssessment(
            stage=stage,
            score=score,
            evidence_refs=(f"{prefix}:{stage.value}",),
            observation_summary=f"Observed {stage.value} behavior.",
        )
        for stage in stages
    )


def _case(
    case_id: str,
    *,
    score: float,
    diagnosis_correct: bool,
    repair_succeeded: bool,
    lesson_applied: bool,
    initial_repair_failed: bool = False,
    split_group_key: str | None = None,
) -> DebuggingEvaluationCase:
    lesson_ids = (_lesson().lesson_id,) if lesson_applied else ()
    return DebuggingEvaluationCase(
        case_id=case_id,
        task_family="heldout-debugging-family",
        split_group_key=split_group_key or f"heldout-group:{case_id}",
        dataset_split=DatasetSplit.HELD_OUT,
        stage_assessments=_assessments(
            prefix=f"ev:{case_id}:{'after' if lesson_applied else 'before'}",
            score=score,
            initial_repair_failed=initial_repair_failed,
        ),
        diagnosis_correct=diagnosis_correct,
        repair_succeeded=repair_succeeded,
        initial_repair_failed=initial_repair_failed,
        applied_lesson_ids=lesson_ids,
        evaluator_ref="deterministic-evaluator:c007",
        evidence_origin=EvidenceOrigin.DETERMINISTIC_VERIFIER,
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
    }

    registry = build_canonical_capability_registry()
    c007 = registry.get("C-007")
    checks["c007_implemented_unverified_not_self_verified"] = bool(
        c007.status is CapabilityStatus.IMPLEMENTED_UNVERIFIED
        and c007.evidence_freshness is EvidenceFreshness.PARTIAL
        and c007.preferred_prerequisites == ("C-002", "C-003", "C-001")
        and c007.implementation_components
        and c007.verifier_refs
        and c007.evidence_refs
    )

    lesson = _lesson()
    binding = ControlledLessonTransferBinding(
        lesson_id=lesson.lesson_id,
        reviewer_ref="human-review:c007",
        approval_scope=("held-out debugging evaluation",),
    )
    baseline = (
        _case(
            "debug-a",
            score=0.40,
            diagnosis_correct=False,
            repair_succeeded=False,
            lesson_applied=False,
            initial_repair_failed=True,
        ),
        _case(
            "debug-b",
            score=0.55,
            diagnosis_correct=True,
            repair_succeeded=True,
            lesson_applied=False,
        ),
    )
    transfer = (
        _case(
            "debug-a",
            score=0.80,
            diagnosis_correct=True,
            repair_succeeded=True,
            lesson_applied=True,
            initial_repair_failed=True,
        ),
        _case(
            "debug-b",
            score=0.85,
            diagnosis_correct=True,
            repair_succeeded=True,
            lesson_applied=True,
        ),
    )
    evaluator = DebuggingTransferEvaluator()
    result = evaluator.evaluate(
        lesson=lesson,
        binding=binding,
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=baseline,
        transfer_cases=transfer,
    )
    checks["reviewed_lesson_supports_paired_heldout_transfer_evaluation"] = bool(
        result.verdict is DebuggingTransferVerdict.SUPPORTED
        and DebuggingMetric.REPAIR_SUCCESS in result.meaningfully_improved_metrics
        and DebuggingMetric.DIAGNOSIS_QUALITY in result.meaningfully_improved_metrics
        and not result.regressed_metrics
    )

    contaminated = evaluator.evaluate(
        lesson=lesson,
        binding=binding,
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=(
            baseline[0].model_copy(update={"split_group_key": "train-group-a"}),
            baseline[1],
        ),
        transfer_cases=(
            transfer[0].model_copy(update={"split_group_key": "train-group-a"}),
            transfer[1],
        ),
    )
    checks["training_group_contamination_is_blocked"] = bool(
        contaminated.verdict is DebuggingTransferVerdict.INSUFFICIENT_EVIDENCE
        and "training_group_reused_in_transfer_eval:debug-a" in contaminated.blocked_reasons
    )

    review_origin_blocked = False
    try:
        ControlledLessonTransferBinding(
            lesson_id=lesson.lesson_id,
            reviewer_ref="model:self",
            review_origin=EvidenceOrigin.MODEL_SELF_REPORT,
            approval_scope=("held-out debugging evaluation",),
        )
    except ValidationError:
        review_origin_blocked = True
    checks["controlled_transfer_requires_explicit_human_review"] = review_origin_blocked

    confounded_transfer = transfer[0].model_copy(
        update={"applied_lesson_ids": (lesson.lesson_id, "other-lesson")}
    )
    confounded = evaluator.evaluate(
        lesson=lesson,
        binding=binding,
        policy=build_default_debugging_transfer_policy(),
        baseline_cases=baseline,
        transfer_cases=(confounded_transfer, transfer[1]),
    )
    checks["additional_lesson_confounds_are_blocked"] = bool(
        confounded.verdict is DebuggingTransferVerdict.INSUFFICIENT_EVIDENCE
        and "transfer_case_has_lesson_confound:debug-a" in confounded.blocked_reasons
    )

    self_report_blocked = False
    try:
        DebuggingEvaluationCase(
            case_id="self-report",
            task_family="heldout-debugging-family",
            split_group_key="heldout-group:self-report",
            dataset_split=DatasetSplit.HELD_OUT,
            stage_assessments=_assessments(
                prefix="ev:self",
                score=0.5,
                initial_repair_failed=False,
            ),
            diagnosis_correct=True,
            repair_succeeded=True,
            evaluator_ref="model:self",
            evidence_origin=EvidenceOrigin.MODEL_SELF_REPORT,
        )
    except ValidationError:
        self_report_blocked = True
    checks["model_self_report_cannot_score_debugging_transfer"] = self_report_blocked

    checks["changed_basis_replan_is_explicit_after_failed_initial_repair"] = bool(
        DebuggingStage.CHANGED_BASIS_REPLAN
        in tuple(item.stage for item in transfer[0].stage_assessments)
    )
    checks["runtime_training_memory_promotion_authority_absent"] = bool(
        result.review_required is True
        and result.automatic_memory_commit_allowed is False
        and result.runtime_authority is False
        and result.training_authority is False
        and result.promotion_authority is False
        and result.action_executed is False
    )

    passed = all(checks.values())
    payload = {
        "capability": "C-007",
        "name": "Debugging Capability Decomposition & Transfer",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "missing_files": missing,
        "transfer_verdict": result.verdict.value,
        "runtime_authority": False,
        "training_authority": False,
        "promotion_authority": False,
        "automatic_memory_commit": False,
        "action_executed": False,
    }
    verification_path = ROOT / "c007_verification.json"
    existing_payload: object | None = None
    if verification_path.is_file():
        try:
            existing_payload = json.loads(verification_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing_payload = None
    if existing_payload != payload:
        verification_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
