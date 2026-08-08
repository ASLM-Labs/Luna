"""Deterministic Phase 15 Resource Manager / Queue / Scheduler / Notifications gate."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.autonomy import AutonomyLevel, AutonomyPolicy  # noqa: E402
from luna.contracts import (  # noqa: E402
    CompletionStatus,
    RiskLevel,
    TaskPhase,
    TaskScope,
    TaskState,
)
from luna.contracts.task import TaskContract  # noqa: E402
from luna.operations import (  # noqa: E402
    DispatchResultStatus,
    DurableTaskQueue,
    NotificationKind,
    NotificationOutbox,
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
from luna.runtime import (  # noqa: E402
    RequestSource,
    RuntimeActor,
    RuntimeBudget,
    RuntimeOutcome,
    RuntimeRequest,
    RuntimeStopReason,
    RuntimeUsage,
    build_task_fingerprint,
)
from luna.tools import ToolPolicy  # noqa: E402

REQUIRED_FILES = (
    "src/luna/operations/__init__.py",
    "src/luna/operations/models.py",
    "src/luna/operations/store.py",
    "src/luna/operations/queue.py",
    "src/luna/operations/resources.py",
    "src/luna/operations/scheduler.py",
    "src/luna/operations/notifications.py",
    "src/luna/operations/coordinator.py",
    "tests/test_phase15_operations_queue_scheduler_notifications.py",
    "scripts/verify_phase15.py",
    "docs/rfcs/RFC-015_RESOURCE_MANAGER_QUEUE_SCHEDULER_NOTIFICATIONS.md",
    "docs/PHASE_15_REPORT.md",
    "phase_15_verification.json",
)

NOW = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)


def _request(root: Path) -> RuntimeRequest:
    task_id = uuid4()
    return RuntimeRequest(
        task_id=task_id,
        raw_request="Run the deterministic Phase 15 operations verifier fixture.",
        source=RequestSource.TEST,
        actor=RuntimeActor.verified_owner("phase15-verifier"),
        scope=TaskScope(workspace_root=str(root)),
        autonomy=AutonomyPolicy(
            task_id=task_id,
            level=AutonomyLevel.LEVEL_1_READ_ONLY,
            max_risk=RiskLevel.LOW,
        ),
        runtime_budget=RuntimeBudget(),
        required_conditions=("Phase 15 fixture is handled safely.",),
        evidence_required=("runtime outcome",),
        risk_level=RiskLevel.LOW,
        requested_at=NOW,
    )


def _envelope(root: Path) -> WorkEnvelope:
    request = _request(root)
    return WorkEnvelope(
        request=request,
        tool_policy=ToolPolicy(
            autonomy_level=AutonomyLevel.LEVEL_1_READ_ONLY,
            max_risk=RiskLevel.LOW,
        ),
    )


def _outcome(request: RuntimeRequest) -> RuntimeOutcome:
    contract = TaskContract(
        task_id=request.task_id,
        objective="Complete the Phase 15 verifier fixture.",
        required_conditions=("Phase 15 fixture is handled safely.",),
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


class _RuntimeStub:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def run(self, *, request: RuntimeRequest, tool_policy: ToolPolicy) -> RuntimeOutcome:
        del tool_policy
        self.calls += 1
        if self.fail:
            raise RuntimeError("phase15 deterministic fixture failure")
        return _outcome(request)

    def resume(self, *, request: RuntimeRequest, tool_policy: ToolPolicy) -> RuntimeOutcome:
        return self.run(request=request, tool_policy=tool_policy)


def _components(root: Path, runtime: _RuntimeStub) -> tuple[
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
    resources = ResourceManager(store, ResourceCapacity(worker_slots=1, model_slots=1))
    notifications = NotificationOutbox(store)
    coordinator = OperationsCoordinator(
        queue=queue,
        scheduler=scheduler,
        resources=resources,
        notifications=notifications,
        runtime=runtime,
    )
    return store, queue, scheduler, resources, notifications, coordinator


def _canonical_metadata_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _metadata_integrity() -> bool:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    phase = str(manifest.get("phase", ""))
    match = re.fullmatch(r"(\d+)(?:[A-Z])?", phase)
    if match is None or int(match.group(1)) < 15:
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    if manifest.get("metadata_scope") != "release_artifact_allowlist_v2":
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False
    if any(str(relative).endswith(".log") for relative in files):
        return False

    sums: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            return False
        digest, relative = line.split("  ", 1)
        sums[relative] = digest
    if set(sums) != set(files):
        return False

    for relative, metadata in files.items():
        if not isinstance(relative, str) or not isinstance(metadata, dict):
            return False
        target = ROOT / relative
        if not target.is_file():
            return False
        canonical = _canonical_metadata_bytes(target)
        digest = sha256(canonical).hexdigest()
        if metadata.get("sha256") != digest:
            return False
        if metadata.get("size_bytes") != len(canonical):
            return False
        if sums.get(relative) != digest:
            return False
    return True


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {"required_files_present": not missing}

    with TemporaryDirectory(prefix="luna-phase15-verifier-") as temp:
        root = Path(temp)
        runtime = _RuntimeStub()
        store, queue, _, _, _, _ = _components(root, runtime)

        first = queue.enqueue(envelope=_envelope(root), now=NOW)
        reopened = SQLiteOperationsStore(store.path)
        checks["durable_queue_sqlite_wal"] = (
            reopened.journal_mode() == "wal"
            and reopened.schema_version() == 1
            and reopened.load_queue_item(first.item_id) == first
        )

        scheduled_runtime = _RuntimeStub()
        scheduled_root = root / "scheduled"
        _, _, scheduled, _, _, scheduled_coordinator = _components(
            scheduled_root,
            scheduled_runtime,
        )
        job = scheduled.create(
            envelope=_envelope(scheduled_root),
            spec=ScheduleSpec(
                kind=ScheduleKind.ONE_SHOT,
                first_run_at=NOW + timedelta(minutes=1),
            ),
            now=NOW,
        )
        before = scheduled_coordinator.materialize_due(now=NOW)
        at_due = scheduled_coordinator.materialize_due(now=NOW + timedelta(minutes=1))
        checks["scheduler_only_materializes_eligible_work"] = (
            before == 0
            and at_due == 1
            and scheduled_runtime.calls == 0
            and scheduled.store.load_schedule(job.schedule_id).enabled is False
        )

        network_authority_rejected = False
        try:
            QueuePayload(
                envelope=_envelope(root),
                resources=ResourceRequirement(network_slots=1),
            )
        except ValidationError:
            network_authority_rejected = True
        checks["resource_layer_cannot_grant_network_authority"] = network_authority_rejected

        resource_root = root / "resource"
        _, resource_queue, _, resource_manager, _, _ = _components(
            resource_root,
            _RuntimeStub(),
        )
        item_a = resource_queue.enqueue(envelope=_envelope(resource_root), now=NOW)
        item_b = resource_queue.enqueue(envelope=_envelope(resource_root), now=NOW)
        lease_a = resource_manager.acquire(
            item_id=item_a.item_id,
            owner_id="worker-a",
            requirement=item_a.payload.resources,
            lease_seconds=10,
            now=NOW,
        )
        lease_b = resource_manager.acquire(
            item_id=item_b.item_id,
            owner_id="worker-b",
            requirement=item_b.payload.resources,
            lease_seconds=10,
            now=NOW,
        )
        checks["resource_capacity_prevents_oversubscription"] = (
            lease_a is not None and lease_b is None
        )

        assert lease_a is not None
        resource_queue.lease(
            item_id=item_a.item_id,
            owner_id="worker-a",
            resource_lease=lease_a,
            lease_seconds=10,
            now=NOW,
        )
        requeued, ambiguous = resource_manager.recover_expired(
            resource_queue,
            now=NOW + timedelta(seconds=11),
        )
        checks["expired_pre_dispatch_lease_requeues_safely"] = (
            (requeued, ambiguous) == (1, 0)
            and resource_queue.get(item_a.item_id).status is QueueStatus.QUEUED
        )

        ambiguous_root = root / "ambiguous"
        _, ambiguous_queue, _, ambiguous_resources, _, _ = _components(
            ambiguous_root,
            _RuntimeStub(),
        )
        ambiguous_item = ambiguous_queue.enqueue(
            envelope=_envelope(ambiguous_root),
            now=NOW,
        )
        ambiguous_lease = ambiguous_resources.acquire(
            item_id=ambiguous_item.item_id,
            owner_id="worker-a",
            requirement=ambiguous_item.payload.resources,
            lease_seconds=10,
            now=NOW,
        )
        assert ambiguous_lease is not None
        ambiguous_queue.lease(
            item_id=ambiguous_item.item_id,
            owner_id="worker-a",
            resource_lease=ambiguous_lease,
            lease_seconds=10,
            now=NOW,
        )
        ambiguous_queue.mark_dispatched(item_id=ambiguous_item.item_id, now=NOW)
        _, ambiguous_count = ambiguous_resources.recover_expired(
            ambiguous_queue,
            now=NOW + timedelta(seconds=11),
        )
        checks["dispatched_lease_never_blind_replays"] = (
            ambiguous_count == 1
            and ambiguous_queue.get(ambiguous_item.item_id).status
            is QueueStatus.RECOVERY_REQUIRED
            and ambiguous_resources.store.load_resource_lease(ambiguous_lease.lease_id).status
            is ResourceLeaseStatus.STALE
            and ambiguous_queue.ready(now=NOW + timedelta(hours=1)) == ()
        )

        dispatch_root = root / "dispatch"
        dispatch_runtime = _RuntimeStub()
        _, dispatch_queue, _, dispatch_resources, dispatch_outbox, dispatch_coordinator = (
            _components(dispatch_root, dispatch_runtime)
        )
        dispatch_item = dispatch_queue.enqueue(envelope=_envelope(dispatch_root), now=NOW)
        dispatch_result = dispatch_coordinator.dispatch_one(worker_id="worker-a", now=NOW)
        stored_dispatch = dispatch_queue.get(dispatch_item.item_id)
        pending = dispatch_outbox.pending()
        checks["runtime_dispatch_is_fenced_and_single"] = (
            dispatch_result.status is DispatchResultStatus.OUTCOME_RECORDED
            and dispatch_runtime.calls == 1
            and stored_dispatch.status is QueueStatus.COMPLETED
            and dispatch_resources.held_usage().worker_slots == 0
        )
        checks["notifications_are_outcome_bound_and_local_only"] = (
            len(pending) == 1
            and pending[0].kind is NotificationKind.TASK_VERIFIED_COMPLETE
            and pending[0].completion_status is CompletionStatus.VERIFIED_COMPLETE
            and pending[0].verification_report_id is not None
            and pending[0].external_delivery_allowed is False
        )
        if dispatch_result.outcome is not None:
            duplicate = dispatch_outbox.record_outcome(
                item=stored_dispatch,
                outcome=dispatch_result.outcome,
                now=NOW,
            )
            checks["notification_outbox_deduplicates"] = (
                len(dispatch_outbox.pending()) == 1
                and duplicate.notification_id == pending[0].notification_id
            )
        else:
            checks["notification_outbox_deduplicates"] = False

        failure_root = root / "failure"
        failure_runtime = _RuntimeStub(fail=True)
        _, failure_queue, _, _, _, failure_coordinator = _components(
            failure_root,
            failure_runtime,
        )
        failure_item = failure_queue.enqueue(envelope=_envelope(failure_root), now=NOW)
        failure_first = failure_coordinator.dispatch_one(worker_id="worker-f", now=NOW)
        failure_second = failure_coordinator.dispatch_one(
            worker_id="worker-f",
            now=NOW + timedelta(seconds=1),
        )
        checks["runtime_exception_requires_recovery_no_retry"] = (
            failure_first.status is DispatchResultStatus.RECOVERY_REQUIRED
            and failure_second.status is DispatchResultStatus.NO_WORK
            and failure_runtime.calls == 1
            and failure_queue.get(failure_item.item_id).status is QueueStatus.RECOVERY_REQUIRED
        )

        recurrence_root = root / "recurrence"
        _, _, recurrence_scheduler, _, _, _ = _components(
            recurrence_root,
            _RuntimeStub(),
        )
        recurring = recurrence_scheduler.create(
            envelope=_envelope(recurrence_root),
            spec=ScheduleSpec(
                kind=ScheduleKind.FIXED_INTERVAL,
                first_run_at=NOW,
                interval_seconds=60,
                max_occurrences=2,
            ),
            now=NOW,
        )
        occurrences = recurrence_scheduler.materialize_due(
            now=NOW + timedelta(seconds=60),
            limit=2,
        )
        checks["recurrence_is_bounded_and_uses_fresh_task_ids"] = (
            len(occurrences) == 2
            and occurrences[0].payload.envelope.request.task_id
            != occurrences[1].payload.envelope.request.task_id
            and recurrence_scheduler.store.load_schedule(recurring.schedule_id).enabled is False
        )

    phase14 = json.loads((ROOT / "phase_14_verification.json").read_text(encoding="utf-8"))
    checks["phase14_foundation_remains_green"] = phase14.get("status") == "PASS"
    checks["metadata_hashes_current"] = _metadata_integrity()

    payload = {
        "phase": "15",
        "checks": checks,
        "missing_files": missing,
        "status": "PASS" if all(checks.values()) else "BLOCKED",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
