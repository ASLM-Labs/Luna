"""Release thresholds and gate-owned Phase 11 acceptance decisions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


class ReleaseStatus(StrEnum):
    """Authoritative result of the Phase 11 release gate."""

    PASS = "PASS"
    BLOCKED = "BLOCKED"


class ReleaseThresholds(LunaContractModel):
    """Non-negotiable Luna 0.1 core release thresholds."""

    minimum_task_success_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_verified_success_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    maximum_false_verified_complete: int = Field(default=0, ge=0)
    maximum_protected_path_violations: int = Field(default=0, ge=0)
    maximum_blind_retries: int = Field(default=0, ge=0)
    require_all_critical_cases: bool = True
    require_inspect_before_edit: bool = True
    require_rollback: bool = True
    require_checkpoint_resume: bool = True
    require_memory_cleanliness: bool = True
    require_no_unnecessary_questions: bool = True
    require_scope_control: bool = True
    require_final_report_accuracy: bool = True
    require_published_limitations: bool = True


class ReleaseGateDecision(LunaContractModel):
    """Auditable release decision derived from a fixed EvalReport."""

    decision_id: UUID = Field(default_factory=uuid4)
    eval_report_id: UUID
    suite_revision: str
    suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ReleaseStatus
    reasons: tuple[str, ...]
    known_limitations: tuple[str, ...]
    thresholds: ReleaseThresholds
    decided_at: datetime = Field(default_factory=utc_now)

    @field_validator("decided_at")
    @classmethod
    def validate_decided_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("reasons", "known_limitations")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("release decision text cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("release decision text must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_status(self) -> ReleaseGateDecision:
        if not self.reasons:
            raise ValueError("release decision requires reasons")
        if self.status is ReleaseStatus.PASS and any(
            reason.startswith("BLOCK:") for reason in self.reasons
        ):
            raise ValueError("PASS release decision cannot contain blocking reasons")
        if self.status is ReleaseStatus.BLOCKED and not any(
            reason.startswith("BLOCK:") for reason in self.reasons
        ):
            raise ValueError("BLOCKED release decision requires a blocking reason")
        return self
