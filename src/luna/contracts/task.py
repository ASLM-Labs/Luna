"""Task contract and scope definitions."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import RiskLevel


def _validate_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError("scope paths must be non-empty relative paths without '..'")
    return path.as_posix()


class TaskScope(LunaContractModel):
    """Declared boundary for a task before any write-capable action."""

    workspace_root: str = Field(min_length=1)
    allowed_paths: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()
    write_allowed: bool = False
    network_allowed: bool = False
    process_allowed: bool = False

    @field_validator("allowed_paths", "protected_paths")
    @classmethod
    def validate_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_validate_relative_path(value) for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("scope paths must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_protected_subset(self) -> TaskScope:
        overlap = set(self.allowed_paths) & set(self.protected_paths)
        if self.write_allowed and overlap:
            raise ValueError("a path cannot be both write-allowed and protected")
        return self


class TaskContract(LunaContractModel):
    """Explicit success, safety, evidence, and ownership contract for a task."""

    task_id: UUID = Field(default_factory=uuid4)
    objective: str = Field(min_length=1, max_length=4000)
    required_conditions: tuple[str, ...] = Field(min_length=1)
    forbidden_outcomes: tuple[str, ...] = ()
    evidence_required: tuple[str, ...] = Field(min_length=1)
    scope: TaskScope
    risk_level: RiskLevel = RiskLevel.LOW
    unknowns: tuple[str, ...] = ()
    owner: str = Field(default="user", min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "required_conditions",
        "forbidden_outcomes",
        "evidence_required",
        "unknowns",
    )
    @classmethod
    def validate_unique_nonempty_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("list entries must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("list entries must be unique")
        return cleaned

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_no_contract_contradiction(self) -> TaskContract:
        overlap = set(self.required_conditions) & set(self.forbidden_outcomes)
        if overlap:
            raise ValueError(
                "required_conditions and forbidden_outcomes conflict: "
                + ", ".join(sorted(overlap))
            )
        if self.scope.write_allowed and not self.scope.allowed_paths:
            raise ValueError("write_allowed scope requires at least one allowed path")
        return self
