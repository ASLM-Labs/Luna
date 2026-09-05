"""Durable C-011 S2/S3 event, lease, fake-backend, and control contracts.

The contracts in this module describe runtime-authored evidence, but do not wire a
live worker, model, tool, network client, process, or Luna runtime.  Raw root-lease
tokens are intentionally confined to :class:`RootLeaseHandle`; durable records carry
only their SHA-256 digest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    ReadOnlyContextManifest,
    Sha256,
    canonical_contract_json,
    contract_sha256,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _identity_digest(model: C011ContractModel, identity_field: str) -> str:
    payload = model.model_dump(mode="json", exclude={identity_field})
    basis = {
        "contract_type": f"{type(model).__module__}.{type(model).__qualname__}",
        "schema_version": model.schema_version,
        "payload": payload,
    }
    return sha256(_canonical_json(basis).encode("utf-8")).hexdigest()


class _S2ContentAddressedContract(C011ContractModel):
    _identity_field: ClassVar[str]
    _identity_prefix: ClassVar[str]

    @model_validator(mode="after")
    def validate_content_identity(self) -> Self:
        expected = self._identity_prefix + _identity_digest(self, self._identity_field)
        supplied = getattr(self, self._identity_field)
        if not supplied:
            object.__setattr__(self, self._identity_field, expected)
        elif supplied != expected:
            raise ValueError(
                f"{self._identity_field} does not match canonical contract content"
            )
        return self


class RootLeaseStatus(StrEnum):
    """Durable root-lease state."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


class RootLeaseRecord(C011ContractModel):
    """Persistable lease record that never contains the bearer token."""

    lease_id: UUID
    task_id: UUID
    root_owner_ref: str = Field(min_length=1, max_length=500)
    root_instance_id: UUID
    epoch: int = Field(ge=1)
    lease_version: int = Field(default=1, ge=1)
    token_sha256: Sha256
    acquired_at: datetime
    expires_at: datetime
    status: RootLeaseStatus
    ended_at: datetime | None = None

    @field_validator("acquired_at", "expires_at", "ended_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def validate_lease(self) -> Self:
        if self.expires_at <= self.acquired_at:
            raise ValueError("root lease expiry must be after acquisition")
        if self.status is RootLeaseStatus.ACTIVE:
            if self.ended_at is not None:
                raise ValueError("active root lease cannot have ended_at")
        elif self.ended_at is None:
            raise ValueError("ended root lease requires ended_at")
        elif self.ended_at < self.acquired_at:
            raise ValueError("root lease cannot end before acquisition")
        if (
            self.status is RootLeaseStatus.EXPIRED
            and self.ended_at is not None
            and self.ended_at < self.expires_at
        ):
            raise ValueError("expired root lease cannot end before its expiry")
        return self

    @property
    def coordination_epoch(self) -> int:
        """Alias used by event and store boundaries."""

        return self.epoch


@dataclass(frozen=True, slots=True)
class RootLeaseHandle:
    """Ephemeral bearer handle; the raw token is excluded from repr and persistence."""

    record: RootLeaseRecord
    token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("root lease token must not be blank")
        digest = sha256(self.token.encode("utf-8")).hexdigest()
        if digest != self.record.token_sha256:
            raise ValueError("root lease token does not match its durable digest")
        if self.record.status is not RootLeaseStatus.ACTIVE:
            raise ValueError("root lease handle requires an active record")


class CoordinationEventKind(StrEnum):
    """Closed vocabulary for S2 runtime-authored coordination evidence."""

    ROOT_LEASE_ACQUIRED = "ROOT_LEASE_ACQUIRED"
    ROOT_LEASE_RENEWED = "ROOT_LEASE_RENEWED"
    ROOT_LEASE_EXPIRED = "ROOT_LEASE_EXPIRED"
    ROOT_LEASE_RELEASED = "ROOT_LEASE_RELEASED"
    ATTEMPT_TRANSITION = "ATTEMPT_TRANSITION"
    FAKE_INVOCATION_RESERVED = "FAKE_INVOCATION_RESERVED"
    FAKE_RESULT_RECORDED = "FAKE_RESULT_RECORDED"
    EXECUTION_RECEIPT_RECORDED = "EXECUTION_RECEIPT_RECORDED"
    RECOVERY_DECISION_RECORDED = "RECOVERY_DECISION_RECORDED"
    S3_CONTROL_RECORDED = "S3_CONTROL_RECORDED"


_ALLOWED_ATTEMPT_TRANSITIONS: dict[
    AgentLifecycleState | None, frozenset[AgentLifecycleState]
] = {
    None: frozenset({AgentLifecycleState.PROPOSED}),
    AgentLifecycleState.PROPOSED: frozenset(
        {AgentLifecycleState.ADMITTED, AgentLifecycleState.DENIED}
    ),
    AgentLifecycleState.ADMITTED: frozenset(
        {
            AgentLifecycleState.CREATED,
            AgentLifecycleState.CANCEL_REQUESTED,
            AgentLifecycleState.TIMED_OUT,
        }
    ),
    AgentLifecycleState.DENIED: frozenset({AgentLifecycleState.CLOSED}),
    AgentLifecycleState.CREATED: frozenset(
        {
            AgentLifecycleState.STARTED,
            AgentLifecycleState.CANCEL_REQUESTED,
            AgentLifecycleState.TIMED_OUT,
        }
    ),
    AgentLifecycleState.STARTED: frozenset(
        {
            AgentLifecycleState.RESULT_RECEIVED,
            AgentLifecycleState.CANCEL_REQUESTED,
            AgentLifecycleState.TIMED_OUT,
            AgentLifecycleState.FAILED,
        }
    ),
    AgentLifecycleState.RESULT_RECEIVED: frozenset(
        {
            AgentLifecycleState.CLEANUP_COMPLETE,
            AgentLifecycleState.CLEANUP_FAILED,
        }
    ),
    AgentLifecycleState.CANCEL_REQUESTED: frozenset(
        {AgentLifecycleState.CANCELLED, AgentLifecycleState.TERMINATED}
    ),
    AgentLifecycleState.TIMED_OUT: frozenset(
        {
            AgentLifecycleState.CLEANUP_COMPLETE,
            AgentLifecycleState.CLEANUP_FAILED,
        }
    ),
    AgentLifecycleState.FAILED: frozenset(
        {
            AgentLifecycleState.CLEANUP_COMPLETE,
            AgentLifecycleState.CLEANUP_FAILED,
        }
    ),
    AgentLifecycleState.CANCELLED: frozenset(
        {
            AgentLifecycleState.CLEANUP_COMPLETE,
            AgentLifecycleState.CLEANUP_FAILED,
        }
    ),
    AgentLifecycleState.TERMINATED: frozenset(
        {
            AgentLifecycleState.CLEANUP_COMPLETE,
            AgentLifecycleState.CLEANUP_FAILED,
        }
    ),
    AgentLifecycleState.CLEANUP_COMPLETE: frozenset(
        {AgentLifecycleState.RECONCILED, AgentLifecycleState.CLOSED}
    ),
    AgentLifecycleState.CLEANUP_FAILED: frozenset(
        {AgentLifecycleState.VERIFY_REQUIRED, AgentLifecycleState.CLOSED}
    ),
    AgentLifecycleState.RECONCILED: frozenset(
        {
            AgentLifecycleState.ADOPTED,
            AgentLifecycleState.REJECTED,
            AgentLifecycleState.VERIFY_REQUIRED,
        }
    ),
    AgentLifecycleState.ADOPTED: frozenset({AgentLifecycleState.CLOSED}),
    AgentLifecycleState.REJECTED: frozenset({AgentLifecycleState.CLOSED}),
    AgentLifecycleState.VERIFY_REQUIRED: frozenset({AgentLifecycleState.CLOSED}),
    AgentLifecycleState.CLOSED: frozenset(),
}


def validate_attempt_transition(
    from_state: AgentLifecycleState | None,
    to_state: AgentLifecycleState,
) -> None:
    """Fail closed unless an attempt transition is explicitly allowed."""

    allowed = _ALLOWED_ATTEMPT_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        source = "NONE" if from_state is None else from_state.value
        raise ValueError(f"unsupported C-011 attempt transition: {source}->{to_state.value}")


class CoordinationEvent(C011ContractModel):
    """One immutable event in a per-task, hash-linked coordination journal."""

    event_id: UUID
    task_id: UUID
    task_sequence: int = Field(ge=1)
    kind: CoordinationEventKind
    subject_id: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=500)
    intent_sha256: Sha256
    root_lease_id: UUID
    root_owner_ref: str = Field(min_length=1, max_length=500)
    root_instance_id: UUID
    root_coordination_epoch: int = Field(ge=1)
    occurred_at: datetime
    previous_event_sha256: Sha256 | None = None
    attempt_id: str | None = Field(default=None, max_length=208)
    from_state: AgentLifecycleState | None = None
    to_state: AgentLifecycleState | None = None
    artifact_ref: str | None = Field(default=None, max_length=1000)
    artifact_sha256: Sha256 | None = None
    lease_expires_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=2000)
    event_sha256: str = ""
    runtime_authored: Literal[True] = True

    @field_validator("occurred_at", "lease_expires_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @field_validator("attempt_id")
    @classmethod
    def validate_attempt_id(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("attempt:"):
            raise ValueError("coordination attempt_id must use the attempt: namespace")
        return value

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if self.task_sequence == 1:
            if self.previous_event_sha256 is not None:
                raise ValueError("first coordination event cannot have a previous hash")
        elif self.previous_event_sha256 is None:
            raise ValueError("non-first coordination event requires a previous hash")

        if (self.artifact_ref is None) is not (self.artifact_sha256 is None):
            raise ValueError("artifact reference and digest must be supplied together")

        lease_kinds = {
            CoordinationEventKind.ROOT_LEASE_ACQUIRED,
            CoordinationEventKind.ROOT_LEASE_RENEWED,
            CoordinationEventKind.ROOT_LEASE_EXPIRED,
            CoordinationEventKind.ROOT_LEASE_RELEASED,
        }
        artifact_kinds = {
            CoordinationEventKind.FAKE_INVOCATION_RESERVED,
            CoordinationEventKind.FAKE_RESULT_RECORDED,
            CoordinationEventKind.EXECUTION_RECEIPT_RECORDED,
            CoordinationEventKind.RECOVERY_DECISION_RECORDED,
        }

        if self.kind in lease_kinds:
            if any(
                value is not None
                for value in (self.attempt_id, self.from_state, self.to_state)
            ):
                raise ValueError("root lease event cannot claim an attempt transition")
            if self.artifact_ref is not None:
                raise ValueError("root lease event cannot claim an artifact")
            if self.kind in {
                CoordinationEventKind.ROOT_LEASE_ACQUIRED,
                CoordinationEventKind.ROOT_LEASE_RENEWED,
            }:
                if self.lease_expires_at is None:
                    raise ValueError("active root lease event requires lease expiry")
                if self.lease_expires_at <= self.occurred_at:
                    raise ValueError("active root lease event requires a future expiry")
            elif not self.reason:
                raise ValueError("ended root lease event requires a reason")
        elif self.kind is CoordinationEventKind.ATTEMPT_TRANSITION:
            if self.attempt_id is None or self.to_state is None:
                raise ValueError("attempt transition requires attempt_id and to_state")
            validate_attempt_transition(self.from_state, self.to_state)
        elif self.kind in artifact_kinds:
            if self.attempt_id is None:
                raise ValueError("attempt artifact event requires attempt_id")
            if self.from_state is not None or self.to_state is not None:
                raise ValueError("artifact event cannot claim an attempt transition")
            if self.artifact_ref is None:
                raise ValueError("artifact event requires a bound artifact")
            if (
                self.kind is CoordinationEventKind.RECOVERY_DECISION_RECORDED
                and not self.reason
            ):
                raise ValueError("recovery decision event requires a reason")

        expected = _identity_digest(self, "event_sha256")
        if not self.event_sha256:
            object.__setattr__(self, "event_sha256", expected)
        elif self.event_sha256 != expected:
            raise ValueError("event_sha256 does not match canonical event content")
        return self

    @property
    def event_ref(self) -> str:
        return f"c011-event:{self.event_id}:sha256:{self.event_sha256}"


class FakeBackendRequest(_S2ContentAddressedContract):
    """Content-addressed request for the deterministic, non-live S2 backend."""

    _identity_field = "request_id"
    _identity_prefix = "c011-fake-request:sha256:"

    request_id: str = ""
    assignment: AssignmentSemanticSpec
    attempt: AgentExecutionAttempt
    context: ReadOnlyContextManifest
    script_sha256: Sha256
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_request_chain(self) -> Self:
        if self.attempt.lifecycle_state is not AgentLifecycleState.STARTED:
            raise ValueError("fake backend request requires a STARTED attempt")
        if self.attempt.started_at is None:
            raise ValueError("fake backend request requires attempt started_at")
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
            raise ValueError("fake backend attempt does not bind the assignment")
        if (
            self.context.task_id != self.assignment.task_id
            or self.context.source_task_revision
            != self.assignment.source_task_revision
            or contract_sha256(self.context)
            != self.assignment.context_manifest_sha256
        ):
            raise ValueError("fake backend context does not bind the assignment")
        if not (self.attempt.started_at <= self.requested_at < self.attempt.deadline_at):
            raise ValueError("fake backend request must occur while attempt is live")
        return self

    @property
    def request_sha256(self) -> str:
        return contract_sha256(self)


class FakeBackendScript(_S2ContentAddressedContract):
    """Frozen deterministic output fixture; it performs no execution."""

    _identity_field = "script_id"
    _identity_prefix = "c011-fake-script:sha256:"

    script_id: str = ""
    payload: AgentPayload
    outcome_state: AgentLifecycleState
    cleanup_state: CleanupState
    outcome_at: datetime
    cleanup_at: datetime
    tokens: int = Field(ge=0)
    runtime_ms: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("outcome_at", "cleanup_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_script(self) -> Self:
        allowed = {
            AgentLifecycleState.RESULT_RECEIVED,
            AgentLifecycleState.FAILED,
            AgentLifecycleState.TIMED_OUT,
        }
        if self.outcome_state not in allowed:
            raise ValueError("fake script outcome is outside the S2 closed vocabulary")
        if self.cleanup_at < self.outcome_at:
            raise ValueError("fake script cleanup cannot precede its outcome")
        if self.outcome_state is not AgentLifecycleState.RESULT_RECEIVED and not self.reason:
            raise ValueError("non-result fake script requires a reason")
        return self

    @property
    def script_sha256(self) -> str:
        return contract_sha256(self)


class FakeBackendResult(_S2ContentAddressedContract):
    """Raw fake observation exactly bound to its request and frozen script."""

    _identity_field = "result_id"
    _identity_prefix = "c011-fake-result:sha256:"

    result_id: str = ""
    request: FakeBackendRequest
    script: FakeBackendScript
    backend_id: str = Field(min_length=1, max_length=500)
    profile_id: str = Field(min_length=1, max_length=500)
    usage: AgentResourceUsage

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.request.script_sha256 != contract_sha256(self.script):
            raise ValueError("fake result script does not match the requested digest")
        if self.request.attempt.backend_id != self.backend_id:
            raise ValueError("fake result backend does not match the started attempt")
        if self.request.attempt.profile_id != self.profile_id:
            raise ValueError("fake result profile does not match the started attempt")
        payload = self.script.payload
        if (
            payload.task_id,
            payload.source_task_revision,
            payload.assignment_id,
            payload.attempt_id,
            payload.context_manifest_sha256,
        ) != (
            self.request.assignment.task_id,
            self.request.assignment.source_task_revision,
            self.request.assignment.assignment_id,
            self.request.attempt.attempt_id,
            self.request.assignment.context_manifest_sha256,
        ):
            raise ValueError("fake result payload does not bind the request")
        started_at = self.request.attempt.started_at
        if started_at is None or self.script.outcome_at < started_at:
            raise ValueError("fake result outcome cannot precede attempt start")
        expected_usage = AgentResourceUsage(
            context_bytes=self.request.context.total_size_bytes,
            result_bytes=len(canonical_contract_json(payload).encode("utf-8")),
            claims_count=len(payload.claims),
            tokens=self.script.tokens,
            runtime_ms=self.script.runtime_ms,
        )
        if self.usage != expected_usage:
            raise ValueError("fake result usage is not derived from request and script")
        return self

    @classmethod
    def from_request_script(
        cls,
        request: FakeBackendRequest,
        script: FakeBackendScript,
        *,
        backend_id: str,
        profile_id: str,
    ) -> Self:
        usage = AgentResourceUsage(
            context_bytes=request.context.total_size_bytes,
            result_bytes=len(canonical_contract_json(script.payload).encode("utf-8")),
            claims_count=len(script.payload.claims),
            tokens=script.tokens,
            runtime_ms=script.runtime_ms,
        )
        return cls(
            request=request,
            script=script,
            backend_id=backend_id,
            profile_id=profile_id,
            usage=usage,
        )

    @property
    def result_sha256(self) -> str:
        return contract_sha256(self)

    @property
    def payload(self) -> AgentPayload:
        return self.script.payload

    @property
    def outcome_state(self) -> AgentLifecycleState:
        return self.script.outcome_state

    @property
    def cleanup_state(self) -> CleanupState:
        return self.script.cleanup_state

    @property
    def outcome_at(self) -> datetime:
        return self.script.outcome_at

    @property
    def cleanup_at(self) -> datetime:
        return self.script.cleanup_at


class FakeInvocationState(StrEnum):
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"


class FakeInvocationRecord(C011ContractModel):
    """Durable idempotency record for one fake-backend request."""

    invocation_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=500)
    request: FakeBackendRequest
    state: FakeInvocationState
    reserved_at: datetime
    completed_at: datetime | None = None
    result: FakeBackendResult | None = None
    durable_completion_count: int = Field(ge=0, le=1)
    record_sha256: str = ""

    @field_validator("reserved_at", "completed_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if self.state is FakeInvocationState.RESERVED:
            if self.completed_at is not None or self.result is not None:
                raise ValueError("reserved fake invocation cannot contain a result")
            if self.durable_completion_count != 0:
                raise ValueError("reserved fake invocation has no durable completion")
        else:
            if self.completed_at is None or self.result is None:
                raise ValueError("completed fake invocation requires a result")
            if self.completed_at < self.reserved_at:
                raise ValueError("fake invocation cannot complete before reservation")
            if self.durable_completion_count != 1:
                raise ValueError("completed fake invocation requires one durable completion")
            if self.result.request != self.request:
                raise ValueError("fake invocation result is bound to another request")
        expected = _identity_digest(self, "record_sha256")
        if not self.record_sha256:
            object.__setattr__(self, "record_sha256", expected)
        elif self.record_sha256 != expected:
            raise ValueError("fake invocation record digest mismatch")
        return self


class RecoveryDisposition(StrEnum):
    """Fail-closed restart choices; no member authorizes blind replay."""

    NO_ACTION = "NO_ACTION"
    RECEIPT_REUSED = "RECEIPT_REUSED"
    NO_REPLAY = "NO_REPLAY"
    MANUAL_RECONCILIATION = "MANUAL_RECONCILIATION"


class AttemptRecoveryRecord(_S2ContentAddressedContract):
    """Immutable decision for one attempt observed during restart recovery."""

    _identity_field = "recovery_id"
    _identity_prefix = "c011-recovery:sha256:"

    recovery_id: str = ""
    task_id: UUID
    attempt_id: str = Field(pattern=r"^attempt:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    root_coordination_epoch: int = Field(ge=1)
    disposition: RecoveryDisposition
    reason: str = Field(min_length=1, max_length=2000)
    event_head_sha256: Sha256 | None = None
    receipt_ref: str | None = Field(default=None, max_length=1000)
    receipt_sha256: Sha256 | None = None
    decided_at: datetime
    runtime_authored: Literal[True] = True

    @field_validator("decided_at")
    @classmethod
    def validate_decided_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_recovery(self) -> Self:
        if (self.receipt_ref is None) is not (self.receipt_sha256 is None):
            raise ValueError("recovery receipt reference and digest must be paired")
        if (
            self.disposition is RecoveryDisposition.RECEIPT_REUSED
            and self.receipt_ref is None
        ):
            raise ValueError("receipt reuse recovery requires a durable receipt")
        if (
            self.disposition in {
                RecoveryDisposition.NO_ACTION,
                RecoveryDisposition.NO_REPLAY,
            }
            and self.receipt_ref is not None
        ):
            raise ValueError("non-receipt recovery cannot claim a receipt")
        return self


__all__ = [
    "AttemptRecoveryRecord",
    "CoordinationEvent",
    "CoordinationEventKind",
    "FakeBackendRequest",
    "FakeBackendResult",
    "FakeBackendScript",
    "FakeInvocationRecord",
    "FakeInvocationState",
    "RecoveryDisposition",
    "RootLeaseHandle",
    "RootLeaseRecord",
    "RootLeaseStatus",
    "validate_attempt_transition",
]
