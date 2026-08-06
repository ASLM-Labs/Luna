"""Contracts for adaptive planning and retry-safe recovery."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import ObservationStatus, PlanStepStatus
from luna.contracts.plan import PlanStep


class TaskComplexity(StrEnum):
    """Planning size selected from explicit task properties."""

    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"


class PlanStatus(StrEnum):
    """Lifecycle state of a complete task plan."""

    READY = "READY"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


class RetryReason(StrEnum):
    """Reason returned by the blind-retry guard."""

    FRESH_ACTION = "FRESH_ACTION"
    CHANGED_BASIS = "CHANGED_BASIS"
    BLIND_RETRY_BLOCKED = "BLIND_RETRY_BLOCKED"
    ALREADY_SUCCEEDED = "ALREADY_SUCCEEDED"


class ReplanAction(StrEnum):
    """Planner response to an observed result."""

    CONTINUE = "CONTINUE"
    REPLAN = "REPLAN"
    BLOCK = "BLOCK"


class FailedAssumption(LunaContractModel):
    """Explicit record of an expectation invalidated by observation."""

    assumption_id: UUID = Field(default_factory=uuid4)
    statement: str = Field(min_length=1, max_length=4000)
    step_id: UUID
    observation_id: UUID
    recorded_at: datetime = Field(default_factory=utc_now)

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, value: datetime) -> datetime:
        return require_utc(value)


class TaskPlan(LunaContractModel):
    """Short, ordered, versioned, and observation-adaptive task plan."""

    plan_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    version: int = Field(default=1, ge=1)
    objective: str = Field(min_length=1, max_length=4000)
    complexity: TaskComplexity
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=8)
    significant_step_ids: tuple[UUID, ...] = ()
    assumptions: tuple[str, ...] = ()
    failed_assumptions: tuple[FailedAssumption, ...] = ()
    status: PlanStatus = PlanStatus.READY
    supersedes_plan_id: UUID | None = None
    replan_reason: str | None = Field(default=None, max_length=4000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_datetime(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("assumptions")
    @classmethod
    def validate_assumptions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("plan assumptions must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("plan assumptions must be unique")
        return cleaned

    @field_validator("significant_step_ids")
    @classmethod
    def validate_significant_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("significant_step_ids must be unique")
        return values

    @model_validator(mode="after")
    def validate_plan(self) -> TaskPlan:
        step_by_id = {step.step_id: step for step in self.steps}
        if len(step_by_id) != len(self.steps):
            raise ValueError("plan step IDs must be unique")

        sequences = tuple(step.sequence for step in self.steps)
        expected_sequences = tuple(range(1, len(self.steps) + 1))
        if tuple(sorted(sequences)) != expected_sequences:
            raise ValueError("plan step sequences must be contiguous starting at 1")

        sequence_by_id = {step.step_id: step.sequence for step in self.steps}
        for step in self.steps:
            for dependency_id in step.depends_on:
                if dependency_id not in step_by_id:
                    raise ValueError("plan dependency must reference an existing step")
                if sequence_by_id[dependency_id] >= step.sequence:
                    raise ValueError("plan dependency must reference an earlier step")

        significant_ids = set(self.significant_step_ids)
        if not significant_ids.issubset(step_by_id):
            raise ValueError("significant_step_ids must reference plan steps")
        high_impact_ids = {
            step.step_id
            for step in self.steps
            if step.expectation is not None and step.expectation.high_impact
        }
        if high_impact_ids != significant_ids:
            raise ValueError(
                "every significant step must have a high-impact expectation and vice versa"
            )

        active_steps = [
            step for step in self.steps if step.status is PlanStepStatus.ACTIVE
        ]
        if self.status is PlanStatus.ACTIVE and len(active_steps) != 1:
            raise ValueError("ACTIVE plan requires exactly one active step")
        if self.status is not PlanStatus.ACTIVE and active_steps:
            raise ValueError("only an ACTIVE plan may contain an active step")

        failed_step_ids = {
            step.step_id
            for step in self.steps
            if step.status is PlanStepStatus.FAILED
        }
        recorded_failed_ids = {
            item.step_id for item in self.failed_assumptions
        }
        if self.status in {PlanStatus.READY, PlanStatus.COMPLETE} and not (
            failed_step_ids.issubset(recorded_failed_ids)
        ):
            raise ValueError("recovered failed steps require failed-assumption records")

        if self.status is PlanStatus.COMPLETE:
            unfinished = {
                PlanStepStatus.PENDING,
                PlanStepStatus.ACTIVE,
                PlanStepStatus.BLOCKED,
            }
            if any(step.status in unfinished for step in self.steps):
                raise ValueError("COMPLETE plan cannot contain unfinished steps")
        if self.status is PlanStatus.BLOCKED and not any(
            step.status in {PlanStepStatus.BLOCKED, PlanStepStatus.FAILED}
            for step in self.steps
        ):
            raise ValueError("BLOCKED plan requires a blocked or failed step")

        if self.version == 1:
            if self.supersedes_plan_id is not None or self.replan_reason is not None:
                raise ValueError("version 1 plan cannot supersede another plan")
        else:
            if self.supersedes_plan_id is None or not self.replan_reason:
                raise ValueError("replanned version requires supersedes_plan_id and reason")
        return self

    def semantic_outline(self) -> tuple[object, ...]:
        """Stable outline used by deterministic planning tests."""
        significant = set(self.significant_step_ids)
        return (
            self.objective,
            self.complexity,
            tuple(
                (
                    step.sequence,
                    step.description,
                    step.step_id in significant,
                    tuple(
                        dependency.sequence
                        for dependency in self.steps
                        if dependency.step_id in step.depends_on
                    ),
                )
                for step in self.steps
            ),
            self.assumptions,
        )


class AttemptBasis(LunaContractModel):
    """Observable conditions that make one action attempt distinct."""

    action_key: str = Field(min_length=1, max_length=500)
    context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_refs: tuple[str, ...] = ()
    assumption_revision: int = Field(default=0, ge=0)
    execution_strategy: str = Field(min_length=1, max_length=1000)
    verification_strategy: str = Field(min_length=1, max_length=1000)
    scope_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("evidence references must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("evidence references must be unique")
        return cleaned

    def fingerprint(self) -> str:
        """Return a canonical basis fingerprint for blind-retry detection."""
        payload = {
            "action_key": self.action_key,
            "assumption_revision": self.assumption_revision,
            "context_fingerprint": self.context_fingerprint,
            "evidence_refs": self.evidence_refs,
            "execution_strategy": self.execution_strategy,
            "scope_fingerprint": self.scope_fingerprint,
            "verification_strategy": self.verification_strategy,
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(serialized.encode("utf-8")).hexdigest()


class AttemptRecord(LunaContractModel):
    """Observed result of an action under a specific basis."""

    attempt_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    step_id: UUID
    basis: AttemptBasis
    observation_id: UUID
    outcome: ObservationStatus
    recorded_at: datetime = Field(default_factory=utc_now)

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, value: datetime) -> datetime:
        return require_utc(value)


class RetryDecision(LunaContractModel):
    """Deterministic retry permission result."""

    allowed: bool
    reason: RetryReason
    matching_attempt_id: UUID | None = None
    changed_dimensions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_decision(self) -> RetryDecision:
        if self.reason is RetryReason.FRESH_ACTION:
            if not self.allowed or self.matching_attempt_id is not None:
                raise ValueError("fresh action must be allowed without a match")
        elif self.reason is RetryReason.CHANGED_BASIS:
            if not self.allowed or self.matching_attempt_id is None:
                raise ValueError("changed basis requires an allowed matching attempt")
            if not self.changed_dimensions:
                raise ValueError("changed basis requires changed_dimensions")
        else:
            if self.allowed or self.matching_attempt_id is None:
                raise ValueError("blocked retry requires a matching attempt")
        return self


class ExpectationAssessment(LunaContractModel):
    """Comparison between an expected and an actual observation."""

    expectation_id: UUID
    observation_id: UUID
    matched: bool
    mismatches: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_assessment(self) -> ExpectationAssessment:
        if self.matched and self.mismatches:
            raise ValueError("matched assessment cannot contain mismatches")
        if not self.matched and not self.mismatches:
            raise ValueError("mismatched assessment requires mismatch details")
        return self


class ReplanOutcome(LunaContractModel):
    """Result of reconciling one action observation with its expectation."""

    action: ReplanAction
    plan: TaskPlan
    assessment: ExpectationAssessment
    reason: str = Field(min_length=1, max_length=4000)
    retry_decision: RetryDecision | None = None
    failed_assumption: FailedAssumption | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> ReplanOutcome:
        if self.action is ReplanAction.CONTINUE:
            if self.failed_assumption is not None or self.retry_decision is not None:
                raise ValueError("CONTINUE cannot carry recovery records")
        else:
            if self.failed_assumption is None or self.retry_decision is None:
                raise ValueError("recovery outcome requires assumption and retry decision")
            if self.action is ReplanAction.REPLAN and not self.retry_decision.allowed:
                raise ValueError("REPLAN requires an allowed changed action basis")
            if self.action is ReplanAction.BLOCK and self.retry_decision.allowed:
                raise ValueError("BLOCK requires a denied retry decision")
        return self
