"""S4 live-worker contracts with an authority-negative root boundary.

The contracts in this module describe focused input and root-observed subprocess
results.  They do not grant a worker tools, network, process creation, task-state
mutation, completion, memory, or a user-facing voice.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import require_utc
from luna.parallel_cognition.models import (
    AgentExecutionAttempt,
    AgentLifecycleState,
    AgentPayload,
    AgentResourceUsage,
    AssignmentSemanticSpec,
    C011ContractModel,
    CleanupState,
    DistilledHandoff,
    ReadOnlyContextManifest,
    Sha256,
    canonical_contract_json,
    contract_sha256,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class _S4ContentAddressedContract(C011ContractModel):
    _identity_field: ClassVar[str]
    _identity_prefix: ClassVar[str]

    @model_validator(mode="after")
    def validate_content_identity(self) -> Self:
        payload = self.model_dump(mode="json", exclude={self._identity_field})
        basis = {
            "contract_type": f"{type(self).__module__}.{type(self).__qualname__}",
            "schema_version": self.schema_version,
            "payload": payload,
        }
        expected = (
            self._identity_prefix + sha256(_canonical_json(basis).encode("utf-8")).hexdigest()
        )
        supplied = getattr(self, self._identity_field)
        if not supplied:
            object.__setattr__(self, self._identity_field, expected)
        elif supplied != expected:
            raise ValueError(f"{self._identity_field} does not match canonical contract content")
        return self


class S4RuntimePolicy(C011ContractModel):
    """Injected, immutable S4 feature and resource policy.

    No ambient environment variable can enable S4.  The default remains disabled and
    the kill switch remains engaged.
    """

    enabled: bool = False
    kill_switch_engaged: bool = True
    max_workers: int = Field(default=3, ge=0, le=3)
    max_concurrent_workers: int = Field(default=3, ge=0, le=3)
    poll_interval_ms: int = Field(default=10, ge=1, le=1000)
    cooperative_cancel_grace_ms: int = Field(default=250, ge=1, le=10_000)
    terminate_grace_ms: int = Field(default=250, ge=1, le=10_000)
    hard_kill_grace_ms: int = Field(default=1000, ge=1, le=10_000)
    max_stderr_bytes: int = Field(default=16_384, ge=0, le=1_048_576)

    @model_validator(mode="after")
    def validate_concurrency(self) -> Self:
        if self.max_concurrent_workers > self.max_workers:
            raise ValueError("S4 concurrent worker ceiling cannot exceed total workers")
        return self

    @property
    def active(self) -> bool:
        return self.enabled and not self.kill_switch_engaged and self.max_workers > 0


class BackendSafetyCapabilities(C011ContractModel):
    """Concrete backend claims that S4 verifies before process creation."""

    bounded_driver_calls: bool
    cooperative_cancellation: bool
    hard_termination: bool
    isolated_ephemeral_scratch: bool
    explicit_environment_only: bool
    shell_disabled: bool

    @property
    def accepted(self) -> bool:
        return all(
            (
                self.bounded_driver_calls,
                self.cooperative_cancellation,
                self.hard_termination,
                self.isolated_ephemeral_scratch,
                self.explicit_environment_only,
                self.shell_disabled,
            )
        )


class FocusedContextDocument(C011ContractModel):
    """One exact admitted source after root-side defensive redaction."""

    source_ref: str = Field(min_length=1, max_length=2000)
    source_revision: str = Field(min_length=1, max_length=500)
    manifest_content_sha256: Sha256
    visible_content_sha256: Sha256
    manifest_size_bytes: int = Field(ge=0)
    visible_size_bytes: int = Field(ge=0)
    content: str = Field(max_length=2_000_000)
    redactions_applied: tuple[str, ...] = ()

    @field_validator("redactions_applied")
    @classmethod
    def normalize_redactions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in values)
        if any(not item for item in cleaned):
            raise ValueError("focused-context redaction labels cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("focused-context redaction labels must be unique")
        return tuple(sorted(cleaned))

    @model_validator(mode="after")
    def validate_visible_content(self) -> Self:
        encoded = self.content.encode("utf-8")
        if len(encoded) != self.visible_size_bytes:
            raise ValueError("focused-context visible size does not match content")
        if sha256(encoded).hexdigest() != self.visible_content_sha256:
            raise ValueError("focused-context visible digest does not match content")
        return self


class FocusedContextBundle(_S4ContentAddressedContract):
    """Ephemeral worker input containing only an assignment's admitted sources."""

    focused_context_id: str = ""
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    context_manifest_sha256: Sha256
    documents: tuple[FocusedContextDocument, ...] = Field(min_length=1, max_length=128)
    visible_size_bytes: int = Field(ge=0)
    available_tools: tuple[()] = ()
    credential_refs: tuple[()] = ()
    inherited_memory_refs: tuple[()] = ()
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

    _identity_field = "focused_context_id"
    _identity_prefix = "c011-focused-context:sha256:"

    @field_validator("documents")
    @classmethod
    def normalize_documents(
        cls, values: tuple[FocusedContextDocument, ...]
    ) -> tuple[FocusedContextDocument, ...]:
        refs = tuple(item.source_ref for item in values)
        if len(refs) != len(set(refs)):
            raise ValueError("focused-context source references must be unique")
        return tuple(sorted(values, key=lambda item: item.source_ref))

    @model_validator(mode="after")
    def validate_accounting(self) -> Self:
        if self.visible_size_bytes != sum(item.visible_size_bytes for item in self.documents):
            raise ValueError("focused-context visible byte accounting mismatch")
        return self


class LiveBackendRequest(_S4ContentAddressedContract):
    """Digest-only durable request; focused source contents are never persisted."""

    request_id: str = ""
    assignment: AssignmentSemanticSpec
    attempt: AgentExecutionAttempt
    context: ReadOnlyContextManifest
    focused_context_id: str = Field(pattern=r"^c011-focused-context:sha256:[0-9a-f]{64}$")
    focused_context_sha256: Sha256
    requested_at: datetime
    available_tools: tuple[()] = ()
    credential_refs: tuple[()] = ()
    inherited_memory_refs: tuple[()] = ()
    write_authority: Literal[False] = False
    network_authority: Literal[False] = False
    process_authority: Literal[False] = False
    tool_authority: Literal[False] = False
    external_action_authority: Literal[False] = False
    delegation_authority: Literal[False] = False
    memory_commit_authority: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    _identity_field = "request_id"
    _identity_prefix = "c011-live-request:sha256:"

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_request_chain(self) -> Self:
        if self.attempt.lifecycle_state is not AgentLifecycleState.STARTED:
            raise ValueError("live backend request requires a STARTED attempt")
        started_at = self.attempt.started_at
        if started_at is None:
            raise ValueError("live backend request requires attempt started_at")
        expected = (
            self.assignment.task_id,
            self.assignment.source_task_revision,
            self.assignment.assignment_id,
            self.assignment.context_manifest_sha256,
            self.assignment.root_coordination_epoch,
            self.assignment.budget.deadline_at,
        )
        actual = (
            self.attempt.task_id,
            self.attempt.source_task_revision,
            self.attempt.assignment_id,
            self.attempt.context_manifest_sha256,
            self.attempt.root_coordination_epoch,
            self.attempt.deadline_at,
        )
        if actual != expected:
            raise ValueError("live backend attempt does not bind the assignment")
        if (
            self.context.task_id != self.assignment.task_id
            or self.context.source_task_revision != self.assignment.source_task_revision
            or contract_sha256(self.context) != self.assignment.context_manifest_sha256
        ):
            raise ValueError("live backend context does not bind the assignment")
        if not (started_at <= self.requested_at < self.attempt.deadline_at):
            raise ValueError("live backend request must occur while attempt is live")
        return self


class WorkerClaimDraft(C011ContractModel):
    """Untrusted claim draft emitted by a worker driver."""

    claim_key: str = Field(min_length=1, max_length=500)
    statement: str = Field(min_length=1, max_length=4000)
    source_refs: tuple[str, ...] = Field(min_length=1, max_length=128)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=128)
    observation_refs: tuple[str, ...] = Field(default=(), max_length=128)

    @field_validator("source_refs", "evidence_refs", "observation_refs")
    @classmethod
    def normalize_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in values)
        if any(not item for item in cleaned):
            raise ValueError("worker claim references cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("worker claim references must be unique")
        return tuple(sorted(cleaned))


class LiveNativeTokenUsage(C011ContractModel):
    """Engine-native measured usage attached by the ABI v2 driver only."""

    source: Literal["ENGINE_NATIVE_COUNTERS"] = "ENGINE_NATIVE_COUNTERS"
    input_tokens: int = Field(gt=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("native token total must equal input plus output tokens")
        return self


class LiveWorkerDraft(C011ContractModel):
    """Closed worker-output schema; no hidden-reasoning or authority field exists."""

    summary: str = Field(min_length=1, max_length=8000)
    claims: tuple[WorkerClaimDraft, ...] = Field(default=(), max_length=128)
    assumptions: tuple[str, ...] = Field(default=(), max_length=128)
    uncertainty: tuple[str, ...] = Field(default=(), max_length=128)
    conflicts: tuple[str, ...] = Field(default=(), max_length=128)
    recommended_next_action: str | None = Field(default=None, max_length=4000)
    tokens: int = Field(default=0, ge=0)
    native_usage: LiveNativeTokenUsage | None = None

    @field_validator("claims")
    @classmethod
    def normalize_claims(cls, values: tuple[WorkerClaimDraft, ...]) -> tuple[WorkerClaimDraft, ...]:
        keys = tuple(item.claim_key for item in values)
        if len(keys) != len(set(keys)):
            raise ValueError("worker draft claim keys must be unique")
        return tuple(sorted(values, key=lambda item: item.claim_key))

    @field_validator("assumptions", "uncertainty", "conflicts")
    @classmethod
    def normalize_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in values)
        if any(not item for item in cleaned):
            raise ValueError("worker draft text entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("worker draft text entries must be unique")
        return tuple(sorted(cleaned))

    @model_validator(mode="after")
    def validate_native_usage(self) -> Self:
        if self.native_usage is not None and self.tokens != self.native_usage.total_tokens:
            raise ValueError("worker token total must match engine-native usage")
        return self


class LiveBackendResult(_S4ContentAddressedContract):
    """Root-observed, sanitized result from one interruptible worker process."""

    result_id: str = ""
    request: LiveBackendRequest
    payload: AgentPayload
    backend_id: str = Field(min_length=1, max_length=500)
    profile_id: str = Field(min_length=1, max_length=500)
    usage: AgentResourceUsage
    native_usage: LiveNativeTokenUsage | None = None
    outcome_state: AgentLifecycleState
    cleanup_state: CleanupState
    outcome_at: datetime
    cleanup_at: datetime
    cancel_requested_at: datetime | None = None
    raw_output_sha256: Sha256 | None = None
    raw_output_size_bytes: int = Field(default=0, ge=0)
    hard_termination_used: bool = False
    reason: str | None = Field(default=None, max_length=2000)
    root_observed: Literal[True] = True
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    _identity_field = "result_id"
    _identity_prefix = "c011-live-result:sha256:"

    @field_validator("outcome_at", "cleanup_at", "cancel_requested_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        allowed = {
            AgentLifecycleState.RESULT_RECEIVED,
            AgentLifecycleState.CANCELLED,
            AgentLifecycleState.TIMED_OUT,
            AgentLifecycleState.FAILED,
            AgentLifecycleState.TERMINATED,
        }
        if self.outcome_state not in allowed:
            raise ValueError("live result has an unsupported terminal outcome")
        started_at = self.request.attempt.started_at
        if started_at is None or not (started_at <= self.outcome_at <= self.cleanup_at):
            raise ValueError("live result timestamps must follow attempt start")
        if self.backend_id != self.request.attempt.backend_id:
            raise ValueError("live result backend does not match the attempt")
        if self.profile_id != self.request.attempt.profile_id:
            raise ValueError("live result profile does not match the attempt")
        if (
            self.outcome_state
            in {
                AgentLifecycleState.CANCELLED,
                AgentLifecycleState.TERMINATED,
            }
            and self.cancel_requested_at is None
        ):
            raise ValueError("cancelled or terminated live result requires cancellation")
        if self.cancel_requested_at is not None and not (
            started_at <= self.cancel_requested_at <= self.cleanup_at
        ):
            raise ValueError("live result cancellation time is outside execution")
        if self.outcome_state is not AgentLifecycleState.RESULT_RECEIVED and not self.reason:
            raise ValueError("non-result live outcome requires a reason")
        if (self.raw_output_sha256 is None) != (self.raw_output_size_bytes == 0):
            raise ValueError("raw output digest and non-zero size must be paired")
        links = (
            self.payload.task_id,
            self.payload.source_task_revision,
            self.payload.assignment_id,
            self.payload.attempt_id,
            self.payload.context_manifest_sha256,
        )
        expected = (
            self.request.assignment.task_id,
            self.request.assignment.source_task_revision,
            self.request.assignment.assignment_id,
            self.request.attempt.attempt_id,
            self.request.assignment.context_manifest_sha256,
        )
        if links != expected:
            raise ValueError("live result payload does not bind its request")
        payload_size = len(canonical_contract_json(self.payload).encode("utf-8"))
        if self.usage.context_bytes != self.request.context.total_size_bytes:
            raise ValueError("live result context accounting mismatch")
        if self.usage.result_bytes != payload_size:
            raise ValueError("live result payload accounting mismatch")
        if self.usage.claims_count != len(self.payload.claims):
            raise ValueError("live result claim accounting mismatch")
        if self.native_usage is not None:
            if self.outcome_state is not AgentLifecycleState.RESULT_RECEIVED:
                raise ValueError("native usage requires an admitted live result")
            if self.usage.tokens != self.native_usage.output_tokens:
                raise ValueError("live result native token accounting mismatch")
        return self


class LiveInvocationState(StrEnum):
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"


class LiveInvocationRecord(_S4ContentAddressedContract):
    """Durable no-replay record for one S4 assignment/epoch invocation."""

    record_id: str = ""
    invocation_key: str = Field(min_length=1, max_length=500)
    request: LiveBackendRequest
    state: LiveInvocationState
    reserved_at: datetime
    result: LiveBackendResult | None = None
    receipt_sha256: Sha256 | None = None
    handoff: DistilledHandoff | None = None
    completed_at: datetime | None = None

    _identity_field = "record_id"
    _identity_prefix = "c011-live-invocation:sha256:"

    @field_validator("reserved_at", "completed_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.state is LiveInvocationState.RESERVED:
            if any(
                value is not None
                for value in (
                    self.result,
                    self.receipt_sha256,
                    self.handoff,
                    self.completed_at,
                )
            ):
                raise ValueError("reserved live invocation cannot contain completion data")
            return self
        if self.result is None or self.receipt_sha256 is None or self.completed_at is None:
            raise ValueError("completed live invocation requires result and receipt")
        if self.completed_at < self.reserved_at:
            raise ValueError("live invocation cannot complete before reservation")
        if self.result.request != self.request:
            raise ValueError("live invocation result belongs to another request")
        if (
            self.handoff is not None
            and self.result.outcome_state is not AgentLifecycleState.RESULT_RECEIVED
        ):
            raise ValueError("non-result live invocation cannot contain a handoff")
        return self


class S4IntegrationStatus(StrEnum):
    DISABLED = "DISABLED"
    KILL_SWITCHED = "KILL_SWITCHED"
    NO_DELEGATION = "NO_DELEGATION"
    DENIED = "DENIED"
    COMPLETE = "COMPLETE"
    VERIFY_REQUIRED = "VERIFY_REQUIRED"


__all__ = [
    "BackendSafetyCapabilities",
    "FocusedContextBundle",
    "FocusedContextDocument",
    "LiveBackendRequest",
    "LiveBackendResult",
    "LiveInvocationRecord",
    "LiveInvocationState",
    "LiveWorkerDraft",
    "S4IntegrationStatus",
    "S4RuntimePolicy",
    "WorkerClaimDraft",
]
