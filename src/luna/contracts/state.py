"""Authoritative task-state contract and transition rules."""

from __future__ import annotations

from datetime import datetime
from types import MappingProxyType
from typing import ClassVar
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, stable_payload, utc_now
from luna.contracts.decision import DecisionStateSnapshot
from luna.contracts.enums import CompletionStatus, TaskPhase
from luna.contracts.invalidation import InvalidationStateSnapshot
from luna.contracts.plan import PlanStep
from luna.contracts.specification import IntentConstraintJudgment
from luna.contracts.task import TaskContract

_ALLOWED_TRANSITIONS_SOURCE: dict[TaskPhase, frozenset[TaskPhase]] = {
    TaskPhase.CREATED: frozenset({TaskPhase.CONTRACTED}),
    TaskPhase.CONTRACTED: frozenset({TaskPhase.CONTEXT_READY, TaskPhase.CHECKPOINTED}),
    TaskPhase.CONTEXT_READY: frozenset({TaskPhase.PLANNED, TaskPhase.CHECKPOINTED}),
    TaskPhase.PLANNED: frozenset({TaskPhase.ACTING, TaskPhase.CHECKPOINTED}),
    TaskPhase.ACTING: frozenset({TaskPhase.OBSERVING, TaskPhase.CHECKPOINTED}),
    TaskPhase.OBSERVING: frozenset(
        {
            TaskPhase.ACTING,
            TaskPhase.REPLANNING,
            TaskPhase.VERIFYING,
            TaskPhase.CHECKPOINTED,
        }
    ),
    TaskPhase.REPLANNING: frozenset(
        {TaskPhase.PLANNED, TaskPhase.ACTING, TaskPhase.CHECKPOINTED}
    ),
    TaskPhase.VERIFYING: frozenset(
        {TaskPhase.REPORTING, TaskPhase.REPLANNING, TaskPhase.CHECKPOINTED}
    ),
    TaskPhase.REPORTING: frozenset({TaskPhase.CHECKPOINTED, TaskPhase.CLOSED}),
    TaskPhase.CHECKPOINTED: frozenset(
        {
            TaskPhase.CONTEXT_READY,
            TaskPhase.PLANNED,
            TaskPhase.ACTING,
            TaskPhase.VERIFYING,
            TaskPhase.REPORTING,
            TaskPhase.CLOSED,
        }
    ),
    TaskPhase.CLOSED: frozenset(),
}
ALLOWED_TRANSITIONS = MappingProxyType(_ALLOWED_TRANSITIONS_SOURCE)


class TaskState(LunaContractModel):
    """Single authoritative state for a Luna task."""

    allowed_transitions: ClassVar[MappingProxyType[TaskPhase, frozenset[TaskPhase]]] = (
        ALLOWED_TRANSITIONS
    )

    task_id: UUID
    contract: TaskContract
    phase: TaskPhase = TaskPhase.CREATED
    plan: tuple[PlanStep, ...] = ()
    observation_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    failed_assumptions: tuple[str, ...] = ()
    decision_state: DecisionStateSnapshot | None = None
    specification_judgment: IntentConstraintJudgment | None = None
    acceptance_target_ids: tuple[str, ...] = ()
    acceptance_basis_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    invalidation_state: InvalidationStateSnapshot | None = None
    completion_status: CompletionStatus | None = None
    checkpoint_id: UUID | None = None
    revision: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("acceptance_target_ids")
    @classmethod
    def validate_acceptance_target_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("acceptance target IDs must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("acceptance target IDs must be unique")
        return cleaned

    @field_validator("failed_assumptions")
    @classmethod
    def validate_failed_assumptions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("failed assumptions must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("failed assumptions must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_coherence(self) -> TaskState:
        if self.task_id != self.contract.task_id:
            raise ValueError("TaskState.task_id must match TaskContract.task_id")
        if self.decision_state is not None and self.decision_state.task_id != self.task_id:
            raise ValueError("TaskState.decision_state task_id must match TaskState.task_id")
        if (
            self.specification_judgment is not None
            and self.specification_judgment.task_id != self.task_id
        ):
            raise ValueError(
                "TaskState.specification_judgment task_id must match TaskState.task_id"
            )
        if (
            self.specification_judgment is not None
            and self.specification_judgment.literal_objective != self.contract.objective
        ):
            raise ValueError(
                "C4 literal objective must match the authoritative TaskContract objective"
            )
        has_acceptance_targets = bool(self.acceptance_target_ids)
        has_acceptance_basis = self.acceptance_basis_fingerprint is not None
        if has_acceptance_targets != has_acceptance_basis:
            raise ValueError("C5 acceptance targets and basis fingerprint must be stored together")
        if has_acceptance_basis and self.specification_judgment is None:
            raise ValueError("C5 acceptance basis requires an observable C4 specification")
        if self.invalidation_state is not None and self.invalidation_state.task_id != self.task_id:
            raise ValueError("TaskState.invalidation_state task_id must match TaskState.task_id")
        report = (
            self.invalidation_state.latest_report
            if self.invalidation_state is not None
            else None
        )
        if report is not None and report.result_task_state_revision > self.revision:
            raise ValueError(
                "C3 invalidation report cannot come from a future task revision"
            )
        decision_revision = (
            self.decision_state.revision if self.decision_state is not None else 0
        )
        if report is not None and report.current_decision_state_revision > decision_revision:
            raise ValueError(
                "C3 invalidation report cannot come from a future decision revision"
            )

        step_ids = tuple(step.step_id for step in self.plan)
        sequences = tuple(step.sequence for step in self.plan)
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("plan step IDs must be unique")
        if len(sequences) != len(set(sequences)):
            raise ValueError("plan step sequence values must be unique")
        if sequences and tuple(sorted(sequences)) != tuple(range(1, len(sequences) + 1)):
            raise ValueError("plan step sequences must be contiguous starting at 1")

        if self.phase is TaskPhase.CLOSED and self.completion_status is None:
            raise ValueError("closed task requires completion_status")
        if self.phase not in {
            TaskPhase.VERIFYING,
            TaskPhase.REPORTING,
            TaskPhase.CHECKPOINTED,
            TaskPhase.CLOSED,
        } and self.completion_status is not None:
            raise ValueError("completion_status is only valid from VERIFYING onward")
        if self.phase is TaskPhase.CHECKPOINTED and self.checkpoint_id is None:
            raise ValueError("CHECKPOINTED phase requires checkpoint_id")
        return self

    def revise(
        self,
        *,
        plan: tuple[PlanStep, ...] | None = None,
        observation_ids: tuple[UUID, ...] | None = None,
        evidence_ids: tuple[UUID, ...] | None = None,
        failed_assumptions: tuple[str, ...] | None = None,
        decision_state: DecisionStateSnapshot | None = None,
        specification_judgment: IntentConstraintJudgment | None = None,
        acceptance_target_ids: tuple[str, ...] | None = None,
        acceptance_basis_fingerprint: str | None = None,
        invalidation_state: InvalidationStateSnapshot | None = None,
        updated_at: datetime | None = None,
    ) -> TaskState:
        """Return the same phase with one validated authoritative-state revision."""
        next_specification = (
            specification_judgment
            if specification_judgment is not None
            else self.specification_judgment
        )
        specification_basis_changed = (
            specification_judgment is not None
            and (
                self.specification_judgment is None
                or specification_judgment.specification_basis_fingerprint
                != self.specification_judgment.specification_basis_fingerprint
            )
        )
        acceptance_update_requested = (
            acceptance_target_ids is not None
            or acceptance_basis_fingerprint is not None
        )
        if acceptance_update_requested and (
            acceptance_target_ids is None
            or acceptance_basis_fingerprint is None
        ):
            raise ValueError(
                "C5 acceptance targets and basis fingerprint must be revised together"
            )

        if specification_basis_changed and not acceptance_update_requested:
            next_acceptance_target_ids: tuple[str, ...] = ()
            next_acceptance_basis_fingerprint: str | None = None
        elif acceptance_update_requested:
            assert acceptance_target_ids is not None
            assert acceptance_basis_fingerprint is not None
            next_acceptance_target_ids = acceptance_target_ids
            next_acceptance_basis_fingerprint = acceptance_basis_fingerprint
        else:
            next_acceptance_target_ids = self.acceptance_target_ids
            next_acceptance_basis_fingerprint = self.acceptance_basis_fingerprint

        payload = stable_payload(self)
        payload.update(
            {
                "plan": plan if plan is not None else self.plan,
                "observation_ids": (
                    observation_ids
                    if observation_ids is not None
                    else self.observation_ids
                ),
                "evidence_ids": (
                    evidence_ids if evidence_ids is not None else self.evidence_ids
                ),
                "failed_assumptions": (
                    failed_assumptions
                    if failed_assumptions is not None
                    else self.failed_assumptions
                ),
                "decision_state": (
                    decision_state
                    if decision_state is not None
                    else self.decision_state
                ),
                "specification_judgment": next_specification,
                "acceptance_target_ids": next_acceptance_target_ids,
                "acceptance_basis_fingerprint": next_acceptance_basis_fingerprint,
                "invalidation_state": (
                    invalidation_state
                    if invalidation_state is not None
                    else self.invalidation_state
                ),
                "revision": self.revision + 1,
                "updated_at": updated_at or utc_now(),
            }
        )
        return TaskState.model_validate(payload)

    def transition_to(
        self,
        new_phase: TaskPhase,
        *,
        completion_status: CompletionStatus | None = None,
        checkpoint_id: UUID | None = None,
        updated_at: datetime | None = None,
    ) -> TaskState:
        """Return a revalidated state after one legal transition."""
        allowed = self.allowed_transitions[self.phase]
        if new_phase not in allowed:
            raise ValueError(f"invalid task transition: {self.phase.value} -> {new_phase.value}")

        payload = stable_payload(self)
        payload.update(
            {
                "phase": new_phase,
                "revision": self.revision + 1,
                "updated_at": updated_at or utc_now(),
                "completion_status": completion_status,
                "checkpoint_id": checkpoint_id,
            }
        )
        return TaskState.model_validate(payload)
