"""Evidence-bound assumption and decision-state contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


class AssumptionStatus(StrEnum):
    """Observable lifecycle state for one task-critical assumption."""

    UNVERIFIED = "UNVERIFIED"
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


class DecisionStatus(StrEnum):
    """Observable lifecycle state for one decision that can authorize work."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    INVALIDATED = "INVALIDATED"
    COMPLETED = "COMPLETED"


class AssumptionRecord(LunaContractModel):
    """One explicit assumption with evidence, provenance, and dependencies."""

    assumption_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    key: str = Field(min_length=1, max_length=500)
    statement: str = Field(min_length=1, max_length=4000)
    claim_type: str = Field(min_length=1, max_length=200)
    critical: bool = False
    status: AssumptionStatus = AssumptionStatus.UNVERIFIED
    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = ()
    dependent_decision_ids: tuple[UUID, ...] = ()
    reason: str | None = Field(default=None, max_length=4000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("evidence_refs", "provenance_refs")
    @classmethod
    def validate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("assumption references cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("assumption references must be unique")
        return cleaned

    @field_validator("dependent_decision_ids")
    @classmethod
    def validate_decision_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("dependent decision IDs must be unique")
        return values

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_status_requirements(self) -> AssumptionRecord:
        if self.updated_at < self.created_at:
            raise ValueError("assumption updated_at cannot precede created_at")
        if self.status is AssumptionStatus.SUPPORTED and not self.evidence_refs:
            raise ValueError("SUPPORTED assumption requires evidence refs")
        if self.status in {
            AssumptionStatus.CONTRADICTED,
            AssumptionStatus.INVALIDATED,
            AssumptionStatus.SUPERSEDED,
        } and not self.reason:
            raise ValueError(f"{self.status.value} assumption requires a reason")
        return self


class DecisionRecord(LunaContractModel):
    """One explicit decision linked to the assumptions that authorize it."""

    decision_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    action_key: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=4000)
    status: DecisionStatus = DecisionStatus.PENDING
    assumption_ids: tuple[UUID, ...] = ()
    evidence_requirements: tuple[str, ...] = ()
    subject_ref: str | None = Field(default=None, max_length=1000)
    reason: str | None = Field(default=None, max_length=4000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("assumption_ids")
    @classmethod
    def validate_assumption_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("decision assumption IDs must be unique")
        return values

    @field_validator("evidence_requirements")
    @classmethod
    def validate_requirements(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("decision evidence requirements cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("decision evidence requirements must be unique")
        return cleaned

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_status_requirements(self) -> DecisionRecord:
        if self.updated_at < self.created_at:
            raise ValueError("decision updated_at cannot precede created_at")
        if self.status in {DecisionStatus.BLOCKED, DecisionStatus.INVALIDATED} and not self.reason:
            raise ValueError(f"{self.status.value} decision requires a reason")
        return self


class DecisionStateSnapshot(LunaContractModel):
    """Single versioned assumption/decision graph embedded in authoritative TaskState."""

    task_id: UUID
    revision: int = Field(default=0, ge=0)
    assumptions: tuple[AssumptionRecord, ...] = ()
    decisions: tuple[DecisionRecord, ...] = ()
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_graph(self) -> DecisionStateSnapshot:
        assumptions = {item.assumption_id: item for item in self.assumptions}
        decisions = {item.decision_id: item for item in self.decisions}
        if len(assumptions) != len(self.assumptions):
            raise ValueError("assumption IDs must be unique")
        if len(decisions) != len(self.decisions):
            raise ValueError("decision IDs must be unique")
        if any(item.task_id != self.task_id for item in self.assumptions):
            raise ValueError("assumption task IDs must match decision-state task")
        if any(item.task_id != self.task_id for item in self.decisions):
            raise ValueError("decision task IDs must match decision-state task")

        for decision in self.decisions:
            for assumption_id in decision.assumption_ids:
                assumption = assumptions.get(assumption_id)
                if assumption is None:
                    raise ValueError("decision references an unknown assumption")
                if decision.decision_id not in assumption.dependent_decision_ids:
                    raise ValueError("assumption dependency graph must be bidirectional")
                if decision.status is DecisionStatus.ACTIVE:
                    if assumption.status in {
                        AssumptionStatus.CONTRADICTED,
                        AssumptionStatus.INVALIDATED,
                        AssumptionStatus.SUPERSEDED,
                    }:
                        raise ValueError("ACTIVE decision cannot depend on invalid assumption")
                    if assumption.critical and assumption.status is not AssumptionStatus.SUPPORTED:
                        raise ValueError(
                            "ACTIVE decision cannot use unsupported critical assumption"
                        )

        for assumption in self.assumptions:
            for decision_id in assumption.dependent_decision_ids:
                dependent_decision = decisions.get(decision_id)
                if dependent_decision is None:
                    raise ValueError("assumption references an unknown dependent decision")
                if assumption.assumption_id not in dependent_decision.assumption_ids:
                    raise ValueError("decision dependency graph must be bidirectional")
        return self

    @classmethod
    def empty(cls, task_id: UUID) -> DecisionStateSnapshot:
        return cls(task_id=task_id)
