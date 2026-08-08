"""Durable Phase 15 task queue with a pre-dispatch replay fence."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from luna.contracts.base import require_utc, utc_now
from luna.operations.models import (
    QueueItem,
    QueuePayload,
    QueueStatus,
    ResourceLease,
    ResourceRequirement,
    WorkEnvelope,
    WorkLease,
    canonical_payload_json,
    payload_digest,
)
from luna.operations.store import SQLiteOperationsStore
from luna.runtime import RuntimeOutcome, RuntimePriority, RuntimeStopReason

_RESUMABLE_STOPS = {
    RuntimeStopReason.CLARIFICATION_REQUIRED,
    RuntimeStopReason.CONTEXT_INCOMPLETE,
    RuntimeStopReason.CONFLICTING_EVIDENCE,
    RuntimeStopReason.INTERRUPTED,
    RuntimeStopReason.SUSPENDED,
    RuntimeStopReason.RESOURCE_SUSPENDED,
    RuntimeStopReason.VERIFICATION_PENDING,
    RuntimeStopReason.UNVERIFIED,
    RuntimeStopReason.INCONCLUSIVE,
}

_BLOCKED_STOPS = {
    RuntimeStopReason.PERMISSION_DENIED,
    RuntimeStopReason.BUDGET_EXHAUSTED,
    RuntimeStopReason.BLOCKED,
}

_FAILED_STOPS = {
    RuntimeStopReason.FAILED,
    RuntimeStopReason.INTEGRITY_FAILURE,
}


class DurableTaskQueue:
    """Persistent queue. Queue priority and timing never confer runtime authority."""

    def __init__(self, store: SQLiteOperationsStore) -> None:
        self.store = store

    @staticmethod
    def _default_idempotency_key(
        *,
        payload: QueuePayload,
        priority: RuntimePriority,
        eligible_at: datetime,
    ) -> str:
        material = "|".join(
            (
                canonical_payload_json(payload),
                priority.value,
                require_utc(eligible_at).isoformat(),
            )
        )
        return sha256(material.encode("utf-8")).hexdigest()

    def enqueue(
        self,
        *,
        envelope: WorkEnvelope,
        resources: ResourceRequirement | None = None,
        priority: RuntimePriority = RuntimePriority.NORMAL,
        eligible_at: datetime | None = None,
        idempotency_key: str | None = None,
        schedule_id: UUID | None = None,
        occurrence_index: int | None = None,
        item_id: UUID | None = None,
        now: datetime | None = None,
    ) -> QueueItem:
        """Persist one already-authorized runtime invocation idempotently."""
        current = require_utc(now or utc_now())
        eligible = require_utc(eligible_at or current)
        payload = QueuePayload(
            envelope=envelope,
            resources=resources or ResourceRequirement(),
            schedule_id=schedule_id,
            occurrence_index=occurrence_index,
        )
        key = idempotency_key or self._default_idempotency_key(
            payload=payload,
            priority=priority,
            eligible_at=eligible,
        )
        item = QueueItem(
            item_id=item_id or uuid4(),
            idempotency_key=key,
            payload=payload,
            payload_sha256=payload_digest(payload),
            priority=priority,
            eligible_at=eligible,
            created_at=current,
            updated_at=current,
        )
        return self.store.insert_queue_item(item)

    def get(self, item_id: UUID) -> QueueItem:
        return self.store.load_queue_item(item_id)

    def ready(self, *, now: datetime | None = None, limit: int = 100) -> tuple[QueueItem, ...]:
        current = require_utc(now or utc_now())
        return self.store.ready_queue_items(current.isoformat(), limit=limit)

    def lease(
        self,
        *,
        item_id: UUID,
        owner_id: str,
        resource_lease: ResourceLease,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> WorkLease:
        if lease_seconds < 1 or lease_seconds > 86_400:
            raise ValueError("queue lease_seconds must be in [1, 86400]")
        current_time = require_utc(now or utc_now())
        current = self.store.load_queue_item(item_id)
        if resource_lease.item_id != item_id:
            raise ValueError("resource lease item_id mismatch")
        if resource_lease.owner_id != owner_id:
            raise ValueError("queue lease owner must match resource lease owner")
        expected_expiry = current_time + timedelta(seconds=lease_seconds)
        if resource_lease.expires_at != expected_expiry:
            raise ValueError("queue and resource lease expiry must match")
        updated = current.model_copy(
            update={
                "status": QueueStatus.LEASED,
                "lease_owner": owner_id,
                "lease_expires_at": expected_expiry,
                "resource_lease_id": resource_lease.lease_id,
                "attempt_count": current.attempt_count + 1,
                "updated_at": current_time,
            }
        )
        stored = self.store.transition_queue_item(
            item_id=item_id,
            expected=QueueStatus.QUEUED,
            updated=updated,
        )
        return WorkLease(item=stored, resources=resource_lease)

    def mark_dispatched(
        self,
        *,
        item_id: UUID,
        dispatch_id: UUID | None = None,
        now: datetime | None = None,
    ) -> QueueItem:
        """Write the may-have-executed fence before calling LunaRuntime."""
        current_time = require_utc(now or utc_now())
        current = self.store.load_queue_item(item_id)
        updated = current.model_copy(
            update={
                "status": QueueStatus.DISPATCHED,
                "dispatch_id": dispatch_id or uuid4(),
                "dispatch_started_at": current_time,
                "updated_at": current_time,
            }
        )
        return self.store.transition_queue_item(
            item_id=item_id,
            expected=QueueStatus.LEASED,
            updated=updated,
        )

    @staticmethod
    def finalized_copy(
        current: QueueItem,
        *,
        outcome: RuntimeOutcome,
        now: datetime,
    ) -> QueueItem:
        if outcome.stop_reason is RuntimeStopReason.COMPLETED:
            status = QueueStatus.COMPLETED
        elif outcome.stop_reason is RuntimeStopReason.CANCELLED:
            status = QueueStatus.CANCELLED
        elif outcome.stop_reason in _RESUMABLE_STOPS:
            status = QueueStatus.SUSPENDED
        elif outcome.stop_reason in _BLOCKED_STOPS:
            status = QueueStatus.BLOCKED
        elif outcome.stop_reason in _FAILED_STOPS:
            status = QueueStatus.FAILED
        else:
            status = QueueStatus.BLOCKED
        return current.model_copy(
            update={
                "status": status,
                "outcome": outcome,
                "updated_at": require_utc(now),
            }
        )

    def finalize(
        self,
        *,
        item_id: UUID,
        outcome: RuntimeOutcome,
        now: datetime | None = None,
    ) -> QueueItem:
        current_time = require_utc(now or utc_now())
        current = self.store.load_queue_item(item_id)
        updated = self.finalized_copy(current, outcome=outcome, now=current_time)
        return self.store.transition_queue_item(
            item_id=item_id,
            expected=QueueStatus.DISPATCHED,
            updated=updated,
        )

    def cancel_queued(
        self,
        *,
        item_id: UUID,
        now: datetime | None = None,
    ) -> QueueItem:
        """Cancel work only before any worker lease or dispatch fence exists."""
        current_time = require_utc(now or utc_now())
        current = self.store.load_queue_item(item_id)
        updated = current.model_copy(
            update={
                "status": QueueStatus.CANCELLED,
                "updated_at": current_time,
            }
        )
        return self.store.transition_queue_item(
            item_id=item_id,
            expected=QueueStatus.QUEUED,
            updated=updated,
        )

    def expired_leases(self, *, now: datetime | None = None) -> tuple[QueueItem, ...]:
        current = require_utc(now or utc_now())
        candidates = self.store.list_queue_items(
            statuses=(QueueStatus.LEASED, QueueStatus.DISPATCHED)
        )
        return tuple(
            item
            for item in candidates
            if item.lease_expires_at is not None and item.lease_expires_at <= current
        )

    def requeue_expired_pre_dispatch(
        self,
        *,
        item_id: UUID,
        now: datetime | None = None,
    ) -> QueueItem:
        """Only an expired item with no dispatch fence may be automatically requeued."""
        current_time = require_utc(now or utc_now())
        current = self.store.load_queue_item(item_id)
        if current.lease_expires_at is None or current.lease_expires_at > current_time:
            raise ValueError("queue lease has not expired")
        updated = current.model_copy(
            update={
                "status": QueueStatus.QUEUED,
                "lease_owner": None,
                "lease_expires_at": None,
                "resource_lease_id": None,
                "updated_at": current_time,
            }
        )
        return self.store.transition_queue_item(
            item_id=item_id,
            expected=QueueStatus.LEASED,
            updated=updated,
        )

    def mark_recovery_required(
        self,
        *,
        item_id: UUID,
        now: datetime | None = None,
    ) -> QueueItem:
        """A dispatched item is never blindly replayed after lease ambiguity."""
        current_time = require_utc(now or utc_now())
        current = self.store.load_queue_item(item_id)
        updated = current.model_copy(
            update={
                "status": QueueStatus.RECOVERY_REQUIRED,
                "updated_at": current_time,
            }
        )
        return self.store.transition_queue_item(
            item_id=item_id,
            expected=QueueStatus.DISPATCHED,
            updated=updated,
        )
