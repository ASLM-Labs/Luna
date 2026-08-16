from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import pytest
from pydantic import ValidationError

from luna.context import (
    ContextAuthorityRole,
    ContextClaim,
    ContextClaimType,
    ContextSourceKind,
)
from luna.continuity import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolutionStatus,
    CognitiveSemanticClaimBinding,
    bind_cognitive_semantic_claim,
    build_cognitive_owner_resolution,
)

_TASK_ID = UUID("11111111-1111-4111-8111-111111111111")
_MEMORY_ID = UUID("22222222-2222-4222-8222-222222222222")
_SESSION_ID = UUID("33333333-3333-4333-8333-333333333333")
_NOW = datetime(2026, 8, 16, 20, 0, tzinfo=UTC)


def _digest(seed: str) -> str:
    return sha256(seed.encode("utf-8")).hexdigest()


def _resolution(
    *,
    owner_kind: CognitiveOwnerKind,
    source_ref: str,
    historical_seed: str = "same",
    current_seed: str = "same",
):
    historical = CognitiveOwnerBinding(
        owner_kind=owner_kind,
        source_ref=source_ref,
        content_sha256=_digest(historical_seed),
    )
    current = CognitiveOwnerBinding(
        owner_kind=owner_kind,
        source_ref=source_ref,
        content_sha256=_digest(current_seed),
    )
    return build_cognitive_owner_resolution(
        historical_binding=historical,
        current_binding=current,
    )


def _memory_claim(
    *,
    source_ref: str,
    role: ContextAuthorityRole = ContextAuthorityRole.VERIFIED_MEMORY,
    source_kind: ContextSourceKind = ContextSourceKind.MEMORY,
    verified: bool = True,
) -> ContextClaim:
    return ContextClaim(
        task_id=_TASK_ID,
        key="current_head",
        value="f535a43",
        claim_type=ContextClaimType.REPOSITORY_STATE,
        source_kind=source_kind,
        source_ref=source_ref,
        authority_role=role,
        observed_at=_NOW,
        verified=verified,
        evidence_refs=(("memory:current-head",) if verified else ()),
    )


def _session_claim(
    *,
    source_ref: str,
    role: ContextAuthorityRole = ContextAuthorityRole.CONVERSATION,
    source_kind: ContextSourceKind = ContextSourceKind.DOCUMENT,
    verified: bool = False,
) -> ContextClaim:
    return ContextClaim(
        task_id=_TASK_ID,
        key="user_intent_hint",
        value="Continue the current task.",
        claim_type=ContextClaimType.USER_INTENT,
        source_kind=source_kind,
        source_ref=source_ref,
        authority_role=role,
        observed_at=_NOW,
        verified=verified,
        evidence_refs=(),
    )


def test_memory_claim_binds_without_rewriting_real_evidence_refs() -> None:
    source_ref = f"memory://record/{_MEMORY_ID}"
    resolution = _resolution(
        owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
        source_ref=source_ref,
    )
    claim = _memory_claim(source_ref=source_ref)

    binding = bind_cognitive_semantic_claim(
        owner_resolution=resolution,
        claim=claim,
    )

    assert binding.owner_resolution is resolution
    assert binding.claim is claim
    assert binding.claim.source_ref == source_ref
    assert binding.claim.evidence_refs == ("memory:current-head",)
    assert binding.runtime_authority is False
    assert binding.execution_authority is False
    assert binding.completion_authority is False


def test_changed_snapshot_can_bind_current_claim_without_claiming_contradiction(
) -> None:
    source_ref = f"memory://record/{_MEMORY_ID}"
    resolution = _resolution(
        owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
        source_ref=source_ref,
        historical_seed="historical",
        current_seed="current",
    )

    binding = bind_cognitive_semantic_claim(
        owner_resolution=resolution,
        claim=_memory_claim(source_ref=source_ref),
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert binding.claim.value == "f535a43"


@pytest.mark.parametrize(
    ("role", "source_kind", "verified", "message"),
    (
        (
            ContextAuthorityRole.CONVERSATION,
            ContextSourceKind.MEMORY,
            True,
            "VERIFIED_MEMORY authority",
        ),
        (
            ContextAuthorityRole.VERIFIED_MEMORY,
            ContextSourceKind.MEMORY,
            False,
            "must be explicitly verified",
        ),
    ),
)
def test_memory_claim_rejects_authority_boundary_violations(
    role: ContextAuthorityRole,
    source_kind: ContextSourceKind,
    verified: bool,
    message: str,
) -> None:
    source_ref = f"memory://record/{_MEMORY_ID}"
    resolution = _resolution(
        owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
        source_ref=source_ref,
    )

    with pytest.raises((ValidationError, ValueError), match=message):
        bind_cognitive_semantic_claim(
            owner_resolution=resolution,
            claim=_memory_claim(
                source_ref=source_ref,
                role=role,
                source_kind=source_kind,
                verified=verified,
            ),
        )


def test_memory_claim_rejects_different_owner_source_ref() -> None:
    source_ref = f"memory://record/{_MEMORY_ID}"
    resolution = _resolution(
        owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
        source_ref=source_ref,
    )

    with pytest.raises(ValueError, match="exact owner source ref"):
        bind_cognitive_semantic_claim(
            owner_resolution=resolution,
            claim=_memory_claim(source_ref="memory://record/other"),
        )


def test_session_claim_binds_as_unverified_conversation_data() -> None:
    source_ref = f"session://{_SESSION_ID}"
    resolution = _resolution(
        owner_kind=CognitiveOwnerKind.WORKING_SESSION,
        source_ref=source_ref,
    )
    claim_ref = f"{source_ref}/entry/3"
    claim = _session_claim(source_ref=claim_ref)

    binding = bind_cognitive_semantic_claim(
        owner_resolution=resolution,
        claim=claim,
    )

    assert binding.claim is claim
    assert binding.claim.authority_role is ContextAuthorityRole.CONVERSATION
    assert binding.claim.source_kind is ContextSourceKind.DOCUMENT
    assert binding.claim.verified is False
    assert binding.claim.evidence_refs == ()


@pytest.mark.parametrize(
    ("role", "source_kind", "verified", "message"),
    (
        (
            ContextAuthorityRole.CURRENT_OBSERVATION,
            ContextSourceKind.DOCUMENT,
            False,
            "CONVERSATION authority",
        ),
        (
            ContextAuthorityRole.CONVERSATION,
            ContextSourceKind.MEMORY,
            False,
            "DOCUMENT source kind",
        ),
        (
            ContextAuthorityRole.CONVERSATION,
            ContextSourceKind.DOCUMENT,
            True,
            "cannot self-declare verified",
        ),
    ),
)
def test_session_claim_rejects_authority_boundary_violations(
    role: ContextAuthorityRole,
    source_kind: ContextSourceKind,
    verified: bool,
    message: str,
) -> None:
    source_ref = f"session://{_SESSION_ID}"
    resolution = _resolution(
        owner_kind=CognitiveOwnerKind.WORKING_SESSION,
        source_ref=source_ref,
    )

    claim = _session_claim(
        source_ref=f"{source_ref}/entry/1",
        role=role,
        source_kind=source_kind,
        verified=False,
    )
    if verified:
        payload = claim.model_dump(mode="python")
        payload["verified"] = True
        payload["evidence_refs"] = ("external:test",)
        claim = ContextClaim.model_validate(payload)

    with pytest.raises((ValidationError, ValueError), match=message):
        bind_cognitive_semantic_claim(
            owner_resolution=resolution,
            claim=claim,
        )


def test_session_claim_rejects_source_outside_current_session() -> None:
    source_ref = f"session://{_SESSION_ID}"
    resolution = _resolution(
        owner_kind=CognitiveOwnerKind.WORKING_SESSION,
        source_ref=source_ref,
    )

    with pytest.raises(ValueError, match="session entry source ref"):
        bind_cognitive_semantic_claim(
            owner_resolution=resolution,
            claim=_session_claim(
                source_ref="session://other/entry/1",
            ),
        )


@pytest.mark.parametrize(
    "owner_kind",
    (
        CognitiveOwnerKind.IDENTITY_PROFILE,
        CognitiveOwnerKind.VERIFICATION_EVIDENCE,
    ),
)
def test_direct_semantic_claims_reject_non_claim_owner_families(
    owner_kind: CognitiveOwnerKind,
) -> None:
    source_ref = f"owner://{owner_kind.value.lower()}"
    resolution = _resolution(
        owner_kind=owner_kind,
        source_ref=source_ref,
    )
    claim = ContextClaim(
        task_id=_TASK_ID,
        key="unsupported",
        value="unsupported",
        claim_type=ContextClaimType.GENERIC,
        source_kind=ContextSourceKind.PROJECT_STATE,
        source_ref=source_ref,
        authority_role=ContextAuthorityRole.CANONICAL_PROJECT,
        observed_at=_NOW,
        verified=True,
        evidence_refs=("fixture:unsupported",),
    )

    with pytest.raises(ValueError, match="does not support direct semantic claims"):
        bind_cognitive_semantic_claim(
            owner_resolution=resolution,
            claim=claim,
        )


@pytest.mark.parametrize(
    "absence_status",
    (
        CognitiveOwnerResolutionStatus.MISSING,
        CognitiveOwnerResolutionStatus.UNAVAILABLE,
    ),
)
def test_absent_owner_cannot_bind_semantic_claim(
    absence_status: CognitiveOwnerResolutionStatus,
) -> None:
    source_ref = f"memory://record/{_MEMORY_ID}"
    historical = CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
        source_ref=source_ref,
        content_sha256=_digest("historical"),
    )
    resolution = build_cognitive_owner_resolution(
        historical_binding=historical,
        absence_status=absence_status,
    )

    with pytest.raises(ValueError, match="available current owner"):
        bind_cognitive_semantic_claim(
            owner_resolution=resolution,
            claim=_memory_claim(source_ref=source_ref),
        )


def test_manual_binding_preserves_claim_and_rejects_wrong_family_policy() -> None:
    source_ref = f"memory://record/{_MEMORY_ID}"
    resolution = _resolution(
        owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
        source_ref=source_ref,
    )
    claim = _memory_claim(source_ref=source_ref)

    binding = CognitiveSemanticClaimBinding(
        owner_resolution=resolution,
        claim=claim,
    )

    assert binding.claim is claim
    assert binding.owner_resolution is resolution
