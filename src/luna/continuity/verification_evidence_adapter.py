"""Verification-evidence adapter for cognitive owner snapshot resolution."""

from __future__ import annotations

import json
from collections.abc import Iterable
from hashlib import sha256
from uuid import UUID

from luna.continuity.cognitive import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolution,
    CognitiveOwnerResolutionStatus,
    build_cognitive_owner_resolution,
)
from luna.continuity.models import model_digest
from luna.contracts.evidence import Evidence

_VERIFICATION_EVIDENCE_DIGEST_VERSION = 1


def _canonical_evidence(
    *,
    task_id: UUID,
    evidence: Iterable[Evidence],
) -> tuple[Evidence, ...]:
    evidence_tuple = tuple(evidence)
    if any(item.task_id != task_id for item in evidence_tuple):
        raise ValueError("verification evidence owner records must belong to the task")

    evidence_ids = tuple(item.evidence_id for item in evidence_tuple)
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError(
            "verification evidence owner records must have unique evidence IDs"
        )

    return tuple(sorted(evidence_tuple, key=lambda item: str(item.evidence_id)))


def _verification_evidence_owner_digest(
    *,
    task_id: UUID,
    evidence: Iterable[Evidence],
) -> str:
    ordered = _canonical_evidence(task_id=task_id, evidence=evidence)
    payload = {
        "semantics_version": _VERIFICATION_EVIDENCE_DIGEST_VERSION,
        "task_id": str(task_id),
        "evidence": [
            {
                "evidence_id": str(item.evidence_id),
                "content_sha256": model_digest(item),
            }
            for item in ordered
        ],
    }
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(rendered.encode("utf-8")).hexdigest()


def build_verification_evidence_owner_binding(
    *,
    task_id: UUID,
    evidence: Iterable[Evidence],
) -> CognitiveOwnerBinding:
    """Bind the full immutable evidence set currently recorded for one task."""

    return CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.VERIFICATION_EVIDENCE,
        source_ref=f"verification://task/{task_id}/evidence",
        content_sha256=_verification_evidence_owner_digest(
            task_id=task_id,
            evidence=evidence,
        ),
    )


def resolve_verification_evidence_owner_binding(
    *,
    historical_binding: CognitiveOwnerBinding,
    task_id: UUID,
    current_evidence: Iterable[Evidence] | None,
    current_unavailable: bool = False,
) -> CognitiveOwnerResolution:
    """Compare one historical task evidence-set binding with current durable state."""

    if historical_binding.owner_kind is not CognitiveOwnerKind.VERIFICATION_EVIDENCE:
        raise ValueError("historical binding is not a verification-evidence binding")

    if current_evidence is None:
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
        raise ValueError(
            "available verification evidence cannot also be marked unavailable"
        )

    current_binding = build_verification_evidence_owner_binding(
        task_id=task_id,
        evidence=current_evidence,
    )
    if current_binding.source_ref != historical_binding.source_ref:
        raise ValueError(
            "current verification evidence does not match historical task identity"
        )

    return build_cognitive_owner_resolution(
        historical_binding=historical_binding,
        current_binding=current_binding,
    )
