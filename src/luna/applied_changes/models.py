"""Typed contracts for immutable applied-change evidence."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from pydantic import (
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from luna.contracts.base import (
    SCHEMA_VERSION,
    LunaContractModel,
    require_utc,
    utc_now,
)


class AppliedChangeState(StrEnum):
    """Availability state of rich applied-change evidence."""

    COMPLETE = "COMPLETE"
    NO_CHANGE = "NO_CHANGE"
    DEGRADED = "DEGRADED"


class AppliedChangeOperation(StrEnum):
    """Controlled text mutation represented by applied-change evidence."""

    WRITE_TEXT = "WRITE_TEXT"
    REPLACE_TEXT = "REPLACE_TEXT"


class AppliedChangeSegmentKind(StrEnum):
    """Semantic role of one contiguous hunk segment."""

    CONTEXT = "CONTEXT"
    DELETE = "DELETE"
    INSERT = "INSERT"


class AppliedChangeDegradationReason(StrEnum):
    """Fail-soft reasons for unavailable rich evidence."""

    INPUT_BUDGET_EXCEEDED = (
        "INPUT_BUDGET_EXCEEDED"
    )
    REPRESENTATION_BUDGET_EXCEEDED = (
        "REPRESENTATION_BUDGET_EXCEEDED"
    )
    HUNK_BUDGET_EXCEEDED = (
        "HUNK_BUDGET_EXCEEDED"
    )
    BEFORE_CONTENT_BASIS_MISMATCH = (
        "BEFORE_CONTENT_BASIS_MISMATCH"
    )
    AFTER_CONTENT_BASIS_MISMATCH = (
        "AFTER_CONTENT_BASIS_MISMATCH"
    )
    TEXT_ENCODING_UNSUPPORTED = (
        "TEXT_ENCODING_UNSUPPORTED"
    )
    PROJECTION_UNAVAILABLE = (
        "PROJECTION_UNAVAILABLE"
    )


class AppliedChangeProjectionPolicy(
    LunaContractModel
):
    """Explicit bounded policy for deterministic projection."""

    model_config = ConfigDict(frozen=True)

    max_input_bytes: int = Field(
        default=1_048_576,
        ge=1,
        le=10_485_760,
    )
    max_representation_bytes: int = Field(
        default=131_072,
        ge=1,
        le=10_485_760,
    )
    max_hunks: int = Field(
        default=64,
        ge=1,
        le=1024,
    )
    context_lines: int = Field(
        default=3,
        ge=0,
        le=20,
    )


class AppliedChangeSegment(LunaContractModel):
    """Exact lines belonging to one hunk segment."""

    # Diff evidence must preserve indentation,
    # trailing spaces, and final newline state.
    model_config = ConfigDict(
        frozen=True,
        str_strip_whitespace=False,
    )

    kind: AppliedChangeSegmentKind
    lines: tuple[str, ...] = Field(
        min_length=1
    )


class AppliedChangeHunk(LunaContractModel):
    """Zero-based before/after range and its segments."""

    model_config = ConfigDict(frozen=True)

    before_start: int = Field(ge=0)
    before_count: int = Field(ge=0)
    after_start: int = Field(ge=0)
    after_count: int = Field(ge=0)

    segments: tuple[
        AppliedChangeSegment,
        ...,
    ] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_counts(
        self,
    ) -> AppliedChangeHunk:
        actual_before = sum(
            len(segment.lines)
            for segment in self.segments
            if segment.kind
            in {
                AppliedChangeSegmentKind.CONTEXT,
                AppliedChangeSegmentKind.DELETE,
            }
        )

        actual_after = sum(
            len(segment.lines)
            for segment in self.segments
            if segment.kind
            in {
                AppliedChangeSegmentKind.CONTEXT,
                AppliedChangeSegmentKind.INSERT,
            }
        )

        if actual_before != self.before_count:
            raise ValueError(
                "before_count does not match hunk segments"
            )

        if actual_after != self.after_count:
            raise ValueError(
                "after_count does not match hunk segments"
            )

        return self


class AppliedChangeCandidate(
    LunaContractModel
):
    """Ephemeral evidence before exact result binding."""

    model_config = ConfigDict(frozen=True)

    task_id: UUID
    operation: AppliedChangeOperation

    relative_path: str = Field(
        min_length=1,
        max_length=4000,
    )

    state: AppliedChangeState

    before_existed: bool

    before_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    after_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )

    before_size_bytes: int = Field(ge=0)
    after_size_bytes: int = Field(ge=0)

    hunks: tuple[
        AppliedChangeHunk,
        ...,
    ] = ()

    degradation_reason: (
        AppliedChangeDegradationReason
        | None
    ) = None

    @model_validator(mode="after")
    def validate_state(
        self,
    ) -> AppliedChangeCandidate:
        if self.before_existed:
            if self.before_digest is None:
                raise ValueError(
                    "existing before-state requires "
                    "a before digest"
                )
        elif (
            self.before_digest is not None
            or self.before_size_bytes != 0
        ):
            raise ValueError(
                "absent before-state cannot carry "
                "content metadata"
            )

        if self.state is AppliedChangeState.COMPLETE:
            # Empty-file creation is a real change
            # without a textual line hunk.
            empty_creation = (
                not self.before_existed
                and self.after_size_bytes == 0
            )

            if (
                not self.hunks
                and not empty_creation
            ):
                raise ValueError(
                    "COMPLETE applied change requires "
                    "hunks unless creating an empty file"
                )

            if self.degradation_reason is not None:
                raise ValueError(
                    "COMPLETE applied change cannot "
                    "carry degradation"
                )

        elif (
            self.state
            is AppliedChangeState.NO_CHANGE
        ):
            if (
                not self.before_existed
                or self.before_digest is None
            ):
                raise ValueError(
                    "NO_CHANGE requires an existing "
                    "before-state"
                )

            if (
                self.before_digest
                != self.after_digest
                or self.before_size_bytes
                != self.after_size_bytes
            ):
                raise ValueError(
                    "NO_CHANGE requires identical "
                    "before/after basis"
                )

            if (
                self.hunks
                or self.degradation_reason
                is not None
            ):
                raise ValueError(
                    "NO_CHANGE cannot carry hunks "
                    "or degradation"
                )

        else:
            if self.hunks:
                raise ValueError(
                    "DEGRADED applied change cannot "
                    "carry partial hunks"
                )

            if self.degradation_reason is None:
                raise ValueError(
                    "DEGRADED applied change requires "
                    "a reason"
                )

        return self


def _record_digest_payload(
    *,
    record_version: int,
    record_id: UUID,
    task_id: UUID,
    request_id: UUID,
    result_id: UUID,
    candidate: AppliedChangeCandidate,
    recorded_at: datetime,
) -> bytes:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "record_version": record_version,
        "record_id": str(record_id),
        "task_id": str(task_id),
        "request_id": str(request_id),
        "result_id": str(result_id),
        "candidate": candidate.model_dump(
            mode="json"
        ),
        "recorded_at": recorded_at.isoformat(),
    }

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class AppliedChangeRef(LunaContractModel):
    """Compact immutable pointer to durable evidence."""

    model_config = ConfigDict(frozen=True)

    record_id: UUID

    integrity_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )

    state: AppliedChangeState

    relative_path: str = Field(
        min_length=1,
        max_length=4000,
    )


class AppliedChangeRecord(LunaContractModel):
    """Immutable evidence bound to one exact tool result."""

    model_config = ConfigDict(frozen=True)

    record_version: Literal[1] = 1

    record_id: UUID = Field(
        default_factory=uuid4
    )

    task_id: UUID
    request_id: UUID
    result_id: UUID

    candidate: AppliedChangeCandidate

    recorded_at: datetime = Field(
        default_factory=utc_now
    )

    integrity_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(
        cls,
        value: datetime,
    ) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_record(
        self,
    ) -> AppliedChangeRecord:
        if self.candidate.task_id != self.task_id:
            raise ValueError(
                "candidate task_id must match "
                "applied-change record"
            )

        expected = sha256(
            _record_digest_payload(
                record_version=self.record_version,
                record_id=self.record_id,
                task_id=self.task_id,
                request_id=self.request_id,
                result_id=self.result_id,
                candidate=self.candidate,
                recorded_at=self.recorded_at,
            )
        ).hexdigest()

        if self.integrity_digest != expected:
            raise ValueError(
                "integrity_digest does not match "
                "applied-change record"
            )

        return self

    @classmethod
    def build(
        cls,
        *,
        request_id: UUID,
        result_id: UUID,
        candidate: AppliedChangeCandidate,
        record_id: UUID | None = None,
        recorded_at: datetime | None = None,
    ) -> AppliedChangeRecord:
        active_record_id = (
            record_id or uuid4()
        )

        active_recorded_at = require_utc(
            recorded_at or utc_now()
        )

        digest = sha256(
            _record_digest_payload(
                record_version=1,
                record_id=active_record_id,
                task_id=candidate.task_id,
                request_id=request_id,
                result_id=result_id,
                candidate=candidate,
                recorded_at=active_recorded_at,
            )
        ).hexdigest()

        return cls(
            record_id=active_record_id,
            task_id=candidate.task_id,
            request_id=request_id,
            result_id=result_id,
            candidate=candidate,
            recorded_at=active_recorded_at,
            integrity_digest=digest,
        )

    def as_ref(self) -> AppliedChangeRef:
        """Return the compact durable-record reference."""

        return AppliedChangeRef(
            record_id=self.record_id,
            integrity_digest=self.integrity_digest,
            state=self.candidate.state,
            relative_path=(
                self.candidate.relative_path
            ),
        )
