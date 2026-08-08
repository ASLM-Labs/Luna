"""Resource admission for Phase 15 queued runtime invocations."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from luna.contracts.base import require_utc, utc_now
from luna.operations.models import (
    QueueStatus,
    ResourceCapacity,
    ResourceLease,
    ResourceLeaseStatus,
    ResourceRequirement,
    ResourceUsage,
)
from luna.operations.queue import DurableTaskQueue
from luna.operations.store import SQLiteOperationsStore


class ResourceManager:
    """Durable capacity ledger that cannot expand a RuntimeRequest's authority."""

    def __init__(self, store: SQLiteOperationsStore, capacity: ResourceCapacity) -> None:
        self.store = store
        self.capacity = capacity

    def acquire(
        self,
        *,
        item_id: UUID,
        owner_id: str,
        requirement: ResourceRequirement,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> ResourceLease | None:
        if lease_seconds < 1 or lease_seconds > 86_400:
            raise ValueError("resource lease_seconds must be in [1, 86400]")
        current = require_utc(now or utc_now())
        if not requirement.fits_within(self.capacity):
            return None
        item = self.store.load_queue_item(item_id)
        if item.status is not QueueStatus.QUEUED:
            return None
        if requirement != item.payload.resources:
            raise ValueError("resource requirement must match immutable queue payload")
        lease = ResourceLease(
            item_id=item_id,
            owner_id=owner_id,
            requirement=requirement,
            created_at=current,
            expires_at=current + timedelta(seconds=lease_seconds),
        )
        return self.store.allocate_resource_lease(lease=lease, capacity=self.capacity)

    def release(self, lease_id: UUID, *, now: datetime | None = None) -> ResourceLease:
        current_time = require_utc(now or utc_now())
        current = self.store.load_resource_lease(lease_id)
        if current.status is ResourceLeaseStatus.RELEASED:
            return current
        updated = current.model_copy(
            update={
                "status": ResourceLeaseStatus.RELEASED,
                "released_at": current_time,
            }
        )
        return self.store.update_resource_lease(
            lease_id=lease_id,
            expected=current.status,
            updated=updated,
        )

    def mark_stale(self, lease_id: UUID) -> ResourceLease:
        current = self.store.load_resource_lease(lease_id)
        if current.status is ResourceLeaseStatus.STALE:
            return current
        if current.status is ResourceLeaseStatus.RELEASED:
            return current
        updated = current.model_copy(update={"status": ResourceLeaseStatus.STALE})
        return self.store.update_resource_lease(
            lease_id=lease_id,
            expected=ResourceLeaseStatus.ACTIVE,
            updated=updated,
        )

    def held_usage(self) -> ResourceUsage:
        """Count ACTIVE plus STALE reservations; ambiguity never frees capacity silently."""
        held = self.store.list_resource_leases(
            statuses=(ResourceLeaseStatus.ACTIVE, ResourceLeaseStatus.STALE)
        )
        return ResourceUsage(
            worker_slots=sum(item.requirement.worker_slots for item in held),
            model_slots=sum(item.requirement.model_slots for item in held),
            network_slots=sum(item.requirement.network_slots for item in held),
        )

    def recover_expired(
        self,
        queue: DurableTaskQueue,
        *,
        now: datetime | None = None,
    ) -> tuple[int, int]:
        """Safely reclaim only pre-dispatch leases; dispatched ambiguity requires review."""
        current = require_utc(now or utc_now())
        requeued = 0
        ambiguous = 0
        for item in queue.expired_leases(now=current):
            lease_id = item.resource_lease_id
            if lease_id is None:
                raise ValueError("leased queue item is missing resource lease ID")
            if item.status is QueueStatus.LEASED:
                self.release(lease_id, now=current)
                queue.requeue_expired_pre_dispatch(item_id=item.item_id, now=current)
                requeued += 1
            elif item.status is QueueStatus.DISPATCHED:
                self.mark_stale(lease_id)
                queue.mark_recovery_required(item_id=item.item_id, now=current)
                ambiguous += 1
        return requeued, ambiguous
