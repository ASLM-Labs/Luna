"""Deterministic UTC scheduler that materializes work but never executes it."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4, uuid5

from luna.contracts.base import require_utc, utc_now
from luna.operations.models import (
    QueueItem,
    QueuePayload,
    QueueStatus,
    ResourceRequirement,
    ScheduledJob,
    ScheduleKind,
    ScheduleSpec,
    WorkEnvelope,
    payload_digest,
)
from luna.operations.store import SQLiteOperationsStore
from luna.runtime import RuntimePriority, RuntimeRequest


class Scheduler:
    """Persist schedules and emit queue records only when they become due."""

    def __init__(self, store: SQLiteOperationsStore) -> None:
        self.store = store

    def create(
        self,
        *,
        envelope: WorkEnvelope,
        spec: ScheduleSpec,
        resources: ResourceRequirement | None = None,
        priority: RuntimePriority = RuntimePriority.NORMAL,
        schedule_id: UUID | None = None,
        now: datetime | None = None,
    ) -> ScheduledJob:
        current = require_utc(now or utc_now())
        job = ScheduledJob(
            schedule_id=schedule_id or uuid4(),
            envelope=envelope,
            resources=resources or ResourceRequirement(),
            priority=priority,
            spec=spec,
            next_run_at=spec.first_run_at,
            created_at=current,
            updated_at=current,
        )
        return self.store.insert_schedule(job)

    @staticmethod
    def _recurring_envelope(job: ScheduledJob, occurrence_index: int) -> WorkEnvelope:
        request = job.envelope.request
        task_id = uuid5(job.schedule_id, f"task:{occurrence_index}")
        request_id = uuid5(job.schedule_id, f"request:{occurrence_index}")
        trace_id = uuid5(job.schedule_id, f"trace:{occurrence_index}")
        autonomy = request.autonomy.model_copy(update={"task_id": task_id})
        candidate = request.model_copy(
            update={
                "task_id": task_id,
                "request_id": request_id,
                "trace_id": trace_id,
                "autonomy": autonomy,
                "requested_at": job.next_run_at,
            }
        )
        rebuilt = RuntimeRequest.model_validate(candidate.model_dump(mode="python"))
        return WorkEnvelope(request=rebuilt, tool_policy=job.envelope.tool_policy)

    @staticmethod
    def _occurrence_item(job: ScheduledJob) -> QueueItem:
        occurrence = job.occurrence_count
        envelope = (
            job.envelope
            if job.spec.kind is ScheduleKind.ONE_SHOT
            else Scheduler._recurring_envelope(job, occurrence)
        )
        payload = QueuePayload(
            envelope=envelope,
            resources=job.resources,
            schedule_id=job.schedule_id,
            occurrence_index=occurrence,
        )
        key_material = f"{job.schedule_id}:occurrence:{occurrence}"
        key = sha256(key_material.encode("utf-8")).hexdigest()
        return QueueItem(
            item_id=uuid5(job.schedule_id, f"queue:{occurrence}"),
            idempotency_key=key,
            payload=payload,
            payload_sha256=payload_digest(payload),
            priority=job.priority,
            status=QueueStatus.QUEUED,
            eligible_at=job.next_run_at,
            created_at=job.next_run_at,
            updated_at=job.next_run_at,
        )

    @staticmethod
    def _advance(job: ScheduledJob, *, now: datetime) -> ScheduledJob:
        next_count = job.occurrence_count + 1
        if job.spec.kind is ScheduleKind.ONE_SHOT:
            return job.model_copy(
                update={
                    "occurrence_count": next_count,
                    "enabled": False,
                    "updated_at": now,
                }
            )
        interval = job.spec.interval_seconds
        assert interval is not None
        max_occurrences = job.spec.max_occurrences
        enabled = max_occurrences is None or next_count < max_occurrences
        next_run = job.spec.first_run_at + timedelta(seconds=interval * next_count)
        return job.model_copy(
            update={
                "occurrence_count": next_count,
                "enabled": enabled,
                "next_run_at": next_run,
                "updated_at": now,
            }
        )

    def materialize_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 32,
    ) -> tuple[QueueItem, ...]:
        """Bounded catch-up: due schedules become queue work, never runtime calls."""
        if limit < 1 or limit > 1000:
            raise ValueError("scheduler materialization limit must be in [1, 1000]")
        current = require_utc(now or utc_now())
        materialized: list[QueueItem] = []
        while len(materialized) < limit:
            due = self.store.due_schedules(current.isoformat(), limit=1)
            if not due:
                break
            job = due[0]
            item = self._occurrence_item(job)
            updated = self._advance(job, now=current)
            persisted = self.store.materialize_schedule_occurrence(
                current=job,
                item=item,
                updated=updated,
            )
            materialized.append(persisted)
        return tuple(materialized)
