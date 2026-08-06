"""Structural and behavioral verifier for Luna Phase 7."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from luna.audit import AuditEventKind, AuditSession
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.contracts.enums import (
    CompletionStatus,
    EvidenceResult,
    EvidenceSourceKind,
)
from luna.contracts.evidence import Evidence
from luna.verification import (
    CompletionGate,
    DeterministicVerifier,
    VerificationPolicy,
    forbidden_absence_claim_id,
    required_condition_claim_id,
)

ROOT = Path(__file__).resolve().parents[1]


def _contract() -> TaskContract:
    return TaskContract(
        task_id=uuid4(),
        objective="Verify deterministic completion.",
        required_conditions=("Tests pass.",),
        forbidden_outcomes=("Protected files changed.",),
        evidence_required=("test result", "hash evidence"),
        scope=TaskScope(workspace_root=str(ROOT)),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def _evidence(contract: TaskContract) -> tuple[Evidence, ...]:
    common = {
        "task_id": contract.task_id,
        "environment_fingerprint": "phase7-verifier",
        "revision": "phase7",
        "freshness_seconds": 0,
        "reproducible": True,
        "confidence": 1.0,
        "result": EvidenceResult.PASS,
    }
    return (
        Evidence(
            requirement_id=required_condition_claim_id("Tests pass."),
            source_kind=EvidenceSourceKind.TEST_RESULT,
            source_ref="observation:test",
            **common,
        ),
        Evidence(
            requirement_id=forbidden_absence_claim_id(
                "Protected files changed."
            ),
            source_kind=EvidenceSourceKind.HASH,
            source_ref="observation:hash",
            **common,
        ),
    )


def main() -> int:
    required_files = [
        ROOT / "src" / "luna" / "verification" / "claims.py",
        ROOT / "src" / "luna" / "verification" / "models.py",
        ROOT / "src" / "luna" / "verification" / "verifier.py",
        ROOT / "src" / "luna" / "verification" / "gate.py",
    ]
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in required_files
        if not path.is_file()
    ]
    contract = _contract()
    policy = VerificationPolicy(
        current_revision="phase7",
        expected_environment_fingerprint="phase7-verifier",
    )
    evidence = _evidence(contract)
    verifier = DeterministicVerifier()
    first = verifier.verify(
        contract=contract,
        evidence=evidence,
        policy=policy,
    )
    second = verifier.verify(
        contract=contract,
        evidence=evidence,
        policy=policy,
    )
    stale = tuple(
        item.model_copy(update={"revision": "old"})
        for item in evidence
    )
    stale_report = verifier.verify(
        contract=contract,
        evidence=stale,
        policy=policy,
    )
    conflict = (
        *evidence,
        Evidence(
            task_id=contract.task_id,
            requirement_id=required_condition_claim_id("Tests pass."),
            source_kind=EvidenceSourceKind.TEST_RESULT,
            source_ref="observation:conflict",
            result=EvidenceResult.FAIL,
            environment_fingerprint="phase7-verifier",
            revision="phase7",
            freshness_seconds=0,
            reproducible=True,
            confidence=1.0,
        ),
    )
    conflict_report = verifier.verify(
        contract=contract,
        evidence=conflict,
        policy=policy,
    )

    with TemporaryDirectory(prefix="luna-phase7-") as directory:
        audit = AuditSession(Path(directory) / "audit")
        trace_id = uuid4()
        audit.record_task_contract(contract=contract, trace_id=trace_id)
        gate_result = CompletionGate(audit).evaluate(
            contract=contract,
            evidence=evidence,
            policy=policy,
            trace_id=trace_id,
        )
        events = audit.events_for_task(contract.task_id)
        kinds = {event.kind for event in events}
        audit_valid = audit.verify_integrity().valid

    checks = {
        "required_files_present": not missing,
        "verified_complete_requires_all_current_evidence": (
            first.completion_status is CompletionStatus.VERIFIED_COMPLETE
        ),
        "deterministic_semantic_report": (
            first.semantic_signature() == second.semantic_signature()
        ),
        "old_revision_cannot_complete": (
            stale_report.completion_status is CompletionStatus.UNVERIFIED
        ),
        "conflict_blocks_success": (
            conflict_report.completion_status
            is CompletionStatus.CONFLICTING_EVIDENCE
        ),
        "completion_gate_status_matches_report": (
            gate_result.decision.status is gate_result.report.completion_status
        ),
        "verification_report_audited": (
            AuditEventKind.VERIFICATION_REPORT in kinds
        ),
        "completion_decision_audited": (
            AuditEventKind.COMPLETION_DECISION in kinds
        ),
        "audit_integrity_valid": audit_valid,
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    print(
        json.dumps(
            {
                "phase": 7,
                "checks": checks,
                "missing_files": missing,
                "status": status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
