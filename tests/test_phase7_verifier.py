from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.contracts.base import utc_now
from luna.contracts.enums import (
    CompletionStatus,
    EvidenceResult,
    EvidenceSourceKind,
)
from luna.contracts.evidence import Evidence
from luna.verification import (
    DeterministicVerifier,
    VerificationPolicy,
    forbidden_absence_claim_id,
    required_condition_claim_id,
)
from luna.verification.models import ClaimStatus, EvidenceRejectionCode


def _contract(*, unknowns: tuple[str, ...] = ()) -> TaskContract:
    return TaskContract(
        task_id=uuid4(),
        objective="Verify Phase 7 behavior.",
        required_conditions=("Tests pass.",),
        forbidden_outcomes=("Protected files changed.",),
        evidence_required=("test result", "hash evidence"),
        scope=TaskScope(workspace_root="C:/workspace"),
        risk_level=RiskLevel.LOW,
        unknowns=unknowns,
        owner="user",
    )


def _evidence(
    contract: TaskContract,
    *,
    requirement_id: str,
    source_kind: EvidenceSourceKind,
    result: EvidenceResult = EvidenceResult.PASS,
    revision: str | None = "rev-7",
    freshness_seconds: int | None = 0,
    reproducible: bool = True,
    confidence: float = 1.0,
    environment: str = "windows-test",
) -> Evidence:
    return Evidence(
        task_id=contract.task_id,
        requirement_id=requirement_id,
        source_kind=source_kind,
        source_ref=f"observation:{uuid4()}",
        result=result,
        environment_fingerprint=environment,
        revision=revision,
        freshness_seconds=freshness_seconds,
        reproducible=reproducible,
        confidence=confidence,
    )


def _complete_evidence(contract: TaskContract) -> tuple[Evidence, ...]:
    return (
        _evidence(
            contract,
            requirement_id=required_condition_claim_id("Tests pass."),
            source_kind=EvidenceSourceKind.TEST_RESULT,
        ),
        _evidence(
            contract,
            requirement_id=forbidden_absence_claim_id(
                "Protected files changed."
            ),
            source_kind=EvidenceSourceKind.HASH,
        ),
    )


def _policy() -> VerificationPolicy:
    return VerificationPolicy(
        current_revision="rev-7",
        expected_environment_fingerprint="windows-test",
        max_freshness_seconds=60,
    )


def test_complete_current_evidence_is_verified_complete() -> None:
    contract = _contract()
    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=_complete_evidence(contract),
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.VERIFIED_COMPLETE
    assert all(
        item.status is ClaimStatus.PASS for item in report.claim_assessments
    )
    assert all(
        item.status is ClaimStatus.PASS
        for item in report.evidence_requirement_assessments
    )


def test_missing_claim_evidence_is_unverified() -> None:
    contract = _contract()
    evidence = _complete_evidence(contract)[:1]

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.UNVERIFIED
    assert report.claim_assessments[1].status is ClaimStatus.UNVERIFIED


def test_old_revision_is_rejected_and_cannot_complete() -> None:
    contract = _contract()
    stale = tuple(
        item.model_copy(update={"revision": "old-revision"})
        for item in _complete_evidence(contract)
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=stale,
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.UNVERIFIED
    assert {item.code for item in report.rejected_evidence} == {
        EvidenceRejectionCode.REVISION_MISMATCH
    }


def test_stale_evidence_is_rejected() -> None:
    contract = _contract()
    stale = tuple(
        item.model_copy(update={"freshness_seconds": 61})
        for item in _complete_evidence(contract)
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=stale,
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.UNVERIFIED
    assert {item.code for item in report.rejected_evidence} == {
        EvidenceRejectionCode.STALE
    }


def test_future_timestamp_is_rejected() -> None:
    contract = _contract()
    future = _complete_evidence(contract)[0].model_copy(
        update={"observed_at": utc_now() + timedelta(minutes=1)}
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=(future,),
        policy=_policy(),
    )

    assert report.rejected_evidence[0].code is EvidenceRejectionCode.FUTURE_TIMESTAMP


def test_conflicting_current_evidence_blocks_success() -> None:
    contract = _contract()
    claim_id = required_condition_claim_id("Tests pass.")
    evidence = (
        *_complete_evidence(contract),
        _evidence(
            contract,
            requirement_id=claim_id,
            source_kind=EvidenceSourceKind.TEST_RESULT,
            result=EvidenceResult.FAIL,
        ),
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.CONFLICTING_EVIDENCE
    assert report.claim_assessments[0].status is ClaimStatus.CONFLICTING


def test_direct_fail_produces_failed() -> None:
    contract = _contract()
    evidence = (
        _evidence(
            contract,
            requirement_id=required_condition_claim_id("Tests pass."),
            source_kind=EvidenceSourceKind.TEST_RESULT,
            result=EvidenceResult.FAIL,
        ),
        _complete_evidence(contract)[1],
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.FAILED


def test_blocked_evidence_produces_blocked() -> None:
    contract = _contract()
    evidence = (
        _evidence(
            contract,
            requirement_id=required_condition_claim_id("Tests pass."),
            source_kind=EvidenceSourceKind.TEST_RESULT,
            result=EvidenceResult.BLOCKED,
        ),
        _complete_evidence(contract)[1],
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.BLOCKED


def test_non_reproducible_pass_is_inconclusive() -> None:
    contract = _contract()
    evidence = tuple(
        item.model_copy(update={"reproducible": False})
        for item in _complete_evidence(contract)
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.INCONCLUSIVE


def test_document_only_pass_is_inconclusive() -> None:
    contract = _contract()
    evidence = (
        _evidence(
            contract,
            requirement_id=required_condition_claim_id("Tests pass."),
            source_kind=EvidenceSourceKind.DOCUMENT,
        ),
        _complete_evidence(contract)[1],
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.INCONCLUSIVE


def test_contract_unknowns_prevent_verified_complete() -> None:
    contract = _contract(unknowns=("target platform confirmation",))
    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=_complete_evidence(contract),
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.UNVERIFIED
    assert report.rationale == ("task contract contains unresolved unknowns",)


def test_unrecognized_evidence_requirement_is_unverified() -> None:
    contract = _contract().model_copy(
        update={"evidence_required": ("owner aura reading",)}
    )
    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=_complete_evidence(contract),
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.UNVERIFIED
    assert (
        report.evidence_requirement_assessments[0].status
        is ClaimStatus.UNVERIFIED
    )


def test_or_requirement_accepts_any_direct_alternative() -> None:
    contract = _contract().model_copy(
        update={
            "evidence_required": (
                "workspace diff or verifier evidence",
            )
        }
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=_complete_evidence(contract),
        policy=_policy(),
    )

    assessment = report.evidence_requirement_assessments[0]

    assert report.completion_status is CompletionStatus.VERIFIED_COMPLETE
    assert assessment.status is ClaimStatus.PASS
    assert assessment.recognized_rules == (
        "DIFF",
        "ANY_DIRECT",
    )
    assert assessment.reasons == (
        "at least one deterministic evidence alternative is satisfied",
    )


def test_or_requirement_accepts_diff_alternative() -> None:
    contract = _contract().model_copy(
        update={
            "evidence_required": (
                "workspace diff or verifier evidence",
            )
        }
    )
    evidence = (
        _evidence(
            contract,
            requirement_id=required_condition_claim_id(
                "Tests pass."
            ),
            source_kind=EvidenceSourceKind.DIFF,
        ),
        _complete_evidence(contract)[1],
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assessment = report.evidence_requirement_assessments[0]

    assert report.completion_status is CompletionStatus.VERIFIED_COMPLETE
    assert assessment.status is ClaimStatus.PASS
    assert assessment.recognized_rules == (
        "DIFF",
        "ANY_DIRECT",
    )


def test_or_requirement_is_unverified_when_no_alternative_matches() -> None:
    contract = _contract().model_copy(
        update={
            "evidence_required": (
                "workspace diff or verifier evidence",
            )
        }
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=(),
        policy=_policy(),
    )

    assessment = report.evidence_requirement_assessments[0]

    assert assessment.status is ClaimStatus.UNVERIFIED
    assert assessment.recognized_rules == (
        "DIFF",
        "ANY_DIRECT",
    )
    assert assessment.reasons == (
        "no deterministic evidence alternative is fully satisfied",
    )


def test_or_requirement_still_requires_qualifying_evidence() -> None:
    contract = _contract().model_copy(
        update={
            "evidence_required": (
                "workspace diff or verifier evidence",
            )
        }
    )
    evidence = tuple(
        item.model_copy(update={"reproducible": False})
        for item in _complete_evidence(contract)
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assert (
        report.evidence_requirement_assessments[0].status
        is ClaimStatus.UNVERIFIED
    )


def test_non_or_multiple_rules_remain_conjunctive() -> None:
    contract = _contract().model_copy(
        update={
            "evidence_required": (
                "test result and hash evidence",
            )
        }
    )
    evidence = (_complete_evidence(contract)[0],)

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assessment = report.evidence_requirement_assessments[0]

    assert assessment.status is ClaimStatus.UNVERIFIED
    assert assessment.recognized_rules == (
        "TEST_RESULT",
        "HASH",
        "ANY_DIRECT",
    )
    assert assessment.reasons == (
        "missing strong qualifying evidence for: HASH",
    )


def test_or_requirement_with_unmapped_alternative_fails_closed() -> None:
    contract = _contract().model_copy(
        update={
            "evidence_required": (
                "diff or owner aura",
            )
        }
    )
    evidence = (
        _evidence(
            contract,
            requirement_id=required_condition_claim_id(
                "Tests pass."
            ),
            source_kind=EvidenceSourceKind.DIFF,
        ),
        _complete_evidence(contract)[1],
    )

    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assessment = report.evidence_requirement_assessments[0]

    assert assessment.status is ClaimStatus.UNVERIFIED
    assert assessment.recognized_rules == ("DIFF",)
    assert assessment.reasons == (
        "evidence requirement contains unmapped OR alternative(s): 2",
    )


def test_or_requirement_has_deterministic_semantic_signature() -> None:
    contract = _contract().model_copy(
        update={
            "evidence_required": (
                "workspace diff or verifier evidence",
            )
        }
    )
    evidence = _complete_evidence(contract)
    verifier = DeterministicVerifier()

    first = verifier.verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )
    second = verifier.verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assert first.semantic_signature() == second.semantic_signature()


def test_same_input_has_same_semantic_report() -> None:
    contract = _contract()
    evidence = _complete_evidence(contract)
    verifier = DeterministicVerifier()

    first = verifier.verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )
    second = verifier.verify(
        contract=contract,
        evidence=evidence,
        policy=_policy(),
    )

    assert first.semantic_signature() == second.semantic_signature()
