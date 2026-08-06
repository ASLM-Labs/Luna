from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from luna.audit import AuditEventKind, AuditSession
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.contracts.enums import EvidenceResult, EvidenceSourceKind
from luna.contracts.evidence import Evidence
from luna.identity import IdentityProfile
from luna.reporting import FinalReportComposer, ReportRisk
from luna.verification import (
    CompletionGate,
    CompletionGateResult,
    VerificationPolicy,
    required_condition_claim_id,
)


def _contract(root: Path) -> TaskContract:
    return TaskContract(
        objective="Compose a truthful final report.",
        required_conditions=("Tests pass.",),
        evidence_required=("test result",),
        scope=TaskScope(workspace_root=str(root)),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def _gate_result(
    contract: TaskContract,
    audit: AuditSession,
    trace_id: UUID,
) -> CompletionGateResult:
    evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id("Tests pass."),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="observation:pytest",
        result=EvidenceResult.PASS,
        environment_fingerprint="phase10-reporting",
        revision="phase10",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )
    audit.record_task_contract(contract=contract, trace_id=trace_id)
    return CompletionGate(audit).evaluate(
        contract=contract,
        evidence=(evidence,),
        policy=VerificationPolicy(
            current_revision="phase10",
            expected_environment_fingerprint="phase10-reporting",
        ),
        trace_id=trace_id,
    )


def test_final_report_separates_action_change_evidence_uncertainty_and_risk(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    trace_id = uuid4()
    audit = AuditSession(tmp_path / "audit")
    gate = _gate_result(contract, audit, trace_id)

    report = FinalReportComposer(audit).compose(
        contract=contract,
        gate_result=gate,
        identity=IdentityProfile(),
        performed=("Ran the deterministic test suite.",),
        changed=("src/luna/reporting/models.py",),
        risks=(ReportRisk(level=RiskLevel.LOW, summary="No network tool was enabled."),),
        trace_id=trace_id,
    )
    rendered = report.render_text()

    assert report.completion_status.value == "VERIFIED_COMPLETE"
    assert report.performed == ("Ran the deterministic test suite.",)
    assert report.changed == ("src/luna/reporting/models.py",)
    assert report.verified
    assert report.unverified == ()
    assert "## Yapılan" in rendered
    assert "## Değişen" in rendered
    assert "## Doğrulanan" in rendered
    assert "## Doğrulanamayan" in rendered
    assert "## Risk" in rendered
    assert "## Kanıt" in rendered
    assert AuditEventKind.FINAL_REPORT in {
        event.kind for event in audit.events_for_task(contract.task_id)
    }
    assert audit.verify_integrity().valid


def test_unverified_gate_is_reported_as_unverified(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    trace_id = uuid4()
    audit = AuditSession(tmp_path / "audit")
    audit.record_task_contract(contract=contract, trace_id=trace_id)
    gate = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=(),
        policy=VerificationPolicy(
            current_revision="phase10",
            expected_environment_fingerprint="phase10-reporting",
        ),
        trace_id=trace_id,
    )

    report = FinalReportComposer().compose(
        contract=contract,
        gate_result=gate,
        identity=IdentityProfile(),
    )

    assert report.completion_status.value == "UNVERIFIED"
    assert report.unverified
    assert any("UNVERIFIED" in item for item in report.unverified)
