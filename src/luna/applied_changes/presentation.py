"""Read-only historical presentation of durable applied-change evidence.

This module presents already-validated durable replay state. It does not reread
workspace state, recompute a diff, execute tools, verify outcomes, or grant
recovery/undo authority.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from luna.applied_changes.models import (
    AppliedChangeBindingError,
    AppliedChangeDegradationReason,
    AppliedChangeHunk,
    AppliedChangeOperation,
    AppliedChangeRecord,
    AppliedChangeState,
)
from luna.applied_changes.replay import (
    AppliedChangeReplayIntegrityError,
    AppliedChangeReplayResult,
    AppliedChangeReplayState,
)
from luna.contracts.base import LunaContractModel, require_utc


class AppliedChangePresentationEntry(LunaContractModel):
    """One immutable historical file-change entry from a durable record."""

    model_config = ConfigDict(frozen=True)

    record_id: UUID
    integrity_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    recorded_at: datetime

    operation: AppliedChangeOperation
    relative_path: str = Field(min_length=1, max_length=4000)
    state: AppliedChangeState

    before_existed: bool
    before_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    after_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    before_size_bytes: int = Field(ge=0)
    after_size_bytes: int = Field(ge=0)

    hunks: tuple[AppliedChangeHunk, ...] = ()
    degradation_reason: AppliedChangeDegradationReason | None = None

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, value: datetime) -> datetime:
        return require_utc(value)


class AppliedChangePresentation(LunaContractModel):
    """Bounded historical read-model for one exact tool result."""

    model_config = ConfigDict(frozen=True)

    state: AppliedChangeReplayState

    task_id: UUID
    request_id: UUID
    result_id: UUID

    expected_count: int | None = Field(default=None, ge=0)
    expected_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    binding_error: AppliedChangeBindingError | None = None
    integrity_error: AppliedChangeReplayIntegrityError | None = None

    entries: tuple[AppliedChangePresentationEntry, ...] = ()

    @model_validator(mode="after")
    def validate_state(self) -> AppliedChangePresentation:
        if self.state is AppliedChangeReplayState.AVAILABLE:
            if self.expected_count is None:
                raise ValueError(
                    "AVAILABLE presentation requires expected_count"
                )
            if self.expected_manifest_sha256 is None:
                raise ValueError(
                    "AVAILABLE presentation requires expected manifest"
                )
            if self.binding_error is not None:
                raise ValueError(
                    "AVAILABLE presentation cannot carry binding_error"
                )
            if self.integrity_error is not None:
                raise ValueError(
                    "AVAILABLE presentation cannot carry integrity_error"
                )
            if not self.entries:
                raise ValueError(
                    "AVAILABLE presentation requires historical entries"
                )
            if len(self.entries) != self.expected_count:
                raise ValueError(
                    "AVAILABLE presentation entry count mismatch"
                )
            return self

        if self.entries:
            raise ValueError(
                "non-AVAILABLE presentation cannot expose historical entries"
            )

        if self.state is AppliedChangeReplayState.ABSENT:
            if (
                self.expected_count is not None
                or self.expected_manifest_sha256 is not None
                or self.binding_error is not None
                or self.integrity_error is not None
            ):
                raise ValueError(
                    "ABSENT presentation cannot carry replay evidence"
                )
            return self

        if self.state is AppliedChangeReplayState.UNAVAILABLE:
            if self.expected_count is None:
                raise ValueError(
                    "UNAVAILABLE presentation requires expected_count"
                )
            if self.binding_error is None:
                raise ValueError(
                    "UNAVAILABLE presentation requires binding_error"
                )
            if (
                self.expected_manifest_sha256 is not None
                or self.integrity_error is not None
            ):
                raise ValueError(
                    "UNAVAILABLE presentation cannot claim durable evidence"
                )
            return self

        if self.integrity_error is None:
            raise ValueError(
                "INTEGRITY_FAILURE presentation requires integrity_error"
            )

        if self.binding_error is not None:
            raise ValueError(
                "INTEGRITY_FAILURE presentation cannot carry binding_error"
            )

        return self


def _entry_from_record(
    record: AppliedChangeRecord,
) -> AppliedChangePresentationEntry:
    candidate = record.candidate

    return AppliedChangePresentationEntry(
        record_id=record.record_id,
        integrity_digest=record.integrity_digest,
        recorded_at=record.recorded_at,
        operation=candidate.operation,
        relative_path=candidate.relative_path,
        state=candidate.state,
        before_existed=candidate.before_existed,
        before_digest=candidate.before_digest,
        after_digest=candidate.after_digest,
        before_size_bytes=candidate.before_size_bytes,
        after_size_bytes=candidate.after_size_bytes,
        hunks=candidate.hunks,
        degradation_reason=candidate.degradation_reason,
    )


def project_applied_change_presentation(
    replay: AppliedChangeReplayResult,
) -> AppliedChangePresentation:
    """Project durable replay state without reconstructing historical changes."""

    entries: tuple[AppliedChangePresentationEntry, ...] = ()

    if replay.state is AppliedChangeReplayState.AVAILABLE:
        records = sorted(
            replay.records,
            key=lambda record: (
                record.candidate.relative_path,
                str(record.record_id),
            ),
        )
        entries = tuple(
            _entry_from_record(record)
            for record in records
        )

    return AppliedChangePresentation(
        state=replay.state,
        task_id=replay.task_id,
        request_id=replay.request_id,
        result_id=replay.result_id,
        expected_count=replay.expected_count,
        expected_manifest_sha256=replay.expected_manifest_sha256,
        binding_error=replay.binding_error,
        integrity_error=replay.integrity_error,
        entries=entries,
    )
