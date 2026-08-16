from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from luna.audit import AuditSession
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.contracts.enums import EvidenceResult, EvidenceSourceKind, TaskPhase
from luna.contracts.evidence import Evidence
from luna.identity import IdentityProfile
from luna.learning import LearningCandidateBuilder
from luna.reporting import FinalReportComposer
from luna.verification.claims import required_condition_claim_id
from luna.verification.coordinator import VerificationCoordinator
from luna.verification.episode import (
    DETERMINISTIC_VERIFIER_SEMANTICS_VERSION,
    VerificationEpisodeManifest,
    build_verification_episode,
    compute_verification_basis_fingerprint,
)
from luna.verification.gate import CompletionGate
from luna.verification.models import VerificationPolicy


def _contract(root: Path) -> TaskContract:
    return TaskContract(
        objective="Verify the episode manifest.",
        required_conditions=("Tests pass.",),
        evidence_required=("test result",),
        scope=TaskScope(workspace_root=str(root)),
        risk_level=RiskLevel.LOW,
    )


def _policy() -> VerificationPolicy:
    return VerificationPolicy(
        current_revision="rev-episode",
        expected_environment_fingerprint="env-episode",
    )


def _evidence(
    contract: TaskContract,
    *,
    observed_at: datetime,
    details: str | None = None,
) -> Evidence:
    return Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id("Tests pass."),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:episode-test",
        result=EvidenceResult.PASS,
        observed_at=observed_at,
        environment_fingerprint="env-episode",
        revision="rev-episode",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
        details=details,
    )


def test_verification_basis_changes_with_time_and_input_order(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    policy = _policy()
    now = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)
    first = _evidence(contract, observed_at=now)
    second = _evidence(contract, observed_at=now - timedelta(seconds=1))

    base = compute_verification_basis_fingerprint(
        contract=contract,
        evidence=(first, second),
        policy=policy,
        verification_time=now,
    )
    reordered = compute_verification_basis_fingerprint(
        contract=contract,
        evidence=(second, first),
        policy=policy,
        verification_time=now,
    )
    later = compute_verification_basis_fingerprint(
        contract=contract,
        evidence=(first, second),
        policy=policy,
        verification_time=now + timedelta(seconds=10),
    )

    assert base != reordered
    assert base != later


def test_nonsemantic_evidence_details_do_not_change_verification_basis(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = _policy()
    now = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)
    evidence = _evidence(contract, observed_at=now, details="diagnostic A")
    changed_details = evidence.model_copy(update={"details": "diagnostic B"})

    assert compute_verification_basis_fingerprint(
        contract=contract,
        evidence=(evidence,),
        policy=policy,
        verification_time=now,
    ) == compute_verification_basis_fingerprint(
        contract=contract,
        evidence=(changed_details,),
        policy=policy,
        verification_time=now,
    )


def test_episode_identity_changes_when_full_evidence_payload_changes(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    policy = _policy()
    now = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)
    evidence = _evidence(contract, observed_at=now, details="diagnostic A")
    changed_details = evidence.model_copy(update={"details": "diagnostic B"})

    audit = AuditSession(tmp_path / "audit")
    trace_id = uuid4()
    audit.record_task_contract(contract=contract, trace_id=trace_id)
    gate_result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=(evidence,),
        policy=policy,
        trace_id=trace_id,
    )

    first = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(evidence,),
        policy=policy,
        gate_result=gate_result,
        trace_id=trace_id,
    )
    second = build_verification_episode(
        contract=contract,
        source_task_revision=0,
        evidence=(changed_details,),
        policy=policy,
        gate_result=gate_result,
        trace_id=trace_id,
    )

    assert first.verification_basis_fingerprint == second.verification_basis_fingerprint
    assert first.input_evidence[0].payload_sha256 != second.input_evidence[0].payload_sha256
    assert first.episode_id != second.episode_id

def test_episode_is_non_authoritative_and_content_addressed(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    policy = _policy()
    now = datetime.now(UTC)
    evidence = (_evidence(contract, observed_at=now),)
    audit = AuditSession(tmp_path / "audit")
    trace_id = uuid4()
    audit.record_task_contract(contract=contract, trace_id=trace_id)

    gate_result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=evidence,
        policy=policy,
        trace_id=trace_id,
    )
    episode = build_verification_episode(
        contract=contract,
        source_task_revision=7,
        evidence=evidence,
        policy=policy,
        gate_result=gate_result,
        trace_id=trace_id,
    )

    assert isinstance(episode, VerificationEpisodeManifest)
    assert episode.episode_id.startswith("verification-episode:sha256:")
    assert len(episode.verification_basis_fingerprint) == 64
    assert episode.verifier_semantics_version == DETERMINISTIC_VERIFIER_SEMANTICS_VERSION
    assert episode.verification_time == gate_result.report.generated_at
    assert episode.execution_authority is False
    assert episode.verification_authority is False
    assert episode.completion_authority is False


def test_coordinator_freezes_evidence_and_returns_episode(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    policy = _policy()
    now = datetime.now(UTC)
    records = (_evidence(contract, observed_at=now),)
    state = TaskState(
        task_id=contract.task_id,
        contract=contract,
        phase=TaskPhase.VERIFYING,
    )
    audit = AuditSession(tmp_path / "audit")
    trace_id = uuid4()
    audit.record_task_contract(contract=contract, trace_id=trace_id)

    coordinator = VerificationCoordinator(
        completion_gate=CompletionGate(audit),
        report_composer=FinalReportComposer(audit),
        identity=IdentityProfile(),
        learning_builder=LearningCandidateBuilder(audit),
    )

    consumed = False

    def evidence_stream():
        nonlocal consumed
        assert not consumed
        consumed = True
        yield from records

    finalization = coordinator.finalize(
        state=state,
        evidence=evidence_stream(),
        policy=policy,
        trace_id=trace_id,
    )

    assert consumed is True
    assert finalization.verification_episode.task_id == contract.task_id
    assert finalization.verification_episode.input_evidence[0].evidence_id == records[0].evidence_id
    assert (
        finalization.verification_episode.verification_report_id
        == finalization.gate_result.report.report_id
    )
