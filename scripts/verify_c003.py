"""Deterministic C-003 Experience Distillation gate."""

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
from luna.experience import (  # noqa: E402
    CaseRelation,
    DistillationDisposition,
    EvidenceOrigin,
    ExperienceDistiller,
    ExperienceLessonProposal,
    GeneralizationScope,
    LessonCaseEvidence,
    LessonKind,
)
from luna.trajectories import (  # noqa: E402
    DatasetSplit,
    DatasetTaxonomy,
    LeakFreeSplitReport,
    ObservableDecisionEvent,
    SplitAssignment,
    StructuredDecisionTrace,
    TraceStage,
    TrajectoryOutcome,
)

REQUIRED_FILES = (
    "src/luna/experience/__init__.py",
    "src/luna/experience/models.py",
    "src/luna/experience/distillation.py",
    "tests/test_c003_experience_distillation.py",
    "scripts/verify_c003.py",
    "docs/rfcs/RFC-C003_EXPERIENCE_DISTILLATION.md",
    "docs/C003_EXPERIENCE_DISTILLATION_REPORT.md",
    "c003_verification.json",
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
    capability = str(manifest.get("capability", ""))
    match = re.fullmatch(r"C-([0-9]{3})", capability)
    if match is None or int(match.group(1)) < 3:
        return False
    if manifest.get("capability_status") not in {"IMPLEMENTED_UNVERIFIED", "VERIFIED"}:
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


def _trace(
    *,
    source_id: str,
    trajectory_family: str,
    task_family: str,
    evidence_ref: str,
) -> StructuredDecisionTrace:
    return StructuredDecisionTrace(
        source_trajectory_id=source_id,
        trajectory_family=trajectory_family,
        task_family=task_family,
        repository_family="repo-luna",
        taxonomy=DatasetTaxonomy.IMPLEMENTATION_CODING,
        task_summary="C-003 verifier fixture",
        events=(
            ObservableDecisionEvent(
                sequence=0,
                stage=TraceStage.TASK,
                summary="Perform a bounded task.",
            ),
            ObservableDecisionEvent(
                sequence=1,
                stage=TraceStage.EVIDENCE,
                summary="Record observable evidence.",
                evidence_refs=(evidence_ref,),
            ),
            ObservableDecisionEvent(
                sequence=2,
                stage=TraceStage.VERIFICATION,
                summary="Verify the observed result.",
                evidence_refs=(evidence_ref,),
            ),
            ObservableDecisionEvent(
                sequence=3,
                stage=TraceStage.FINAL,
                summary="Report the verified result.",
            ),
        ),
        outcome=TrajectoryOutcome.SUCCESS,
        provenance_refs=(f"source:{source_id}",),
        license_reviewed=True,
        pii_reviewed=True,
    )


def _report(
    *traces: StructuredDecisionTrace,
    split: DatasetSplit = DatasetSplit.TRAIN,
) -> LeakFreeSplitReport:
    held_out = (
        (traces[0].task_family,)
        if split is DatasetSplit.HELD_OUT
        else ("reserved-heldout-family",)
    )
    return LeakFreeSplitReport(
        assignments=tuple(
            SplitAssignment(
                trajectory_id=str(trace.trajectory_id),
                source_trajectory_id=trace.source_trajectory_id,
                split_group_key=trace.split_group_key,
                task_family=trace.task_family,
                split=split,
            )
            for trace in traces
        ),
        held_out_task_families=held_out,
    )


def _case(
    trace: StructuredDecisionTrace,
    *,
    evidence_ref: str,
    relation: CaseRelation = CaseRelation.SUPPORTS,
) -> LessonCaseEvidence:
    return LessonCaseEvidence(
        source_trajectory_id=trace.source_trajectory_id,
        relation=relation,
        evidence_refs=(evidence_ref,),
        evidence_origin=EvidenceOrigin.DETERMINISTIC_VERIFIER,
        evaluator_ref="verifier:c003",
        observation_summary="Observable evidence relation for deterministic C-003 verification.",
    )


def _proposal(*cases: LessonCaseEvidence) -> ExperienceLessonProposal:
    return ExperienceLessonProposal(
        lesson_id="c003.verify-before-done",
        statement="Completion claims require observable verification evidence.",
        kind=LessonKind.INVARIANT,
        applicability_scope=("bounded implementation tasks",),
        cases=cases,
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
    }

    registry = build_canonical_capability_registry()
    c003 = registry.get("C-003")
    checks["c003_implemented_unverified_not_self_verified"] = bool(
        c003.status is CapabilityStatus.IMPLEMENTED_UNVERIFIED
        and c003.evidence_freshness is EvidenceFreshness.PARTIAL
        and c003.preferred_prerequisites == ("C-002", "C-001")
        and c003.implementation_components
        and c003.verifier_refs
        and c003.evidence_refs
    )

    first = _trace(
        source_id="source-a",
        trajectory_family="family-a",
        task_family="debugging",
        evidence_ref="ev:a",
    )
    second = _trace(
        source_id="source-b",
        trajectory_family="family-b",
        task_family="debugging",
        evidence_ref="ev:b",
    )
    cross_task = _trace(
        source_id="source-c",
        trajectory_family="family-c",
        task_family="retrieval",
        evidence_ref="ev:c",
    )
    distiller = ExperienceDistiller()

    clean_proposal = _proposal(
        _case(first, evidence_ref="ev:a"),
        _case(second, evidence_ref="ev:b"),
    )
    clean = distiller.distill(
        proposal=clean_proposal,
        traces=(first, second),
        split_report=_report(first, second),
    )
    checks["cross_case_support_produces_review_candidate"] = bool(
        clean.disposition is DistillationDisposition.REVIEW_REQUIRED_CANDIDATE
        and clean.generalization_test_passed
        and clean.generalization_scope is GeneralizationScope.WITHIN_TASK_FAMILY
        and len(clean.supporting_split_groups) == 2
    )

    broad = distiller.distill(
        proposal=_proposal(
            _case(first, evidence_ref="ev:a"),
            _case(cross_task, evidence_ref="ev:c"),
        ),
        traces=(first, cross_task),
        split_report=_report(first, cross_task),
    )
    checks["generalization_is_scoped_not_universal"] = (
        broad.generalization_scope is GeneralizationScope.CROSS_TASK_FAMILY
    )

    insufficient = distiller.distill(
        proposal=_proposal(_case(first, evidence_ref="ev:a")),
        traces=(first,),
        split_report=_report(first),
    )
    checks["single_case_is_insufficient_evidence"] = bool(
        insufficient.disposition is DistillationDisposition.INSUFFICIENT_EVIDENCE
        and not insufficient.generalization_test_passed
    )

    contradiction = distiller.distill(
        proposal=_proposal(
            _case(first, evidence_ref="ev:a"),
            _case(
                second,
                evidence_ref="ev:b",
                relation=CaseRelation.CONTRADICTS,
            ),
        ),
        traces=(first, second),
        split_report=_report(first, second),
    )
    checks["observable_contradiction_rejects_candidate"] = (
        contradiction.disposition is DistillationDisposition.REJECTED_CONTRADICTION
    )

    self_report_blocked = False
    try:
        LessonCaseEvidence(
            source_trajectory_id=first.source_trajectory_id,
            relation=CaseRelation.SUPPORTS,
            evidence_refs=("ev:a",),
            evidence_origin=EvidenceOrigin.MODEL_SELF_REPORT,
            evaluator_ref="model:self",
            observation_summary="Self report must not count.",
        )
    except ValidationError:
        self_report_blocked = True
    checks["model_self_report_cannot_certify_lesson"] = self_report_blocked

    validation_blocked = False
    try:
        distiller.distill(
            proposal=_proposal(_case(first, evidence_ref="ev:a")),
            traces=(first,),
            split_report=_report(first, split=DatasetSplit.VALIDATION),
        )
    except ValueError:
        validation_blocked = True
    checks["validation_and_heldout_remain_evaluation_only"] = validation_blocked

    unobserved_blocked = False
    try:
        distiller.distill(
            proposal=_proposal(_case(first, evidence_ref="ev:missing")),
            traces=(first,),
            split_report=_report(first),
        )
    except ValueError:
        unobserved_blocked = True
    checks["lesson_evidence_must_exist_in_source_trace"] = unobserved_blocked

    checks["distillation_is_deterministic"] = clean == distiller.distill(
        proposal=clean_proposal,
        traces=(first, second),
        split_report=_report(first, second),
    )
    checks["runtime_training_memory_promotion_authority_absent"] = bool(
        clean.review_required is True
        and clean.automatic_memory_commit_allowed is False
        and clean.runtime_authority is False
        and clean.training_authority is False
        and clean.promotion_authority is False
    )
    checks["raw_hidden_chain_of_thought_not_required_or_ingested"] = all(
        trace.raw_hidden_chain_of_thought_included is False
        for trace in (first, second, cross_task)
    )

    passed = all(checks.values())
    payload = {
        "capability": "C-003",
        "name": "Experience Distillation",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "missing_files": missing,
        "runtime_authority": False,
        "training_authority": False,
        "promotion_authority": False,
        "automatic_memory_commit": False,
        "candidate_disposition": clean.disposition.value,
    }
    verification_path = ROOT / "c003_verification.json"
    existing_payload: object | None = None
    if verification_path.is_file():
        try:
            existing_payload = json.loads(
                verification_path.read_text(encoding="utf-8")
            )
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
