"""Authority-bounded semantic claim bindings for cognitive rehydration."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from luna.context import (
    ContextAuthorityRole,
    ContextClaim,
    ContextSourceKind,
)
from luna.continuity.cognitive import (
    CognitiveOwnerKind,
    CognitiveOwnerResolution,
)
from luna.contracts.base import LunaContractModel


class CognitiveSemanticClaimBinding(LunaContractModel):
    """Bind one explicit semantic claim to one current owner resolution."""

    owner_resolution: CognitiveOwnerResolution
    claim: ContextClaim

    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_owner_boundary(self) -> Self:
        current = self.owner_resolution.current_binding
        if current is None:
            raise ValueError(
                "semantic claim binding requires an available current owner"
            )

        if current.owner_kind is CognitiveOwnerKind.VERIFIED_MEMORY:
            if self.claim.authority_role is not ContextAuthorityRole.VERIFIED_MEMORY:
                raise ValueError(
                    "verified-memory semantic claim requires VERIFIED_MEMORY authority"
                )
            if not self.claim.verified:
                raise ValueError(
                    "verified-memory semantic claim must be explicitly verified"
                )
            if self.claim.source_ref != current.source_ref:
                raise ValueError(
                    "verified-memory semantic claim must use exact owner source ref"
                )
            return self

        if current.owner_kind is CognitiveOwnerKind.WORKING_SESSION:
            if self.claim.authority_role is not ContextAuthorityRole.CONVERSATION:
                raise ValueError(
                    "working-session semantic claim requires CONVERSATION authority"
                )
            if self.claim.source_kind is not ContextSourceKind.DOCUMENT:
                raise ValueError(
                    "working-session semantic claim requires DOCUMENT source kind"
                )
            if self.claim.verified:
                raise ValueError(
                    "working-session semantic claim cannot self-declare verified"
                )
            entry_prefix = current.source_ref.rstrip("/") + "/entry/"
            if not self.claim.source_ref.startswith(entry_prefix):
                raise ValueError(
                    "working-session semantic claim must use a session entry source ref"
                )
            return self

        raise ValueError(
            "owner kind does not support direct semantic claims in CCF v0.1"
        )


def bind_cognitive_semantic_claim(
    *,
    owner_resolution: CognitiveOwnerResolution,
    claim: ContextClaim,
) -> CognitiveSemanticClaimBinding:
    """Bind an explicit claim to the exact current snapshot without interpreting it."""

    return CognitiveSemanticClaimBinding(
        owner_resolution=owner_resolution,
        claim=claim,
    )
