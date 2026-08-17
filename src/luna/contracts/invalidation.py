"""C3 contracts for evidence-bound targeted cross-layer invalidation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


class InvalidationLayer(StrEnum):
    """Observable Luna layer whose derived state may lose its basis."""

    ASSUMPTION = "ASSUMPTION"
    DECISION = "DECISION"
    ACCEPTANCE_BACKCHAIN = "ACCEPTANCE_BACKCHAIN"
    PLAN_STEP = "PLAN_STEP"
    DECISION_COMPRESSION = "DECISION_COMPRESSION"
    DECISION_ALTERNATIVES = "DECISION_ALTERNATIVES"
    RETRIEVAL_STRATEGY = "RETRIEVAL_STRATEGY"
    COMPLETION_CLAIM = "COMPLETION_CLAIM"


class InvalidationControlAction(StrEnum):
    """Required control response after targeted invalidation."""

    NONE = "NONE"
    REPLAN = "REPLAN"
    STOP_VERIFY = "STOP_VERIFY"


class InvalidationImpact(LunaContractModel):
    """One directly or transitively invalidated cross-layer basis."""

    target_ref: str = Field(min_length=1, max_length=1000)
    layer: InvalidationLayer
    direct: bool
    cause_refs: tuple[str, ...] = Field(min_length=1)
    changed_basis_evidence_refs: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("cause_refs", "changed_basis_evidence_refs", "reason_codes")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("invalidation impact entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("invalidation impact entries must be unique")
        return cleaned


class CrossLayerInvalidationReport(LunaContractModel):
    """Evidence-linked C3 invalidation result over one authoritative state delta."""

    report_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    previous_task_state_revision: int = Field(ge=0)
    input_task_state_revision: int = Field(ge=0)
    result_task_state_revision: int = Field(ge=0)
    previous_decision_state_revision: int = Field(ge=0)
    current_decision_state_revision: int = Field(ge=0)
    trigger_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    changed_basis_evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = ()
    impacts: tuple[InvalidationImpact, ...] = ()
    preserved_refs: tuple[str, ...] = ()
    control_action: InvalidationControlAction = InvalidationControlAction.NONE
    changed_basis_required: bool = False
    completion_claim_stale: bool = False
    reason_codes: tuple[str, ...] = Field(min_length=1)
    raw_evidence_preserved: Literal[True] = True
    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    generated_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "trigger_refs",
        "evidence_refs",
        "changed_basis_evidence_refs",
        "provenance_refs",
        "preserved_refs",
        "reason_codes",
    )
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("cross-layer invalidation entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("cross-layer invalidation entries must be unique")
        return cleaned

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if self.input_task_state_revision < self.previous_task_state_revision:
            raise ValueError("C3 input task revision cannot precede previous revision")
        if self.current_decision_state_revision < self.previous_decision_state_revision:
            raise ValueError("C3 decision-state revision cannot move backwards")

        impacted_refs = tuple(item.target_ref for item in self.impacts)
        if len(impacted_refs) != len(set(impacted_refs)):
            raise ValueError("C3 invalidation impacts must target unique refs")
        if set(impacted_refs) & set(self.preserved_refs):
            raise ValueError("invalidated and preserved refs must be disjoint")

        if not set(self.changed_basis_evidence_refs).issubset(self.evidence_refs):
            raise ValueError("changed-basis evidence must be a subset of C3 source evidence")
        impact_changed_evidence = {
            ref
            for impact in self.impacts
            for ref in impact.changed_basis_evidence_refs
        }
        if impact_changed_evidence != set(self.changed_basis_evidence_refs):
            raise ValueError(
                "C3 report changed-basis evidence must match impact-level evidence bindings"
            )

        if self.impacts:
            if not self.trigger_refs:
                raise ValueError("C3 invalidation requires explicit trigger refs")
            if not self.evidence_refs and not self.provenance_refs:
                raise ValueError("C3 invalidation requires evidence or provenance")
            if self.control_action is InvalidationControlAction.NONE:
                raise ValueError("C3 invalidation cannot return NONE control")
            if not self.changed_basis_required:
                raise ValueError("C3 invalidation must require a changed basis")
            if self.result_task_state_revision <= self.input_task_state_revision:
                raise ValueError("persisted C3 invalidation must advance task revision")
        else:
            if self.trigger_refs:
                raise ValueError("C3 no-op report cannot expose invalidation triggers")
            if self.control_action is not InvalidationControlAction.NONE:
                raise ValueError("C3 no-op report must return NONE control")
            if self.changed_basis_required or self.completion_claim_stale:
                raise ValueError("C3 no-op report cannot mark stale dependent state")
            if self.result_task_state_revision != self.input_task_state_revision:
                raise ValueError("C3 no-op report cannot revise authoritative task state")

        if (
            self.completion_claim_stale
            and self.control_action is not InvalidationControlAction.STOP_VERIFY
        ):
            raise ValueError("stale completion claim requires STOP_VERIFY")
        return self


class InvalidationStateSnapshot(LunaContractModel):
    """Task-owned C3 state; this records invalidation, not a second truth authority."""

    task_id: UUID
    revision: int = Field(default=0, ge=0)
    latest_report: CrossLayerInvalidationReport | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        if self.latest_report is not None and self.latest_report.task_id != self.task_id:
            raise ValueError("C3 invalidation report task must match snapshot task")
        return self

    @classmethod
    def empty(cls, task_id: UUID) -> InvalidationStateSnapshot:
        return cls(task_id=task_id)
