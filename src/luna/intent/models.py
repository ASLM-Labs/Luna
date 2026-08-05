"""Intent-resolution models for Luna Phase 2."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


class IntentKind(StrEnum):
    """High-level, model-independent request category."""

    CONVERSATION = "CONVERSATION"
    QUESTION = "QUESTION"
    CODE_CHANGE = "CODE_CHANGE"
    CODE_INSPECTION = "CODE_INSPECTION"
    FILE_OPERATION = "FILE_OPERATION"
    RESEARCH = "RESEARCH"
    UNKNOWN = "UNKNOWN"


class RequestedAction(StrEnum):
    """Normalized actions explicitly or strongly requested by the user."""

    INSPECT = "INSPECT"
    MODIFY = "MODIFY"
    CREATE = "CREATE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"
    RESEARCH = "RESEARCH"
    EXPLAIN = "EXPLAIN"
    UNKNOWN = "UNKNOWN"


class IntentResolution(LunaContractModel):
    """Structured interpretation of one user request."""

    resolution_id: UUID = Field(default_factory=uuid4)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_request: str = Field(min_length=1, max_length=16000)
    normalized_request: str = Field(min_length=1, max_length=16000)
    kind: IntentKind
    objective: str = Field(min_length=1, max_length=4000)
    actions: tuple[RequestedAction, ...] = ()
    referenced_resources: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    risk_signals: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    requires_clarification: bool = False
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("referenced_resources", "unknowns", "risk_signals")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("intent entries must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("intent entries must be unique")
        return cleaned

    @field_validator("actions")
    @classmethod
    def validate_unique_actions(
        cls,
        values: tuple[RequestedAction, ...],
    ) -> tuple[RequestedAction, ...]:
        if len(values) != len(set(values)):
            raise ValueError("requested actions must be unique")
        return values

    @model_validator(mode="after")
    def validate_fingerprint_and_clarification(self) -> IntentResolution:
        expected = sha256(self.normalized_request.encode("utf-8")).hexdigest()
        if self.request_fingerprint != expected:
            raise ValueError("request_fingerprint does not match normalized_request")
        if self.requires_clarification and not self.unknowns:
            raise ValueError("clarification requires at least one explicit unknown")
        return self

    def semantic_signature(self) -> tuple[object, ...]:
        """Return stable semantic fields for deterministic regression tests."""
        return (
            self.request_fingerprint,
            self.normalized_request,
            self.kind,
            self.objective,
            self.actions,
            self.referenced_resources,
            self.unknowns,
            self.risk_signals,
            self.confidence,
            self.requires_clarification,
        )
