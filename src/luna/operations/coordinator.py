"""Phase 15 coordinator: queue/resource admission around the authoritative Luna runtime."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime
from typing import Protocol

from luna.contracts.base import require_utc, utc_now
from luna.operations.models import (
    DispatchResult,
    DispatchResultStatus,
    QueueStatus,
    ResourceLeaseStatus,
    WorkLease,
)
from luna.operations.notifications import NotificationOutbox
from luna.operations.queue import DurableTaskQueue
from luna.operations.resources import ResourceManager
from luna.operations.scheduler import Scheduler
from luna.operations.store import OperationsConflictError
from luna.runtime import RuntimeMode, RuntimeOutcome, RuntimeRequest
from luna.tools import ToolPolicy


class RuntimeExecutor(Protocol):
    """Only this boundary may turn eligible queued work into runtime execution."""

    def run(self, *, request: RuntimeRequest, tool_policy: ToolPolicy) -> RuntimeOutcome: ...

    def resume(self, *, request: RuntimeRequest, tool_policy: ToolPolicy) -> RuntimeOutcome: ...


class OperationsCoordinator:
    """Admit at most one runtime invocation per dispatch call."""

    def __init__(
        self,
        *,
        queue: DurableTaskQueue,
        scheduler: Scheduler,
        resources: ResourceManager,
        notifications: NotificationOutbox,
        runtime: RuntimeExecutor,
    ) -> None:
        self.queue = queue
        self.scheduler = scheduler
        self.resources = resources
        self.notifications = notifications
        self.runtime = runtime
        stores = {
            queue.store.path,
            scheduler.store.path,
            resources.store.path,
            notifications.store.path,
        }
        if len(stores) != 1:
            raise ValueError("Phase 15 components must share one SQLiteOperationsStore database")

    def materialize_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 32,
    ) -> int:
        """Move due schedule occurrences into the queue; never invoke the runtime."""
        return len(self.scheduler.materialize_due(now=now, limit=limit))

    def _claim_one(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> WorkLease | None:
        for item in self.queue.ready(now=now):
            lease = self.resources.acquire(
                item_id=item.item_id,
                owner_id=worker_id,
                requirement=item.payload.resources,
                lease_seconds=lease_seconds,
                now=now,
            )
            if lease is None:
                continue
            try:
                return self.queue.lease(
                    item_id=item.item_id,
                    owner_id=worker_id,
                    resource_lease=lease,
                    lease_seconds=lease_seconds,
                    now=now,
                )
            except OperationsConflictError:
                self.resources.release(lease.lease_id, now=now)
                continue
        return None

    def dispatch_one(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> DispatchResult:
        """Dispatch one eligible item through LunaRuntime with a pre-call durable fence."""
        current = require_utc(now or utc_now())
        self.resources.recover_expired(self.queue, now=current)
        lease = self._claim_one(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            now=current,
        )
        if lease is None:
            return DispatchResult(status=DispatchResultStatus.NO_WORK)

        dispatched = self.queue.mark_dispatched(item_id=lease.item.item_id, now=current)
        envelope = dispatched.payload.envelope
        try:
            if envelope.request.mode is RuntimeMode.RESUME:
                outcome = self.runtime.resume(
                    request=envelope.request,
                    tool_policy=envelope.tool_policy,
                )
            else:
                outcome = self.runtime.run(
                    request=envelope.request,
                    tool_policy=envelope.tool_policy,
                )
        except Exception as exc:
            self.resources.mark_stale(lease.resources.lease_id)
            with suppress(OperationsConflictError):
                self.queue.mark_recovery_required(item_id=dispatched.item_id, now=current)
            return DispatchResult(
                status=DispatchResultStatus.RECOVERY_REQUIRED,
                item_id=dispatched.item_id,
                reason=f"runtime invocation became ambiguous: {type(exc).__name__}",
            )

        finalized = self.queue.finalized_copy(dispatched, outcome=outcome, now=current)
        current_resource = self.resources.store.load_resource_lease(lease.resources.lease_id)
        if current_resource.status not in {
            ResourceLeaseStatus.ACTIVE,
            ResourceLeaseStatus.STALE,
        }:
            return DispatchResult(
                status=DispatchResultStatus.RECOVERY_REQUIRED,
                item_id=dispatched.item_id,
                reason="resource lease was released before runtime outcome finalization",
            )
        released = current_resource.model_copy(
            update={
                "status": ResourceLeaseStatus.RELEASED,
                "released_at": current,
            }
        )
        event = self.notifications.build_event(
            item=finalized,
            outcome=outcome,
            now=current,
        )
        stored_event = self.queue.store.finalize_dispatch_atomically(
            current_item=dispatched,
            updated_item=finalized,
            current_lease=current_resource,
            released_lease=released,
            event=event,
        )
        stored_item = self.queue.get(dispatched.item_id)
        if stored_item.status is QueueStatus.RECOVERY_REQUIRED:
            return DispatchResult(
                status=DispatchResultStatus.RECOVERY_REQUIRED,
                item_id=stored_item.item_id,
                reason="queue entered recovery-required state during finalization",
            )
        return DispatchResult(
            status=DispatchResultStatus.OUTCOME_RECORDED,
            item_id=stored_item.item_id,
            outcome=outcome,
            notification_id=stored_event.notification_id,
        )
