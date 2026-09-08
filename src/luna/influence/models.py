"""Authority-negative influence provenance contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel


class InfluenceSourceClass(StrEnum):
    """Host-assigned class for one decision-driving influence source."""

    HOST_ADMITTED = "HOST_ADMITTED"
    USER_DIRECT = "USER_DIRECT"
    EXTERNAL_UNTRUSTED = "EXTERNAL_UNTRUSTED"
    UNKNOWN = "UNKNOWN"


class InfluenceTrustState(StrEnum):
    """Derived binary taint state; never an authority or factual-truth label."""

    UNTAINTED = "UNTAINTED"
    TAINTED = "TAINTED"


class InfluenceContribution(LunaContractModel):
    """One explicit provenance contributor to a derived influence."""

    source_ref: str = Field(min_length=1, max_length=4000)
    source_class: InfluenceSourceClass

    @field_validator("source_ref")
    @classmethod
    def validate_source_ref(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("influence source_ref cannot be blank")
        return cleaned


def derive_influence_state(
    contributions: tuple[InfluenceContribution, ...],
) -> InfluenceTrustState:
    """Derive sticky taint without inventing a global source-authority ranking."""
    tainted_classes = {
        InfluenceSourceClass.EXTERNAL_UNTRUSTED,
        InfluenceSourceClass.UNKNOWN,
    }
    if any(item.source_class in tainted_classes for item in contributions):
        return InfluenceTrustState.TAINTED
    return InfluenceTrustState.UNTAINTED


class InfluenceTrust(LunaContractModel):
    """Canonical influence provenance whose taint cannot grant authority."""

    contributions: tuple[InfluenceContribution, ...] = Field(
        min_length=1,
        max_length=128,
    )
    state: InfluenceTrustState
    authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def validate_canonical_state(self) -> InfluenceTrust:
        refs = tuple(item.source_ref for item in self.contributions)
        if len(refs) != len(set(refs)):
            raise ValueError("influence contribution source_refs must be unique")
        canonical = tuple(sorted(self.contributions, key=lambda item: item.source_ref))
        if self.contributions != canonical:
            raise ValueError("influence contributions must be canonical-sorted by source_ref")
        expected = derive_influence_state(self.contributions)
        if self.state is not expected:
            raise ValueError("influence trust state must match contributor taint")
        return self
