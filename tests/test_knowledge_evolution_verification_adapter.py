from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

import luna.verification as package
from luna.contracts.enums import CompletionStatus
from luna.knowledge_evolution import (
    KnowledgeApplicabilitySignalState,
    KnowledgeValiditySignalState,
)
from luna.verification import (
    ClaimKind,
    ClaimStatus,
    KnowledgeVerificationClaimBinding,
    KnowledgeVerificationClaimRole,
    VerificationClaim,
    VerificationKnowledgeEvolutionAdapter,
    VerificationReport,
)
from luna.verification.models import ClaimAssessment

KNOWLEDGE_REF = "memory://record/a"


def _claim(
    token: str,
) -> VerificationClaim:
    return VerificationClaim(
        claim_id=(
            "required:sha256:"
            + token * 64
        ),
        kind=ClaimKind.REQUIRED_CONDITION,
        text=f"condition {token}",
    )


def _assessment(
    *,
    claim: VerificationClaim,
    status: ClaimStatus,
) -> ClaimAssessment:
    evidence_ids = (
        ()
        if status
        in {
            ClaimStatus.UNVERIFIED,
            ClaimStatus.BLOCKED,
        }
        else (uuid4(),)
    )

    return ClaimAssessment(
        claim=claim,
        status=status,
        considered_evidence_ids=evidence_ids,
        qualifying_evidence_ids=evidence_ids,
        reasons=(f"fixture:{status.value}",),
    )


def _report(
    *assessments: ClaimAssessment,
) -> VerificationReport:
    # Report integrity belongs to existing Verification tests.
    # This focused adapter fixture needs only the already-owned
    # report identity and claim-assessment surface.
    return VerificationReport.model_construct(
        report_id=uuid4(),
        task_id=uuid4(),
        claim_assessments=tuple(assessments),
        evidence_requirement_assessments=(),
        evidence_strength_assessments=(),
        disagreements=(),
        accepted_evidence_ids=(),
        rejected_evidence=(),
        unmatched_requirement_ids=(),
        completion_status=CompletionStatus.UNVERIFIED,
        rationale=("focused adapter fixture",),
    )


def _binding(
    *,
    report: VerificationReport,
    claim: VerificationClaim,
    role: KnowledgeVerificationClaimRole,
    condition_ref: str | None = None,
) -> KnowledgeVerificationClaimBinding:
    return KnowledgeVerificationClaimBinding(
        task_id=report.task_id,
        knowledge_ref=KNOWLEDGE_REF,
        claim_id=claim.claim_id,
        role=role,
        condition_ref=condition_ref,
        provenance_refs=(
            "owner://verification",
        ),
    )


def test_o1_verification_adapter_is_public() -> None:
    assert (
        package.KnowledgeVerificationClaimBinding
        is KnowledgeVerificationClaimBinding
    )
    assert (
        package.KnowledgeVerificationClaimRole
        is KnowledgeVerificationClaimRole
    )
    assert (
        package.VerificationKnowledgeEvolutionAdapter
        is VerificationKnowledgeEvolutionAdapter
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (
            ClaimStatus.PASS,
            KnowledgeValiditySignalState.SUPPORTED,
        ),
        (
            ClaimStatus.FAIL,
            KnowledgeValiditySignalState.CONTRADICTED,
        ),
        (
            ClaimStatus.CONFLICTING,
            KnowledgeValiditySignalState.UNRESOLVED,
        ),
        (
            ClaimStatus.INCONCLUSIVE,
            KnowledgeValiditySignalState.UNRESOLVED,
        ),
        (
            ClaimStatus.BLOCKED,
            KnowledgeValiditySignalState.UNRESOLVED,
        ),
        (
            ClaimStatus.UNVERIFIED,
            KnowledgeValiditySignalState.UNRESOLVED,
        ),
    ),
)
def test_validity_projection_uses_verifier_owned_status(
    status: ClaimStatus,
    expected: KnowledgeValiditySignalState,
) -> None:
    validity_claim = _claim("a")
    applicability_claim = _claim("b")

    report = _report(
        _assessment(
            claim=validity_claim,
            status=status,
        ),
        _assessment(
            claim=applicability_claim,
            status=ClaimStatus.PASS,
        ),
    )

    validity, _ = (
        VerificationKnowledgeEvolutionAdapter().project(
            report=report,
            bindings=(
                _binding(
                    report=report,
                    claim=validity_claim,
                    role=(
                        KnowledgeVerificationClaimRole.VALIDITY
                    ),
                ),
                _binding(
                    report=report,
                    claim=applicability_claim,
                    role=(
                        KnowledgeVerificationClaimRole
                        .APPLICABILITY_CONDITION
                    ),
                    condition_ref=(
                        "condition://runtime/windows"
                    ),
                ),
            ),
        )
    )

    assert validity.state is expected
    assert validity.knowledge_ref == KNOWLEDGE_REF
    assert validity.truth_authority is False
    assert validity.verification_authority is False
    assert validity.ranking_authority is False
    assert validity.execution_authority is False
    assert validity.runtime_authority is False


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (
            ClaimStatus.PASS,
            KnowledgeApplicabilitySignalState.APPLICABLE,
        ),
        (
            ClaimStatus.FAIL,
            KnowledgeApplicabilitySignalState.INAPPLICABLE,
        ),
        (
            ClaimStatus.CONFLICTING,
            KnowledgeApplicabilitySignalState.UNRESOLVED,
        ),
        (
            ClaimStatus.INCONCLUSIVE,
            KnowledgeApplicabilitySignalState.UNRESOLVED,
        ),
        (
            ClaimStatus.BLOCKED,
            KnowledgeApplicabilitySignalState.UNRESOLVED,
        ),
        (
            ClaimStatus.UNVERIFIED,
            KnowledgeApplicabilitySignalState.UNRESOLVED,
        ),
    ),
)
def test_applicability_projection_requires_explicit_condition_claim(
    status: ClaimStatus,
    expected: KnowledgeApplicabilitySignalState,
) -> None:
    validity_claim = _claim("c")
    applicability_claim = _claim("d")

    report = _report(
        _assessment(
            claim=validity_claim,
            status=ClaimStatus.PASS,
        ),
        _assessment(
            claim=applicability_claim,
            status=status,
        ),
    )

    _, applicability = (
        VerificationKnowledgeEvolutionAdapter().project(
            report=report,
            bindings=(
                _binding(
                    report=report,
                    claim=validity_claim,
                    role=(
                        KnowledgeVerificationClaimRole.VALIDITY
                    ),
                ),
                _binding(
                    report=report,
                    claim=applicability_claim,
                    role=(
                        KnowledgeVerificationClaimRole
                        .APPLICABILITY_CONDITION
                    ),
                    condition_ref=(
                        "condition://runtime/windows"
                    ),
                ),
            ),
        )
    )

    assert applicability.state is expected
    assert applicability.condition_refs == (
        "condition://runtime/windows",
    )
    assert applicability.truth_authority is False
    assert applicability.verification_authority is False
    assert applicability.ranking_authority is False
    assert applicability.execution_authority is False
    assert applicability.runtime_authority is False


def test_multiple_claims_are_conjunctive_and_fail_closed() -> None:
    validity_a = _claim("e")
    validity_b = _claim("f")
    applicability_a = _claim("1")
    applicability_b = _claim("2")

    report = _report(
        _assessment(
            claim=validity_a,
            status=ClaimStatus.PASS,
        ),
        _assessment(
            claim=validity_b,
            status=ClaimStatus.FAIL,
        ),
        _assessment(
            claim=applicability_a,
            status=ClaimStatus.PASS,
        ),
        _assessment(
            claim=applicability_b,
            status=ClaimStatus.INCONCLUSIVE,
        ),
    )

    validity, applicability = (
        VerificationKnowledgeEvolutionAdapter().project(
            report=report,
            bindings=(
                _binding(
                    report=report,
                    claim=validity_a,
                    role=(
                        KnowledgeVerificationClaimRole.VALIDITY
                    ),
                ),
                _binding(
                    report=report,
                    claim=validity_b,
                    role=(
                        KnowledgeVerificationClaimRole.VALIDITY
                    ),
                ),
                _binding(
                    report=report,
                    claim=applicability_a,
                    role=(
                        KnowledgeVerificationClaimRole
                        .APPLICABILITY_CONDITION
                    ),
                    condition_ref="condition://a",
                ),
                _binding(
                    report=report,
                    claim=applicability_b,
                    role=(
                        KnowledgeVerificationClaimRole
                        .APPLICABILITY_CONDITION
                    ),
                    condition_ref="condition://b",
                ),
            ),
        )
    )

    assert (
        validity.state
        is KnowledgeValiditySignalState.CONTRADICTED
    )
    assert (
        applicability.state
        is KnowledgeApplicabilitySignalState.UNRESOLVED
    )


def test_binding_rejects_role_condition_mismatch() -> None:
    task_id = uuid4()

    with pytest.raises(ValidationError):
        KnowledgeVerificationClaimBinding(
            task_id=task_id,
            knowledge_ref=KNOWLEDGE_REF,
            claim_id=(
                "required:sha256:"
                + "a" * 64
            ),
            role=(
                KnowledgeVerificationClaimRole.VALIDITY
            ),
            condition_ref="condition://unexpected",
            provenance_refs=(
                "owner://verification",
            ),
        )

    with pytest.raises(ValidationError):
        KnowledgeVerificationClaimBinding(
            task_id=task_id,
            knowledge_ref=KNOWLEDGE_REF,
            claim_id=(
                "required:sha256:"
                + "b" * 64
            ),
            role=(
                KnowledgeVerificationClaimRole
                .APPLICABILITY_CONDITION
            ),
            condition_ref=None,
            provenance_refs=(
                "owner://verification",
            ),
        )


def test_adapter_rejects_missing_bound_claim() -> None:
    validity_claim = _claim("7")
    applicability_claim = _claim("8")

    report = _report(
        _assessment(
            claim=validity_claim,
            status=ClaimStatus.PASS,
        ),
    )

    with pytest.raises(
        ValueError,
        match="claim absent from report",
    ):
        VerificationKnowledgeEvolutionAdapter().project(
            report=report,
            bindings=(
                _binding(
                    report=report,
                    claim=validity_claim,
                    role=(
                        KnowledgeVerificationClaimRole.VALIDITY
                    ),
                ),
                _binding(
                    report=report,
                    claim=applicability_claim,
                    role=(
                        KnowledgeVerificationClaimRole
                        .APPLICABILITY_CONDITION
                    ),
                    condition_ref="condition://missing",
                ),
            ),
        )


def test_adapter_rejects_cross_task_binding() -> None:
    validity_claim = _claim("9")
    applicability_claim = _claim("0")

    report = _report(
        _assessment(
            claim=validity_claim,
            status=ClaimStatus.PASS,
        ),
        _assessment(
            claim=applicability_claim,
            status=ClaimStatus.PASS,
        ),
    )

    bad = _binding(
        report=report,
        claim=validity_claim,
        role=KnowledgeVerificationClaimRole.VALIDITY,
    ).model_copy(
        update={
            "task_id": uuid4(),
        }
    )

    with pytest.raises(
        ValueError,
        match="share one task",
    ):
        VerificationKnowledgeEvolutionAdapter().project(
            report=report,
            bindings=(
                bad,
                _binding(
                    report=report,
                    claim=applicability_claim,
                    role=(
                        KnowledgeVerificationClaimRole
                        .APPLICABILITY_CONDITION
                    ),
                    condition_ref="condition://task",
                ),
            ),
        )


def test_unresolved_projection_does_not_invent_evidence() -> None:
    validity_claim = _claim("3")
    applicability_claim = _claim("4")

    report = _report(
        _assessment(
            claim=validity_claim,
            status=ClaimStatus.UNVERIFIED,
        ),
        _assessment(
            claim=applicability_claim,
            status=ClaimStatus.UNVERIFIED,
        ),
    )

    validity, applicability = (
        VerificationKnowledgeEvolutionAdapter().project(
            report=report,
            bindings=(
                _binding(
                    report=report,
                    claim=validity_claim,
                    role=(
                        KnowledgeVerificationClaimRole.VALIDITY
                    ),
                ),
                _binding(
                    report=report,
                    claim=applicability_claim,
                    role=(
                        KnowledgeVerificationClaimRole
                        .APPLICABILITY_CONDITION
                    ),
                    condition_ref=(
                        "condition://unverified"
                    ),
                ),
            ),
        )
    )

    assert validity.evidence_refs == ()
    assert applicability.evidence_refs == ()
