"""Pure C-011 S3 current-state admission and hierarchical budget controls.

This module rebuilds a non-executable admission plan from one atomic current-state
snapshot. It does not create workers, invoke a backend, expose tools, mutate root
state, or grant completion or user-facing voice authority.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from luna.contracts.base import require_utc
from luna.contracts.enums import TaskPhase
from luna.contracts.plan import PlanStep
from luna.contracts.state import TaskState
from luna.parallel_cognition.events import RootLeaseRecord, RootLeaseStatus
from luna.parallel_cognition.models import (
    AssignmentSemanticSpec,
    C011ContractModel,
    ContextFreshness,
    ContextSourceReference,
    ParallelCognitionRole,
    ReadOnlyContextManifest,
    RedactionState,
    Sha256,
    SourceStepSemantics,
    WorkerBudgetEnvelope,
    contract_sha256,
)
from luna.planning.capability_selection import CapabilitySelectionPlan
from luna.tools import ToolPolicy


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def authoritative_model_sha256(model: BaseModel) -> str:
    """Hash one revalidated authoritative object with type-domain separation."""

    validated = type(model).model_validate(model.model_dump(mode="json"))
    basis = {
        "contract_type": f"{type(validated).__module__}.{type(validated).__qualname__}",
        "payload": validated.model_dump(mode="json"),
    }
    return sha256(_canonical_json(basis).encode("utf-8")).hexdigest()


def _sealed_sha256(model: C011ContractModel, *, seal_field: str) -> str:
    payload = model.model_dump(mode="json", exclude={seal_field})
    basis = {
        "contract_type": f"{type(model).__module__}.{type(model).__qualname__}",
        "schema_version": model.schema_version,
        "payload": payload,
    }
    return sha256(_canonical_json(basis).encode("utf-8")).hexdigest()


def _normalized_text(values: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = tuple(value.strip() for value in values)
    if any(not value for value in cleaned):
        raise ValueError("references cannot contain blank values")
    return tuple(sorted(cleaned))


class DelegationDisposition(StrEnum):
    """Root-authored declaration of whether independent delegation has value."""

    NO_DELEGATION = "NO_DELEGATION"
    DELEGATE = "DELEGATE"


class AdmissionDisposition(StrEnum):
    """Closed admission outcome vocabulary."""

    ADMIT = "ADMIT"
    DENY = "DENY"


class AdmissionReason(StrEnum):
    """Deterministic, non-executable reasons emitted by the admission boundary."""

    ADMITTED = "ADMITTED"
    NO_DELEGATION = "NO_DELEGATION"
    CLOCK_UNAVAILABLE = "CLOCK_UNAVAILABLE"
    SNAPSHOT_UNAVAILABLE = "SNAPSHOT_UNAVAILABLE"
    SNAPSHOT_INVALID = "SNAPSHOT_INVALID"
    INTENT_INVALID = "INTENT_INVALID"
    DELEGATION_DISABLED = "DELEGATION_DISABLED"
    NO_INDEPENDENT_VALUE = "NO_INDEPENDENT_VALUE"
    NO_DELEGATION_HAS_ASSIGNMENTS = "NO_DELEGATION_HAS_ASSIGNMENTS"
    WORKER_LIMIT_EXCEEDED = "WORKER_LIMIT_EXCEEDED"
    TOTAL_WORKER_BUDGET_EXCEEDED = "TOTAL_WORKER_BUDGET_EXCEEDED"
    CONCURRENT_WORKER_BUDGET_EXHAUSTED = "CONCURRENT_WORKER_BUDGET_EXHAUSTED"
    DUPLICATE_ASSIGNMENT_INTENT = "DUPLICATE_ASSIGNMENT_INTENT"
    DUPLICATE_ASSIGNMENT = "DUPLICATE_ASSIGNMENT"
    ROOT_LEASE_INACTIVE = "ROOT_LEASE_INACTIVE"
    ROOT_LEASE_NOT_CURRENT = "ROOT_LEASE_NOT_CURRENT"
    ROOT_LEASE_DEADLINE_EXCEEDED = "ROOT_LEASE_DEADLINE_EXCEEDED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    TASK_NOT_ADMISSIBLE = "TASK_NOT_ADMISSIBLE"
    ACCEPTANCE_BASIS_MISSING = "ACCEPTANCE_BASIS_MISSING"
    CAPABILITY_BASIS_MISMATCH = "CAPABILITY_BASIS_MISMATCH"
    DEADLINE_ELAPSED = "DEADLINE_ELAPSED"
    WORKER_DEADLINE_EXCEEDED = "WORKER_DEADLINE_EXCEEDED"
    WORKER_RUNTIME_EXCEEDS_DEADLINE = "WORKER_RUNTIME_EXCEEDS_DEADLINE"
    WORKER_BUDGET_EXCEEDED = "WORKER_BUDGET_EXCEEDED"
    AGGREGATE_CONTEXT_BUDGET_EXCEEDED = "AGGREGATE_CONTEXT_BUDGET_EXCEEDED"
    AGGREGATE_RESULT_BUDGET_EXCEEDED = "AGGREGATE_RESULT_BUDGET_EXCEEDED"
    AGGREGATE_TOKEN_BUDGET_EXCEEDED = "AGGREGATE_TOKEN_BUDGET_EXCEEDED"
    AGGREGATE_RUNTIME_BUDGET_EXCEEDED = "AGGREGATE_RUNTIME_BUDGET_EXCEEDED"
    CONTEXT_SOURCE_REQUIRED = "CONTEXT_SOURCE_REQUIRED"
    CONTEXT_SOURCE_LIMIT_EXCEEDED = "CONTEXT_SOURCE_LIMIT_EXCEEDED"
    DUPLICATE_CONTEXT_SOURCE = "DUPLICATE_CONTEXT_SOURCE"
    CONTEXT_SOURCE_MISSING = "CONTEXT_SOURCE_MISSING"
    CONTEXT_SOURCE_STALE = "CONTEXT_SOURCE_STALE"
    CONTEXT_SOURCE_NOT_CURRENT = "CONTEXT_SOURCE_NOT_CURRENT"
    CONTEXT_REDACTION_UNKNOWN = "CONTEXT_REDACTION_UNKNOWN"
    CONTEXT_BUDGET_EXCEEDED = "CONTEXT_BUDGET_EXCEEDED"
    SOURCE_STEP_REQUIRED = "SOURCE_STEP_REQUIRED"
    DUPLICATE_SOURCE_STEP = "DUPLICATE_SOURCE_STEP"
    SOURCE_STEP_MISSING = "SOURCE_STEP_MISSING"
    SOURCE_STEP_LIMIT_EXCEEDED = "SOURCE_STEP_LIMIT_EXCEEDED"
    SOURCE_STEP_DEPENDENCY_INVALID = "SOURCE_STEP_DEPENDENCY_INVALID"
    PLAN_BUILD_FAILED = "PLAN_BUILD_FAILED"


class HierarchicalBudgetEnvelope(C011ContractModel):
    """Explicit root, per-worker, and aggregate ceilings for one admission plan.

    Numeric thresholds intentionally have no production defaults. A caller must obtain
    them from an owner-approved policy before requesting admission.
    """

    max_total_workers: int = Field(ge=0, le=3)
    max_concurrent_workers: int = Field(ge=0, le=3)
    delegation_depth: Literal[1]
    max_worker_context_bytes: int = Field(ge=0)
    max_worker_result_bytes: int = Field(ge=0)
    max_worker_tokens: int = Field(ge=0)
    max_worker_runtime_ms: int = Field(ge=0)
    max_total_context_bytes: int = Field(ge=0)
    max_total_result_bytes: int = Field(ge=0)
    max_total_tokens: int = Field(ge=0)
    max_total_runtime_ms: int = Field(ge=0)
    overall_deadline_at: datetime

    @field_validator("overall_deadline_at")
    @classmethod
    def validate_deadline(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_hierarchy(self) -> Self:
        if self.max_concurrent_workers > self.max_total_workers:
            raise ValueError("concurrent worker ceiling cannot exceed total worker ceiling")
        if self.max_worker_context_bytes > self.max_total_context_bytes:
            raise ValueError("per-worker context ceiling cannot exceed aggregate ceiling")
        if self.max_worker_result_bytes > self.max_total_result_bytes:
            raise ValueError("per-worker result ceiling cannot exceed aggregate ceiling")
        if self.max_worker_tokens > self.max_total_tokens:
            raise ValueError("per-worker token ceiling cannot exceed aggregate ceiling")
        if self.max_worker_runtime_ms > self.max_total_runtime_ms:
            raise ValueError("per-worker runtime ceiling cannot exceed aggregate ceiling")
        return self


class AssignmentIntent(C011ContractModel):
    """Caller intent for one lane, deliberately excluding IDs, digests, and epochs."""

    worker_role: ParallelCognitionRole
    objective: str = Field(min_length=1, max_length=4000)
    independent_value_basis: str = Field(min_length=1, max_length=2000)
    source_step_sequences: tuple[int, ...] = Field(max_length=64)
    budget: WorkerBudgetEnvelope

    @field_validator("source_step_sequences")
    @classmethod
    def normalize_step_sequences(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value < 1 for value in values):
            raise ValueError("source step sequences must be positive")
        return tuple(sorted(values))


class DelegationIntent(C011ContractModel):
    """Untrusted request shape; current authority is never carried by this model."""

    disposition: DelegationDisposition
    assignments: tuple[AssignmentIntent, ...] = Field(max_length=64)
    source_refs: tuple[str, ...] = Field(max_length=256)
    budget: HierarchicalBudgetEnvelope

    @field_validator("source_refs")
    @classmethod
    def normalize_source_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_text(values)

    @field_validator("assignments")
    @classmethod
    def normalize_assignments(
        cls,
        values: tuple[AssignmentIntent, ...],
    ) -> tuple[AssignmentIntent, ...]:
        return tuple(
            sorted(
                values,
                key=lambda item: _canonical_json(item.model_dump(mode="json")),
            )
        )


class CurrentAdmissionSnapshot(C011ContractModel):
    """One atomic provider-owned view of all current admission authority.

    No digest is accepted as a substitute for the actual authoritative objects. The
    engine recomputes every fingerprint from this revalidated snapshot.
    """

    task_state: TaskState
    tool_policy: ToolPolicy
    context_sources: tuple[ContextSourceReference, ...]
    capability_selection: CapabilitySelectionPlan
    root_lease: RootLeaseRecord
    cancellation_generation: int = Field(ge=0)
    cancellation_requested: bool
    delegation_enabled: bool

    @field_validator("context_sources")
    @classmethod
    def normalize_context_sources(
        cls,
        values: tuple[ContextSourceReference, ...],
    ) -> tuple[ContextSourceReference, ...]:
        refs = tuple(item.source_ref for item in values)
        if len(refs) != len(set(refs)):
            raise ValueError("current context source references must be unique")
        return tuple(sorted(values, key=lambda item: item.source_ref))

    @model_validator(mode="after")
    def validate_current_bindings(self) -> Self:
        task_id = self.task_state.task_id
        revision = self.task_state.revision
        if self.root_lease.task_id != task_id:
            raise ValueError("root lease must belong to the current task")
        if self.capability_selection.task_id != task_id:
            raise ValueError("capability selection must belong to the current task")
        current_step_ids = {step.step_id for step in self.task_state.plan}
        if self.capability_selection.step_id not in current_step_ids:
            raise ValueError("capability selection must reference a current plan step")
        if any(item.task_id != task_id for item in self.context_sources):
            raise ValueError("context sources must belong to the current task")
        if any(item.source_task_revision != revision for item in self.context_sources):
            raise ValueError("context sources must match the current task revision")
        return self

    @property
    def root_coordination_epoch(self) -> int:
        return self.root_lease.epoch

    @property
    def cancellation_epoch(self) -> int:
        return self.cancellation_generation


class CurrentAdmissionSnapshotProvider(Protocol):
    """Provide one transactionally coherent current snapshot per admission call."""

    def current_snapshot(self) -> CurrentAdmissionSnapshot:
        """Return actual current objects from one atomic read boundary."""


class Clock(Protocol):
    """Injected wall clock used for deterministic admission and deadline checks."""

    def now(self) -> datetime:
        """Return a timezone-aware timestamp."""


class AdmissionPlanSeal(C011ContractModel):
    """Content-verified seal over current inputs and derived assignment identities."""

    seal_sha256: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    intent_sha256: Sha256
    task_state_sha256: Sha256
    autonomy_policy_sha256: Sha256
    tool_policy_sha256: Sha256
    capability_selection_sha256: Sha256
    root_coordination_epoch: int = Field(ge=1)
    cancellation_generation: int = Field(ge=0)
    hierarchical_budget_sha256: Sha256
    context_manifest_sha256: Sha256 | None
    assignment_ids: tuple[str, ...]
    admitted_at: datetime
    expires_at: datetime

    @field_validator("assignment_ids")
    @classmethod
    def normalize_assignment_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("sealed assignment IDs must be unique")
        return tuple(sorted(values))

    @field_validator("admitted_at", "expires_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_seal(self) -> Self:
        if self.expires_at <= self.admitted_at:
            raise ValueError("admission plan expiry must be after admission")
        if bool(self.assignment_ids) != (self.context_manifest_sha256 is not None):
            raise ValueError("a sealed context manifest is required exactly when workers exist")
        expected = _sealed_sha256(self, seal_field="seal_sha256")
        if not self.seal_sha256:
            object.__setattr__(self, "seal_sha256", expected)
        elif self.seal_sha256 != expected:
            raise ValueError("admission plan seal does not match canonical content")
        return self


class AdmittedPlan(C011ContractModel):
    """Derived, sealed, non-executable plan for zero to three read-only workers."""

    seal: AdmissionPlanSeal
    budget: HierarchicalBudgetEnvelope
    context_manifest: ReadOnlyContextManifest | None
    assignments: tuple[AssignmentSemanticSpec, ...] = Field(max_length=3)
    write_authority: Literal[False] = False
    network_authority: Literal[False] = False
    process_authority: Literal[False] = False
    tool_authority: Literal[False] = False
    external_action_authority: Literal[False] = False
    delegation_authority: Literal[False] = False
    inherited_memory_authority: Literal[False] = False
    memory_commit_authority: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    live_execution_authority: Literal[False] = False
    production_wiring_authority: Literal[False] = False
    capability_promotion_authority: Literal[False] = False

    @field_validator("assignments")
    @classmethod
    def normalize_assignments(
        cls,
        values: tuple[AssignmentSemanticSpec, ...],
    ) -> tuple[AssignmentSemanticSpec, ...]:
        ids = tuple(item.assignment_id for item in values)
        if len(ids) != len(set(ids)):
            raise ValueError("admitted assignment IDs must be unique")
        return tuple(sorted(values, key=lambda item: item.assignment_id))

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        assignments = self.assignments
        context = self.context_manifest
        if len(assignments) > self.budget.max_total_workers:
            raise ValueError("admitted assignments exceed the total worker ceiling")
        if assignments and self.budget.max_concurrent_workers < 1:
            raise ValueError("a worker plan requires a non-zero concurrency ceiling")
        if bool(assignments) != (context is not None):
            raise ValueError("context manifest is required exactly when workers exist")
        if self.seal.expires_at != self.budget.overall_deadline_at:
            raise ValueError("sealed expiry must equal the overall deadline")
        if self.seal.hierarchical_budget_sha256 != authoritative_model_sha256(self.budget):
            raise ValueError("sealed hierarchical budget digest mismatch")
        if self.seal.assignment_ids != tuple(item.assignment_id for item in assignments):
            raise ValueError("sealed assignment identities do not match the admitted plan")
        if not assignments:
            if self.seal.context_manifest_sha256 is not None:
                raise ValueError("zero-worker plan cannot seal a context manifest")
            return self

        assert context is not None
        context_digest = contract_sha256(context)
        if self.seal.context_manifest_sha256 != context_digest:
            raise ValueError("sealed context manifest digest mismatch")
        if (
            context.task_id != self.seal.task_id
            or context.source_task_revision != self.seal.source_task_revision
            or context.created_at != self.seal.admitted_at
            or context.expires_at != self.seal.expires_at
        ):
            raise ValueError("context manifest does not match the sealed current-state basis")
        context_refs = tuple(item.source_ref for item in context.sources)
        for assignment in assignments:
            if (
                assignment.task_id != self.seal.task_id
                or assignment.source_task_revision != self.seal.source_task_revision
                or assignment.root_coordination_epoch != self.seal.root_coordination_epoch
                or assignment.context_manifest_sha256 != context_digest
                or assignment.granted_source_refs != context_refs
                or assignment.budget.deadline_at > self.seal.expires_at
            ):
                raise ValueError("assignment does not match the sealed current-state plan")
        return self

    @property
    def worker_count(self) -> int:
        return len(self.assignments)

    @property
    def plan_seal_sha256(self) -> str:
        return self.seal.seal_sha256


class AdmissionDecision(C011ContractModel):
    """Deterministic fail-closed result; even ADMIT carries no execution authority."""

    decision_sha256: str = ""
    disposition: AdmissionDisposition
    reason_codes: tuple[AdmissionReason, ...] = Field(min_length=1)
    observed_at: datetime | None
    task_id: UUID | None
    source_task_revision: int | None = Field(default=None, ge=0)
    root_coordination_epoch: int | None = Field(default=None, ge=1)
    cancellation_generation: int | None = Field(default=None, ge=0)
    snapshot_sha256: Sha256 | None
    intent_sha256: Sha256 | None
    plan: AdmittedPlan | None
    executable: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator("reason_codes")
    @classmethod
    def normalize_reasons(
        cls,
        values: tuple[AdmissionReason, ...],
    ) -> tuple[AdmissionReason, ...]:
        if len(values) != len(set(values)):
            raise ValueError("admission reasons must be unique")
        return tuple(sorted(values, key=lambda item: item.value))

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        success_reasons = {AdmissionReason.ADMITTED, AdmissionReason.NO_DELEGATION}
        if self.disposition is AdmissionDisposition.ADMIT:
            if self.plan is None:
                raise ValueError("ADMIT decision requires a sealed plan")
            if len(self.reason_codes) != 1 or self.reason_codes[0] not in success_reasons:
                raise ValueError("ADMIT decision requires one success reason")
            if self.observed_at is None or self.snapshot_sha256 is None:
                raise ValueError("ADMIT decision requires an observed current snapshot")
            if self.reason_codes[0] is AdmissionReason.NO_DELEGATION:
                if self.plan.worker_count != 0:
                    raise ValueError("NO_DELEGATION must admit zero workers")
            elif self.plan.worker_count == 0:
                raise ValueError("ADMITTED worker plan cannot be empty")
        else:
            if self.plan is not None:
                raise ValueError("DENY decision cannot expose a partial plan")
            if any(reason in success_reasons for reason in self.reason_codes):
                raise ValueError("DENY decision cannot use a success reason")
        expected = _sealed_sha256(self, seal_field="decision_sha256")
        if not self.decision_sha256:
            object.__setattr__(self, "decision_sha256", expected)
        elif self.decision_sha256 != expected:
            raise ValueError("admission decision digest does not match canonical content")
        return self

    @property
    def admitted(self) -> bool:
        return self.disposition is AdmissionDisposition.ADMIT


class _AdmissionBuildError(ValueError):
    def __init__(self, reason: AdmissionReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class AdmissionEngine:
    """Rebuild and seal one C-011 S3 plan from current provider-owned state."""

    def __init__(
        self,
        *,
        snapshot_provider: CurrentAdmissionSnapshotProvider,
        clock: Clock,
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._clock = clock

    def admit(self, intent: DelegationIntent) -> AdmissionDecision:
        """Return a whole-plan ADMIT or structured DENY without side effects."""

        try:
            current_intent = DelegationIntent.model_validate(intent.model_dump(mode="json"))
            intent_sha256 = contract_sha256(current_intent)
        except (AttributeError, TypeError, ValueError, ValidationError):
            return self._deny(
                reasons={AdmissionReason.INTENT_INVALID},
                observed_at=None,
                intent_sha256=None,
            )

        try:
            supplied_snapshot = self._snapshot_provider.current_snapshot()
        except Exception:
            return self._deny(
                reasons={AdmissionReason.SNAPSHOT_UNAVAILABLE},
                observed_at=None,
                intent_sha256=intent_sha256,
            )
        try:
            snapshot = CurrentAdmissionSnapshot.model_validate(
                supplied_snapshot.model_dump(mode="json")
            )
            snapshot_sha256 = contract_sha256(snapshot)
        except (AttributeError, TypeError, ValueError, ValidationError):
            return self._deny(
                reasons={AdmissionReason.SNAPSHOT_INVALID},
                observed_at=None,
                intent_sha256=intent_sha256,
            )

        try:
            observed_at = require_utc(self._clock.now())
        except Exception:
            return self._deny(
                reasons={AdmissionReason.CLOCK_UNAVAILABLE},
                observed_at=None,
                snapshot=snapshot,
                snapshot_sha256=snapshot_sha256,
                intent_sha256=intent_sha256,
            )

        reasons = self._structural_reasons(
            intent=current_intent,
            snapshot=snapshot,
            observed_at=observed_at,
        )
        if reasons:
            return self._deny(
                reasons=reasons,
                observed_at=observed_at,
                snapshot=snapshot,
                snapshot_sha256=snapshot_sha256,
                intent_sha256=intent_sha256,
            )

        if current_intent.disposition is DelegationDisposition.NO_DELEGATION:
            try:
                plan = self._build_zero_worker_plan(
                    intent=current_intent,
                    snapshot=snapshot,
                    observed_at=observed_at,
                    snapshot_sha256=snapshot_sha256,
                    intent_sha256=intent_sha256,
                )
            except Exception:
                return self._deny(
                    reasons={AdmissionReason.PLAN_BUILD_FAILED},
                    observed_at=observed_at,
                    snapshot=snapshot,
                    snapshot_sha256=snapshot_sha256,
                    intent_sha256=intent_sha256,
                )
            return self._admit_decision(
                reason=AdmissionReason.NO_DELEGATION,
                observed_at=observed_at,
                snapshot=snapshot,
                snapshot_sha256=snapshot_sha256,
                intent_sha256=intent_sha256,
                plan=plan,
            )

        try:
            plan = self._build_worker_plan(
                intent=current_intent,
                snapshot=snapshot,
                observed_at=observed_at,
                snapshot_sha256=snapshot_sha256,
                intent_sha256=intent_sha256,
            )
        except _AdmissionBuildError as exc:
            return self._deny(
                reasons={exc.reason},
                observed_at=observed_at,
                snapshot=snapshot,
                snapshot_sha256=snapshot_sha256,
                intent_sha256=intent_sha256,
            )
        except Exception:
            return self._deny(
                reasons={AdmissionReason.PLAN_BUILD_FAILED},
                observed_at=observed_at,
                snapshot=snapshot,
                snapshot_sha256=snapshot_sha256,
                intent_sha256=intent_sha256,
            )
        return self._admit_decision(
            reason=AdmissionReason.ADMITTED,
            observed_at=observed_at,
            snapshot=snapshot,
            snapshot_sha256=snapshot_sha256,
            intent_sha256=intent_sha256,
            plan=plan,
        )

    @staticmethod
    def _structural_reasons(
        *,
        intent: DelegationIntent,
        snapshot: CurrentAdmissionSnapshot,
        observed_at: datetime,
    ) -> set[AdmissionReason]:
        reasons: set[AdmissionReason] = set()
        assignments = intent.assignments
        budget = intent.budget

        if budget.overall_deadline_at <= observed_at:
            reasons.add(AdmissionReason.DEADLINE_ELAPSED)
        if intent.disposition is DelegationDisposition.NO_DELEGATION:
            if assignments or intent.source_refs:
                reasons.add(AdmissionReason.NO_DELEGATION_HAS_ASSIGNMENTS)
            return reasons

        if not snapshot.delegation_enabled:
            reasons.add(AdmissionReason.DELEGATION_DISABLED)
        if not assignments:
            reasons.add(AdmissionReason.NO_INDEPENDENT_VALUE)
        if len(assignments) > 3:
            reasons.add(AdmissionReason.WORKER_LIMIT_EXCEEDED)
        if len(assignments) > budget.max_total_workers:
            reasons.add(AdmissionReason.TOTAL_WORKER_BUDGET_EXCEEDED)
        if assignments and budget.max_concurrent_workers == 0:
            reasons.add(AdmissionReason.CONCURRENT_WORKER_BUDGET_EXHAUSTED)

        assignment_keys = tuple(
            _canonical_json(item.model_dump(mode="json")) for item in assignments
        )
        if len(assignment_keys) != len(set(assignment_keys)):
            reasons.add(AdmissionReason.DUPLICATE_ASSIGNMENT_INTENT)

        lease = snapshot.root_lease
        if lease.status is not RootLeaseStatus.ACTIVE:
            reasons.add(AdmissionReason.ROOT_LEASE_INACTIVE)
        if lease.acquired_at > observed_at or lease.expires_at <= observed_at:
            reasons.add(AdmissionReason.ROOT_LEASE_NOT_CURRENT)
        if budget.overall_deadline_at > lease.expires_at:
            reasons.add(AdmissionReason.ROOT_LEASE_DEADLINE_EXCEEDED)
        if snapshot.cancellation_requested:
            reasons.add(AdmissionReason.CANCELLATION_REQUESTED)
        if (
            snapshot.task_state.phase is TaskPhase.CLOSED
            or snapshot.task_state.completion_status is not None
        ):
            reasons.add(AdmissionReason.TASK_NOT_ADMISSIBLE)

        state = snapshot.task_state
        capability = snapshot.capability_selection
        if not state.acceptance_target_ids or state.acceptance_basis_fingerprint is None:
            reasons.add(AdmissionReason.ACCEPTANCE_BASIS_MISSING)
        else:
            specification = state.specification_judgment
            if (
                specification is None
                or capability.specification_basis_fingerprint
                != specification.specification_basis_fingerprint
                or capability.acceptance_basis_fingerprint != state.acceptance_basis_fingerprint
            ):
                reasons.add(AdmissionReason.CAPABILITY_BASIS_MISMATCH)

        if not intent.source_refs:
            reasons.add(AdmissionReason.CONTEXT_SOURCE_REQUIRED)
        if len(intent.source_refs) > 128:
            reasons.add(AdmissionReason.CONTEXT_SOURCE_LIMIT_EXCEEDED)
        if len(intent.source_refs) != len(set(intent.source_refs)):
            reasons.add(AdmissionReason.DUPLICATE_CONTEXT_SOURCE)

        current_sources = {item.source_ref: item for item in snapshot.context_sources}
        selected_sources: list[ContextSourceReference] = []
        for source_ref in intent.source_refs:
            source = current_sources.get(source_ref)
            if source is None:
                reasons.add(AdmissionReason.CONTEXT_SOURCE_MISSING)
                continue
            selected_sources.append(source)
            if source.freshness is not ContextFreshness.CURRENT:
                reasons.add(AdmissionReason.CONTEXT_SOURCE_STALE)
            if source.freshness_checked_at > observed_at:
                reasons.add(AdmissionReason.CONTEXT_SOURCE_NOT_CURRENT)
            if source.redaction_state is RedactionState.UNKNOWN:
                reasons.add(AdmissionReason.CONTEXT_REDACTION_UNKNOWN)

        total_context_bytes = sum(item.size_bytes for item in selected_sources)
        if any(total_context_bytes > item.budget.max_context_bytes for item in assignments):
            reasons.add(AdmissionReason.CONTEXT_BUDGET_EXCEEDED)

        total_declared_context = sum(item.budget.max_context_bytes for item in assignments)
        total_declared_result = sum(item.budget.max_result_bytes for item in assignments)
        total_declared_tokens = sum(item.budget.max_tokens for item in assignments)
        total_declared_runtime = sum(item.budget.max_runtime_ms for item in assignments)
        if total_declared_context > budget.max_total_context_bytes:
            reasons.add(AdmissionReason.AGGREGATE_CONTEXT_BUDGET_EXCEEDED)
        if total_declared_result > budget.max_total_result_bytes:
            reasons.add(AdmissionReason.AGGREGATE_RESULT_BUDGET_EXCEEDED)
        if total_declared_tokens > budget.max_total_tokens:
            reasons.add(AdmissionReason.AGGREGATE_TOKEN_BUDGET_EXCEEDED)
        if total_declared_runtime > budget.max_total_runtime_ms:
            reasons.add(AdmissionReason.AGGREGATE_RUNTIME_BUDGET_EXCEEDED)

        for assignment in assignments:
            worker_budget = assignment.budget
            if not assignment.source_step_sequences:
                reasons.add(AdmissionReason.SOURCE_STEP_REQUIRED)
            if len(assignment.source_step_sequences) != len(set(assignment.source_step_sequences)):
                reasons.add(AdmissionReason.DUPLICATE_SOURCE_STEP)
            if worker_budget.deadline_at <= observed_at:
                reasons.add(AdmissionReason.DEADLINE_ELAPSED)
            if (
                worker_budget.deadline_at > budget.overall_deadline_at
                or worker_budget.deadline_at > lease.expires_at
            ):
                reasons.add(AdmissionReason.WORKER_DEADLINE_EXCEEDED)
            if observed_at + timedelta(milliseconds=worker_budget.max_runtime_ms) > (
                worker_budget.deadline_at
            ):
                reasons.add(AdmissionReason.WORKER_RUNTIME_EXCEEDS_DEADLINE)
            if (
                worker_budget.max_context_bytes > budget.max_worker_context_bytes
                or worker_budget.max_result_bytes > budget.max_worker_result_bytes
                or worker_budget.max_tokens > budget.max_worker_tokens
                or worker_budget.max_runtime_ms > budget.max_worker_runtime_ms
            ):
                reasons.add(AdmissionReason.WORKER_BUDGET_EXCEEDED)

        return reasons

    @staticmethod
    def _dependency_closure(
        *,
        state: TaskState,
        sequences: tuple[int, ...],
    ) -> tuple[PlanStep, ...]:
        by_sequence = {step.sequence: step for step in state.plan}
        by_id = {step.step_id: step for step in state.plan}
        requested: list[PlanStep] = []
        for sequence in sequences:
            step = by_sequence.get(sequence)
            if step is None:
                raise _AdmissionBuildError(AdmissionReason.SOURCE_STEP_MISSING)
            requested.append(step)

        visiting: set[UUID] = set()
        visited: set[UUID] = set()
        closure: dict[UUID, PlanStep] = {}

        def visit(step: PlanStep) -> None:
            if step.step_id in visited:
                return
            if step.step_id in visiting:
                raise _AdmissionBuildError(AdmissionReason.SOURCE_STEP_DEPENDENCY_INVALID)
            visiting.add(step.step_id)
            for dependency_id in step.depends_on:
                dependency = by_id.get(dependency_id)
                if dependency is None or dependency.sequence >= step.sequence:
                    raise _AdmissionBuildError(AdmissionReason.SOURCE_STEP_DEPENDENCY_INVALID)
                visit(dependency)
            visiting.remove(step.step_id)
            visited.add(step.step_id)
            closure[step.step_id] = step

        for step in requested:
            visit(step)
        if len(closure) > 32:
            raise _AdmissionBuildError(AdmissionReason.SOURCE_STEP_LIMIT_EXCEEDED)
        return tuple(sorted(closure.values(), key=lambda item: item.sequence))

    @staticmethod
    def _semantic_steps(steps: tuple[PlanStep, ...]) -> tuple[SourceStepSemantics, ...]:
        return tuple(
            SourceStepSemantics(
                step_id=step.step_id,
                sequence=step.sequence,
                description=step.description,
                status=step.status,
                expectation_payload_sha256=(
                    None
                    if step.expectation is None
                    else authoritative_model_sha256(step.expectation)
                ),
                dependency_step_ids=step.depends_on,
                status_reason=step.status_reason,
                source_step_payload_sha256=authoritative_model_sha256(step),
            )
            for step in steps
        )

    @staticmethod
    def _current_digests(
        snapshot: CurrentAdmissionSnapshot,
    ) -> tuple[str, str, str, str, str]:
        task_state_sha256 = authoritative_model_sha256(snapshot.task_state)
        task_contract_sha256 = authoritative_model_sha256(snapshot.task_state.contract)
        tool_policy_sha256 = authoritative_model_sha256(snapshot.tool_policy)
        autonomy_policy_sha256 = authoritative_model_sha256(
            snapshot.tool_policy.autonomy_policy_for(snapshot.task_state.task_id)
        )
        capability_selection_sha256 = authoritative_model_sha256(snapshot.capability_selection)
        return (
            task_state_sha256,
            task_contract_sha256,
            tool_policy_sha256,
            autonomy_policy_sha256,
            capability_selection_sha256,
        )

    def _build_zero_worker_plan(
        self,
        *,
        intent: DelegationIntent,
        snapshot: CurrentAdmissionSnapshot,
        observed_at: datetime,
        snapshot_sha256: str,
        intent_sha256: str,
    ) -> AdmittedPlan:
        (
            task_state_sha256,
            _,
            tool_policy_sha256,
            autonomy_policy_sha256,
            capability_sha256,
        ) = self._current_digests(snapshot)
        seal = AdmissionPlanSeal(
            task_id=snapshot.task_state.task_id,
            source_task_revision=snapshot.task_state.revision,
            snapshot_sha256=snapshot_sha256,
            intent_sha256=intent_sha256,
            task_state_sha256=task_state_sha256,
            autonomy_policy_sha256=autonomy_policy_sha256,
            tool_policy_sha256=tool_policy_sha256,
            capability_selection_sha256=capability_sha256,
            root_coordination_epoch=snapshot.root_lease.epoch,
            cancellation_generation=snapshot.cancellation_generation,
            hierarchical_budget_sha256=authoritative_model_sha256(intent.budget),
            context_manifest_sha256=None,
            assignment_ids=(),
            admitted_at=observed_at,
            expires_at=intent.budget.overall_deadline_at,
        )
        return AdmittedPlan(
            seal=seal,
            budget=intent.budget,
            context_manifest=None,
            assignments=(),
        )

    def _build_worker_plan(
        self,
        *,
        intent: DelegationIntent,
        snapshot: CurrentAdmissionSnapshot,
        observed_at: datetime,
        snapshot_sha256: str,
        intent_sha256: str,
    ) -> AdmittedPlan:
        by_ref = {item.source_ref: item for item in snapshot.context_sources}
        selected_sources = tuple(by_ref[source_ref] for source_ref in intent.source_refs)
        context = ReadOnlyContextManifest(
            task_id=snapshot.task_state.task_id,
            source_task_revision=snapshot.task_state.revision,
            sources=selected_sources,
            total_size_bytes=sum(item.size_bytes for item in selected_sources),
            created_at=observed_at,
            expires_at=intent.budget.overall_deadline_at,
        )
        context_sha256 = contract_sha256(context)
        (
            task_state_sha256,
            task_contract_sha256,
            tool_policy_sha256,
            autonomy_policy_sha256,
            capability_sha256,
        ) = self._current_digests(snapshot)
        acceptance_basis = snapshot.task_state.acceptance_basis_fingerprint
        if acceptance_basis is None or not snapshot.task_state.acceptance_target_ids:
            raise _AdmissionBuildError(AdmissionReason.ACCEPTANCE_BASIS_MISSING)

        assignments = tuple(
            AssignmentSemanticSpec(
                task_id=snapshot.task_state.task_id,
                source_task_revision=snapshot.task_state.revision,
                task_contract_sha256=task_contract_sha256,
                source_steps=self._semantic_steps(
                    self._dependency_closure(
                        state=snapshot.task_state,
                        sequences=item.source_step_sequences,
                    )
                ),
                acceptance_basis_sha256=acceptance_basis,
                acceptance_target_refs=snapshot.task_state.acceptance_target_ids,
                context_manifest_sha256=context_sha256,
                autonomy_policy_sha256=autonomy_policy_sha256,
                tool_policy_sha256=tool_policy_sha256,
                worker_role=item.worker_role,
                objective=item.objective,
                granted_source_refs=intent.source_refs,
                capability_selection_basis_sha256=capability_sha256,
                root_coordination_epoch=snapshot.root_lease.epoch,
                delegation_depth=1,
                budget=item.budget,
            )
            for item in intent.assignments
        )
        assignment_ids = tuple(item.assignment_id for item in assignments)
        if len(assignment_ids) != len(set(assignment_ids)):
            raise _AdmissionBuildError(AdmissionReason.DUPLICATE_ASSIGNMENT)
        assignments = tuple(sorted(assignments, key=lambda item: item.assignment_id))

        seal = AdmissionPlanSeal(
            task_id=snapshot.task_state.task_id,
            source_task_revision=snapshot.task_state.revision,
            snapshot_sha256=snapshot_sha256,
            intent_sha256=intent_sha256,
            task_state_sha256=task_state_sha256,
            autonomy_policy_sha256=autonomy_policy_sha256,
            tool_policy_sha256=tool_policy_sha256,
            capability_selection_sha256=capability_sha256,
            root_coordination_epoch=snapshot.root_lease.epoch,
            cancellation_generation=snapshot.cancellation_generation,
            hierarchical_budget_sha256=authoritative_model_sha256(intent.budget),
            context_manifest_sha256=context_sha256,
            assignment_ids=tuple(item.assignment_id for item in assignments),
            admitted_at=observed_at,
            expires_at=intent.budget.overall_deadline_at,
        )
        return AdmittedPlan(
            seal=seal,
            budget=intent.budget,
            context_manifest=context,
            assignments=assignments,
        )

    @staticmethod
    def _admit_decision(
        *,
        reason: AdmissionReason,
        observed_at: datetime,
        snapshot: CurrentAdmissionSnapshot,
        snapshot_sha256: str,
        intent_sha256: str,
        plan: AdmittedPlan,
    ) -> AdmissionDecision:
        return AdmissionDecision(
            disposition=AdmissionDisposition.ADMIT,
            reason_codes=(reason,),
            observed_at=observed_at,
            task_id=snapshot.task_state.task_id,
            source_task_revision=snapshot.task_state.revision,
            root_coordination_epoch=snapshot.root_lease.epoch,
            cancellation_generation=snapshot.cancellation_generation,
            snapshot_sha256=snapshot_sha256,
            intent_sha256=intent_sha256,
            plan=plan,
        )

    @staticmethod
    def _deny(
        *,
        reasons: set[AdmissionReason],
        observed_at: datetime | None,
        intent_sha256: str | None,
        snapshot: CurrentAdmissionSnapshot | None = None,
        snapshot_sha256: str | None = None,
    ) -> AdmissionDecision:
        return AdmissionDecision(
            disposition=AdmissionDisposition.DENY,
            reason_codes=tuple(sorted(reasons, key=lambda item: item.value)),
            observed_at=observed_at,
            task_id=None if snapshot is None else snapshot.task_state.task_id,
            source_task_revision=(None if snapshot is None else snapshot.task_state.revision),
            root_coordination_epoch=(None if snapshot is None else snapshot.root_lease.epoch),
            cancellation_generation=(
                None if snapshot is None else snapshot.cancellation_generation
            ),
            snapshot_sha256=snapshot_sha256,
            intent_sha256=intent_sha256,
            plan=None,
        )


# A descriptive alias keeps integration call sites readable without duplicating logic.
AdmissionController = AdmissionEngine


__all__ = [
    "AdmissionController",
    "AdmissionDecision",
    "AdmissionDisposition",
    "AdmissionEngine",
    "AdmissionPlanSeal",
    "AdmissionReason",
    "AdmittedPlan",
    "AssignmentIntent",
    "Clock",
    "CurrentAdmissionSnapshot",
    "CurrentAdmissionSnapshotProvider",
    "DelegationDisposition",
    "DelegationIntent",
    "HierarchicalBudgetEnvelope",
    "authoritative_model_sha256",
]
