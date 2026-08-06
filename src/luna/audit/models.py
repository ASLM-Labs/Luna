"""Tamper-evident audit, redaction, and log-artifact contracts."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

GENESIS_EVENT_HASH = "0" * 64


def canonical_json(value: JsonValue | dict[str, JsonValue]) -> str:
    """Return deterministic UTF-8 JSON used by digest and chain calculations."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class AuditEventKind(StrEnum):
    """Stable event categories written to the append-only audit ledger."""

    TASK_CONTRACT = "TASK_CONTRACT"
    TOOL_REQUEST = "TOOL_REQUEST"
    TOOL_RESULT = "TOOL_RESULT"
    TOOL_EVENT = "TOOL_EVENT"
    OBSERVATION = "OBSERVATION"
    EVIDENCE = "EVIDENCE"
    VERIFICATION_REPORT = "VERIFICATION_REPORT"
    COMPLETION_DECISION = "COMPLETION_DECISION"
    CHECKPOINT_CREATED = "CHECKPOINT_CREATED"
    RESUME_DECISION = "RESUME_DECISION"
    MEMORY_CANDIDATE = "MEMORY_CANDIDATE"
    MEMORY_DECISION = "MEMORY_DECISION"
    MEMORY_COMMITTED = "MEMORY_COMMITTED"
    MEMORY_RETRIEVAL = "MEMORY_RETRIEVAL"
    MEMORY_FORGOTTEN = "MEMORY_FORGOTTEN"
    FINAL_REPORT = "FINAL_REPORT"
    CORRECTION = "CORRECTION"


class RedactionResult(LunaContractModel):
    """Text after sensitive values have been removed."""

    text: str
    redactions_applied: tuple[str, ...] = ()

    @field_validator("redactions_applied")
    @classmethod
    def validate_redactions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("redaction labels must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("redaction labels must be unique")
        return cleaned


class CapturedOutput(LunaContractModel):
    """Redacted full output stored by content digest."""

    stream_name: str = Field(min_length=1, max_length=50)
    text: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    ref: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    original_chars: int = Field(ge=0)
    stored_chars: int = Field(ge=0)
    redactions_applied: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_digest(self) -> CapturedOutput:
        expected = sha256(self.text.encode("utf-8")).hexdigest()
        if self.digest != expected or self.ref != f"sha256:{expected}":
            raise ValueError("captured output digest or reference mismatch")
        if self.stored_chars != len(self.text):
            raise ValueError("stored_chars must match redacted text length")
        return self


class LogArtifact(LunaContractModel):
    """Content-addressed log artifact stored outside task state."""

    artifact_id: UUID = Field(default_factory=uuid4)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    relative_path: str = Field(min_length=1, max_length=4000)
    byte_count: int = Field(ge=0)
    media_type: str = Field(default="text/plain; charset=utf-8", min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=utc_now)
    redactions_applied: tuple[str, ...] = ()

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @property
    def ref(self) -> str:
        return f"sha256:{self.digest}"


class AuditEvent(LunaContractModel):
    """One immutable JSONL event linked into a SHA-256 hash chain."""

    event_id: UUID = Field(default_factory=uuid4)
    sequence: int = Field(ge=1)
    task_id: UUID
    trace_id: UUID
    kind: AuditEventKind
    subject_id: str = Field(min_length=1, max_length=500)
    occurred_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, JsonValue]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    redactions_applied: tuple[str, ...] = ()

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("redactions_applied")
    @classmethod
    def validate_redactions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("redaction labels must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("redaction labels must be unique")
        return cleaned

    def hash_payload(self) -> dict[str, JsonValue]:
        """Return all immutable fields included in the event hash."""
        return {
            "schema_version": self.schema_version,
            "event_id": str(self.event_id),
            "sequence": self.sequence,
            "task_id": str(self.task_id),
            "trace_id": str(self.trace_id),
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload,
            "payload_sha256": self.payload_sha256,
            "previous_event_hash": self.previous_event_hash,
            "redactions_applied": list(self.redactions_applied),
        }

    @model_validator(mode="after")
    def validate_hashes(self) -> AuditEvent:
        expected_payload = sha256(canonical_json(self.payload).encode("utf-8")).hexdigest()
        if self.payload_sha256 != expected_payload:
            raise ValueError("audit payload digest mismatch")
        expected_event = sha256(
            canonical_json(self.hash_payload()).encode("utf-8")
        ).hexdigest()
        if self.event_hash != expected_event:
            raise ValueError("audit event hash mismatch")
        return self


class AuditVerification(LunaContractModel):
    """Result of replaying and verifying an append-only ledger."""

    valid: bool
    event_count: int = Field(ge=0)
    last_event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    first_error: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_result(self) -> AuditVerification:
        if self.valid and self.first_error is not None:
            raise ValueError("valid audit verification cannot carry an error")
        if not self.valid and self.first_error is None:
            raise ValueError("invalid audit verification requires an error")
        return self
