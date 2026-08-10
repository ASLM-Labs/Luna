"""Durable, bounded working-session continuity contracts for Luna R7-B."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


class SessionStatus(StrEnum):
    """Lifecycle of a working conversation session."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SessionEntryRole(StrEnum):
    """Visible conversational roles that may be persisted in a working session."""

    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SUMMARY = "SUMMARY"


class WorkingSession(LunaContractModel):
    """Durable session identity; it grants no runtime or tool authority."""

    session_id: UUID = Field(default_factory=uuid4)
    owner_ref: str = Field(min_length=1, max_length=500)
    status: SessionStatus = SessionStatus.OPEN
    label: str | None = Field(default=None, min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None

    @field_validator("owner_ref", "label")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("session text fields cannot be blank")
        return cleaned

    @field_validator("created_at", "closed_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> WorkingSession:
        if self.status is SessionStatus.OPEN and self.closed_at is not None:
            raise ValueError("OPEN session cannot define closed_at")
        if self.status is SessionStatus.CLOSED and self.closed_at is None:
            raise ValueError("CLOSED session requires closed_at")
        if self.closed_at is not None and self.closed_at < self.created_at:
            raise ValueError("closed_at cannot precede created_at")
        return self


class SessionEntry(LunaContractModel):
    """One redacted visible message stored under a monotonic session sequence."""

    entry_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    sequence: int = Field(ge=1)
    role: SessionEntryRole
    content: str = Field(min_length=1, max_length=4000)
    source_task_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    redactions_applied: tuple[str, ...] = ()

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("redactions_applied")
    @classmethod
    def validate_redactions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("session redaction labels cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("session redaction labels must be unique")
        return cleaned


class SessionSnapshot(LunaContractModel):
    """Bounded chronological view used for explicit model-context projection."""

    session: WorkingSession
    entries: tuple[SessionEntry, ...] = ()
    truncated_entries: int = Field(default=0, ge=0)
    chars_used: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_snapshot(self) -> SessionSnapshot:
        if any(entry.session_id != self.session.session_id for entry in self.entries):
            raise ValueError("snapshot entries must belong to the selected session")
        sequences = tuple(entry.sequence for entry in self.entries)
        if sequences != tuple(sorted(sequences)):
            raise ValueError("snapshot entries must remain in chronological sequence order")
        if len(sequences) != len(set(sequences)):
            raise ValueError("snapshot entry sequences must be unique")
        if self.chars_used != sum(len(entry.content) for entry in self.entries):
            raise ValueError("snapshot chars_used must match retained session content")
        return self


def canonical_model_json(model: LunaContractModel) -> str:
    """Return deterministic JSON used by the session store integrity boundary."""
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def model_digest(model: LunaContractModel) -> str:
    """Return SHA-256 over deterministic model JSON."""
    return sha256(canonical_model_json(model).encode("utf-8")).hexdigest()
