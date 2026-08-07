"""Deterministic Phase 12F verification, evidence, and learning gate."""

from __future__ import annotations

import ast
import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.audit import AuditEventKind, AuditSession  # noqa: E402
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState  # noqa: E402
from luna.contracts.enums import (  # noqa: E402
    CompletionStatus,
    EvidenceResult,
    EvidenceSourceKind,
    TaskPhase,
)
from luna.contracts.evidence import Evidence  # noqa: E402
from luna.identity import IdentityProfile  # noqa: E402
from luna.learning import (  # noqa: E402
    LearningCandidate,
    LearningCandidateBuilder,
    LearningCandidateKind,
)
from luna.reporting import FinalReportComposer  # noqa: E402
from luna.verification import (  # noqa: E402
    CompletionGate,
    DeterministicVerifier,
    EvidenceStoreConflictError,
    EvidenceStrength,
    SQLiteEvidenceStore,
    VerificationPolicy,
    required_condition_claim_id,
)
from luna.verification.coordinator import VerificationCoordinator  # noqa: E402

REQUIRED_FILES = (
    "src/luna/verification/evidence_store.py",
    "src/luna/verification/coordinator.py",
    "src/luna/learning/__init__.py",
    "src/luna/learning/models.py",
    "src/luna/learning/builder.py",
    "tests/test_phase12f_verification_learning.py",
    "scripts/verify_phase12f.py",
    "docs/rfcs/RFC-012F_VERIFICATION_EVIDENCE_LEARNING.md",
    "docs/PHASE_12F_REPORT.md",
    "phase_12f_verification.json",
)


def _canonical_metadata_bytes(path: Path) -> bytes:
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
    phase = manifest.get("phase")
    if not isinstance(phase, str):
        return False
    match = re.fullmatch(r"(\d+)([A-Z]?)", phase)
    if match is None:
        return False
    phase_number = int(match.group(1))
    phase_suffix = match.group(2)
    if phase_number < 12 or (phase_number == 12 and phase_suffix < "F"):
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    if manifest.get("metadata_scope") != "release_artifact_allowlist_v2":
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False
    if any(str(relative).endswith(".log") for relative in files):
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
        target = ROOT / relative
        if not target.is_file():
            return False
        canonical = _canonical_metadata_bytes(target)
        digest = sha256(canonical).hexdigest()
        if metadata.get("sha256") != digest:
            return False
        if metadata.get("size_bytes") != len(canonical):
            return False
        if sums.get(relative) != digest:
            return False
    return True


def _contract(root: Path) -> TaskContract:
    return TaskContract(
        objective="Verify Phase 12F evidence discipline.",
        required_conditions=("Tests pass.",),
        evidence_required=("test result",),
        scope=TaskScope(workspace_root=str(root)),
        risk_level=RiskLevel.LOW,
        owner="phase12f-verifier",
    )


def _evidence(
    contract: TaskContract,
    *,
    source_kind: EvidenceSourceKind = EvidenceSourceKind.TEST_RESULT,
    result: EvidenceResult = EvidenceResult.PASS,
    revision: str = "phase12f-current",
) -> Evidence:
    return Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id("Tests pass."),
        source_kind=source_kind,
        source_ref="verification:phase12f",
        result=result,
        environment_fingerprint="phase12f-env",
        revision=revision,
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )


def _policy() -> VerificationPolicy:
    return VerificationPolicy(
        current_revision="phase12f-current",
        expected_environment_fingerprint="phase12f-env",
    )


def _learning_boundary_is_static() -> bool:
    builder_path = ROOT / "src/luna/learning/builder.py"
    tree = ast.parse(builder_path.read_text(encoding="utf-8"))
    forbidden_import_roots = {
        "luna.memory",
        "subprocess",
        "socket",
        "requests",
        "urllib",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name.startswith(root) for root in forbidden_import_roots):
                    return False
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(module.startswith(root) for root in forbidden_import_roots):
                return False
    return True


def _runtime_handoff_is_bound() -> bool:
    source = (ROOT / "src/luna/runtime/loop.py").read_text(encoding="utf-8")
    required = (
        "def record_evidence(",
        "def _phase12f_or_pending(",
        "RuntimeStopReason.VERIFICATION_PENDING",
        "RuntimeStopReason.COMPLETED",
        "verification_report_id=",
        "learning_candidate_ids=",
    )
    return all(item in source for item in required)


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {
        "required_files_present": not missing,
    }

    with TemporaryDirectory(prefix="luna-phase12f-verifier-") as temp:
        root = Path(temp)
        contract = _contract(root)
        verifier = DeterministicVerifier()
        policy = _policy()
        strong_evidence = _evidence(contract)
        weak_evidence = _evidence(
            contract,
            source_kind=EvidenceSourceKind.TOOL_OUTPUT,
        )

        strong = verifier.verify(
            contract=contract,
            evidence=(strong_evidence,),
            policy=policy,
        )
        weak = verifier.verify(
            contract=contract,
            evidence=(weak_evidence,),
            policy=policy,
        )
        stale = verifier.verify(
            contract=contract,
            evidence=(_evidence(contract, revision="old-revision"),),
            policy=policy,
        )
        conflict = verifier.verify(
            contract=contract,
            evidence=(
                strong_evidence,
                _evidence(contract, result=EvidenceResult.FAIL),
            ),
            policy=policy,
        )

        checks["strong_evidence_required"] = (
            strong.completion_status is CompletionStatus.VERIFIED_COMPLETE
            and len(strong.evidence_strength_assessments) == 1
            and strong.evidence_strength_assessments[0].strength
            is EvidenceStrength.DETERMINISTIC
            and strong.evidence_strength_assessments[0].qualifying
        )
        checks["weak_tool_output_cannot_complete"] = (
            weak.completion_status is CompletionStatus.INCONCLUSIVE
            and weak.evidence_strength_assessments[0].strength
            is EvidenceStrength.MODERATE
            and not weak.evidence_strength_assessments[0].qualifying
        )
        checks["old_revision_cannot_verify"] = (
            stale.completion_status is not CompletionStatus.VERIFIED_COMPLETE
            and len(stale.rejected_evidence) == 1
        )
        checks["explicit_disagreement_blocks_success"] = (
            conflict.completion_status is CompletionStatus.CONFLICTING_EVIDENCE
            and len(conflict.disagreements) == 1
            and conflict.disagreements[0].unresolved
        )

        store = SQLiteEvidenceStore(root / "evidence.sqlite3")
        store.save(strong_evidence)
        store.save(strong_evidence)
        conflicting_record = strong_evidence.model_copy(
            update={"result": EvidenceResult.FAIL}
        )
        conflict_safe = False
        try:
            store.save(conflicting_record)
        except EvidenceStoreConflictError:
            conflict_safe = True
        checks["evidence_store_integrity"] = (
            store.verify_integrity()
            and store.list_for_task(contract.task_id) == (strong_evidence,)
        )
        checks["evidence_store_conflict_safe"] = conflict_safe

        trace_id = uuid4()
        audit = AuditSession(root / "audit")
        audit.record_task_contract(contract=contract, trace_id=trace_id)
        coordinator = VerificationCoordinator(
            completion_gate=CompletionGate(audit),
            report_composer=FinalReportComposer(audit),
            identity=IdentityProfile(),
            learning_builder=LearningCandidateBuilder(audit),
        )
        state = TaskState(
            task_id=contract.task_id,
            contract=contract,
            phase=TaskPhase.VERIFYING,
            failed_assumptions=("A stale result could prove current completion.",),
        )
        finalization = coordinator.finalize(
            state=state,
            evidence=(strong_evidence,),
            policy=policy,
            trace_id=trace_id,
            performed=("Ran deterministic verification.",),
        )
        learning = finalization.learning_candidates.candidates
        checks["final_report_strength_visible"] = (
            finalization.final_report.completion_status
            is CompletionStatus.VERIFIED_COMPLETE
            and bool(finalization.final_report.evidence_refs)
            and finalization.final_report.evidence_refs[0].endswith(
                "strength:DETERMINISTIC"
            )
        )
        checks["learning_review_required"] = bool(learning) and all(
            item.review_required for item in learning
        )
        checks["learning_auto_commit_blocked"] = bool(learning) and all(
            not item.automatic_commit_allowed for item in learning
        )
        checks["learning_candidate_audited"] = (
            AuditEventKind.LEARNING_CANDIDATE
            in {event.kind for event in audit.events_for_task(contract.task_id)}
            and audit.verify_integrity().valid
        )

        auto_commit_contract_rejected = False
        try:
            LearningCandidate(
                task_id=contract.task_id,
                kind=LearningCandidateKind.RECOVERY_PATTERN,
                statement="Unsafe autonomous learning attempt.",
                verification_report_id=strong.report_id,
                completion_status=CompletionStatus.VERIFIED_COMPLETE,
                confidence=1.0,
                automatic_commit_allowed=True,
            )
        except ValidationError:
            auto_commit_contract_rejected = True
        checks["learning_contract_rejects_auto_commit"] = auto_commit_contract_rejected

    checks["learning_has_no_hidden_mutation"] = _learning_boundary_is_static()
    checks["runtime_phase12f_handoff_bound"] = _runtime_handoff_is_bound()
    checks["metadata_hashes_current"] = _metadata_integrity()

    payload = {
        "phase": "12F",
        "checks": checks,
        "missing_files": missing,
        "status": "PASS" if all(checks.values()) else "BLOCKED",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
