"""Verified-memory contracts with provenance, scope, expiry, and supersession."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now

_SECRET_PLACEHOLDER = "[SECRET_REFERENCE]"
_ALLOWED_SECRET_PREFIXES = ("secret://", "keyring://", "vault://")


class MemoryType(StrEnum):
    """Supported Phase 9 memory categories."""

    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    PROJECT_DECISION = "PROJECT_DECISION"
    RESEARCH_FACT = "RESEARCH_FACT"
    SUMMARY = "SUMMARY"
    SECRET_REFERENCE = "SECRET_REFERENCE"


class MemoryScope(StrEnum):
    """Hard retrieval boundaries preventing cross-domain leakage."""

    PRIVATE_USER = "PRIVATE_USER"
    PROJECT = "PROJECT"
    REPOSITORY = "REPOSITORY"
    RESEARCH = "RESEARCH"
    COMMUNITY = "COMMUNITY"
    BEHAVIOR = "BEHAVIOR"


class MemorySourceKind(StrEnum):
    """Origin class retained with every candidate and committed record."""

    USER_STATEMENT = "USER_STATEMENT"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    VERIFIED_OBSERVATION = "VERIFIED_OBSERVATION"
    DOCUMENT = "DOCUMENT"
    TOOL_RESULT = "TOOL_RESULT"
    MODEL_INFERENCE = "MODEL_INFERENCE"
    SECRET_REFERENCE = "SECRET_REFERENCE"


class MemorySensitivity(StrEnum):
    """Storage sensitivity attached to a memory record."""

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    SECRET = "SECRET"


class MemoryRecordStatus(StrEnum):
    """Lifecycle states visible to deterministic retrieval."""

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class MemoryDecisionStatus(StrEnum):
    """Policy result for one memory candidate."""

    COMMIT = "COMMIT"
    REJECT = "REJECT"


class MemoryRejectionCode(StrEnum):
    """Stable rejection reasons suitable for tests and audit."""

    MODEL_INFERENCE_UNVERIFIED = "MODEL_INFERENCE_UNVERIFIED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    ONE_OFF_PREFERENCE = "ONE_OFF_PREFERENCE"
    PLAINTEXT_SECRET = "PLAINTEXT_SECRET"
    INVALID_SECRET_REFERENCE = "INVALID_SECRET_REFERENCE"
    EXPIRY_REQUIRED = "EXPIRY_REQUIRED"
    SUPERSEDE_TARGET_INVALID = "SUPERSEDE_TARGET_INVALID"


class MemoryCandidate(LunaContractModel):
    """Uncommitted memory proposal awaiting policy and verification."""

    candidate_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    memory_type: MemoryType
    statement: str = Field(min_length=1, max_length=8000)
    source_kind: MemorySourceKind
    source_ref: str = Field(min_length=1, max_length=4000)
    observed_at: datetime = Field(default_factory=utc_now)
    confidence: float = Field(ge=0.0, le=1.0)
    scope: MemoryScope
    sensitivity: MemorySensitivity = MemorySensitivity.PRIVATE
    expires_at: datetime | None = None
    supersedes: UUID | None = None
    occurrence_count: int = Field(default=1, ge=1, le=10_000)
    explicit_persistence: bool = False
    secret_ref: str | None = Field(default=None, min_length=1, max_length=4000)

    @field_validator("observed_at", "expires_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value)

    @model_validator(mode="after")
    def validate_coherence(self) -> MemoryCandidate:
        if self.expires_at is not None and self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be later than observed_at")
        if self.memory_type is MemoryType.SECRET_REFERENCE:
            if self.sensitivity is not MemorySensitivity.SECRET:
                raise ValueError("SECRET_REFERENCE memory requires SECRET sensitivity")
            if self.secret_ref is None:
                raise ValueError("SECRET_REFERENCE memory requires secret_ref")
        if self.sensitivity is MemorySensitivity.SECRET and self.secret_ref is None:
            raise ValueError("SECRET sensitivity requires secret_ref")
        if self.secret_ref is not None and self.sensitivity is not MemorySensitivity.SECRET:
            raise ValueError("secret_ref is only valid for SECRET sensitivity")
        return self


class MemoryRecord(LunaContractModel):
    """Committed, source-preserving verified memory record."""

    memory_id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    task_id: UUID
    memory_type: MemoryType
    statement: str = Field(min_length=1, max_length=8000)
    source_kind: MemorySourceKind
    source_ref: str = Field(min_length=1, max_length=4000)
    observed_at: datetime
    created_at: datetime = Field(default_factory=utc_now)
    last_verified_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    scope: MemoryScope
    sensitivity: MemorySensitivity
    expires_at: datetime | None = None
    supersedes: UUID | None = None
    superseded_by: UUID | None = None
    secret_ref: str | None = Field(default=None, min_length=1, max_length=4000)
    status: MemoryRecordStatus = MemoryRecordStatus.ACTIVE

    @field_validator("observed_at", "created_at", "last_verified_at", "expires_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value)

    @model_validator(mode="after")
    def validate_coherence(self) -> MemoryRecord:
        if self.last_verified_at < self.observed_at:
            raise ValueError("last_verified_at cannot precede observed_at")
        if self.last_verified_at < self.created_at:
            raise ValueError("last_verified_at cannot precede created_at")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if self.status is MemoryRecordStatus.SUPERSEDED and self.superseded_by is None:
            raise ValueError("SUPERSEDED memory requires superseded_by")
        if self.status is not MemoryRecordStatus.SUPERSEDED and self.superseded_by is not None:
            raise ValueError("superseded_by is only valid for SUPERSEDED memory")
        if self.sensitivity is MemorySensitivity.SECRET:
            if self.memory_type is not MemoryType.SECRET_REFERENCE:
                raise ValueError("SECRET memory must use SECRET_REFERENCE type")
            if self.statement != _SECRET_PLACEHOLDER:
                raise ValueError("SECRET memory cannot contain plaintext statement")
            if self.secret_ref is None:
                raise ValueError("SECRET memory requires secret_ref")
            normalized_ref = self.secret_ref.casefold()
            if not normalized_ref.startswith(_ALLOWED_SECRET_PREFIXES):
                raise ValueError("SECRET memory requires an approved secret reference")
            if any(character.isspace() for character in self.secret_ref) or "=" in self.secret_ref:
                raise ValueError("secret reference must be opaque")
        elif self.secret_ref is not None:
            raise ValueError("non-secret memory cannot contain secret_ref")
        return self


class MemoryPolicy(LunaContractModel):
    """Deterministic acceptance policy for memory candidates."""

    minimum_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    minimum_preference_occurrences: int = Field(default=2, ge=2, le=100)
    require_expiry_for: tuple[MemoryType, ...] = (MemoryType.RESEARCH_FACT,)
    allowed_secret_schemes: tuple[str, ...] = (
        "secret://",
        "keyring://",
        "vault://",
    )

    @field_validator("allowed_secret_schemes")
    @classmethod
    def validate_secret_schemes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip().casefold() for value in values)
        if any(not value.endswith("://") for value in cleaned):
            raise ValueError("secret schemes must end with ://")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("secret schemes must be unique")
        return cleaned


class MemoryPolicyDecision(LunaContractModel):
    """Transparent policy result before database mutation."""

    candidate_id: UUID
    status: MemoryDecisionStatus
    rejection_codes: tuple[MemoryRejectionCode, ...] = ()
    reasons: tuple[str, ...] = ()
    sanitized_statement: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def validate_decision(self) -> MemoryPolicyDecision:
        if self.status is MemoryDecisionStatus.COMMIT:
            if self.rejection_codes or self.reasons:
                raise ValueError("COMMIT decision cannot carry rejection reasons")
            if self.sanitized_statement is None:
                raise ValueError("COMMIT decision requires sanitized_statement")
        else:
            if not self.rejection_codes or not self.reasons:
                raise ValueError("REJECT decision requires code and reason")
            if len(self.rejection_codes) != len(set(self.rejection_codes)):
                raise ValueError("rejection codes must be unique")
        return self


class MemoryCommitDecision(LunaContractModel):
    """Final candidate outcome after policy and store validation."""

    candidate_id: UUID
    status: MemoryDecisionStatus
    rejection_codes: tuple[MemoryRejectionCode, ...] = ()
    reasons: tuple[str, ...] = ()
    record: MemoryRecord | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> MemoryCommitDecision:
        if self.status is MemoryDecisionStatus.COMMIT:
            if self.record is None:
                raise ValueError("COMMIT requires a memory record")
            if self.rejection_codes or self.reasons:
                raise ValueError("COMMIT cannot carry rejection details")
        else:
            if self.record is not None:
                raise ValueError("REJECT cannot carry a memory record")
            if not self.rejection_codes or not self.reasons:
                raise ValueError("REJECT requires rejection details")
        return self


class MemoryQuery(LunaContractModel):
    """Scope-bound deterministic memory retrieval request."""

    scope: MemoryScope
    memory_types: tuple[MemoryType, ...] = ()
    terms: tuple[str, ...] = ()
    minimum_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("memory_types")
    @classmethod
    def validate_types(cls, values: tuple[MemoryType, ...]) -> tuple[MemoryType, ...]:
        if len(values) != len(set(values)):
            raise ValueError("memory_types must be unique")
        return values

    @field_validator("terms")
    @classmethod
    def validate_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("query terms must not be empty")
        normalized = tuple(value.casefold() for value in cleaned)
        if len(normalized) != len(set(normalized)):
            raise ValueError("query terms must be unique")
        return cleaned


class MemoryRetrieval(LunaContractModel):
    """Records returned after scope, status, expiry, and confidence filtering."""

    query: MemoryQuery
    records: tuple[MemoryRecord, ...]
    excluded_count: int = Field(ge=0)
    retrieved_at: datetime = Field(default_factory=utc_now)

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_scope(self) -> MemoryRetrieval:
        if len(self.records) > self.query.limit:
            raise ValueError("retrieval exceeds query limit")
        if any(record.scope is not self.query.scope for record in self.records):
            raise ValueError("retrieval contains a cross-scope record")
        if any(record.status is not MemoryRecordStatus.ACTIVE for record in self.records):
            raise ValueError("retrieval contains inactive memory")
        return self


class MemoryIntegrity(LunaContractModel):
    """Result of validating persisted memory payloads and links."""

    valid: bool
    record_count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    first_error: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_result(self) -> MemoryIntegrity:
        if self.valid and self.first_error is not None:
            raise ValueError("valid integrity result cannot carry an error")
        if not self.valid and self.first_error is None:
            raise ValueError("invalid integrity result requires an error")
        return self


def canonical_model_json(model: LunaContractModel) -> str:
    """Return deterministic JSON for SQLite payload hashing."""
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def model_digest(model: LunaContractModel) -> str:
    """Return SHA-256 digest of a canonical model payload."""
    return sha256(canonical_model_json(model).encode("utf-8")).hexdigest()


SECRET_PLACEHOLDER = _SECRET_PLACEHOLDER
