"""Plan and expected-observation contracts."""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.enums import ObservationStatus, PlanStepStatus


class ExpectedObservation(LunaContractModel):
    """Expected outcome recorded before a meaningful action."""

    expectation_id: UUID = Field(default_factory=uuid4)
    summary: str = Field(min_length=1, max_length=2000)
    expected_status: ObservationStatus | None = None
    expected_exit_codes: tuple[int, ...] = ()
    expected_changed_paths: tuple[str, ...] = ()
    failure_signals: tuple[str, ...] = Field(min_length=1)
    verification_method: str = Field(min_length=1, max_length=2000)
    high_impact: bool = False

    @field_validator("expected_exit_codes")
    @classmethod
    def validate_exit_codes(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if len(values) != len(set(values)):
            raise ValueError("expected exit codes must be unique")
        return values

    @field_validator("expected_changed_paths", "failure_signals")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("entries must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_high_impact_detail(self) -> ExpectedObservation:
        if self.high_impact and self.expected_status is None:
            raise ValueError("high-impact expectation requires expected_status")
        return self


class PlanStep(LunaContractModel):
    """A single ordered, updateable step in a task plan."""

    step_id: UUID = Field(default_factory=uuid4)
    sequence: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=2000)
    status: PlanStepStatus = PlanStepStatus.PENDING
    expectation: ExpectedObservation | None = None
    depends_on: tuple[UUID, ...] = ()
    status_reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_status_reason(self) -> PlanStep:
        statuses_requiring_reason = {
            PlanStepStatus.BLOCKED,
            PlanStepStatus.FAILED,
            PlanStepStatus.SKIPPED_WITH_REASON,
        }
        if self.status in statuses_requiring_reason and not self.status_reason:
            raise ValueError(f"{self.status.value} requires status_reason")
        if self.step_id in self.depends_on:
            raise ValueError("a plan step cannot depend on itself")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("depends_on values must be unique")
        return self
