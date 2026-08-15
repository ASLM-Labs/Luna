"""Phase 12A runtime request, usage, and outcome contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.autonomy import AutonomyLevel, AutonomyPolicy
from luna.context import (
    ContextBudget,
    ContextCandidate,
    ContextClaim,
    ContextRequirement,
    LayeredContextCandidate,
)
from luna.contracts import CompletionStatus, RiskLevel, TaskScope, TaskState
from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import TaskPhase
from luna.modeling import ProviderRetryEvidence
from luna.runtime.budgets import RuntimeBudget
from luna.runtime.identity_context import RequestSource, RuntimeActor


class RuntimeMode(StrEnum):
    """Execution intent at the runtime boundary."""

    DRY_RUN = "DRY_RUN"
    EXECUTE = "EXECUTE"
    RESUME = "RESUME"


class RuntimePriority(StrEnum):
    """Owner-visible scheduling priority; not an authority grant."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RuntimeStopReason(StrEnum):
    """Explicit reason why a runtime invocation returned control."""

    COMPLETED = "COMPLETED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    CONTEXT_INCOMPLETE = "CONTEXT_INCOMPLETE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    INTERRUPTED = "INTERRUPTED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    RESOURCE_SUSPENDED = "RESOURCE_SUSPENDED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    UNVERIFIED = "UNVERIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"


class RuntimeRequest(LunaContractModel):
    """Complete runtime-owned request before intent resolution or tool selection."""

    request_id: UUID = Field(default_factory=uuid4)
    task_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)
    raw_request: str = Field(min_length=1, max_length=32000)
    source: RequestSource
    actor: RuntimeActor
    scope: TaskScope
    autonomy: AutonomyPolicy
    context_budget: ContextBudget = Field(default_factory=ContextBudget)
    runtime_budget: RuntimeBudget = Field(default_factory=RuntimeBudget)
    context_candidates: tuple[ContextCandidate, ...] = ()
    layered_context_candidates: tuple[LayeredContextCandidate, ...] = ()
    context_claims: tuple[ContextClaim, ...] = ()
    context_requirements: tuple[ContextRequirement, ...] = ()
    required_conditions: tuple[str, ...] = ()
    forbidden_outcomes: tuple[str, ...] = ()
    evidence_required: tuple[str, ...] = ()
    soft_preferences: tuple[str, ...] = ()
    risk_level: RiskLevel = RiskLevel.LOW
    priority: RuntimePriority = RuntimePriority.NORMAL
    mode: RuntimeMode = RuntimeMode.DRY_RUN
    resume_task_id: UUID | None = None
    requested_at: datetime = Field(default_factory=utc_now)

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator(
        "required_conditions",
        "forbidden_outcomes",
        "evidence_required",
        "soft_preferences",
    )
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("runtime request constraints cannot contain blank values")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("runtime request constraints must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_boundary(self) -> RuntimeRequest:
        if self.autonomy.task_id != self.task_id:
            raise ValueError("autonomy policy task_id must match runtime request task_id")
        if any(claim.task_id != self.task_id for claim in self.context_claims):
            raise ValueError("context claim task_id must match runtime request task_id")
        requirement_keys = tuple(item.key for item in self.context_requirements)
        if len(requirement_keys) != len(set(requirement_keys)):
            raise ValueError("context requirement keys must be unique")
        if self.mode is RuntimeMode.RESUME:
            if self.resume_task_id is None:
                raise ValueError("RESUME mode requires resume_task_id")
            if self.resume_task_id != self.task_id:
                raise ValueError("resume_task_id must match runtime request task_id")
        elif self.resume_task_id is not None:
            raise ValueError("resume_task_id is valid only in RESUME mode")

        if self.scope.write_allowed and self.autonomy.level in {
            AutonomyLevel.LEVEL_0_ADVISORY,
            AutonomyLevel.LEVEL_1_READ_ONLY,
        }:
            raise ValueError("write-enabled scope requires Level 2 or higher autonomy")
        if self.scope.network_allowed and self.autonomy.level in {
            AutonomyLevel.LEVEL_0_ADVISORY,
            AutonomyLevel.LEVEL_1_READ_ONLY,
            AutonomyLevel.LEVEL_2_CONTROLLED,
        }:
            raise ValueError("network-enabled scope requires Level 3 or Level 4 autonomy")

        risk_rank = {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.CRITICAL: 3,
        }
        if risk_rank[self.risk_level] > risk_rank[self.autonomy.max_risk]:
            raise ValueError("task risk exceeds the autonomy policy risk ceiling")

        budget = self.runtime_budget
        if not self.scope.write_allowed and any(
            (
                budget.max_changed_files,
                budget.max_added_lines,
                budget.max_deleted_lines,
            )
        ):
            raise ValueError("read-only scope cannot carry a write budget")
        if self.scope.write_allowed and budget.max_changed_files == 0:
            raise ValueError("write-enabled scope requires an explicit change budget")
        if not self.scope.network_allowed and budget.max_network_requests > 0:
            raise ValueError("network-disabled scope cannot carry a network request budget")
        if self.mode is RuntimeMode.DRY_RUN and self.scope.write_allowed:
            raise ValueError("DRY_RUN cannot authorize workspace writes")
        return self


class RuntimeUsage(LunaContractModel):
    """Observable resource use correlated to one immutable runtime budget."""

    budget: RuntimeBudget
    steps: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    replans: int = Field(default=0, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)
    model_input_tokens: int = Field(default=0, ge=0)
    model_output_tokens: int = Field(default=0, ge=0)
    changed_files: int = Field(default=0, ge=0)
    added_lines: int = Field(default=0, ge=0)
    deleted_lines: int = Field(default=0, ge=0)
    questions: int = Field(default=0, ge=0)
    network_requests: int = Field(default=0, ge=0)
    provider_retry_evidence: tuple[ProviderRetryEvidence, ...] = ()

    def exhausted_reasons(self) -> tuple[str, ...]:
        """Return deterministic budget names that are exhausted or exceeded."""
        checks = (
            ("steps", self.steps, self.budget.max_steps),
            ("model_calls", self.model_calls, self.budget.max_model_calls),
            ("tool_calls", self.tool_calls, self.budget.max_tool_calls),
            ("replans", self.replans, self.budget.max_replans),
            ("elapsed_seconds", self.elapsed_ms, self.budget.max_elapsed_seconds * 1000),
            ("model_input_tokens", self.model_input_tokens, self.budget.max_model_input_tokens),
            (
                "model_output_tokens",
                self.model_output_tokens,
                self.budget.max_model_output_tokens,
            ),
            ("changed_files", self.changed_files, self.budget.max_changed_files),
            ("added_lines", self.added_lines, self.budget.max_added_lines),
            ("deleted_lines", self.deleted_lines, self.budget.max_deleted_lines),
            ("questions", self.questions, self.budget.max_questions),
            ("network_requests", self.network_requests, self.budget.max_network_requests),
        )
        return tuple(
            name
            for name, used, limit in checks
            if (limit > 0 and used >= limit) or (limit == 0 and used > 0)
        )

    def exceeded_reasons(self) -> tuple[str, ...]:
        """Return only hard limit violations; equality means exhausted, not exceeded."""
        checks = (
            ("steps", self.steps, self.budget.max_steps),
            ("model_calls", self.model_calls, self.budget.max_model_calls),
            ("tool_calls", self.tool_calls, self.budget.max_tool_calls),
            ("replans", self.replans, self.budget.max_replans),
            ("elapsed_seconds", self.elapsed_ms, self.budget.max_elapsed_seconds * 1000),
            ("model_input_tokens", self.model_input_tokens, self.budget.max_model_input_tokens),
            (
                "model_output_tokens",
                self.model_output_tokens,
                self.budget.max_model_output_tokens,
            ),
            ("changed_files", self.changed_files, self.budget.max_changed_files),
            ("added_lines", self.added_lines, self.budget.max_added_lines),
            ("deleted_lines", self.deleted_lines, self.budget.max_deleted_lines),
            ("questions", self.questions, self.budget.max_questions),
            ("network_requests", self.network_requests, self.budget.max_network_requests),
        )
        return tuple(name for name, used, limit in checks if used > limit)


class RuntimeOutcome(LunaContractModel):
    """One authoritative return value from run, resume, suspend, or cancel."""

    outcome_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    task_id: UUID
    trace_id: UUID
    task_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: TaskState
    stop_reason: RuntimeStopReason
    completion_status: CompletionStatus | None = None
    verification_report_id: UUID | None = None
    final_report_id: UUID | None = None
    checkpoint_id: UUID | None = None
    observation_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    memory_decision_ids: tuple[UUID, ...] = ()
    learning_candidate_ids: tuple[UUID, ...] = ()
    usage: RuntimeUsage
    reasons: tuple[str, ...] = ()
    unresolved_uncertainty: tuple[str, ...] = ()
    started_at: datetime
    finished_at: datetime = Field(default_factory=utc_now)

    @field_validator("started_at", "finished_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("reasons", "unresolved_uncertainty")
    @classmethod
    def validate_reason_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("runtime outcome text values cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("runtime outcome text values must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_links_and_terminal_status(self) -> RuntimeOutcome:
        if self.task_id != self.state.task_id:
            raise ValueError("runtime outcome task_id must match TaskState")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at")
        if self.completion_status is not self.state.completion_status:
            raise ValueError("runtime outcome completion_status must match TaskState")
        if self.checkpoint_id != self.state.checkpoint_id:
            raise ValueError("runtime outcome checkpoint_id must match TaskState")
        if self.observation_ids != self.state.observation_ids:
            raise ValueError("runtime outcome observation_ids must match TaskState")
        if self.evidence_ids != self.state.evidence_ids:
            raise ValueError("runtime outcome evidence_ids must match TaskState")
        if self.stop_reason is RuntimeStopReason.COMPLETED:
            if self.state.phase is not TaskPhase.CLOSED:
                raise ValueError("COMPLETED outcome requires CLOSED TaskState")
            if self.completion_status is not CompletionStatus.VERIFIED_COMPLETE:
                raise ValueError("COMPLETED outcome requires VERIFIED_COMPLETE")
            if self.final_report_id is None:
                raise ValueError("COMPLETED outcome requires final_report_id")
        if (
            self.stop_reason is RuntimeStopReason.BUDGET_EXHAUSTED
            and not self.usage.exhausted_reasons()
        ):
            raise ValueError("BUDGET_EXHAUSTED requires an exhausted budget")
        if self.usage.exceeded_reasons() and self.stop_reason not in {
            RuntimeStopReason.BUDGET_EXHAUSTED,
            RuntimeStopReason.FAILED,
            RuntimeStopReason.INTEGRITY_FAILURE,
        }:
            raise ValueError("budget overrun must be reported as a terminal runtime failure")
        return self
