"""IdentityProfile adapter for cognitive owner binding and snapshot resolution."""

from __future__ import annotations

from luna.continuity.cognitive import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolution,
    build_cognitive_owner_resolution,
)
from luna.continuity.models import model_digest
from luna.identity.models import IdentityProfile


def build_identity_owner_binding(identity: IdentityProfile) -> CognitiveOwnerBinding:
    """Bind one caller-supplied canonical identity without copying its payload."""

    return CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.IDENTITY_PROFILE,
        source_ref=f"identity://luna/profile/{identity.profile_id}",
        content_sha256=model_digest(identity),
    )


def resolve_identity_owner_binding(
    *,
    historical_binding: CognitiveOwnerBinding,
    current_identity: IdentityProfile,
) -> CognitiveOwnerResolution:
    """Compare one historical binding with the supplied current identity."""

    if historical_binding.owner_kind is not CognitiveOwnerKind.IDENTITY_PROFILE:
        raise ValueError("historical binding is not an identity-profile binding")

    current_binding = build_identity_owner_binding(current_identity)
    return build_cognitive_owner_resolution(
        historical_binding=historical_binding,
        current_binding=current_binding,
    )
