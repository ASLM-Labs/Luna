"""Verified request-source and actor contracts for the runtime boundary."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


class RequestSource(StrEnum):
    """Authenticated entry point that supplied a runtime request."""

    DESKTOP = "DESKTOP"
    WEB_UI = "WEB_UI"
    VOICE = "VOICE"
    DISCORD = "DISCORD"
    SCHEDULER = "SCHEDULER"
    INTERNAL_RESEARCH = "INTERNAL_RESEARCH"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    TEST = "TEST"


class ActorRole(StrEnum):
    """Runtime role established outside model output."""

    OWNER = "OWNER"
    TRUSTED_TEAM = "TRUSTED_TEAM"
    COMMUNITY = "COMMUNITY"
    GUEST = "GUEST"
    SYSTEM = "SYSTEM"


class ActorVerificationSource(StrEnum):
    """Authority that established the actor role."""

    LOCAL_SESSION = "LOCAL_SESSION"
    GATEWAY_ROLE = "GATEWAY_ROLE"
    RUNTIME_POLICY = "RUNTIME_POLICY"
    TEST_FIXTURE = "TEST_FIXTURE"
    UNVERIFIED = "UNVERIFIED"


class RuntimeActor(LunaContractModel):
    """Identity/role context trusted by runtime policy, never inferred by a model."""

    actor_id: str = Field(min_length=1, max_length=300)
    role: ActorRole
    verified: bool = False
    verification_source: ActorVerificationSource = ActorVerificationSource.UNVERIFIED
    verified_at: datetime | None = None
    display_name: str | None = Field(default=None, max_length=200)

    @field_validator("verified_at")
    @classmethod
    def validate_verified_at(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("display_name cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_authority_source(self) -> RuntimeActor:
        privileged = self.role in {
            ActorRole.OWNER,
            ActorRole.TRUSTED_TEAM,
            ActorRole.SYSTEM,
        }
        if privileged and not self.verified:
            raise ValueError("privileged actor roles require runtime verification")
        if self.verified:
            if self.verification_source is ActorVerificationSource.UNVERIFIED:
                raise ValueError("verified actor requires a verification source")
            if self.verified_at is None:
                raise ValueError("verified actor requires verified_at")
        elif any(
            (
                self.verification_source is not ActorVerificationSource.UNVERIFIED,
                self.verified_at is not None,
            )
        ):
            raise ValueError("unverified actor cannot carry verification metadata")
        return self

    @classmethod
    def verified_owner(cls, actor_id: str, *, display_name: str | None = None) -> RuntimeActor:
        """Create the local owner identity from a runtime-owned session."""
        return cls(
            actor_id=actor_id,
            role=ActorRole.OWNER,
            verified=True,
            verification_source=ActorVerificationSource.LOCAL_SESSION,
            verified_at=utc_now(),
            display_name=display_name,
        )
