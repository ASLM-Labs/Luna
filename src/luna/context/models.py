"""Context source, budget and bundle models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now

type JsonScalar = str | int | float | bool | None


class ContextSourceKind(StrEnum):
    """Origin category for a context source."""

    USER_MESSAGE = "USER_MESSAGE"
    FILE = "FILE"
    DIRECTORY_LISTING = "DIRECTORY_LISTING"
    COMMAND_OUTPUT = "COMMAND_OUTPUT"
    DOCUMENT = "DOCUMENT"
    MEMORY = "MEMORY"
    PROJECT_STATE = "PROJECT_STATE"


class ContextAvailability(StrEnum):
    """Whether source content has actually been observed."""

    OBSERVED = "OBSERVED"
    DECLARED_NOT_OBSERVED = "DECLARED_NOT_OBSERVED"
    MISSING = "MISSING"


class ContextExclusionReason(StrEnum):
    """Why a candidate was not admitted to active context."""

    NOT_OBSERVED = "NOT_OBSERVED"
    MISSING = "MISSING"
    SOURCE_LIMIT = "SOURCE_LIMIT"
    CHARACTER_LIMIT = "CHARACTER_LIMIT"
    TOKEN_LIMIT = "TOKEN_LIMIT"
    DUPLICATE = "DUPLICATE"


class ContextSource(LunaContractModel):
    """One explicit source; unseen content cannot masquerade as observed."""

    source_id: UUID = Field(default_factory=uuid4)
    kind: ContextSourceKind
    locator: str = Field(min_length=1, max_length=4000)
    availability: ContextAvailability
    content_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_excerpt: str | None = Field(default=None, max_length=16000)
    char_count: int = Field(default=0, ge=0)
    token_estimate: int = Field(default=0, ge=0)
    observed_at: datetime | None = None
    verified: bool = False
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_observation_boundary(self) -> ContextSource:
        if self.availability is ContextAvailability.OBSERVED:
            if self.content_digest is None or self.observed_at is None:
                raise ValueError("observed context requires digest and observed_at")
            if self.content_excerpt is not None and len(self.content_excerpt) > self.char_count:
                raise ValueError("content_excerpt cannot exceed char_count")
        else:
            if any(
                (
                    self.content_digest is not None,
                    self.content_excerpt is not None,
                    self.char_count != 0,
                    self.token_estimate != 0,
                    self.observed_at is not None,
                    self.verified,
                )
            ):
                raise ValueError("unobserved context cannot carry observed content fields")
        return self

    @classmethod
    def from_text(
        cls,
        *,
        kind: ContextSourceKind,
        locator: str,
        text: str,
        verified: bool = False,
        excerpt_limit: int = 4000,
        observed_at: datetime | None = None,
        metadata: dict[str, JsonScalar] | None = None,
    ) -> ContextSource:
        """Create an observed source from text already supplied by a caller."""
        encoded = text.encode("utf-8")
        return cls(
            kind=kind,
            locator=locator,
            availability=ContextAvailability.OBSERVED,
            content_digest=sha256(encoded).hexdigest(),
            content_excerpt=text[:excerpt_limit],
            char_count=len(text),
            token_estimate=(len(text) + 3) // 4,
            observed_at=observed_at or utc_now(),
            verified=verified,
            metadata=metadata or {},
        )


class ContextCandidate(LunaContractModel):
    """Prioritized source candidate presented to the collector."""

    source: ContextSource
    priority: int = Field(default=50, ge=0, le=100)
    required: bool = False


class ContextBudget(LunaContractModel):
    """Hard active-context limits."""

    max_sources: int = Field(default=32, ge=1)
    max_chars: int = Field(default=64000, ge=1)
    max_estimated_tokens: int = Field(default=16000, ge=1)


class ContextExclusion(LunaContractModel):
    """Traceable exclusion from active context."""

    locator: str = Field(min_length=1, max_length=4000)
    reason: ContextExclusionReason
    required: bool = False


class ContextBundle(LunaContractModel):
    """Deterministic active context plus explicit gaps and exclusions."""

    bundle_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    sources: tuple[ContextSource, ...] = ()
    missing_sources: tuple[str, ...] = ()
    exclusions: tuple[ContextExclusion, ...] = ()
    budget: ContextBudget
    chars_used: int = Field(ge=0)
    estimated_tokens_used: int = Field(ge=0)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("missing_sources")
    @classmethod
    def validate_missing_sources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("missing source locators must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("missing source locators must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_budget_and_sources(self) -> ContextBundle:
        if any(
            source.availability is not ContextAvailability.OBSERVED
            for source in self.sources
        ):
            raise ValueError("active context can contain only observed sources")
        if len(self.sources) > self.budget.max_sources:
            raise ValueError("active source count exceeds budget")
        if self.chars_used != sum(source.char_count for source in self.sources):
            raise ValueError("chars_used does not match active sources")
        if self.estimated_tokens_used != sum(
            source.token_estimate for source in self.sources
        ):
            raise ValueError("estimated_tokens_used does not match active sources")
        if self.chars_used > self.budget.max_chars:
            raise ValueError("active characters exceed budget")
        if self.estimated_tokens_used > self.budget.max_estimated_tokens:
            raise ValueError("estimated tokens exceed budget")
        locators = tuple(source.locator for source in self.sources)
        if len(locators) != len(set(locators)):
            raise ValueError("active source locators must be unique")
        return self
