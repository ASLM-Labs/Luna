"""Review-gated learning proposals derived only from runtime evidence."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import CompletionStatus


class LearningCandidateKind(StrEnum):
    """Deterministic categories that may be reviewed for future learning."""

    FAILED_ASSUMPTION = "FAILED_ASSUMPTION"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    VERIFICATION_GAP = "VERIFICATION_GAP"
    RECOVERY_PATTERN = "RECOVERY_PATTERN"


class LearningCandidate(LunaContractModel):
    """A non-authoritative proposal; it never mutates policy or memory by itself."""

    candidate_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    kind: LearningCandidateKind
    statement: str = Field(min_length=1, max_length=4000)
    verification_report_id: UUID
    completion_status: CompletionStatus
    evidence_ids: tuple[UUID, ...] = ()
    source_refs: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    review_required: bool = True
    automatic_commit_allowed: bool = False
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("learning evidence IDs must be unique")
        return values

    @field_validator("source_refs")
    @classmethod
    def validate_source_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("learning source references cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("learning source references must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_review_boundary(self) -> LearningCandidate:
        if not self.review_required:
            raise ValueError("Phase 12F learning candidates always require review")
        if self.automatic_commit_allowed:
            raise ValueError("Phase 12F learning candidates cannot auto-commit")
        return self


class LearningCandidateBatch(LunaContractModel):
    """Deterministic set of candidate lessons for one verification report."""

    task_id: UUID
    verification_report_id: UUID
    candidates: tuple[LearningCandidate, ...] = ()
    generated_at: datetime = Field(default_factory=utc_now)

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_links(self) -> LearningCandidateBatch:
        ids = tuple(item.candidate_id for item in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("learning candidate IDs must be unique")
        if any(item.task_id != self.task_id for item in self.candidates):
            raise ValueError("learning candidate task IDs must match batch")
        if any(
            item.verification_report_id != self.verification_report_id
            for item in self.candidates
        ):
            raise ValueError("learning candidate report IDs must match batch")
        return self
