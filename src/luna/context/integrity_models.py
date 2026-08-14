"""Structured context claims, requirements, and readiness results."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.context.models import ContextSourceKind
from luna.contracts.base import LunaContractModel, require_utc, utc_now


class ContextClaimType(StrEnum):
    """Claim category used for claim-type-aware authority resolution."""

    CURRENT_STATE = "CURRENT_STATE"
    REPOSITORY_STATE = "REPOSITORY_STATE"
    PROJECT_POLICY = "PROJECT_POLICY"
    USER_INTENT = "USER_INTENT"
    CONTINUITY_STATE = "CONTINUITY_STATE"
    EXECUTION_STATE = "EXECUTION_STATE"
    GENERIC = "GENERIC"


class ContextAuthorityRole(StrEnum):
    """Semantic authority role of a context source for one claim."""

    CURRENT_OBSERVATION = "CURRENT_OBSERVATION"
    CANONICAL_PROJECT = "CANONICAL_PROJECT"
    CURRENT_USER = "CURRENT_USER"
    VERIFIED_MEMORY = "VERIFIED_MEMORY"
    HANDOFF = "HANDOFF"
    CONVERSATION = "CONVERSATION"
    INFERENCE = "INFERENCE"


class ContextFailureAction(StrEnum):
    """Action required when a critical context requirement is unresolved."""

    VERIFY = "VERIFY"
    STOP = "STOP"


class ContextResolutionStatus(StrEnum):
    """Deterministic resolution outcome for one context requirement."""

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    CONFLICTING = "CONFLICTING"


class ReadinessDecision(StrEnum):
    """Task-start/context-resume gate decision."""

    READY = "READY"
    VERIFY = "VERIFY"
    STOP = "STOP"


class ContextClaim(LunaContractModel):
    """One structured claim observed from an explicit context source."""

    claim_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    key: str = Field(min_length=1, max_length=500)
    value: str = Field(min_length=1, max_length=4000)
    claim_type: ContextClaimType
    source_kind: ContextSourceKind
    source_ref: str = Field(min_length=1, max_length=4000)
    authority_role: ContextAuthorityRole
    observed_at: datetime = Field(default_factory=utc_now)
    verified: bool = False
    evidence_refs: tuple[str, ...] = ()

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("context claim evidence refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("context claim evidence refs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_role_boundaries(self) -> ContextClaim:
        if self.verified and not self.evidence_refs:
            raise ValueError("verified context claim requires evidence refs")
        if self.authority_role is ContextAuthorityRole.INFERENCE and self.verified:
            raise ValueError("inference cannot self-declare as verified context")
        if (
            self.authority_role is ContextAuthorityRole.VERIFIED_MEMORY
            and self.source_kind is not ContextSourceKind.MEMORY
        ):
            raise ValueError("VERIFIED_MEMORY role requires a MEMORY context source")
        return self


class ContextRequirement(LunaContractModel):
    """One task-critical context claim that must be reconciled before action."""

    key: str = Field(min_length=1, max_length=500)
    claim_type: ContextClaimType
    critical: bool = True
    require_verified: bool = True
    max_age_seconds: int | None = Field(default=None, ge=0)
    failure_action: ContextFailureAction = ContextFailureAction.VERIFY


class ContextResolution(LunaContractModel):
    """Deterministic claim reconciliation for one requirement."""

    requirement: ContextRequirement
    status: ContextResolutionStatus
    selected_claim_id: UUID | None = None
    selected_value: str | None = Field(default=None, max_length=4000)
    considered_claim_ids: tuple[UUID, ...] = ()
    superseded_claim_ids: tuple[UUID, ...] = ()
    reasons: tuple[str, ...] = ()

    @field_validator("considered_claim_ids", "superseded_claim_ids")
    @classmethod
    def validate_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("context resolution claim IDs must be unique")
        return values

    @field_validator("reasons")
    @classmethod
    def validate_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("context resolution reasons cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("context resolution reasons must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_resolution(self) -> ContextResolution:
        selected = self.selected_claim_id is not None or self.selected_value is not None
        if self.status is ContextResolutionStatus.RESOLVED:
            if self.selected_claim_id is None or self.selected_value is None:
                raise ValueError("RESOLVED context requires selected claim and value")
        elif selected:
            raise ValueError("unresolved/conflicting context cannot select a claim")
        if not set(self.superseded_claim_ids).issubset(self.considered_claim_ids):
            raise ValueError("superseded claims must be considered claims")
        return self


class ContextReadinessReport(LunaContractModel):
    """Structured READY/VERIFY/STOP result from context integrity evaluation."""

    report_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    decision: ReadinessDecision
    resolutions: tuple[ContextResolution, ...] = ()
    raw_missing_sources: tuple[str, ...] = ()
    unresolved_critical_keys: tuple[str, ...] = ()
    conflicting_critical_keys: tuple[str, ...] = ()
    blocking_assumption_ids: tuple[UUID, ...] = ()
    contradicted_assumption_ids: tuple[UUID, ...] = ()
    invalidated_decision_ids: tuple[UUID, ...] = ()
    reasons: tuple[str, ...] = ()
    generated_at: datetime = Field(default_factory=utc_now)

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator(
        "raw_missing_sources",
        "unresolved_critical_keys",
        "conflicting_critical_keys",
        "reasons",
    )
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("readiness report text values cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("readiness report text values must be unique")
        return cleaned

    @field_validator(
        "blocking_assumption_ids",
        "contradicted_assumption_ids",
        "invalidated_decision_ids",
    )
    @classmethod
    def validate_unique_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("readiness report IDs must be unique")
        return values

    @model_validator(mode="after")
    def validate_decision(self) -> ContextReadinessReport:
        if not set(self.contradicted_assumption_ids).issubset(
            self.blocking_assumption_ids
        ):
            raise ValueError("contradicted assumptions must also be blocking assumptions")
        has_critical_gap = bool(
            self.raw_missing_sources
            or self.unresolved_critical_keys
            or self.conflicting_critical_keys
            or self.blocking_assumption_ids
        )
        if self.decision is ReadinessDecision.READY and has_critical_gap:
            raise ValueError("READY context cannot contain critical gaps")
        return self
