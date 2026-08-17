"""Verified-memory adapter for cognitive owner binding and snapshot resolution."""

from __future__ import annotations

from luna.continuity.cognitive import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolution,
    CognitiveOwnerResolutionStatus,
    build_cognitive_owner_resolution,
)
from luna.continuity.models import model_digest
from luna.memory.models import MemoryRecord

_MEMORY_SOURCE_PREFIX = "memory://record/"


def build_memory_owner_binding(record: MemoryRecord) -> CognitiveOwnerBinding:
    """Bind one canonical memory record without copying its payload."""

    return CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
        source_ref=f"{_MEMORY_SOURCE_PREFIX}{record.memory_id}",
        content_sha256=model_digest(record),
    )


def resolve_memory_owner_binding(
    *,
    historical_binding: CognitiveOwnerBinding,
    current_record: MemoryRecord | None,
    current_unavailable: bool = False,
) -> CognitiveOwnerResolution:
    """Compare one historical memory binding with its exact current owner record."""

    if historical_binding.owner_kind is not CognitiveOwnerKind.VERIFIED_MEMORY:
        raise ValueError("historical binding is not a verified-memory binding")

    if current_record is None:
        absence_status = (
            CognitiveOwnerResolutionStatus.UNAVAILABLE
            if current_unavailable
            else CognitiveOwnerResolutionStatus.MISSING
        )
        return build_cognitive_owner_resolution(
            historical_binding=historical_binding,
            absence_status=absence_status,
        )

    if current_unavailable:
        raise ValueError("available memory record cannot also be marked unavailable")

    current_binding = build_memory_owner_binding(current_record)
    if current_binding.source_ref != historical_binding.source_ref:
        raise ValueError(
            "current memory record does not match historical memory identity"
        )

    return build_cognitive_owner_resolution(
        historical_binding=historical_binding,
        current_binding=current_binding,
    )
