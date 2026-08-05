"""Task-contract draft models used before a contract is finalized."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.enums import RiskLevel
from luna.contracts.task import TaskScope


class ContractDraftStatus(StrEnum):
    """Whether a task draft has enough explicit information."""

    READY = "READY"
    BLOCKED = "BLOCKED"


class TaskContractDraft(LunaContractModel):
    """Transparent intermediate form; missing fields are never invented."""

    task_id: UUID
    objective: str = Field(min_length=1, max_length=4000)
    required_conditions: tuple[str, ...] = ()
    forbidden_outcomes: tuple[str, ...] = ()
    evidence_required: tuple[str, ...] = ()
    scope: TaskScope
    risk_level: RiskLevel
    unresolved_unknowns: tuple[str, ...] = ()
    blocking_unknowns: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    owner: str = Field(min_length=1, max_length=200)
    status: ContractDraftStatus

    @field_validator(
        "required_conditions",
        "forbidden_outcomes",
        "evidence_required",
        "unresolved_unknowns",
        "blocking_unknowns",
        "conflicts",
    )
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("draft entries must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("draft entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_status(self) -> TaskContractDraft:
        should_be_blocked = bool(self.blocking_unknowns or self.conflicts)
        if should_be_blocked and self.status is not ContractDraftStatus.BLOCKED:
            raise ValueError("draft with blocking unknowns or conflicts must be BLOCKED")
        if not should_be_blocked and self.status is not ContractDraftStatus.READY:
            raise ValueError("complete draft must be READY")
        return self
