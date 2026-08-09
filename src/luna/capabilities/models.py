"""Capability-lineage contracts for Luna C-002."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel


class CapabilityStatus(StrEnum):
    """Repository-evidence state for a capability."""

    CONCEPT = "CONCEPT"
    QUEUED = "QUEUED"
    DESIGNED = "DESIGNED"
    IMPLEMENTING = "IMPLEMENTING"
    IMPLEMENTED_UNVERIFIED = "IMPLEMENTED_UNVERIFIED"
    VERIFIED = "VERIFIED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"


class EvidenceFreshness(StrEnum):
    """Freshness of evidence relative to the declared source revision."""

    MISSING = "MISSING"
    PARTIAL = "PARTIAL"
    CURRENT = "CURRENT"
    STALE = "STALE"


class DependencyKind(StrEnum):
    """Capability-to-capability dependency strength."""

    HARD = "HARD"
    PREFERRED = "PREFERRED"


class CapabilityRecord(LunaContractModel):
    """Canonical, non-authoritative lineage record for one Luna capability."""

    capability_id: str = Field(pattern=r"^C-[0-9]{3}$")
    name: str = Field(min_length=1, max_length=200)
    status: CapabilityStatus
    scope: str = Field(min_length=1, max_length=1000)
    hard_prerequisites: tuple[str, ...] = ()
    preferred_prerequisites: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = Field(min_length=1)
    foundation_refs: tuple[str, ...] = ()
    implementation_components: tuple[str, ...] = ()
    verifier_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    authority_boundary: str = Field(min_length=1, max_length=1000)
    rollback_or_disable_path: str = Field(min_length=1, max_length=1000)
    source_revision: str = Field(min_length=1, max_length=200)
    evidence_revision: str | None = Field(default=None, min_length=1, max_length=200)
    evidence_freshness: EvidenceFreshness = EvidenceFreshness.MISSING

    @field_validator(
        "hard_prerequisites",
        "preferred_prerequisites",
        "source_refs",
        "foundation_refs",
        "implementation_components",
        "verifier_refs",
        "evidence_refs",
        "metrics",
    )
    @classmethod
    def validate_unique_nonblank(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("capability lineage references cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("capability lineage references must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_evidence_state(self) -> Self:
        hard = set(self.hard_prerequisites)
        preferred = set(self.preferred_prerequisites)
        if self.capability_id in hard | preferred:
            raise ValueError("capability cannot depend on itself")
        if hard & preferred:
            raise ValueError("capability dependency cannot be both hard and preferred")

        implemented = self.status in {
            CapabilityStatus.IMPLEMENTED_UNVERIFIED,
            CapabilityStatus.VERIFIED,
        }
        if implemented and not self.implementation_components:
            raise ValueError("implemented capability requires implementation components")
        if implemented and not self.verifier_refs:
            raise ValueError("implemented capability requires verifier references")
        if implemented and not self.evidence_refs:
            raise ValueError("implemented capability requires evidence references")
        if implemented and self.evidence_revision is None:
            raise ValueError("implemented capability requires evidence revision")
        if (
            self.status is CapabilityStatus.VERIFIED
            and self.evidence_freshness is not EvidenceFreshness.CURRENT
        ):
            raise ValueError("VERIFIED capability requires CURRENT evidence")
        if (
            self.evidence_freshness is EvidenceFreshness.MISSING
            and self.evidence_revision is not None
        ):
            raise ValueError("missing evidence cannot declare an evidence revision")
        if (
            self.evidence_freshness is not EvidenceFreshness.MISSING
            and self.evidence_revision is None
        ):
            raise ValueError("non-missing evidence requires an evidence revision")
        return self


class CapabilityImpact(LunaContractModel):
    """Deterministic dependency/blast-radius query result."""

    capability_id: str = Field(pattern=r"^C-[0-9]{3}$")
    direct_dependents: tuple[str, ...] = ()
    indirect_dependents: tuple[str, ...] = ()
    dependency_paths: tuple[tuple[str, ...], ...] = ()
    includes_preferred_edges: bool
