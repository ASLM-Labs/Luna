"""Phase 15 durable operations contracts.

Scheduling, queueing, resource admission, and notifications are coordination layers.
They do not grant tool, network, write, process, model, or completion authority.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.autonomy import AutonomyLevel
from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import CompletionStatus, RiskLevel
from luna.runtime.models import RuntimeMode, RuntimeOutcome, RuntimePriority, RuntimeRequest
from luna.tools import ToolPolicy


class QueueStatus(StrEnum):
    """Durable work-item lifecycle outside the authoritative runtime."""

    QUEUED = "QUEUED"
    LEASED = "LEASED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class ScheduleKind(StrEnum):
    """Phase 15 schedule forms kept deliberately small and deterministic."""

    ONE_SHOT = "ONE_SHOT"
    FIXED_INTERVAL = "FIXED_INTERVAL"


class ResourceLeaseStatus(StrEnum):
    """Resource reservation state."""

    ACTIVE = "ACTIVE"
    STALE = "STALE"
    RELEASED = "RELEASED"


class NotificationKind(StrEnum):
    """Channel-neutral notification semantics derived from RuntimeOutcome."""

    TASK_VERIFIED_COMPLETE = "TASK_VERIFIED_COMPLETE"
    TASK_REQUIRES_ATTENTION = "TASK_REQUIRES_ATTENTION"
    TASK_CANCELLED = "TASK_CANCELLED"


class NotificationStatus(StrEnum):
    """Local durable outbox state. Phase 15 performs no external delivery."""

    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ResourceCapacity(LunaContractModel):
    """Coordinator capacity; never an authority grant."""

    worker_slots: int = Field(default=1, ge=1, le=1024)
    model_slots: int = Field(default=1, ge=0, le=1024)
    network_slots: int = Field(default=0, ge=0, le=1024)


class ResourceUsage(LunaContractModel):
    """Observed held coordinator capacity, including stale reservations."""

    worker_slots: int = Field(default=0, ge=0, le=1024)
    model_slots: int = Field(default=0, ge=0, le=1024)
    network_slots: int = Field(default=0, ge=0, le=1024)


class ResourceRequirement(LunaContractModel):
    """Resources required to admit one queued runtime invocation."""

    worker_slots: int = Field(default=1, ge=1, le=1024)
    model_slots: int = Field(default=1, ge=0, le=1024)
    network_slots: int = Field(default=0, ge=0, le=1024)

    def fits_within(self, capacity: ResourceCapacity) -> bool:
        return (
            self.worker_slots <= capacity.worker_slots
            and self.model_slots <= capacity.model_slots
            and self.network_slots <= capacity.network_slots
        )


_RISK_RANK = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


class WorkEnvelope(LunaContractModel):
    """Persisted runtime invocation plus its already-authorized tool policy."""

    request: RuntimeRequest
    tool_policy: ToolPolicy

    @model_validator(mode="after")
    def validate_authority_boundary(self) -> WorkEnvelope:
        policy = self.tool_policy
        request = self.request
        if policy.autonomy_level.number > request.autonomy.level.number:
            raise ValueError("queued tool policy cannot raise RuntimeRequest autonomy")
        if not set(policy.allowed_tools).issubset(request.autonomy.allowed_tools):
            raise ValueError("queued tool policy cannot grant undeclared RuntimeRequest tools")
        if _RISK_RANK[policy.max_risk] > _RISK_RANK[request.autonomy.max_risk]:
            raise ValueError("queued tool policy cannot raise RuntimeRequest risk ceiling")
        if (
            policy.free_research_contract is not None
            and request.autonomy.free_research_contract != policy.free_research_contract
        ):
            raise ValueError("queued FREE_RESEARCH contract must match RuntimeRequest authority")
        return self


class QueuePayload(LunaContractModel):
    """Immutable content of a durable work item."""

    envelope: WorkEnvelope
    resources: ResourceRequirement = Field(default_factory=ResourceRequirement)
    schedule_id: UUID | None = None
    occurrence_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_resource_boundary(self) -> QueuePayload:
        if self.resources.network_slots > 0 and not self.envelope.request.scope.network_allowed:
            raise ValueError("network resource reservation cannot manufacture network authority")
        if (self.schedule_id is None) != (self.occurrence_index is None):
            raise ValueError("scheduled queue payload requires schedule_id and occurrence_index")
        return self


def canonical_payload_json(payload: LunaContractModel) -> str:
    """Stable JSON representation used by idempotency and integrity checks."""
    import json

    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def payload_digest(payload: LunaContractModel) -> str:
    """SHA-256 of the stable JSON form."""
    return sha256(canonical_payload_json(payload).encode("utf-8")).hexdigest()


class QueueItem(LunaContractModel):
    """Durable work queue record."""

    item_id: UUID = Field(default_factory=uuid4)
    idempotency_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: QueuePayload
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    priority: RuntimePriority = RuntimePriority.NORMAL
    status: QueueStatus = QueueStatus.QUEUED
    eligible_at: datetime = Field(default_factory=utc_now)
    lease_owner: str | None = Field(default=None, max_length=200)
    lease_expires_at: datetime | None = None
    resource_lease_id: UUID | None = None
    dispatch_id: UUID | None = None
    dispatch_started_at: datetime | None = None
    attempt_count: int = Field(default=0, ge=0)
    outcome: RuntimeOutcome | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "eligible_at",
        "lease_expires_at",
        "dispatch_started_at",
        "created_at",
        "updated_at",
    )
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_record(self) -> QueueItem:
        if self.payload_sha256 != payload_digest(self.payload):
            raise ValueError("queue payload digest mismatch")
        if self.updated_at < self.created_at:
            raise ValueError("queue updated_at cannot precede created_at")
        if self.lease_expires_at is not None and self.lease_expires_at <= self.created_at:
            raise ValueError("queue lease expiry must follow creation")
        if self.status is QueueStatus.QUEUED and any(
            value is not None
            for value in (
                self.lease_owner,
                self.lease_expires_at,
                self.resource_lease_id,
                self.dispatch_id,
                self.dispatch_started_at,
                self.outcome,
            )
        ):
            raise ValueError("QUEUED item cannot carry lease, dispatch, or outcome state")
        if self.status is QueueStatus.LEASED:
            if (
                self.lease_owner is None
                or self.lease_expires_at is None
                or self.resource_lease_id is None
            ):
                raise ValueError("LEASED item requires owner, expiry, and resource lease")
            if self.dispatch_id is not None or self.dispatch_started_at is not None:
                raise ValueError("LEASED item cannot carry a dispatch fence")
        if self.status in {QueueStatus.DISPATCHED, QueueStatus.RECOVERY_REQUIRED} and (
            self.lease_owner is None
            or self.lease_expires_at is None
            or self.resource_lease_id is None
            or self.dispatch_id is None
            or self.dispatch_started_at is None
        ):
            raise ValueError(f"{self.status.value} item requires durable dispatch metadata")
        if self.outcome is not None:
            if self.dispatch_id is None or self.dispatch_started_at is None:
                raise ValueError("queue outcome requires an earlier dispatch fence")
            if self.outcome.task_id != self.payload.envelope.request.task_id:
                raise ValueError("queue outcome task_id must match queued RuntimeRequest")
            if self.outcome.request_id != self.payload.envelope.request.request_id:
                raise ValueError("queue outcome request_id must match queued RuntimeRequest")
        return self


class ScheduleSpec(LunaContractModel):
    """UTC-only deterministic schedule definition."""

    kind: ScheduleKind
    first_run_at: datetime
    interval_seconds: int | None = Field(default=None, ge=60, le=31_536_000)
    max_occurrences: int | None = Field(default=None, ge=1, le=100_000)

    @field_validator("first_run_at")
    @classmethod
    def validate_first_run_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_shape(self) -> ScheduleSpec:
        if self.kind is ScheduleKind.ONE_SHOT:
            if self.interval_seconds is not None:
                raise ValueError("ONE_SHOT schedule cannot define interval_seconds")
            if self.max_occurrences not in {None, 1}:
                raise ValueError("ONE_SHOT max_occurrences can only be 1")
        else:
            if self.interval_seconds is None:
                raise ValueError("FIXED_INTERVAL requires interval_seconds")
        return self


class ScheduledJob(LunaContractModel):
    """Durable schedule whose only power is to materialize queue work."""

    schedule_id: UUID = Field(default_factory=uuid4)
    envelope: WorkEnvelope
    resources: ResourceRequirement = Field(default_factory=ResourceRequirement)
    priority: RuntimePriority = RuntimePriority.NORMAL
    spec: ScheduleSpec
    next_run_at: datetime
    occurrence_count: int = Field(default=0, ge=0)
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("next_run_at", "created_at", "updated_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_job(self) -> ScheduledJob:
        if self.next_run_at < self.spec.first_run_at:
            raise ValueError("next_run_at cannot precede schedule start")
        if self.spec.kind is ScheduleKind.FIXED_INTERVAL:
            if self.envelope.request.mode is RuntimeMode.RESUME:
                raise ValueError("recurring schedule cannot clone a RESUME request")
            if self.envelope.request.autonomy.level is AutonomyLevel.LEVEL_4_FREE_RESEARCH:
                raise ValueError(
                    "recurring schedule cannot clone task-bound FREE_RESEARCH authority"
                )
        if self.resources.network_slots > 0 and not self.envelope.request.scope.network_allowed:
            raise ValueError("schedule resources cannot manufacture network authority")
        return self


class ResourceLease(LunaContractModel):
    """Durable capacity reservation associated with one queue item."""

    lease_id: UUID = Field(default_factory=uuid4)
    item_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    requirement: ResourceRequirement
    status: ResourceLeaseStatus = ResourceLeaseStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    released_at: datetime | None = None

    @field_validator("created_at", "expires_at", "released_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_lease(self) -> ResourceLease:
        if self.expires_at <= self.created_at:
            raise ValueError("resource lease expiry must follow creation")
        if self.status is ResourceLeaseStatus.RELEASED:
            if self.released_at is None:
                raise ValueError("released resource lease requires released_at")
        elif self.released_at is not None:
            raise ValueError("non-released resource lease cannot carry released_at")
        return self


class WorkLease(LunaContractModel):
    """Queue lease and resource lease returned together to a worker."""

    item: QueueItem
    resources: ResourceLease

    @model_validator(mode="after")
    def validate_links(self) -> WorkLease:
        if self.item.item_id != self.resources.item_id:
            raise ValueError("queue and resource lease must reference the same item")
        if self.item.resource_lease_id != self.resources.lease_id:
            raise ValueError("queue item must reference the returned resource lease")
        return self


class NotificationEvent(LunaContractModel):
    """Evidence-bound local event; no Phase 15 transport can send it externally."""

    notification_id: UUID = Field(default_factory=uuid4)
    item_id: UUID
    task_id: UUID
    outcome_id: UUID
    kind: NotificationKind
    status: NotificationStatus = NotificationStatus.PENDING
    stop_reason: str = Field(min_length=1, max_length=100)
    completion_status: CompletionStatus | None = None
    verification_report_id: UUID | None = None
    final_report_id: UUID | None = None
    checkpoint_id: UUID | None = None
    message: str = Field(min_length=1, max_length=2000)
    dedupe_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    external_delivery_allowed: Literal[False] = False
    created_at: datetime = Field(default_factory=utc_now)
    acknowledged_at: datetime | None = None

    @field_validator("created_at", "acknowledged_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_truth_boundary(self) -> NotificationEvent:
        if self.kind is NotificationKind.TASK_VERIFIED_COMPLETE:
            if self.completion_status is not CompletionStatus.VERIFIED_COMPLETE:
                raise ValueError("verified-complete notification requires VERIFIED_COMPLETE")
            if self.verification_report_id is None or self.final_report_id is None:
                raise ValueError(
                    "verified-complete notification requires verification and final report"
                )
        if self.status is NotificationStatus.ACKNOWLEDGED:
            if self.acknowledged_at is None:
                raise ValueError("acknowledged notification requires timestamp")
        elif self.acknowledged_at is not None:
            raise ValueError("pending notification cannot carry acknowledged_at")
        return self


class DispatchResultStatus(StrEnum):
    """One coordinator dispatch attempt."""

    NO_WORK = "NO_WORK"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class DispatchResult(LunaContractModel):
    """Coordinator return value; never substitutes for RuntimeOutcome truth."""

    status: DispatchResultStatus
    item_id: UUID | None = None
    outcome: RuntimeOutcome | None = None
    notification_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_shape(self) -> DispatchResult:
        if self.status is DispatchResultStatus.NO_WORK:
            if any(
                value is not None
                for value in (self.item_id, self.outcome, self.notification_id)
            ):
                raise ValueError("NO_WORK result cannot carry work state")
        elif self.item_id is None:
            raise ValueError("dispatch result requires item_id")
        if self.status is DispatchResultStatus.OUTCOME_RECORDED and self.outcome is None:
            raise ValueError("OUTCOME_RECORDED requires RuntimeOutcome")
        if self.status is DispatchResultStatus.RECOVERY_REQUIRED and self.outcome is not None:
            raise ValueError("RECOVERY_REQUIRED cannot claim a RuntimeOutcome")
        return self
