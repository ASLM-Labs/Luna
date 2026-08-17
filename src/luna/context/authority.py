"""Claim-type-aware deterministic context authority resolution."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from luna.context.integrity_models import (
    ContextAuthorityRole,
    ContextClaim,
    ContextClaimType,
    ContextRequirement,
    ContextResolution,
    ContextResolutionStatus,
)
from luna.contracts.base import utc_now

_DEFAULT_ORDER = (
    ContextAuthorityRole.CURRENT_OBSERVATION,
    ContextAuthorityRole.CANONICAL_PROJECT,
    ContextAuthorityRole.CURRENT_USER,
    ContextAuthorityRole.VERIFIED_MEMORY,
    ContextAuthorityRole.HANDOFF,
    ContextAuthorityRole.CONVERSATION,
    ContextAuthorityRole.INFERENCE,
)

_AUTHORITY_ORDER: dict[ContextClaimType, tuple[ContextAuthorityRole, ...]] = {
    ContextClaimType.CURRENT_STATE: (
        ContextAuthorityRole.CURRENT_OBSERVATION,
        ContextAuthorityRole.CANONICAL_PROJECT,
        ContextAuthorityRole.VERIFIED_MEMORY,
        ContextAuthorityRole.HANDOFF,
        ContextAuthorityRole.CONVERSATION,
        ContextAuthorityRole.INFERENCE,
        ContextAuthorityRole.CURRENT_USER,
    ),
    ContextClaimType.REPOSITORY_STATE: (
        ContextAuthorityRole.CURRENT_OBSERVATION,
        ContextAuthorityRole.CANONICAL_PROJECT,
        ContextAuthorityRole.VERIFIED_MEMORY,
        ContextAuthorityRole.HANDOFF,
        ContextAuthorityRole.CONVERSATION,
        ContextAuthorityRole.INFERENCE,
        ContextAuthorityRole.CURRENT_USER,
    ),
    ContextClaimType.CONTINUITY_STATE: (
        ContextAuthorityRole.CURRENT_OBSERVATION,
        ContextAuthorityRole.CANONICAL_PROJECT,
        ContextAuthorityRole.VERIFIED_MEMORY,
        ContextAuthorityRole.HANDOFF,
        ContextAuthorityRole.CONVERSATION,
        ContextAuthorityRole.INFERENCE,
        ContextAuthorityRole.CURRENT_USER,
    ),
    ContextClaimType.EXECUTION_STATE: (
        ContextAuthorityRole.CURRENT_OBSERVATION,
        ContextAuthorityRole.CANONICAL_PROJECT,
        ContextAuthorityRole.VERIFIED_MEMORY,
        ContextAuthorityRole.HANDOFF,
        ContextAuthorityRole.CONVERSATION,
        ContextAuthorityRole.INFERENCE,
        ContextAuthorityRole.CURRENT_USER,
    ),
    ContextClaimType.PROJECT_POLICY: (
        ContextAuthorityRole.CANONICAL_PROJECT,
        ContextAuthorityRole.CURRENT_OBSERVATION,
        ContextAuthorityRole.VERIFIED_MEMORY,
        ContextAuthorityRole.HANDOFF,
        ContextAuthorityRole.CONVERSATION,
        ContextAuthorityRole.INFERENCE,
        ContextAuthorityRole.CURRENT_USER,
    ),
    ContextClaimType.USER_INTENT: (
        ContextAuthorityRole.CURRENT_USER,
        ContextAuthorityRole.CONVERSATION,
        ContextAuthorityRole.VERIFIED_MEMORY,
        ContextAuthorityRole.HANDOFF,
        ContextAuthorityRole.INFERENCE,
        ContextAuthorityRole.CURRENT_OBSERVATION,
        ContextAuthorityRole.CANONICAL_PROJECT,
    ),
    ContextClaimType.GENERIC: _DEFAULT_ORDER,
}


class ContextAuthorityResolver:
    """Resolve one required context key without a single global authority ranking."""

    @staticmethod
    def _fresh(
        claim: ContextClaim,
        requirement: ContextRequirement,
        now: datetime,
    ) -> bool:
        if requirement.max_age_seconds is None:
            return True
        age = max(0.0, (now - claim.observed_at).total_seconds())
        return age <= requirement.max_age_seconds

    def resolve(
        self,
        *,
        task_id: UUID,
        requirement: ContextRequirement,
        claims: Iterable[ContextClaim],
        now: datetime | None = None,
    ) -> ContextResolution:
        current_time = now or utc_now()
        candidates = tuple(
            claim
            for claim in claims
            if claim.task_id == task_id
            and claim.key == requirement.key
            and claim.claim_type is requirement.claim_type
        )
        considered = tuple(claim.claim_id for claim in candidates)
        if not candidates:
            return ContextResolution(
                requirement=requirement,
                status=ContextResolutionStatus.UNRESOLVED,
                considered_claim_ids=(),
                reasons=("no matching structured context claim",),
            )

        fresh = tuple(
            claim
            for claim in candidates
            if self._fresh(claim, requirement, current_time)
        )
        if not fresh:
            return ContextResolution(
                requirement=requirement,
                status=ContextResolutionStatus.UNRESOLVED,
                considered_claim_ids=considered,
                reasons=("all matching context claims are stale",),
            )

        eligible = (
            tuple(claim for claim in fresh if claim.verified)
            if requirement.require_verified
            else fresh
        )
        if not eligible:
            return ContextResolution(
                requirement=requirement,
                status=ContextResolutionStatus.UNRESOLVED,
                considered_claim_ids=considered,
                reasons=("no verified matching context claim",),
            )

        order = _AUTHORITY_ORDER[requirement.claim_type]
        rank = {role: index for index, role in enumerate(order)}
        best_role_rank = min(rank.get(claim.authority_role, len(order)) for claim in eligible)
        role_peers = tuple(
            claim
            for claim in eligible
            if rank.get(claim.authority_role, len(order)) == best_role_rank
        )

        best_verified_rank = max(int(claim.verified) for claim in role_peers)
        verified_peers = tuple(
            claim for claim in role_peers if int(claim.verified) == best_verified_rank
        )
        newest = max(claim.observed_at for claim in verified_peers)
        top = tuple(claim for claim in verified_peers if claim.observed_at == newest)
        top_values = {claim.value for claim in top}
        if len(top_values) > 1:
            return ContextResolution(
                requirement=requirement,
                status=ContextResolutionStatus.CONFLICTING,
                considered_claim_ids=considered,
                reasons=(
                    "equal-authority equally-fresh context claims disagree",
                ),
            )

        selected = min(top, key=lambda claim: str(claim.claim_id))
        superseded = tuple(
            claim.claim_id for claim in candidates if claim.claim_id != selected.claim_id
        )
        reasons = [
            (
                f"selected {selected.authority_role.value} authority for "
                f"{requirement.claim_type.value}"
            )
        ]
        if requirement.require_verified:
            reasons.append("requirement accepts verified claims only")
        reasons.append("non-selected claims are superseded by the resolved claim")
        return ContextResolution(
            requirement=requirement,
            status=ContextResolutionStatus.RESOLVED,
            selected_claim_id=selected.claim_id,
            selected_value=selected.value,
            considered_claim_ids=considered,
            superseded_claim_ids=superseded,
            reasons=tuple(reasons),
        )
