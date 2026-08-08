"""Observable, governance-ready trajectory contracts for Phase 19."""

from __future__ import annotations

from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.cognition import FailureLabel
from luna.contracts.base import LunaContractModel
from luna.tools.models import ToolArgumentValue


class TraceStage(StrEnum):
    TASK = "TASK"
    INTENT = "INTENT"
    CONTEXT = "CONTEXT"
    PLAN = "PLAN"
    ACTION = "ACTION"
    OBSERVATION = "OBSERVATION"
    INTERPRETATION = "INTERPRETATION"
    REPLAN = "REPLAN"
    EVIDENCE = "EVIDENCE"
    VERIFICATION = "VERIFICATION"
    FINAL = "FINAL"


class TrajectoryOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class DatasetTaxonomy(StrEnum):
    IMPLEMENTATION_CODING = "IMPLEMENTATION_CODING"
    SECURITY_HARNESS = "SECURITY_HARNESS"
    MODEL_JUDGE_REVIEW = "MODEL_JUDGE_REVIEW"
    SEED_AUTHORING = "SEED_AUTHORING"
    FAILED_RISKY_ACTION = "FAILED_RISKY_ACTION"
    OTHER = "OTHER"


class ObservableDecisionEvent(LunaContractModel):
    """One auditable decision event; not raw hidden chain-of-thought."""

    event_id: UUID = Field(default_factory=uuid4)
    sequence: int = Field(ge=0)
    stage: TraceStage
    summary: str = Field(min_length=1, max_length=8000)
    decision_basis: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    tool_name: str | None = Field(default=None, max_length=120)
    tool_arguments: dict[str, ToolArgumentValue] = Field(default_factory=dict)

    @field_validator("decision_basis", "evidence_refs")
    @classmethod
    def validate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("decision trace references cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("decision trace references must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_tool_binding(self) -> Self:
        if self.tool_arguments and self.tool_name is None:
            raise ValueError("tool arguments require tool_name")
        return self


class StructuredDecisionTrace(LunaContractModel):
    """Canonical observable trajectory for training governance and evaluation."""

    trajectory_id: UUID = Field(default_factory=uuid4)
    source_trajectory_id: str = Field(min_length=1, max_length=500)
    trajectory_family: str = Field(min_length=1, max_length=500)
    task_family: str = Field(min_length=1, max_length=500)
    repository_family: str = Field(min_length=1, max_length=500)
    taxonomy: DatasetTaxonomy
    task_summary: str = Field(min_length=1, max_length=8000)
    events: tuple[ObservableDecisionEvent, ...] = Field(min_length=2)
    outcome: TrajectoryOutcome
    failure_labels: tuple[FailureLabel, ...] = ()
    provenance_refs: tuple[str, ...] = Field(min_length=1)
    license_reviewed: bool = False
    pii_reviewed: bool = False
    raw_hidden_chain_of_thought_included: bool = False

    @field_validator("provenance_refs")
    @classmethod
    def validate_provenance(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("provenance refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("provenance refs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_trace(self) -> Self:
        sequences = tuple(event.sequence for event in self.events)
        if sequences != tuple(range(len(self.events))):
            raise ValueError("trajectory event sequence must be contiguous from zero")
        if self.events[0].stage is not TraceStage.TASK:
            raise ValueError("trajectory must begin with TASK")
        if self.events[-1].stage is not TraceStage.FINAL:
            raise ValueError("trajectory must end with FINAL")
        if self.raw_hidden_chain_of_thought_included:
            raise ValueError("raw hidden chain-of-thought is forbidden")
        if (
            self.outcome in {TrajectoryOutcome.FAILED, TrajectoryOutcome.PARTIAL}
            and not self.failure_labels
        ):
            raise ValueError("failed/partial trace requires failure taxonomy labels")
        return self

    @property
    def split_group_key(self) -> str:
        return "::".join(
            (self.repository_family, self.task_family, self.trajectory_family)
        )
