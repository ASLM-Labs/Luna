from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from luna.autonomy import AutonomyLevel, AutonomyPolicy, FreeResearchContract
from luna.contracts import CompletionStatus, RiskLevel, TaskPhase, TaskScope, TaskState
from luna.contracts.task import TaskContract
from luna.operations import (
    DispatchResultStatus,
    DurableTaskQueue,
    NotificationEvent,
    NotificationKind,
    NotificationOutbox,
    NotificationStatus,
    OperationsConflictError,
    OperationsCoordinator,
    QueuePayload,
    QueueStatus,
    ResourceCapacity,
    ResourceLeaseStatus,
    ResourceManager,
    ResourceRequirement,
    ScheduleKind,
    Scheduler,
    ScheduleSpec,
    SQLiteOperationsStore,
    WorkEnvelope,
)
from luna.runtime import (
    RequestSource,
    RuntimeActor,
    RuntimeBudget,
    RuntimeMode,
    RuntimeOutcome,
    RuntimePriority,
    RuntimeRequest,
    RuntimeStopReason,
    RuntimeUsage,
    build_task_fingerprint,
)
from luna.tools import ToolPolicy

NOW = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)


def _request(
    root: Path,
    *,
    task_id: UUID | None = None,
    mode: RuntimeMode = RuntimeMode.EXECUTE,
    network_allowed: bool = False,
    autonomy: AutonomyPolicy | None = None,
) -> RuntimeRequest:
    active_task_id = task_id or uuid4()
    effective_autonomy = autonomy or AutonomyPolicy(
        task_id=active_task_id,
        level=(
            AutonomyLevel.LEVEL_3_TASK
            if network_allowed
            else AutonomyLevel.LEVEL_1_READ_ONLY
        ),
        max_risk=RiskLevel.LOW,
    )
    return RuntimeRequest(
        task_id=active_task_id,
        raw_request="Run the Phase 15 operations fixture.",
        source=RequestSource.TEST,
        actor=RuntimeActor.verified_owner("phase15-test"),
        scope=TaskScope(
            workspace_root=str(root),
            network_allowed=network_allowed,
        ),
        autonomy=effective_autonomy,
        runtime_budget=RuntimeBudget(
            max_network_requests=2 if network_allowed else 0,
        ),
        required_conditions=("Phase 15 fixture is processed safely.",),
        evidence_required=("runtime outcome",),
        risk_level=RiskLevel.LOW,
        mode=mode,
        resume_task_id=active_task_id if mode is RuntimeMode.RESUME else None,
        requested_at=NOW,
    )


def _envelope(root: Path, **kwargs: object) -> WorkEnvelope:
    request = _request(root, **kwargs)
    return WorkEnvelope(
        request=request,
        tool_policy=ToolPolicy(
            autonomy_level=request.autonomy.level,
            max_risk=request.autonomy.max_risk,
        ),
    )


def _completed_outcome(request: RuntimeRequest) -> RuntimeOutcome:
    contract = TaskContract(
        task_id=request.task_id,
        objective="Complete the Phase 15 fixture.",
        required_conditions=("Phase 15 fixture is processed safely.",),
        evidence_required=("runtime outcome",),
        scope=request.scope,
        owner=request.actor.actor_id,
    )
    state = TaskState(
        task_id=request.task_id,
        contract=contract,
        phase=TaskPhase.CLOSED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
    )
    return RuntimeOutcome(
        request_id=request.request_id,
        task_id=request.task_id,
        trace_id=request.trace_id,
        task_fingerprint=build_task_fingerprint(request).digest,
        state=state,
        stop_reason=RuntimeStopReason.COMPLETED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
        verification_report_id=uuid4(),
        final_report_id=uuid4(),
        usage=RuntimeUsage(budget=request.runtime_budget),
        started_at=NOW,
        finished_at=NOW,
    )


def _suspended_outcome(request: RuntimeRequest) -> RuntimeOutcome:
    contract = TaskContract(
        task_id=request.task_id,
        objective="Pause the Phase 15 fixture safely.",
        required_conditions=("Phase 15 fixture is processed safely.",),
        evidence_required=("runtime outcome",),
        scope=request.scope,
        owner=request.actor.actor_id,
    )
    state = TaskState(task_id=request.task_id, contract=contract)
    return RuntimeOutcome(
        request_id=request.request_id,
        task_id=request.task_id,
        trace_id=request.trace_id,
        task_fingerprint=build_task_fingerprint(request).digest,
        state=state,
        stop_reason=RuntimeStopReason.SUSPENDED,
        usage=RuntimeUsage(budget=request.runtime_budget),
        started_at=NOW,
        finished_at=NOW,
    )


class _StubRuntime:
    def __init__(self, *, suspended: bool = False, fail: bool = False) -> None:
        self.suspended = suspended
        self.fail = fail
        self.run_calls = 0
        self.resume_calls = 0

    def _invoke(self, request: RuntimeRequest) -> RuntimeOutcome:
        if self.fail:
            raise RuntimeError("fixture backend failure")
        if self.suspended:
            return _suspended_outcome(request)
        return _completed_outcome(request)

    def run(self, *, request: RuntimeRequest, tool_policy: ToolPolicy) -> RuntimeOutcome:
        del tool_policy
        self.run_calls += 1
        return self._invoke(request)

    def resume(self, *, request: RuntimeRequest, tool_policy: ToolPolicy) -> RuntimeOutcome:
        del tool_policy
        self.resume_calls += 1
        return self._invoke(request)


def _components(
    root: Path,
    *,
    capacity: ResourceCapacity | None = None,
    runtime: _StubRuntime | None = None,
) -> tuple[
    SQLiteOperationsStore,
    DurableTaskQueue,
    Scheduler,
    ResourceManager,
    NotificationOutbox,
    OperationsCoordinator,
]:
    store = SQLiteOperationsStore(root / "operations.sqlite3")
    queue = DurableTaskQueue(store)
    scheduler = Scheduler(store)
    resources = ResourceManager(store, capacity or ResourceCapacity())
    outbox = NotificationOutbox(store)
    coordinator = OperationsCoordinator(
        queue=queue,
        scheduler=scheduler,
        resources=resources,
        notifications=outbox,
        runtime=runtime or _StubRuntime(),
    )
    return store, queue, scheduler, resources, outbox, coordinator


def test_operations_store_uses_wal_and_queue_survives_reopen(tmp_path: Path) -> None:
    store, queue, *_ = _components(tmp_path)
    item = queue.enqueue(envelope=_envelope(tmp_path), now=NOW)

    reopened = SQLiteOperationsStore(store.path)

    assert reopened.schema_version() == 1
    assert reopened.journal_mode() == "wal"
    assert reopened.load_queue_item(item.item_id) == item


def test_queue_enqueue_is_idempotent_and_conflicting_key_is_rejected(tmp_path: Path) -> None:
    _, queue, *_ = _components(tmp_path)
    envelope = _envelope(tmp_path)
    key = "a" * 64

    first = queue.enqueue(envelope=envelope, idempotency_key=key, now=NOW)
    second = queue.enqueue(envelope=envelope, idempotency_key=key, now=NOW)
    assert second == first

    with pytest.raises(OperationsConflictError, match="different work"):
        queue.enqueue(
            envelope=_envelope(tmp_path),
            idempotency_key=key,
            now=NOW,
        )


def test_ready_queue_orders_priority_then_eligibility(tmp_path: Path) -> None:
    _, queue, *_ = _components(tmp_path)
    low = queue.enqueue(
        envelope=_envelope(tmp_path),
        priority=RuntimePriority.LOW,
        eligible_at=NOW - timedelta(minutes=1),
        now=NOW - timedelta(minutes=2),
    )
    high = queue.enqueue(
        envelope=_envelope(tmp_path),
        priority=RuntimePriority.HIGH,
        eligible_at=NOW,
        now=NOW - timedelta(minutes=2),
    )
    future = queue.enqueue(
        envelope=_envelope(tmp_path),
        priority=RuntimePriority.CRITICAL,
        eligible_at=NOW + timedelta(minutes=1),
        now=NOW,
    )

    ready = queue.ready(now=NOW)

    assert tuple(item.item_id for item in ready) == (high.item_id, low.item_id)
    assert future.item_id not in {item.item_id for item in ready}


def test_resource_capacity_blocks_oversubscription_until_release(tmp_path: Path) -> None:
    _, queue, _, resources, *_ = _components(
        tmp_path,
        capacity=ResourceCapacity(worker_slots=1, model_slots=1),
    )
    first = queue.enqueue(envelope=_envelope(tmp_path), now=NOW)
    second = queue.enqueue(envelope=_envelope(tmp_path), now=NOW)

    lease = resources.acquire(
        item_id=first.item_id,
        owner_id="worker-1",
        requirement=first.payload.resources,
        lease_seconds=60,
        now=NOW,
    )
    assert lease is not None
    blocked = resources.acquire(
        item_id=second.item_id,
        owner_id="worker-2",
        requirement=second.payload.resources,
        lease_seconds=60,
        now=NOW,
    )
    assert blocked is None

    resources.release(lease.lease_id, now=NOW + timedelta(seconds=1))
    admitted = resources.acquire(
        item_id=second.item_id,
        owner_id="worker-2",
        requirement=second.payload.resources,
        lease_seconds=60,
        now=NOW + timedelta(seconds=1),
    )
    assert admitted is not None


def test_resource_request_cannot_manufacture_network_authority(tmp_path: Path) -> None:
    envelope = _envelope(tmp_path)
    with pytest.raises(ValidationError, match="manufacture network authority"):
        QueuePayload(
            envelope=envelope,
            resources=ResourceRequirement(network_slots=1),
        )


def test_one_shot_scheduler_only_materializes_when_due(tmp_path: Path) -> None:
    _, queue, scheduler, *_ = _components(tmp_path)
    job = scheduler.create(
        envelope=_envelope(tmp_path),
        spec=ScheduleSpec(
            kind=ScheduleKind.ONE_SHOT,
            first_run_at=NOW + timedelta(minutes=5),
        ),
        now=NOW,
    )

    assert scheduler.materialize_due(now=NOW) == ()
    assert queue.ready(now=NOW) == ()

    materialized = scheduler.materialize_due(now=NOW + timedelta(minutes=5))
    assert len(materialized) == 1
    assert materialized[0].payload.schedule_id == job.schedule_id
    assert materialized[0].payload.envelope == job.envelope
    assert scheduler.store.load_schedule(job.schedule_id).enabled is False


def test_fixed_interval_scheduler_creates_deterministic_fresh_task_ids(tmp_path: Path) -> None:
    _, _, scheduler, *_ = _components(tmp_path)
    job = scheduler.create(
        envelope=_envelope(tmp_path),
        spec=ScheduleSpec(
            kind=ScheduleKind.FIXED_INTERVAL,
            first_run_at=NOW,
            interval_seconds=60,
            max_occurrences=2,
        ),
        now=NOW,
    )

    first = scheduler.materialize_due(now=NOW, limit=1)[0]
    second = scheduler.materialize_due(now=NOW + timedelta(seconds=60), limit=1)[0]
    stored = scheduler.store.load_schedule(job.schedule_id)

    assert first.payload.envelope.request.task_id != job.envelope.request.task_id
    assert first.payload.envelope.request.task_id != second.payload.envelope.request.task_id
    assert first.payload.occurrence_index == 0
    assert second.payload.occurrence_index == 1
    assert stored.occurrence_count == 2
    assert stored.enabled is False


def test_recurring_schedule_cannot_clone_free_research_authority(tmp_path: Path) -> None:
    task_id = uuid4()
    contract = FreeResearchContract(
        task_id=task_id,
        purpose="One task-bound research authorization.",
        allowed_tools=("research.fetch",),
        allowed_domains=("example.com",),
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    autonomy = AutonomyPolicy(
        task_id=task_id,
        level=AutonomyLevel.LEVEL_4_FREE_RESEARCH,
        allowed_tools=("research.fetch",),
        max_risk=RiskLevel.LOW,
        free_research_contract=contract,
    )
    request = _request(
        tmp_path,
        task_id=task_id,
        network_allowed=True,
        autonomy=autonomy,
    )
    envelope = WorkEnvelope(
        request=request,
        tool_policy=ToolPolicy(
            allowed_tools=("research.fetch",),
            autonomy_level=AutonomyLevel.LEVEL_4_FREE_RESEARCH,
            max_risk=RiskLevel.LOW,
            free_research_contract=contract,
        ),
    )
    _, _, scheduler, *_ = _components(tmp_path)

    with pytest.raises(ValidationError, match="task-bound FREE_RESEARCH"):
        scheduler.create(
            envelope=envelope,
            spec=ScheduleSpec(
                kind=ScheduleKind.FIXED_INTERVAL,
                first_run_at=NOW,
                interval_seconds=60,
            ),
            resources=ResourceRequirement(network_slots=1),
            now=NOW,
        )


def test_expired_pre_dispatch_lease_is_safe_to_requeue(tmp_path: Path) -> None:
    _, queue, _, resources, *_ = _components(tmp_path)
    item = queue.enqueue(envelope=_envelope(tmp_path), now=NOW)
    resource = resources.acquire(
        item_id=item.item_id,
        owner_id="worker-1",
        requirement=item.payload.resources,
        lease_seconds=10,
        now=NOW,
    )
    assert resource is not None
    queue.lease(
        item_id=item.item_id,
        owner_id="worker-1",
        resource_lease=resource,
        lease_seconds=10,
        now=NOW,
    )

    requeued, ambiguous = resources.recover_expired(
        queue,
        now=NOW + timedelta(seconds=11),
    )

    assert (requeued, ambiguous) == (1, 0)
    assert queue.get(item.item_id).status is QueueStatus.QUEUED
    stored_resource = resources.store.load_resource_lease(resource.lease_id)
    assert stored_resource.status is ResourceLeaseStatus.RELEASED


def test_expired_dispatched_lease_requires_recovery_and_never_requeues(tmp_path: Path) -> None:
    _, queue, _, resources, *_ = _components(tmp_path)
    item = queue.enqueue(envelope=_envelope(tmp_path), now=NOW)
    resource = resources.acquire(
        item_id=item.item_id,
        owner_id="worker-1",
        requirement=item.payload.resources,
        lease_seconds=10,
        now=NOW,
    )
    assert resource is not None
    queue.lease(
        item_id=item.item_id,
        owner_id="worker-1",
        resource_lease=resource,
        lease_seconds=10,
        now=NOW,
    )
    queue.mark_dispatched(item_id=item.item_id, now=NOW)

    requeued, ambiguous = resources.recover_expired(
        queue,
        now=NOW + timedelta(seconds=11),
    )

    assert (requeued, ambiguous) == (0, 1)
    assert queue.get(item.item_id).status is QueueStatus.RECOVERY_REQUIRED
    stored_resource = resources.store.load_resource_lease(resource.lease_id)
    assert stored_resource.status is ResourceLeaseStatus.STALE
    assert queue.ready(now=NOW + timedelta(hours=1)) == ()


def test_coordinator_dispatches_exactly_once_and_atomically_records_outcome(tmp_path: Path) -> None:
    runtime = _StubRuntime()
    store, queue, _, resources, outbox, coordinator = _components(
        tmp_path,
        runtime=runtime,
    )
    item = queue.enqueue(envelope=_envelope(tmp_path), now=NOW)

    result = coordinator.dispatch_one(worker_id="worker-1", now=NOW)

    assert result.status is DispatchResultStatus.OUTCOME_RECORDED
    assert runtime.run_calls == 1
    stored = queue.get(item.item_id)
    assert stored.status is QueueStatus.COMPLETED
    assert stored.outcome == result.outcome
    assert resources.held_usage().worker_slots == 0
    pending = outbox.pending()
    assert len(pending) == 1
    assert pending[0].kind is NotificationKind.TASK_VERIFIED_COMPLETE
    assert pending[0].external_delivery_allowed is False
    assert stored.resource_lease_id is not None
    stored_resource = store.load_resource_lease(stored.resource_lease_id)
    assert stored_resource.status is ResourceLeaseStatus.RELEASED


def test_runtime_exception_becomes_recovery_required_without_blind_retry(tmp_path: Path) -> None:
    runtime = _StubRuntime(fail=True)
    _, queue, _, resources, _, coordinator = _components(tmp_path, runtime=runtime)
    item = queue.enqueue(envelope=_envelope(tmp_path), now=NOW)

    first = coordinator.dispatch_one(worker_id="worker-1", now=NOW)
    second = coordinator.dispatch_one(worker_id="worker-1", now=NOW + timedelta(seconds=1))

    assert first.status is DispatchResultStatus.RECOVERY_REQUIRED
    assert second.status is DispatchResultStatus.NO_WORK
    assert runtime.run_calls == 1
    stored = queue.get(item.item_id)
    assert stored.status is QueueStatus.RECOVERY_REQUIRED
    assert stored.resource_lease_id is not None
    stored_resource = resources.store.load_resource_lease(stored.resource_lease_id)
    assert stored_resource.status is ResourceLeaseStatus.STALE


def test_suspended_runtime_outcome_is_not_reported_as_success(tmp_path: Path) -> None:
    runtime = _StubRuntime(suspended=True)
    _, queue, _, _, outbox, coordinator = _components(tmp_path, runtime=runtime)
    item = queue.enqueue(envelope=_envelope(tmp_path), now=NOW)

    result = coordinator.dispatch_one(worker_id="worker-1", now=NOW)

    assert result.status is DispatchResultStatus.OUTCOME_RECORDED
    assert queue.get(item.item_id).status is QueueStatus.SUSPENDED
    event = outbox.pending()[0]
    assert event.kind is NotificationKind.TASK_REQUIRES_ATTENTION
    assert event.completion_status is None


def test_verified_complete_notification_cannot_be_forged_without_verification() -> None:
    with pytest.raises(ValidationError, match="VERIFIED_COMPLETE"):
        NotificationEvent(
            item_id=uuid4(),
            task_id=uuid4(),
            outcome_id=uuid4(),
            kind=NotificationKind.TASK_VERIFIED_COMPLETE,
            stop_reason=RuntimeStopReason.COMPLETED.value,
            message="Forged success.",
            dedupe_key="b" * 64,
        )


def test_notification_outbox_is_local_idempotent_and_acknowledgeable(tmp_path: Path) -> None:
    runtime = _StubRuntime()
    _, queue, _, _, outbox, coordinator = _components(tmp_path, runtime=runtime)
    item = queue.enqueue(envelope=_envelope(tmp_path), now=NOW)
    result = coordinator.dispatch_one(worker_id="worker-1", now=NOW)
    assert result.outcome is not None
    stored = queue.get(item.item_id)

    repeated = outbox.record_outcome(item=stored, outcome=result.outcome, now=NOW)
    pending = outbox.pending()
    assert len(pending) == 1
    assert repeated.notification_id == pending[0].notification_id
    acknowledged = outbox.acknowledge(pending[0].notification_id, now=NOW + timedelta(seconds=1))
    assert acknowledged.status is NotificationStatus.ACKNOWLEDGED
    assert outbox.pending() == ()


def test_queued_cancel_prevents_runtime_dispatch(tmp_path: Path) -> None:
    runtime = _StubRuntime()
    _, queue, _, _, _, coordinator = _components(tmp_path, runtime=runtime)
    item = queue.enqueue(envelope=_envelope(tmp_path), now=NOW)

    cancelled = queue.cancel_queued(item_id=item.item_id, now=NOW)
    result = coordinator.dispatch_one(worker_id="worker-1", now=NOW)

    assert cancelled.status is QueueStatus.CANCELLED
    assert result.status is DispatchResultStatus.NO_WORK
    assert runtime.run_calls == 0
