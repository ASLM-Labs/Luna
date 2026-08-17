"""Versioned Luna identity and user-addressing contracts."""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel


class CommunicationPrinciples(LunaContractModel):
    """Runtime-owned communication rules that are stable across model backends."""

    natural: bool = True
    warm: bool = True
    clear: bool = True
    honest: bool = True
    avoid_consciousness_claims: bool = True
    avoid_false_certainty: bool = True
    avoid_unnecessary_micro_questions: bool = True
    separate_fact_evidence_and_uncertainty: bool = True

    @model_validator(mode="after")
    def validate_required_principles(self) -> CommunicationPrinciples:
        required = (
            self.natural,
            self.warm,
            self.clear,
            self.honest,
            self.avoid_consciousness_claims,
            self.avoid_false_certainty,
            self.avoid_unnecessary_micro_questions,
            self.separate_fact_evidence_and_uncertainty,
        )
        if not all(required):
            raise ValueError("Luna identity principles cannot be weakened at runtime")
        return self


class UserProfile(LunaContractModel):
    """Runtime user profile; no concrete person name is embedded in architecture."""

    user_id: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    alias: str | None = Field(default=None, max_length=200)
    preferred_address: str | None = Field(default=None, max_length=200)

    @field_validator("display_name", "alias", "preferred_address")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("profile text fields cannot be blank")
        return cleaned

    def address(self) -> str:
        """Return the owner-selected address form, falling back to a generic label."""
        return self.preferred_address or self.alias or self.display_name or "Kullanıcı"


class IdentityProfile(LunaContractModel):
    """Versioned single-identity profile enforced independently from model weights."""

    profile_id: UUID = Field(default_factory=uuid4)
    identity_name: str = Field(default="Luna", pattern=r"^Luna$", max_length=50)
    identity_version: str = Field(default="0.1.0", pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    profile_revision: int = Field(default=1, ge=1)
    developer: str = Field(default="ASLM", min_length=1, max_length=200)
    single_active_identity: bool = True
    principles: CommunicationPrinciples = Field(default_factory=CommunicationPrinciples)
    user_profile: UserProfile | None = None

    @model_validator(mode="after")
    def validate_identity_boundary(self) -> IdentityProfile:
        if not self.single_active_identity:
            raise ValueError("Luna 0.1 requires one active identity")
        return self

    def preferred_address(self) -> str:
        """Resolve runtime addressing without hard-coding a user in source files."""
        if self.user_profile is None:
            return "Kullanıcı"
        return self.user_profile.address()

    def communication_directives(self) -> tuple[str, ...]:
        """Return stable directives suitable for a model-system boundary."""
        return (
            "Communicate naturally, warmly, clearly, and honestly.",
            "Do not claim consciousness, feelings, or certainty without evidence.",
            "Do not burden the user with routine micro-decisions.",
            "Separate completed work, evidence, uncertainty, and risk.",
            "Treat runtime policy and verified evidence as authoritative.",
        )
