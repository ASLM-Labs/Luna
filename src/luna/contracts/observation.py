"""Normalized observation contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import ObservationStatus


class TestSummary(LunaContractModel):
    """Structured test counts extracted from a tool result."""

    __test__ = False

    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped + self.errors


class Observation(LunaContractModel):
    """A structured, traceable account of what actually happened."""

    observation_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID
    tool_event_id: UUID | None = None
    captured_at: datetime = Field(default_factory=utc_now)
    status: ObservationStatus
    exit_code: int | None = None
    changed_files: tuple[str, ...] = ()
    protected_files_changed: tuple[str, ...] = ()
    tests: TestSummary | None = None
    errors: tuple[str, ...] = ()
    stdout_ref: str | None = None
    stderr_ref: str | None = None
    measured_values: dict[str, int | float | str | bool] = Field(default_factory=dict)
    redactions_applied: tuple[str, ...] = ()

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator(
        "changed_files",
        "protected_files_changed",
        "errors",
        "redactions_applied",
    )
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("entries must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_status_consistency(self) -> Observation:
        if self.status is ObservationStatus.SUCCESS:
            if self.exit_code not in (None, 0):
                raise ValueError("successful observation cannot have a non-zero exit code")
            if self.protected_files_changed:
                raise ValueError("successful observation cannot include protected file changes")
            if self.tests is not None and (self.tests.failed or self.tests.errors):
                raise ValueError("successful observation cannot include failed test results")
        if self.status is ObservationStatus.FAILURE and not (
            self.errors
            or self.protected_files_changed
            or (self.exit_code is not None and self.exit_code != 0)
            or (self.tests is not None and (self.tests.failed or self.tests.errors))
        ):
            raise ValueError("failure observation requires an observable failure signal")
        return self
