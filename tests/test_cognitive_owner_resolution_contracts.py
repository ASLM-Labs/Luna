from __future__ import annotations

from hashlib import sha256

import pytest
from pydantic import ValidationError

from luna.continuity import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolution,
    CognitiveOwnerResolutionReason,
    CognitiveOwnerResolutionStatus,
    build_cognitive_owner_resolution,
)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _binding(
    *,
    owner_kind: CognitiveOwnerKind = CognitiveOwnerKind.IDENTITY_PROFILE,
    source_ref: str = "identity://luna/profile/1",
    digest_seed: str = "identity-v1",
) -> CognitiveOwnerBinding:
    return CognitiveOwnerBinding(
        owner_kind=owner_kind,
        source_ref=source_ref,
        content_sha256=_digest(digest_seed),
    )


def test_exact_owner_snapshot_match_is_non_authoritative() -> None:
    historical = _binding()
    resolution = build_cognitive_owner_resolution(
        historical_binding=historical,
        current_binding=historical,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.MATCHED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.SNAPSHOT_MATCH
    assert resolution.requires_semantic_reconciliation is False
    assert resolution.runtime_authority is False
    assert resolution.execution_authority is False
    assert resolution.completion_authority is False


def test_digest_change_marks_snapshot_changed_without_semantic_conflict_claim() -> None:
    historical = _binding()
    current = _binding(digest_seed="identity-v2")

    resolution = build_cognitive_owner_resolution(
        historical_binding=historical,
        current_binding=current,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.CONTENT_CHANGED
    assert resolution.requires_semantic_reconciliation is True
    assert "CONFLICT" not in resolution.status.value
    assert "CONTRADICT" not in resolution.reason_code.value


def test_source_change_is_distinguished_from_content_change() -> None:
    historical = _binding()
    current = _binding(source_ref="identity://luna/profile/2")

    resolution = build_cognitive_owner_resolution(
        historical_binding=historical,
        current_binding=current,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.SOURCE_CHANGED


def test_source_and_content_change_have_explicit_reason() -> None:
    historical = _binding()
    current = _binding(
        source_ref="identity://luna/profile/2",
        digest_seed="identity-v2",
    )

    resolution = build_cognitive_owner_resolution(
        historical_binding=historical,
        current_binding=current,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert (
        resolution.reason_code
        is CognitiveOwnerResolutionReason.SOURCE_AND_CONTENT_CHANGED
    )


@pytest.mark.parametrize(
    ("status", "reason"),
    (
        (
            CognitiveOwnerResolutionStatus.MISSING,
            CognitiveOwnerResolutionReason.OWNER_MISSING,
        ),
        (
            CognitiveOwnerResolutionStatus.UNAVAILABLE,
            CognitiveOwnerResolutionReason.OWNER_UNAVAILABLE,
        ),
    ),
)
def test_absent_current_owner_requires_explicit_status(
    status: CognitiveOwnerResolutionStatus,
    reason: CognitiveOwnerResolutionReason,
) -> None:
    resolution = build_cognitive_owner_resolution(
        historical_binding=_binding(),
        absence_status=status,
    )

    assert resolution.current_binding is None
    assert resolution.status is status
    assert resolution.reason_code is reason
    assert resolution.requires_semantic_reconciliation is True


def test_missing_current_binding_without_absence_status_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="requires MISSING or UNAVAILABLE absence_status",
    ):
        build_cognitive_owner_resolution(historical_binding=_binding())


def test_absence_status_cannot_override_present_current_binding() -> None:
    binding = _binding()

    with pytest.raises(
        ValueError,
        match="absence_status is invalid when current binding is present",
    ):
        build_cognitive_owner_resolution(
            historical_binding=binding,
            current_binding=binding,
            absence_status=CognitiveOwnerResolutionStatus.MISSING,
        )


def test_current_binding_owner_kind_must_match_historical_owner() -> None:
    historical = _binding()
    current = _binding(
        owner_kind=CognitiveOwnerKind.WORKING_SESSION,
        source_ref="session://current",
    )

    with pytest.raises(
        ValueError,
        match="current owner binding kind must match historical owner kind",
    ):
        build_cognitive_owner_resolution(
            historical_binding=historical,
            current_binding=current,
        )


def test_resolution_contract_rejects_tampered_snapshot_status() -> None:
    historical = _binding()
    current = _binding(digest_seed="identity-v2")

    with pytest.raises(
        ValidationError,
        match="cognitive owner resolution comparison mismatch",
    ):
        CognitiveOwnerResolution(
            historical_binding=historical,
            current_binding=current,
            status=CognitiveOwnerResolutionStatus.MATCHED,
            reason_code=CognitiveOwnerResolutionReason.SNAPSHOT_MATCH,
        )


def test_resolution_contract_cannot_copy_owner_payload_or_grant_authority() -> None:
    fields = set(CognitiveOwnerResolution.model_fields)

    assert "content" not in fields
    assert "statement" not in fields
    assert "payload" not in fields
    assert "evidence" not in fields
    assert "claims" not in fields

    binding = _binding()
    payload = build_cognitive_owner_resolution(
        historical_binding=binding,
        current_binding=binding,
    ).model_dump(mode="python")
    payload["runtime_authority"] = True

    with pytest.raises(ValidationError):
        CognitiveOwnerResolution.model_validate(payload)


def test_owner_resolution_is_deterministic_for_same_bindings() -> None:
    historical = _binding()
    current = _binding(digest_seed="identity-v2")

    first = build_cognitive_owner_resolution(
        historical_binding=historical,
        current_binding=current,
    )
    second = build_cognitive_owner_resolution(
        historical_binding=historical,
        current_binding=current,
    )

    assert first == second
