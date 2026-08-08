"""Channel-neutral local notification outbox for authoritative runtime outcomes."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from uuid import UUID

from luna.contracts.base import require_utc, utc_now
from luna.operations.models import (
    NotificationEvent,
    NotificationKind,
    NotificationStatus,
    QueueItem,
)
from luna.operations.store import SQLiteOperationsStore
from luna.runtime import RuntimeOutcome, RuntimeStopReason


class NotificationOutbox:
    """Persist evidence-bound events without performing any external delivery."""

    def __init__(self, store: SQLiteOperationsStore) -> None:
        self.store = store

    @staticmethod
    def _kind(outcome: RuntimeOutcome) -> NotificationKind:
        if outcome.stop_reason is RuntimeStopReason.COMPLETED:
            return NotificationKind.TASK_VERIFIED_COMPLETE
        if outcome.stop_reason is RuntimeStopReason.CANCELLED:
            return NotificationKind.TASK_CANCELLED
        return NotificationKind.TASK_REQUIRES_ATTENTION

    @staticmethod
    def _message(kind: NotificationKind, outcome: RuntimeOutcome) -> str:
        if kind is NotificationKind.TASK_VERIFIED_COMPLETE:
            return "Task reached runtime-verified completion."
        if kind is NotificationKind.TASK_CANCELLED:
            return "Task was cancelled by the runtime control boundary."
        return f"Task returned control with stop reason {outcome.stop_reason.value}."

    @classmethod
    def build_event(
        cls,
        *,
        item: QueueItem,
        outcome: RuntimeOutcome,
        now: datetime,
    ) -> NotificationEvent:
        """Build an event from authoritative RuntimeOutcome without sending it."""
        if item.outcome != outcome:
            raise ValueError("notification requires a queue item finalized with this outcome")
        if outcome.task_id != item.payload.envelope.request.task_id:
            raise ValueError("notification RuntimeOutcome task mismatch")
        current = require_utc(now)
        kind = cls._kind(outcome)
        dedupe = sha256(
            f"{item.item_id}:{outcome.outcome_id}:{kind.value}".encode()
        ).hexdigest()
        return NotificationEvent(
            item_id=item.item_id,
            task_id=outcome.task_id,
            outcome_id=outcome.outcome_id,
            kind=kind,
            stop_reason=outcome.stop_reason.value,
            completion_status=outcome.completion_status,
            verification_report_id=outcome.verification_report_id,
            final_report_id=outcome.final_report_id,
            checkpoint_id=outcome.checkpoint_id,
            message=cls._message(kind, outcome),
            dedupe_key=dedupe,
            created_at=current,
        )

    def record_outcome(
        self,
        *,
        item: QueueItem,
        outcome: RuntimeOutcome,
        now: datetime | None = None,
    ) -> NotificationEvent:
        """Create an idempotent local event from RuntimeOutcome, never from model prose."""
        event = self.build_event(
            item=item,
            outcome=outcome,
            now=require_utc(now or utc_now()),
        )
        return self.store.insert_notification(event)

    def pending(self, *, limit: int = 100) -> tuple[NotificationEvent, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("notification limit must be in [1, 1000]")
        return self.store.pending_notifications(limit=limit)

    def acknowledge(
        self,
        notification_id: UUID,
        *,
        now: datetime | None = None,
    ) -> NotificationEvent:
        current_time = require_utc(now or utc_now())
        current = self.store.load_notification(notification_id)
        if current.status is NotificationStatus.ACKNOWLEDGED:
            return current
        updated = current.model_copy(
            update={
                "status": NotificationStatus.ACKNOWLEDGED,
                "acknowledged_at": current_time,
            }
        )
        return self.store.acknowledge_notification(current=current, updated=updated)
