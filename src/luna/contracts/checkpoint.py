"""Checkpoint contract for restart-safe task continuity."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import TaskPhase


class Checkpoint(LunaContractModel):
    """Atomic description of the last coherent task state."""

    checkpoint_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    created_at: datetime = Field(default_factory=utc_now)
    workspace_fingerprint: str = Field(min_length=1, max_length=2000)
    environment_fingerprint: str = Field(min_length=1, max_length=2000)
    last_verified_phase: TaskPhase
    completed_step_ids: tuple[UUID, ...] = ()
    open_step_ids: tuple[UUID, ...] = ()
    failed_assumptions: tuple[str, ...] = ()
    observation_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    next_step: str | None = Field(default=None, max_length=4000)
    risks: tuple[str, ...] = ()
    immutable: bool = True

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("failed_assumptions", "risks")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("entries must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_step_sets(self) -> Checkpoint:
        completed = set(self.completed_step_ids)
        open_steps = set(self.open_step_ids)
        if completed & open_steps:
            raise ValueError("a plan step cannot be both completed and open")
        if len(completed) != len(self.completed_step_ids):
            raise ValueError("completed_step_ids must be unique")
        if len(open_steps) != len(self.open_step_ids):
            raise ValueError("open_step_ids must be unique")
        if self.last_verified_phase is not TaskPhase.CLOSED and not self.next_step:
            raise ValueError("non-closed checkpoint requires next_step")
        return self
