from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from luna.audit import AuditSession
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.contracts.enums import EvidenceResult, EvidenceSourceKind
from luna.contracts.evidence import Evidence
from luna.verification.claims import required_condition_claim_id
from luna.verification.delta import build_verification_delta
from luna.verification.episode import (
    VerificationEpisodeManifest,
    build_verification_episode,
)
from luna.verification.gate import CompletionGate
from luna.verification.models import (
    ClaimStatus,
    CompletionGateResult,
    EvidenceRejectionCode,
    VerificationPolicy,
    VerificationReport,
)

_REQUIRED = "Tests pass."


def _contract(root: Path) -> TaskContract:
    return TaskContract(
        objective="Verify delta projection behavior.",
        required_conditions=(_REQUIRED,),
        evidence_required=("test result",),
        scope=TaskScope(workspace_root=str(root)),
        risk_level=RiskLevel.LOW,
    )


def _policy(revision: str = "rev-delta") -> VerificationPolicy:
    return VerificationPolicy(
        current_revision=revision,
        expected_environment_fingerprint="env-delta",
    )


def _evidence(
    contract: TaskContract,
    *,
    result: EvidenceResult = EvidenceResult.PASS,
    revision: str = "rev-delta",
    evidence_id: UUID | None = None,
    details: str | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id or uuid4(),
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:delta-test",
        result=result,
        observed_at=datetime.now(UTC),
        environment_fingerprint="env-delta",
        revision=revision,
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
        details=details,
    )


def _evaluate(
    tmp_path: Path,
    *,
    contract: TaskContract,
    policy: VerificationPolicy,
    evidence: tuple[Evidence, ...],
    label: str,
) -> tuple[CompletionGateResult, UUID]:
    audit = AuditSession(tmp_path / f"audit-{label}")
    trace_id = uuid4()
    audit.record_task_contract(contract=contract, trace_id=trace_id)
    result = CompletionGate(audit).evaluate(
        contract=contract,
        evidence=evidence,
        policy=policy,
        trace_id=trace_id,
    )
    return result, trace_id


def _episode(
    *,
    contract: TaskContract,
    policy: VerificationPolicy,
    evidence: tuple[Evidence, ...],
    gate_result: CompletionGateResult,
    trace_id: UUID,
    revision: int = 0,
) -> VerificationEpisodeManifest:
    return build_verification_episode(
        contract=contract,
        source_task_revision=revision,
        evidence=evidence,
        policy=policy,
        gate_result=gate_result,
        trace_id=trace_id,
    )


def _run(
    tmp_path: Path,
    *,
    contract: TaskContract,
    policy: VerificationPolicy,
    evidence: tuple[Evidence, ...],
    label: str,
    revision: int = 0,
) -> tuple[VerificationEpisodeManifest, VerificationReport]:
    gate_result, trace_id = _evaluate(
        tmp_path,
        contract=contract,
        policy=policy,
        evidence=evidence,
        label=label,
    )
    return (
        _episode(
            contract=contract,
            policy=policy,
            evidence=evidence,
            gate_result=gate_result,
            trace_id=trace_id,
            revision=revision,
        ),
        gate_result.report,
    )


def test_same_episode_produces_empty_semantic_delta(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    evidence = (_evidence(contract),)
    episode, report = _run(
        tmp_path,
        contract=contract,
        policy=_policy(),
        evidence=evidence,
        label="same",
    )

    delta = build_verification_delta(
        before_episode=episode,
        before_report=report,
        after_episode=episode,
        after_report=report,
    )

    assert delta.delta_id.startswith("verification-delta:sha256:")
    assert delta.contract_changed is False
    assert delta.policy_changed is False
    assert delta.verifier_semantics_changed is False
    assert delta.verification_time_changed is False
    assert delta.verification_basis_changed is False
    assert delta.source_task_revision_changed is False
    assert delta.verification_output_changed is False
    assert delta.evidence_changes == ()
    assert delta.evidence_identity_conflicts == ()
    assert delta.claim_changes == ()
    assert delta.evidence_requirement_changes == ()
    assert delta.verification_authority is False
    assert delta.completion_authority is False


def test_claim_pass_to_fail_is_reported(tmp_path: Path) -> None:
    contract = _contract(tmp_path)

    before, before_report = _run(
        tmp_path,
        contract=contract,
        policy=_policy(),
        evidence=(_evidence(contract, result=EvidenceResult.PASS),),
        label="claim-before",
    )
    after, after_report = _run(
        tmp_path,
        contract=contract,
        policy=_policy(),
        evidence=(_evidence(contract, result=EvidenceResult.FAIL),),
        label="claim-after",
    )

    delta = build_verification_delta(
        before_episode=before,
        before_report=before_report,
        after_episode=after,
        after_report=after_report,
    )

    change = next(
        item
        for item in delta.claim_changes
        if item.claim_id == required_condition_claim_id(_REQUIRED)
    )
    assert change.before.status is ClaimStatus.PASS
    assert change.after.status is ClaimStatus.FAIL
    assert delta.verification_output_changed is True
    assert delta.before_completion_status != delta.after_completion_status


def test_evidence_addition_is_reported(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    first = _evidence(contract)
    added = _evidence(contract)

    before, before_report = _run(
        tmp_path,
        contract=contract,
        policy=_policy(),
        evidence=(first,),
        label="evidence-before",
    )
    after, after_report = _run(
        tmp_path,
        contract=contract,
        policy=_policy(),
        evidence=(first, added),
        label="evidence-after",
    )

    delta = build_verification_delta(
        before_episode=before,
        before_report=before_report,
        after_episode=after,
        after_report=after_report,
    )

    change = next(
        item for item in delta.evidence_changes
        if item.evidence_id == added.evidence_id
    )
    assert change.before is None
    assert change.after is not None


def test_accepted_evidence_can_become_revision_rejected(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    evidence = _evidence(contract, revision="rev-delta")

    before, before_report = _run(
        tmp_path,
        contract=contract,
        policy=_policy("rev-delta"),
        evidence=(evidence,),
        label="accepted",
    )
    after, after_report = _run(
        tmp_path,
        contract=contract,
        policy=_policy("rev-other"),
        evidence=(evidence,),
        label="rejected",
    )

    delta = build_verification_delta(
        before_episode=before,
        before_report=before_report,
        after_episode=after,
        after_report=after_report,
    )

    change = next(
        item for item in delta.evidence_changes
        if item.evidence_id == evidence.evidence_id
    )
    assert change.before is not None
    assert change.after is not None
    assert change.before.accepted is True
    assert change.after.accepted is False
    assert change.after.rejection_code is EvidenceRejectionCode.REVISION_MISMATCH
    assert delta.policy_changed is True


def test_same_evidence_id_with_different_payload_is_identity_conflict(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    evidence_id = uuid4()
    original = _evidence(
        contract,
        evidence_id=evidence_id,
        details="diagnostic A",
    )
    changed = original.model_copy(update={"details": "diagnostic B"})
    policy = _policy()

    gate_result, trace_id = _evaluate(
        tmp_path,
        contract=contract,
        policy=policy,
        evidence=(original,),
        label="identity",
    )

    before = _episode(
        contract=contract,
        policy=policy,
        evidence=(original,),
        gate_result=gate_result,
        trace_id=trace_id,
    )
    after = _episode(
        contract=contract,
        policy=policy,
        evidence=(changed,),
        gate_result=gate_result,
        trace_id=trace_id,
    )

    delta = build_verification_delta(
        before_episode=before,
        before_report=gate_result.report,
        after_episode=after,
        after_report=gate_result.report,
    )

    assert len(delta.evidence_identity_conflicts) == 1
    conflict = delta.evidence_identity_conflicts[0]
    assert conflict.evidence_id == evidence_id
    assert conflict.before_payload_sha256 != conflict.after_payload_sha256
    assert delta.verification_output_changed is False


def test_policy_change_without_output_change_is_distinguished(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)

    before, before_report = _run(
        tmp_path,
        contract=contract,
        policy=_policy("rev-a"),
        evidence=(),
        label="policy-a",
    )
    after, after_report = _run(
        tmp_path,
        contract=contract,
        policy=_policy("rev-b"),
        evidence=(),
        label="policy-b",
    )

    delta = build_verification_delta(
        before_episode=before,
        before_report=before_report,
        after_episode=after,
        after_report=after_report,
    )

    assert delta.policy_changed is True
    assert delta.verification_time_changed is True
    assert delta.verification_basis_changed is True
    assert delta.verification_output_changed is False


def test_report_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    episode, report = _run(
        tmp_path,
        contract=contract,
        policy=_policy(),
        evidence=(_evidence(contract),),
        label="tamper",
    )
    tampered = report.model_copy(
        update={"rationale": (*report.rationale, "tampered rationale")}
    )

    with pytest.raises(ValueError, match="report digest"):
        build_verification_delta(
            before_episode=episode,
            before_report=tampered,
            after_episode=episode,
            after_report=report,
        )


def test_cross_task_delta_is_rejected(tmp_path: Path) -> None:
    first_contract = _contract(tmp_path / "first")
    second_contract = _contract(tmp_path / "second")

    before, before_report = _run(
        tmp_path,
        contract=first_contract,
        policy=_policy(),
        evidence=(_evidence(first_contract),),
        label="task-first",
    )
    after, after_report = _run(
        tmp_path,
        contract=second_contract,
        policy=_policy(),
        evidence=(_evidence(second_contract),),
        label="task-second",
    )

    with pytest.raises(ValueError, match="same task"):
        build_verification_delta(
            before_episode=before,
            before_report=before_report,
            after_episode=after,
            after_report=after_report,
        )
