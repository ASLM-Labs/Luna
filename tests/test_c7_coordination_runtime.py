from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from threading import Barrier, Event, Lock
from time import sleep
from uuid import UUID, uuid4

import pytest

from luna.planning.coordination import (
    CoordinationMode,
    CoordinationPlan,
    WorkerAssignment,
    WorkerRole,
)
from luna.planning.reconciliation import (
    CoordinationReconciler,
    WorkerResult,
    WorkerResultStatus,
)
from luna.runtime.coordination import (
    CoordinationExecutionStatus,
    CoordinationRuntime,
    CoordinationRuntimeError,
)


def _fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _assignment(
    *,
    task_id: UUID,
    revision: int,
    index: int,
    role: WorkerRole = WorkerRole.PARALLEL,
) -> WorkerAssignment:
    basis = _fingerprint(
        f"{task_id}:{revision}:{index}:{role.value}"
    )
    return WorkerAssignment(
        assignment_id=f"assignment:sha256:{basis}",
        task_id=task_id,
        role=role,
        objective=f"Execute bounded worker objective {index}.",
        source_task_revision=revision,
        source_step_ids=(uuid4(),),
        acceptance_target_refs=(f"acceptance:{index}",),
        allowed_path_refs=(),
        assignment_basis_fingerprint=basis,
        provenance_refs=(
            f"task:{task_id}",
            f"test:assignment:{index}",
        ),
    )


def _parallel_plan(count: int = 2) -> CoordinationPlan:
    task_id = uuid4()
    revision = 10
    assignments = tuple(
        _assignment(
            task_id=task_id,
            revision=revision,
            index=index,
        )
        for index in range(count)
    )
    return CoordinationPlan(
        task_id=task_id,
        source_task_revision=revision,
        capability_selection_basis_fingerprint="a" * 64,
        mode=CoordinationMode.PARALLEL_WORKERS,
        assignments=assignments,
        coordination_basis_fingerprint=_fingerprint(
            f"parallel:{task_id}:{count}"
        ),
        reason_codes=("test_parallel_coordination",),
        provenance_refs=(f"task:{task_id}", "test:c7-runtime"),
    )


def _review_plan() -> CoordinationPlan:
    task_id = uuid4()
    revision = 10
    assignment = _assignment(
        task_id=task_id,
        revision=revision,
        index=0,
        role=WorkerRole.INDEPENDENT_REVIEWER,
    )
    return CoordinationPlan(
        task_id=task_id,
        source_task_revision=revision,
        capability_selection_basis_fingerprint="a" * 64,
        mode=CoordinationMode.INDEPENDENT_REVIEW,
        assignments=(assignment,),
        coordination_basis_fingerprint=_fingerprint(
            f"review:{task_id}"
        ),
        reason_codes=("test_independent_review",),
        provenance_refs=(f"task:{task_id}", "test:c7-runtime"),
    )


def _solo_plan() -> CoordinationPlan:
    task_id = uuid4()
    return CoordinationPlan(
        task_id=task_id,
        source_task_revision=10,
        capability_selection_basis_fingerprint="a" * 64,
        mode=CoordinationMode.SOLO,
        assignments=(),
        coordination_basis_fingerprint=_fingerprint(
            f"solo:{task_id}"
        ),
        reason_codes=("test_solo_coordination",),
        provenance_refs=(f"task:{task_id}", "test:c7-runtime"),
    )


_RECONCILER = CoordinationReconciler()


def _success_result(assignment: WorkerAssignment) -> WorkerResult:
    return _RECONCILER.result(
        assignment=assignment,
        status=WorkerResultStatus.SUCCESS,
        evidence_ids=(uuid4(),),
    )


class _Worker:
    def __init__(
        self,
        worker_id: str,
        execute_fn: Callable[[WorkerAssignment], WorkerResult],
        *,
        close_raises: bool = False,
    ) -> None:
        self._worker_id = worker_id
        self._execute_fn = execute_fn
        self._close_raises = close_raises
        self.execute_count = 0
        self.close_count = 0

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def execute(self, assignment: WorkerAssignment) -> WorkerResult:
        self.execute_count += 1
        return self._execute_fn(assignment)

    def close(self) -> None:
        self.close_count += 1
        if self._close_raises:
            raise RuntimeError("synthetic cleanup failure")


class _SequenceFactory:
    def __init__(self, workers: tuple[_Worker, ...]) -> None:
        self.workers = workers
        self.create_count = 0

    def create(self, assignment: WorkerAssignment) -> _Worker:
        del assignment
        worker = self.workers[self.create_count]
        self.create_count += 1
        return worker


class _ExplodingFactory:
    def __init__(self) -> None:
        self.create_count = 0

    def create(self, assignment: WorkerAssignment) -> _Worker:
        del assignment
        self.create_count += 1
        raise AssertionError("factory must not be called")


def test_c7_coordination_runtime_solo_starts_no_workers() -> None:
    plan = _solo_plan()
    factory = _ExplodingFactory()

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=factory,
        max_concurrent_worker_executions=1,
    )

    assert report.status is CoordinationExecutionStatus.SOLO
    assert factory.create_count == 0
    assert report.worker_ids == ()
    assert report.results == ()
    assert report.runtime_authority is False
    assert report.execution_authority is False
    assert report.completion_authority is False


def test_c7_parallel_requires_two_worker_slots() -> None:
    plan = _parallel_plan()
    factory = _ExplodingFactory()

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=factory,
        max_concurrent_worker_executions=1,
    )

    assert report.status is CoordinationExecutionStatus.RESOURCE_BLOCKED
    assert factory.create_count == 0
    assert report.results == ()


def test_c7_parallel_workers_really_overlap() -> None:
    plan = _parallel_plan()
    barrier = Barrier(2, timeout=3)
    lock = Lock()
    active = 0
    peak_active = 0

    def execute(assignment: WorkerAssignment) -> WorkerResult:
        nonlocal active, peak_active

        with lock:
            active += 1
            peak_active = max(peak_active, active)

        barrier.wait()

        with lock:
            active -= 1

        return _success_result(assignment)

    workers = (
        _Worker("worker:a", execute),
        _Worker("worker:b", execute),
    )

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=_SequenceFactory(workers),
        max_concurrent_worker_executions=2,
    )

    assert report.status is CoordinationExecutionStatus.COLLECTED
    assert peak_active == 2
    assert all(result.status is WorkerResultStatus.SUCCESS for result in report.results)
    assert all(worker.close_count == 1 for worker in workers)


def test_c7_results_are_returned_in_plan_order() -> None:
    plan = _parallel_plan()
    second_started = Event()

    def slow_first(assignment: WorkerAssignment) -> WorkerResult:
        if not second_started.wait(timeout=3):
            raise RuntimeError("second worker did not start")
        sleep(0.02)
        return _success_result(assignment)

    def fast_second(assignment: WorkerAssignment) -> WorkerResult:
        second_started.set()
        return _success_result(assignment)

    workers = (
        _Worker("worker:first", slow_first),
        _Worker("worker:second", fast_second),
    )

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=_SequenceFactory(workers),
        max_concurrent_worker_executions=2,
    )

    assert tuple(result.assignment_id for result in report.results) == tuple(
        assignment.assignment_id for assignment in plan.assignments
    )


def test_c7_duplicate_worker_ids_fail_closed_and_cleanup() -> None:
    plan = _parallel_plan()
    workers = (
        _Worker("worker:duplicate", _success_result),
        _Worker("worker:duplicate", _success_result),
    )

    with pytest.raises(
        CoordinationRuntimeError,
        match="unique worker identities",
    ):
        CoordinationRuntime().execute(
            plan=plan,
            worker_factory=_SequenceFactory(workers),
            max_concurrent_worker_executions=2,
        )

    assert tuple(worker.close_count for worker in workers) == (1, 1)
    assert workers[0].execute_count <= 1
    assert workers[1].execute_count == 0


def test_c7_factory_cannot_reuse_same_worker_object_under_new_ids() -> None:
    plan = _parallel_plan()
    worker = _Worker("worker:first", _success_result)

    class ReusingFactory:
        def __init__(self) -> None:
            self.count = 0

        def create(self, assignment: WorkerAssignment) -> _Worker:
            del assignment
            self.count += 1
            worker._worker_id = f"worker:{self.count}"
            return worker

    with pytest.raises(
        CoordinationRuntimeError,
        match="distinct worker objects",
    ):
        CoordinationRuntime().execute(
            plan=plan,
            worker_factory=ReusingFactory(),
            max_concurrent_worker_executions=2,
        )

    assert worker.close_count == 1
    assert worker.execute_count <= 1


def test_c7_worker_protocol_violation_becomes_failed_result() -> None:
    plan = _parallel_plan()
    wrong_assignment = plan.assignments[1]

    workers = (
        _Worker(
            "worker:bad-binding",
            lambda assignment: _success_result(wrong_assignment),
        ),
        _Worker("worker:valid", _success_result),
    )

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=_SequenceFactory(workers),
        max_concurrent_worker_executions=2,
    )

    first = report.results[0]
    assert first.assignment_id == plan.assignments[0].assignment_id
    assert first.status is WorkerResultStatus.FAILED
    assert "coordination:worker_protocol_violation" in first.blocker_refs


def test_c7_execution_and_cleanup_failures_preserve_both_blockers() -> None:
    plan = _review_plan()

    def fail_execution(assignment: WorkerAssignment) -> WorkerResult:
        del assignment
        raise RuntimeError("synthetic execution failure")

    worker = _Worker(
        "worker:failing",
        fail_execution,
        close_raises=True,
    )

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=_SequenceFactory((worker,)),
        max_concurrent_worker_executions=1,
    )

    result = report.results[0]

    assert result.status is WorkerResultStatus.FAILED
    assert result.blocker_refs == (
        "coordination:worker_execution_failed",
        "coordination:worker_cleanup_failed",
    )
    assert worker.execute_count == 1
    assert worker.close_count == 1


def test_c7_cancellation_stops_new_worker_starts_at_safe_boundary() -> None:
    plan = _parallel_plan(count=3)
    cancellation = Event()

    def cancel_after_first_execution(
        assignment: WorkerAssignment,
    ) -> WorkerResult:
        cancellation.set()
        return _success_result(assignment)

    workers = (
        _Worker("worker:0", cancel_after_first_execution),
        _Worker("worker:1", _success_result),
        _Worker("worker:2", _success_result),
    )
    factory = _SequenceFactory(workers)

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=factory,
        max_concurrent_worker_executions=2,
        cancellation_requested=cancellation.is_set,
    )

    assert report.status is CoordinationExecutionStatus.CANCELLED
    assert workers[0].execute_count == 1

    # Cancellation may race with creation/submission of worker 1,
    # but no new worker may start after the cancellation boundary.
    assert workers[2].execute_count == 0
    assert factory.create_count <= 2
    assert workers[2].close_count == 0

    assert report.results[2].status is WorkerResultStatus.BLOCKED
    assert report.results[2].blocker_refs == (
        "coordination:cancelled_before_worker_start",
    )

def test_c7_zero_worker_capacity_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="max concurrent worker executions must be at least one",
    ):
        CoordinationRuntime().execute(
            plan=_solo_plan(),
            worker_factory=_ExplodingFactory(),
            max_concurrent_worker_executions=0,
        )


def test_c7_worker_creation_obeys_concurrency_ceiling() -> None:
    plan = _parallel_plan(count=3)
    lock = Lock()

    live_workers = 0
    peak_live_workers = 0
    create_count = 0

    class TrackingWorker:
        def __init__(self, worker_id: str) -> None:
            self._worker_id = worker_id
            self._closed = False

        @property
        def worker_id(self) -> str:
            return self._worker_id

        def execute(self, assignment: WorkerAssignment) -> WorkerResult:
            sleep(0.02)
            return _success_result(assignment)

        def close(self) -> None:
            nonlocal live_workers

            if self._closed:
                return

            self._closed = True
            with lock:
                live_workers -= 1

    class TrackingFactory:
        def create(self, assignment: WorkerAssignment) -> TrackingWorker:
            nonlocal live_workers, peak_live_workers, create_count
            del assignment

            with lock:
                create_count += 1
                live_workers += 1
                peak_live_workers = max(peak_live_workers, live_workers)
                worker_id = f"worker:tracked:{create_count}"

            return TrackingWorker(worker_id)

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=TrackingFactory(),
        max_concurrent_worker_executions=2,
    )

    assert report.status is CoordinationExecutionStatus.COLLECTED
    assert create_count == 3
    assert peak_live_workers == 2
    assert live_workers == 0
    assert len(report.worker_ids) == 3


def test_c7_worker_creation_failure_becomes_failed_result() -> None:
    plan = _review_plan()

    class FailingFactory:
        def create(self, assignment: WorkerAssignment) -> _Worker:
            del assignment
            raise RuntimeError("synthetic worker creation failure")

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=FailingFactory(),
        max_concurrent_worker_executions=1,
    )

    assert report.status is CoordinationExecutionStatus.COLLECTED
    assert report.worker_ids == ()
    assert len(report.results) == 1
    assert report.results[0].assignment_id == plan.assignments[0].assignment_id
    assert report.results[0].status is WorkerResultStatus.FAILED
    assert report.results[0].blocker_refs == (
        "coordination:worker_creation_failed",
    )

def test_c7_cancellation_during_worker_creation_prevents_execution() -> None:
    plan = _review_plan()
    cancellation = Event()
    worker = _Worker("worker:cancel-during-create", _success_result)

    class CancellingFactory:
        def create(self, assignment: WorkerAssignment) -> _Worker:
            del assignment
            cancellation.set()
            return worker

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=CancellingFactory(),
        max_concurrent_worker_executions=1,
        cancellation_requested=cancellation.is_set,
    )

    assert report.status is CoordinationExecutionStatus.CANCELLED
    assert report.worker_ids == ("worker:cancel-during-create",)
    assert worker.execute_count == 0
    assert worker.close_count == 1
    assert report.results[0].status is WorkerResultStatus.BLOCKED
    assert report.results[0].blocker_refs == (
        "coordination:cancelled_before_worker_start",
    )


def test_c7_worker_id_is_read_once_before_execution() -> None:
    plan = _review_plan()

    class UnstableIdWorker:
        def __init__(self) -> None:
            self.worker_id_reads = 0
            self.execute_count = 0
            self.close_count = 0

        @property
        def worker_id(self) -> str:
            self.worker_id_reads += 1
            if self.worker_id_reads > 1:
                raise RuntimeError("worker ID must not be read twice")
            return "worker:stable-snapshot"

        def execute(self, assignment: WorkerAssignment) -> WorkerResult:
            del assignment
            self.execute_count += 1
            raise RuntimeError("synthetic execution failure")

        def close(self) -> None:
            self.close_count += 1

    worker = UnstableIdWorker()

    class Factory:
        def create(self, assignment: WorkerAssignment) -> UnstableIdWorker:
            del assignment
            return worker

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=Factory(),
        max_concurrent_worker_executions=1,
    )

    assert report.status is CoordinationExecutionStatus.COLLECTED
    assert worker.worker_id_reads == 1
    assert worker.execute_count == 1
    assert worker.close_count == 1
    assert report.results[0].status is WorkerResultStatus.FAILED
    assert report.results[0].blocker_refs == (
        "coordination:worker_execution_failed",
    )


def test_c7_worker_id_failure_is_contained_and_worker_is_closed() -> None:
    plan = _review_plan()

    class BrokenIdentityWorker:
        def __init__(self) -> None:
            self.execute_count = 0
            self.close_count = 0

        @property
        def worker_id(self) -> str:
            raise RuntimeError("synthetic worker identity failure")

        def execute(self, assignment: WorkerAssignment) -> WorkerResult:
            del assignment
            self.execute_count += 1
            raise AssertionError("worker with invalid identity must not execute")

        def close(self) -> None:
            self.close_count += 1

    worker = BrokenIdentityWorker()

    class Factory:
        def create(self, assignment: WorkerAssignment) -> BrokenIdentityWorker:
            del assignment
            return worker

    report = CoordinationRuntime().execute(
        plan=plan,
        worker_factory=Factory(),
        max_concurrent_worker_executions=1,
    )

    assert report.status is CoordinationExecutionStatus.COLLECTED
    assert report.worker_ids == ()
    assert worker.execute_count == 0
    assert worker.close_count == 1
    assert report.results[0].status is WorkerResultStatus.FAILED
    assert report.results[0].blocker_refs == (
        "coordination:worker_identity_failed",
    )
