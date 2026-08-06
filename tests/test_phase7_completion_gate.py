from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from luna.audit import AuditEventKind, AuditSession
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.contracts.enums import (
    CompletionStatus,
    EvidenceResult,
    EvidenceSourceKind,
    TaskPhase,
)
from luna.contracts.evidence import Evidence
from luna.verification import (
    CompletionGate,
    CompletionGateError,
    VerificationPolicy,
    forbidden_absence_claim_id,
    required_condition_claim_id,
)


def _contract() -> TaskContract:
    return TaskContract(
        task_id=uuid4(),
        objective="Verify audited completion.",
        required_conditions=("Tests pass.",),
        forbidden_outcomes=("Protected files changed.",),
        evidence_required=("test result", "hash evidence"),
        scope=TaskScope(workspace_root="C:/workspace"),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def _evidence(contract: TaskContract) -> tuple[Evidence, ...]:
    common = {
        "task_id": contract.task_id,
        "environment_fingerprint": "gate-test",
        "revision": "rev-gate",
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


def _policy() -> VerificationPolicy:
    return VerificationPolicy(
        current_revision="rev-gate",
        expected_environment_fingerprint="gate-test",
    )


def test_gate_records_report_and_completion_decision(tmp_path: Path) -> None:
    contract = _contract()
    trace_id = uuid4()
    audit = AuditSession(tmp_path / "audit")
    audit.record_task_contract(contract=contract, trace_id=trace_id)

    result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=_evidence(contract),
        policy=_policy(),
        trace_id=trace_id,
    )

    events = audit.events_for_task(contract.task_id)
    kinds = tuple(event.kind for event in events)
    assert result.decision.status is CompletionStatus.VERIFIED_COMPLETE
    assert AuditEventKind.VERIFICATION_REPORT in kinds
    assert AuditEventKind.COMPLETION_DECISION in kinds
    assert audit.verify_integrity().valid


def test_gate_applies_status_only_from_verifying(tmp_path: Path) -> None:
    contract = _contract()
    trace_id = uuid4()
    audit = AuditSession(tmp_path / "audit")
    audit.record_task_contract(contract=contract, trace_id=trace_id)
    result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=_evidence(contract),
        policy=_policy(),
        trace_id=trace_id,
    )
    state = TaskState(
        task_id=contract.task_id,
        contract=contract,
        phase=TaskPhase.VERIFYING,
    )

    reporting = CompletionGate.apply_to_state(state=state, result=result)

    assert reporting.phase is TaskPhase.REPORTING
    assert reporting.completion_status is CompletionStatus.VERIFIED_COMPLETE


def test_gate_rejects_non_verifying_state(tmp_path: Path) -> None:
    contract = _contract()
    trace_id = uuid4()
    audit = AuditSession(tmp_path / "audit")
    audit.record_task_contract(contract=contract, trace_id=trace_id)
    result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=_evidence(contract),
        policy=_policy(),
        trace_id=trace_id,
    )
    state = TaskState(
        task_id=contract.task_id,
        contract=contract,
        phase=TaskPhase.OBSERVING,
    )

    with pytest.raises(CompletionGateError, match="VERIFYING"):
        CompletionGate.apply_to_state(state=state, result=result)


def test_tampered_audit_blocks_completion_gate(tmp_path: Path) -> None:
    contract = _contract()
    trace_id = uuid4()
    audit = AuditSession(tmp_path / "audit")
    audit.record_task_contract(contract=contract, trace_id=trace_id)

    line = audit.ledger.path.read_text(encoding="utf-8")
    payload = json.loads(line)
    payload["payload"]["objective"] = "tampered"
    audit.ledger.path.write_text(
        json.dumps(payload, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CompletionGateError, match="valid audit integrity"):
        CompletionGate(audit).evaluate(
            contract=contract,
            evidence=_evidence(contract),
            policy=_policy(),
            trace_id=trace_id,
        )
