from __future__ import annotations

from uuid import uuid4

import pytest

from luna.continuity import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolutionReason,
    CognitiveOwnerResolutionStatus,
    build_identity_owner_binding,
    resolve_identity_owner_binding,
)
from luna.continuity.models import model_digest
from luna.identity import IdentityProfile, UserProfile


def test_identity_binding_uses_existing_profile_identity_and_digest() -> None:
    identity = IdentityProfile(profile_id=uuid4(), profile_revision=7)

    binding = build_identity_owner_binding(identity)

    assert binding.owner_kind is CognitiveOwnerKind.IDENTITY_PROFILE
    assert binding.source_ref == f"identity://luna/profile/{identity.profile_id}"
    assert binding.content_sha256 == model_digest(identity)
    assert binding.runtime_authority is False
    assert binding.execution_authority is False
    assert binding.completion_authority is False


def test_same_identity_instance_builds_same_binding() -> None:
    identity = IdentityProfile(profile_id=uuid4(), profile_revision=3)

    first = build_identity_owner_binding(identity)
    second = build_identity_owner_binding(identity)

    assert second == first


def test_identity_revision_change_preserves_source_ref_but_changes_digest() -> None:
    identity = IdentityProfile(profile_id=uuid4(), profile_revision=2)
    revised = identity.model_copy(update={"profile_revision": 3})

    first = build_identity_owner_binding(identity)
    second = build_identity_owner_binding(revised)

    assert second.source_ref == first.source_ref
    assert second.content_sha256 != first.content_sha256


def test_identity_resolution_matches_exact_supplied_profile() -> None:
    identity = IdentityProfile(profile_id=uuid4(), profile_revision=4)
    historical = build_identity_owner_binding(identity)

    resolution = resolve_identity_owner_binding(
        historical_binding=historical,
        current_identity=identity,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.MATCHED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.SNAPSHOT_MATCH


def test_identity_revision_change_requires_semantic_reconciliation_only() -> None:
    identity = IdentityProfile(profile_id=uuid4(), profile_revision=4)
    historical = build_identity_owner_binding(identity)
    revised = identity.model_copy(update={"profile_revision": 5})

    resolution = resolve_identity_owner_binding(
        historical_binding=historical,
        current_identity=revised,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.CONTENT_CHANGED
    assert resolution.requires_semantic_reconciliation is True


def test_new_identity_profile_id_changes_source_and_content() -> None:
    historical_identity = IdentityProfile(profile_id=uuid4(), profile_revision=1)
    current_identity = historical_identity.model_copy(update={"profile_id": uuid4()})

    resolution = resolve_identity_owner_binding(
        historical_binding=build_identity_owner_binding(historical_identity),
        current_identity=current_identity,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert (
        resolution.reason_code
        is CognitiveOwnerResolutionReason.SOURCE_AND_CONTENT_CHANGED
    )


def test_identity_user_profile_change_is_content_change_on_same_owner() -> None:
    identity = IdentityProfile(profile_id=uuid4(), profile_revision=1)
    historical = build_identity_owner_binding(identity)
    current = identity.model_copy(
        update={
            "profile_revision": 2,
            "user_profile": UserProfile(
                user_id="owner",
                preferred_address="Murat",
            ),
        }
    )

    resolution = resolve_identity_owner_binding(
        historical_binding=historical,
        current_identity=current,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.CONTENT_CHANGED


def test_identity_adapter_rejects_non_identity_historical_binding() -> None:
    identity = IdentityProfile(profile_id=uuid4())
    historical = CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
        source_ref="memory://record/1",
        content_sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="not an identity-profile binding"):
        resolve_identity_owner_binding(
            historical_binding=historical,
            current_identity=identity,
        )
