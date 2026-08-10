"""Persistent checkpoint and resume-decision contracts."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.checkpoint import Checkpoint
from luna.contracts.enums import PlanStepStatus, TaskPhase
from luna.contracts.state import ALLOWED_TRANSITIONS, TaskState
from luna.planning.models import AttemptRecord


def canonical_model_json(model: LunaContractModel) -> str:
    """Return deterministic JSON for integrity hashing."""
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def model_digest(model: LunaContractModel) -> str:
    """Return SHA-256 over deterministic model JSON."""
    return sha256(canonical_model_json(model).encode("utf-8")).hexdigest()


class ResumeStatus(StrEnum):
    """Restart outcome for one checkpoint."""

    READY = "READY"
    BLOCKED = "BLOCKED"
    TERMINAL = "TERMINAL"


class ResumeCompatibilityDimension(StrEnum):
    """Observable compatibility dimension used to explain a blocked resume."""

    VECTOR = "VECTOR"
    RUNTIME_REVISION = "RUNTIME_REVISION"
    CONTINUITY_SCHEMA_VERSION = "CONTINUITY_SCHEMA_VERSION"
    RUNTIME_JOURNAL_SCHEMA_VERSION = "RUNTIME_JOURNAL_SCHEMA_VERSION"
    CONTRACT_SCHEMA_VERSION = "CONTRACT_SCHEMA_VERSION"
    WORKSPACE_FINGERPRINT = "WORKSPACE_FINGERPRINT"
    ENVIRONMENT_FINGERPRINT = "ENVIRONMENT_FINGERPRINT"


class ResumeCompatibilityVector(LunaContractModel):
    """Versioned runtime facts that must remain compatible for automatic resume."""

    runtime_revision: str = Field(min_length=1, max_length=500)
    continuity_schema_version: int = Field(ge=1)
    runtime_journal_schema_version: int = Field(ge=1)
    contract_schema_version: str = Field(min_length=1, max_length=100)
    workspace_fingerprint: str = Field(min_length=1, max_length=2000)
    environment_fingerprint: str = Field(min_length=1, max_length=2000)


class CheckpointEnvelope(LunaContractModel):
    """Checkpoint, authoritative state, and retry history stored atomically."""

    checkpoint: Checkpoint
    state: TaskState
    runtime_revision: str = Field(min_length=1, max_length=500)
    compatibility_vector: ResumeCompatibilityVector | None = None
    resume_phase: TaskPhase | None = None
    previous_checkpoint_id: UUID | None = None
    attempt_records: tuple[AttemptRecord, ...] = ()
    terminal: bool = False

    @model_validator(mode="after")
    def validate_links(self) -> CheckpointEnvelope:
        if self.checkpoint.task_id != self.state.task_id:
            raise ValueError("checkpoint and state task IDs must match")
        if self.previous_checkpoint_id == self.checkpoint.checkpoint_id:
            raise ValueError("checkpoint cannot supersede itself")
        if self.compatibility_vector is not None:
            if self.compatibility_vector.runtime_revision != self.runtime_revision:
                raise ValueError("compatibility vector runtime revision mismatch")
            if (
                self.compatibility_vector.workspace_fingerprint
                != self.checkpoint.workspace_fingerprint
            ):
                raise ValueError("compatibility vector workspace fingerprint mismatch")
            if (
                self.compatibility_vector.environment_fingerprint
                != self.checkpoint.environment_fingerprint
            ):
                raise ValueError("compatibility vector environment fingerprint mismatch")

        completed = {
            step.step_id
            for step in self.state.plan
            if step.status in {
                PlanStepStatus.COMPLETE,
                PlanStepStatus.SKIPPED_WITH_REASON,
            }
        }
        open_steps = {
            step.step_id
            for step in self.state.plan
            if step.status not in {
                PlanStepStatus.COMPLETE,
                PlanStepStatus.SKIPPED_WITH_REASON,
            }
        }
        if completed != set(self.checkpoint.completed_step_ids):
            raise ValueError("completed step IDs must match TaskState.plan")
        if open_steps != set(self.checkpoint.open_step_ids):
            raise ValueError("open step IDs must match TaskState.plan")
        if tuple(self.state.observation_ids) != tuple(
            self.checkpoint.observation_ids
        ):
            raise ValueError("checkpoint observation IDs must match TaskState")
        if tuple(self.state.evidence_ids) != tuple(self.checkpoint.evidence_ids):
            raise ValueError("checkpoint evidence IDs must match TaskState")
        if tuple(self.state.failed_assumptions) != tuple(
            self.checkpoint.failed_assumptions
        ):
            raise ValueError("checkpoint failed assumptions must match TaskState")

        plan_step_ids = {step.step_id for step in self.state.plan}
        for attempt in self.attempt_records:
            if attempt.task_id != self.state.task_id:
                raise ValueError("attempt task_id must match checkpoint task")
            if attempt.step_id not in plan_step_ids:
                raise ValueError("attempt step_id must exist in checkpoint plan")

        if self.terminal:
            if self.state.phase is not TaskPhase.CLOSED:
                raise ValueError("terminal checkpoint requires CLOSED TaskState")
            if self.checkpoint.last_verified_phase is not TaskPhase.CLOSED:
                raise ValueError("terminal checkpoint must verify CLOSED phase")
            if self.resume_phase is not None:
                raise ValueError("terminal checkpoint cannot define resume_phase")
            if self.checkpoint.next_step is not None:
                raise ValueError("terminal checkpoint cannot define next_step")
        else:
            if self.state.phase is not TaskPhase.CHECKPOINTED:
                raise ValueError(
                    "non-terminal checkpoint must persist CHECKPOINTED TaskState"
                )
            if self.state.checkpoint_id != self.checkpoint.checkpoint_id:
                raise ValueError(
                    "TaskState.checkpoint_id must reference persisted checkpoint"
                )
            if self.resume_phase is None:
                raise ValueError("non-terminal checkpoint requires resume_phase")
            if self.resume_phase not in ALLOWED_TRANSITIONS[TaskPhase.CHECKPOINTED]:
                raise ValueError(
                    "resume_phase must be reachable from CHECKPOINTED"
                )
            if self.checkpoint.last_verified_phase is TaskPhase.CLOSED:
                raise ValueError("non-terminal checkpoint cannot verify CLOSED")
        return self


class StoredCheckpoint(LunaContractModel):
    """Checkpoint envelope plus its persisted content digest."""

    envelope: CheckpointEnvelope
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_digest(self) -> StoredCheckpoint:
        if self.payload_sha256 != model_digest(self.envelope):
            raise ValueError("checkpoint envelope digest mismatch")
        return self


class ResumePolicy(LunaContractModel):
    """Current runtime conditions required for automatic resume."""

    runtime_revision: str = Field(min_length=1, max_length=500)
    workspace_fingerprint: str = Field(min_length=1, max_length=2000)
    environment_fingerprint: str = Field(min_length=1, max_length=2000)
    compatibility_vector: ResumeCompatibilityVector | None = None

    @model_validator(mode="after")
    def validate_compatibility_vector(self) -> ResumePolicy:
        if self.compatibility_vector is None:
            return self
        if self.compatibility_vector.runtime_revision != self.runtime_revision:
            raise ValueError("resume policy runtime revision mismatch")
        if self.compatibility_vector.workspace_fingerprint != self.workspace_fingerprint:
            raise ValueError("resume policy workspace fingerprint mismatch")
        if (
            self.compatibility_vector.environment_fingerprint
            != self.environment_fingerprint
        ):
            raise ValueError("resume policy environment fingerprint mismatch")
        return self


class ResumeDecision(LunaContractModel):
    """Auditable decision produced before a persisted task resumes."""

    decision_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    checkpoint_id: UUID
    status: ResumeStatus
    reasons: tuple[str, ...]
    policy: ResumePolicy
    compatibility_mismatches: tuple[ResumeCompatibilityDimension, ...] = ()
    resume_phase: TaskPhase | None = None
    resumed_state: TaskState | None = None
    replay_prohibited_step_ids: tuple[UUID, ...] = ()
    decided_at: datetime = Field(default_factory=utc_now)

    @field_validator("decided_at")
    @classmethod
    def validate_decided_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("reasons")
    @classmethod
    def validate_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if not cleaned or any(not value for value in cleaned):
            raise ValueError("resume decision requires non-empty reasons")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("resume reasons must be unique")
        return cleaned

    @field_validator("compatibility_mismatches")
    @classmethod
    def validate_unique_mismatches(
        cls,
        values: tuple[ResumeCompatibilityDimension, ...],
    ) -> tuple[ResumeCompatibilityDimension, ...]:
        if len(values) != len(set(values)):
            raise ValueError("resume compatibility mismatches must be unique")
        return values

    @field_validator("replay_prohibited_step_ids")
    @classmethod
    def validate_unique_steps(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("replay-prohibited step IDs must be unique")
        return values

    @model_validator(mode="after")
    def validate_status(self) -> ResumeDecision:
        if self.status is ResumeStatus.READY:
            if self.compatibility_mismatches:
                raise ValueError("READY resume cannot carry compatibility mismatches")
            if self.resumed_state is None or self.resume_phase is None:
                raise ValueError("READY resume requires state and resume phase")
            if self.resumed_state.task_id != self.task_id:
                raise ValueError("resumed state task_id mismatch")
            if self.resumed_state.phase is not self.resume_phase:
                raise ValueError("resumed state phase must match resume_phase")
            if self.resumed_state.checkpoint_id is not None:
                raise ValueError("resumed state must clear checkpoint_id")
        else:
            if self.resumed_state is not None:
                raise ValueError("non-READY resume cannot carry resumed_state")
            if self.status is ResumeStatus.TERMINAL and self.resume_phase is not None:
                raise ValueError("TERMINAL resume cannot define resume_phase")
        return self


class ContinuityIntegrity(LunaContractModel):
    """Result of verifying SQLite checkpoint and task-state payloads."""

    valid: bool
    database_schema_version: int = Field(ge=0)
    checkpoint_count: int = Field(ge=0)
    task_state_count: int = Field(ge=0)
    first_error: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_result(self) -> ContinuityIntegrity:
        if self.valid and self.first_error is not None:
            raise ValueError("valid continuity integrity cannot carry error")
        if not self.valid and self.first_error is None:
            raise ValueError("invalid continuity integrity requires error")
        return self
