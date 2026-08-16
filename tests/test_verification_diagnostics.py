from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from luna.audit import AuditSession
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.contracts.enums import EvidenceResult, EvidenceSourceKind
from luna.contracts.evidence import Evidence
from luna.verification.claims import required_condition_claim_id
from luna.verification.delta import build_verification_delta
from luna.verification.diagnostics import (
    build_verification_diagnostic_assessment,
    validate_verification_diagnostic_assessment_binding,
    validate_verification_diagnostic_assessment_integrity,
)
from luna.verification.episode import build_verification_episode
from luna.verification.gate import CompletionGate
from luna.verification.models import (
    ClaimStatus,
    EvidenceRejectionCode,
    EvidenceStrength,
    VerificationPolicy,
)

_REQUIRED = "Tests pass."


def _contract(root: Path) -> TaskContract:
    return TaskContract(
        objective="Explain incomplete verification.",
        required_conditions=(_REQUIRED,),
        evidence_required=("test result",),
        scope=TaskScope(workspace_root=str(root)),
        risk_level=RiskLevel.LOW,
    )


def test_incomplete_verification_becomes_typed_diagnostic_gaps(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = VerificationPolicy(
        current_revision="expected-revision",
        expected_environment_fingerprint="env-diagnostic",
    )

    evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:diagnostic-test",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="wrong-revision",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    audit = AuditSession(tmp_path / "audit")
    trace_id = uuid4()
    audit.record_task_contract(contract=contract, trace_id=trace_id)

    gate_result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=(evidence,),
        policy=policy,
        trace_id=trace_id,
    )

    episode = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(evidence,),
        policy=policy,
        gate_result=gate_result,
        trace_id=trace_id,
    )

    diagnostic = build_verification_diagnostic_assessment(
        episode=episode,
        report=gate_result.report,
    )

    assert diagnostic.assessment_id.startswith(
        "verification-diagnostic:sha256:"
    )
    assert diagnostic.task_id == contract.task_id
    assert diagnostic.episode_id == episode.episode_id
    assert diagnostic.verification_report_id == gate_result.report.report_id
    assert diagnostic.completion_status == gate_result.report.completion_status

    assert diagnostic.claim_gaps
    assert all(
        gap.status is not ClaimStatus.PASS
        for gap in diagnostic.claim_gaps
    )

    assert diagnostic.requirement_gaps
    assert all(
        gap.status is not ClaimStatus.PASS
        for gap in diagnostic.requirement_gaps
    )

    assert diagnostic.execution_authority is False
    assert diagnostic.verification_authority is False
    assert diagnostic.completion_authority is False

def test_rejected_evidence_is_exposed_with_exact_payload_identity(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = VerificationPolicy(
        current_revision="expected-revision",
        expected_environment_fingerprint="env-diagnostic",
    )

    evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:rejected-evidence",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="wrong-revision",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    audit = AuditSession(tmp_path / "audit-rejected")
    trace_id = uuid4()
    audit.record_task_contract(contract=contract, trace_id=trace_id)

    gate_result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=(evidence,),
        policy=policy,
        trace_id=trace_id,
    )

    episode = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(evidence,),
        policy=policy,
        gate_result=gate_result,
        trace_id=trace_id,
    )

    diagnostic = build_verification_diagnostic_assessment(
        episode=episode,
        report=gate_result.report,
    )

    assert len(diagnostic.rejected_evidence_issues) == 1

    issue = diagnostic.rejected_evidence_issues[0]
    assert issue.evidence_id == evidence.evidence_id
    assert issue.payload_sha256 == episode.input_evidence[0].payload_sha256
    assert issue.code is EvidenceRejectionCode.REVISION_MISMATCH
    assert issue.reason

def test_accepted_nonqualifying_evidence_is_exposed_separately(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = VerificationPolicy(
        current_revision="rev-diagnostic",
        expected_environment_fingerprint="env-diagnostic",
        minimum_strength=EvidenceStrength.STRONG,
    )

    evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TOOL_OUTPUT,
        source_ref="verification:moderate-tool-output",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="rev-diagnostic",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    audit = AuditSession(tmp_path / "audit-nonqualifying")
    trace_id = uuid4()
    audit.record_task_contract(contract=contract, trace_id=trace_id)

    gate_result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=(evidence,),
        policy=policy,
        trace_id=trace_id,
    )

    # Fixture guard: accepted is not the same thing as qualifying.
    assert evidence.evidence_id in gate_result.report.accepted_evidence_ids
    assert not gate_result.report.rejected_evidence

    strength = gate_result.report.evidence_strength_assessments[0]
    assert strength.evidence_id == evidence.evidence_id
    assert strength.strength is EvidenceStrength.MODERATE
    assert strength.qualifying is False

    episode = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(evidence,),
        policy=policy,
        gate_result=gate_result,
        trace_id=trace_id,
    )

    diagnostic = build_verification_diagnostic_assessment(
        episode=episode,
        report=gate_result.report,
    )

    assert len(diagnostic.nonqualifying_evidence_issues) == 1

    issue = diagnostic.nonqualifying_evidence_issues[0]
    assert issue.evidence_id == evidence.evidence_id
    assert issue.payload_sha256 == episode.input_evidence[0].payload_sha256
    assert issue.strength is EvidenceStrength.MODERATE
    assert issue.reasons == strength.reasons

def test_unresolved_disagreement_binds_both_evidence_sides(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = VerificationPolicy(
        current_revision="rev-conflict",
        expected_environment_fingerprint="env-diagnostic",
    )

    supporting = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:conflict-pass",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="rev-conflict",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    contradicting = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:conflict-fail",
        result=EvidenceResult.FAIL,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="rev-conflict",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    audit = AuditSession(tmp_path / "audit-conflict")
    trace_id = uuid4()
    audit.record_task_contract(contract=contract, trace_id=trace_id)

    gate_result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=(supporting, contradicting),
        policy=policy,
        trace_id=trace_id,
    )

    # Fixture guard: this must be a real verifier disagreement.
    assert len(gate_result.report.disagreements) == 1
    assert gate_result.report.claim_assessments[0].status is ClaimStatus.CONFLICTING

    episode = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(supporting, contradicting),
        policy=policy,
        gate_result=gate_result,
        trace_id=trace_id,
    )

    diagnostic = build_verification_diagnostic_assessment(
        episode=episode,
        report=gate_result.report,
    )

    assert len(diagnostic.disagreements) == 1

    disagreement = diagnostic.disagreements[0]
    verifier_disagreement = gate_result.report.disagreements[0]

    assert disagreement.claim_id == verifier_disagreement.claim_id

    assert tuple(
        item.evidence_id
        for item in disagreement.supporting_evidence
    ) == verifier_disagreement.supporting_evidence_ids

    assert tuple(
        item.evidence_id
        for item in disagreement.contradicting_evidence
    ) == verifier_disagreement.contradicting_evidence_ids

    episode_refs = {
        item.evidence_id: item.payload_sha256
        for item in episode.input_evidence
    }

    assert all(
        item.payload_sha256 == episode_refs[item.evidence_id]
        for item in (
            *disagreement.supporting_evidence,
            *disagreement.contradicting_evidence,
        )
    )

    assert (
        disagreement.strongest_support
        is verifier_disagreement.strongest_support
    )
    assert (
        disagreement.strongest_contradiction
        is verifier_disagreement.strongest_contradiction
    )

def test_previous_verification_projects_resolved_progress(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = VerificationPolicy(
        current_revision="rev-progress",
        expected_environment_fingerprint="env-diagnostic",
        minimum_strength=EvidenceStrength.STRONG,
    )

    before_evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TOOL_OUTPUT,
        source_ref="verification:progress-before",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="rev-progress",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    after_evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:progress-after",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="rev-progress",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    before_audit = AuditSession(tmp_path / "audit-progress-before")
    before_trace = uuid4()
    before_audit.record_task_contract(
        contract=contract,
        trace_id=before_trace,
    )
    before_gate = CompletionGate(before_audit).evaluate(
        contract=contract,
        evidence=(before_evidence,),
        policy=policy,
        trace_id=before_trace,
    )
    before_episode = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(before_evidence,),
        policy=policy,
        gate_result=before_gate,
        trace_id=before_trace,
    )

    after_audit = AuditSession(tmp_path / "audit-progress-after")
    after_trace = uuid4()
    after_audit.record_task_contract(
        contract=contract,
        trace_id=after_trace,
    )
    after_gate = CompletionGate(after_audit).evaluate(
        contract=contract,
        evidence=(after_evidence,),
        policy=policy,
        trace_id=after_trace,
    )
    after_episode = build_verification_episode(
        contract=contract,
        source_task_revision=1,
        evidence=(after_evidence,),
        policy=policy,
        gate_result=after_gate,
        trace_id=after_trace,
    )

    # Fixture guards: before is unresolved, after is verified.
    before_claim = before_gate.report.claim_assessments[0]
    after_claim = after_gate.report.claim_assessments[0]
    assert before_claim.status is not ClaimStatus.PASS
    assert after_claim.status is ClaimStatus.PASS

    before_requirement = (
        before_gate.report.evidence_requirement_assessments[0]
    )
    after_requirement = (
        after_gate.report.evidence_requirement_assessments[0]
    )
    assert before_requirement.status is not ClaimStatus.PASS
    assert after_requirement.status is ClaimStatus.PASS

    diagnostic = build_verification_diagnostic_assessment(
        episode=after_episode,
        report=after_gate.report,
        previous_episode=before_episode,
        previous_report=before_gate.report,
    )

    assert diagnostic.progress is not None

    assert diagnostic.progress.resolved_claim_ids == (
        after_claim.claim.claim_id,
    )
    assert diagnostic.progress.regressed_claim_ids == ()
    assert diagnostic.progress.remaining_claim_ids == ()

    assert diagnostic.progress.resolved_requirements == (
        after_requirement.requirement,
    )
    assert diagnostic.progress.regressed_requirements == ()
    assert diagnostic.progress.remaining_requirements == ()

    assert diagnostic.previous_episode_id == before_episode.episode_id
    assert diagnostic.delta_id is not None

def test_evidence_identity_conflict_is_exposed_as_integrity_signal(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = VerificationPolicy(
        current_revision="rev-identity",
        expected_environment_fingerprint="env-diagnostic",
    )

    before_evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:identity-before",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="rev-identity",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    # Preserve evidence identity while changing its semantic payload.
    after_evidence = before_evidence.model_copy(
        update={
            "source_ref": "verification:identity-after",
        }
    )

    assert after_evidence.evidence_id == before_evidence.evidence_id

    before_audit = AuditSession(tmp_path / "audit-identity-before")
    before_trace = uuid4()
    before_audit.record_task_contract(
        contract=contract,
        trace_id=before_trace,
    )
    before_gate = CompletionGate(before_audit).evaluate(
        contract=contract,
        evidence=(before_evidence,),
        policy=policy,
        trace_id=before_trace,
    )
    before_episode = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(before_evidence,),
        policy=policy,
        gate_result=before_gate,
        trace_id=before_trace,
    )

    after_audit = AuditSession(tmp_path / "audit-identity-after")
    after_trace = uuid4()
    after_audit.record_task_contract(
        contract=contract,
        trace_id=after_trace,
    )
    after_gate = CompletionGate(after_audit).evaluate(
        contract=contract,
        evidence=(after_evidence,),
        policy=policy,
        trace_id=after_trace,
    )
    after_episode = build_verification_episode(
        contract=contract,
        source_task_revision=1,
        evidence=(after_evidence,),
        policy=policy,
        gate_result=after_gate,
        trace_id=after_trace,
    )

    # Fixture guard: Delta itself must detect the identity conflict.
    delta = build_verification_delta(
        before_episode=before_episode,
        before_report=before_gate.report,
        after_episode=after_episode,
        after_report=after_gate.report,
    )

    assert len(delta.evidence_identity_conflicts) == 1
    assert (
        delta.evidence_identity_conflicts[0].evidence_id
        == before_evidence.evidence_id
    )

    diagnostic = build_verification_diagnostic_assessment(
        episode=after_episode,
        report=after_gate.report,
        previous_episode=before_episode,
        previous_report=before_gate.report,
    )

    assert len(diagnostic.evidence_identity_conflicts) == 1

    conflict = diagnostic.evidence_identity_conflicts[0]

    assert conflict.evidence_id == before_evidence.evidence_id
    assert (
        conflict.before_payload_sha256
        == before_episode.input_evidence[0].payload_sha256
    )
    assert (
        conflict.after_payload_sha256
        == after_episode.input_evidence[0].payload_sha256
    )
    assert (
        conflict.before_payload_sha256
        != conflict.after_payload_sha256
    )

def test_diagnostic_integrity_rejects_tampered_semantic_payload(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = VerificationPolicy(
        current_revision="rev-integrity",
        expected_environment_fingerprint="env-diagnostic",
    )

    evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TOOL_OUTPUT,
        source_ref="verification:diagnostic-integrity",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="rev-integrity",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    audit = AuditSession(tmp_path / "audit-diagnostic-integrity")
    trace_id = uuid4()
    audit.record_task_contract(
        contract=contract,
        trace_id=trace_id,
    )

    gate_result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=(evidence,),
        policy=policy,
        trace_id=trace_id,
    )

    episode = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(evidence,),
        policy=policy,
        gate_result=gate_result,
        trace_id=trace_id,
    )

    diagnostic = build_verification_diagnostic_assessment(
        episode=episode,
        report=gate_result.report,
    )

    validate_verification_diagnostic_assessment_integrity(diagnostic)

    assert diagnostic.claim_gaps

    tampered = diagnostic.model_copy(
        update={
            "claim_gaps": (),
        }
    )

    with pytest.raises(ValueError, match="assessment ID"):
        validate_verification_diagnostic_assessment_integrity(tampered)

def test_diagnostic_binding_rejects_tampered_episode_provenance(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = VerificationPolicy(
        current_revision="rev-binding",
        expected_environment_fingerprint="env-diagnostic",
    )

    evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:diagnostic-binding",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="rev-binding",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    audit = AuditSession(tmp_path / "audit-diagnostic-binding")
    trace_id = uuid4()
    audit.record_task_contract(
        contract=contract,
        trace_id=trace_id,
    )

    gate_result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=(evidence,),
        policy=policy,
        trace_id=trace_id,
    )

    episode = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(evidence,),
        policy=policy,
        gate_result=gate_result,
        trace_id=trace_id,
    )

    diagnostic = build_verification_diagnostic_assessment(
        episode=episode,
        report=gate_result.report,
    )

    validate_verification_diagnostic_assessment_binding(
        assessment=diagnostic,
        episode=episode,
        report=gate_result.report,
    )

    tampered = diagnostic.model_copy(
        update={
            "episode_id": (
                "verification-episode:sha256:"
                + ("0" * 64)
            )
        }
    )

    # Occurrence provenance is intentionally outside semantic identity.
    validate_verification_diagnostic_assessment_integrity(tampered)

    with pytest.raises(ValueError, match="episode provenance"):
        validate_verification_diagnostic_assessment_binding(
            assessment=tampered,
            episode=episode,
            report=gate_result.report,
        )

def test_diagnostic_integrity_rejects_tampered_authority_flags(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = VerificationPolicy(
        current_revision="rev-authority",
        expected_environment_fingerprint="env-diagnostic",
    )

    evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:diagnostic-authority",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="rev-authority",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    audit = AuditSession(tmp_path / "audit-diagnostic-authority")
    trace_id = uuid4()
    audit.record_task_contract(
        contract=contract,
        trace_id=trace_id,
    )

    gate_result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=(evidence,),
        policy=policy,
        trace_id=trace_id,
    )

    episode = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(evidence,),
        policy=policy,
        gate_result=gate_result,
        trace_id=trace_id,
    )

    diagnostic = build_verification_diagnostic_assessment(
        episode=episode,
        report=gate_result.report,
    )

    validate_verification_diagnostic_assessment_integrity(diagnostic)

    tampered = diagnostic.model_copy(
        update={
            "verification_authority": True,
        }
    )

    with pytest.raises(ValueError, match="assessment ID"):
        validate_verification_diagnostic_assessment_integrity(tampered)
def test_previous_verification_projects_regressed_progress(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = VerificationPolicy(
        current_revision="rev-regression",
        expected_environment_fingerprint="env-diagnostic",
        minimum_strength=EvidenceStrength.STRONG,
    )

    before_evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:regression-before",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="rev-regression",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    after_evidence = Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TOOL_OUTPUT,
        source_ref="verification:regression-after",
        result=EvidenceResult.PASS,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-diagnostic",
        revision="rev-regression",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    before_audit = AuditSession(tmp_path / "audit-regression-before")
    before_trace = uuid4()
    before_audit.record_task_contract(
        contract=contract,
        trace_id=before_trace,
    )
    before_gate = CompletionGate(before_audit).evaluate(
        contract=contract,
        evidence=(before_evidence,),
        policy=policy,
        trace_id=before_trace,
    )
    before_episode = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(before_evidence,),
        policy=policy,
        gate_result=before_gate,
        trace_id=before_trace,
    )

    after_audit = AuditSession(tmp_path / "audit-regression-after")
    after_trace = uuid4()
    after_audit.record_task_contract(
        contract=contract,
        trace_id=after_trace,
    )
    after_gate = CompletionGate(after_audit).evaluate(
        contract=contract,
        evidence=(after_evidence,),
        policy=policy,
        trace_id=after_trace,
    )
    after_episode = build_verification_episode(
        contract=contract,
        source_task_revision=1,
        evidence=(after_evidence,),
        policy=policy,
        gate_result=after_gate,
        trace_id=after_trace,
    )

    before_claim = before_gate.report.claim_assessments[0]
    after_claim = after_gate.report.claim_assessments[0]

    assert before_claim.status is ClaimStatus.PASS
    assert after_claim.status is not ClaimStatus.PASS

    before_requirement = (
        before_gate.report.evidence_requirement_assessments[0]
    )
    after_requirement = (
        after_gate.report.evidence_requirement_assessments[0]
    )

    assert before_requirement.status is ClaimStatus.PASS
    assert after_requirement.status is not ClaimStatus.PASS

    diagnostic = build_verification_diagnostic_assessment(
        episode=after_episode,
        report=after_gate.report,
        previous_episode=before_episode,
        previous_report=before_gate.report,
    )

    assert diagnostic.progress is not None

    assert diagnostic.progress.resolved_claim_ids == ()
    assert diagnostic.progress.regressed_claim_ids == (
        after_claim.claim.claim_id,
    )
    assert diagnostic.progress.remaining_claim_ids == (
        after_claim.claim.claim_id,
    )

    assert diagnostic.progress.resolved_requirements == ()
    assert diagnostic.progress.regressed_requirements == (
        after_requirement.requirement,
    )
    assert diagnostic.progress.remaining_requirements == (
        after_requirement.requirement,
    )
