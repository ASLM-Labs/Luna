"""C7 bounded independent-worker runtime orchestration.

The coordination runtime executes task-local worker assignments through an
explicit worker factory. It does not construct authoritative TaskState,
allocate or enlarge neural resources, grant tool authority, or decide global
task completion.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import suppress
from enum import StrEnum
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.planning.coordination import (
    CoordinationMode,
    CoordinationPlan,
    WorkerAssignment,
)
from luna.planning.reconciliation import (
    CoordinationReconciler,
    WorkerResult,
    WorkerResultStatus,
)


class CoordinationRuntimeError(RuntimeError):
    """Internal C7 worker-runtime wiring violates an independence invariant."""


class CoordinationExecutionStatus(StrEnum):
    """Observable execution state; none of these imply task completion."""

    SOLO = "SOLO"
    COLLECTED = "COLLECTED"
    RESOURCE_BLOCKED = "RESOURCE_BLOCKED"
    CANCELLED = "CANCELLED"


class CoordinationWorker(Protocol):
    """One independent task-local reasoning worker."""

    @property
    def worker_id(self) -> str:
        """Stable identity unique within one coordination execution."""
        ...

    def execute(self, assignment: WorkerAssignment) -> WorkerResult:
        """Execute exactly one bounded assignment."""
        ...

    def close(self) -> None:
        """Release worker-owned resources without mutating parent task truth."""
        ...


class CoordinationWorkerFactory(Protocol):
    """Create independent workers; sharing is forbidden by runtime validation."""

    def create(self, assignment: WorkerAssignment) -> CoordinationWorker:
        """Return one worker dedicated to the supplied assignment."""
        ...


class CoordinationExecutionReport(LunaContractModel):
    """Observable C7 execution report without task/completion authority."""

    task_id: UUID
    coordination_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: CoordinationMode
    status: CoordinationExecutionStatus
    max_concurrent_worker_executions: int = Field(ge=1)
    worker_ids: tuple[str, ...] = ()
    results: tuple[WorkerResult, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)
    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("worker_ids", "reason_codes")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("coordination execution entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("coordination execution entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_execution_shape(self) -> Self:
        if self.mode is CoordinationMode.SOLO:
            if self.status is not CoordinationExecutionStatus.SOLO:
                raise ValueError("SOLO plan requires SOLO execution status")
            if self.worker_ids or self.results:
                raise ValueError("SOLO execution cannot contain workers or results")
            return self

        if self.status is CoordinationExecutionStatus.SOLO:
            raise ValueError("multi-worker plan cannot report SOLO execution")

        if any(result.task_id != self.task_id for result in self.results):
            raise ValueError("worker results must belong to execution task")

        result_assignment_ids = tuple(result.assignment_id for result in self.results)
        if len(result_assignment_ids) != len(set(result_assignment_ids)):
            raise ValueError("coordination execution results must target unique assignments")
        return self


class CoordinationRuntime:
    """Run independent C7 workers under a caller-owned concurrency ceiling."""

    def __init__(self, *, reconciler: CoordinationReconciler | None = None) -> None:
        self._reconciler = reconciler or CoordinationReconciler()

    def _failed_result(
        self,
        *,
        assignment: WorkerAssignment,
        blocker: str,
        worker_id: str | None = None,
        previous: WorkerResult | None = None,
    ) -> WorkerResult:
        provenance = (
            f"task:{assignment.task_id}",
            assignment.assignment_id,
            *(() if worker_id is None else (f"worker:{worker_id}",)),
        )
        prior_blockers = previous.blocker_refs if previous is not None else ()
        blocker_refs = tuple(dict.fromkeys((*prior_blockers, blocker)))

        return self._reconciler.result(
            assignment=assignment,
            status=WorkerResultStatus.FAILED,
            claims=previous.claims if previous is not None else (),
            evidence_ids=previous.evidence_ids if previous is not None else (),
            observation_ids=previous.observation_ids if previous is not None else (),
            blocker_refs=blocker_refs,
            provenance_refs=provenance,
        )

    def _execute_one(
        self,
        *,
        assignment: WorkerAssignment,
        worker: CoordinationWorker,
        worker_id: str,
    ) -> WorkerResult:
        result: WorkerResult | None = None

        try:
            result = worker.execute(assignment)

            if (
                result.task_id != assignment.task_id
                or result.assignment_id != assignment.assignment_id
                or result.source_task_revision != assignment.source_task_revision
                or result.assignment_basis_fingerprint
                != assignment.assignment_basis_fingerprint
            ):
                result = self._failed_result(
                    assignment=assignment,
                    blocker="coordination:worker_protocol_violation",
                    worker_id=worker_id,
                )
        except Exception:
            result = self._failed_result(
                assignment=assignment,
                blocker="coordination:worker_execution_failed",
                worker_id=worker_id,
            )
        finally:
            try:
                worker.close()
            except Exception:
                result = self._failed_result(
                    assignment=assignment,
                    blocker="coordination:worker_cleanup_failed",
                    worker_id=worker_id,
                    previous=result,
                )

        assert result is not None
        return result

    def execute(
        self,
        *,
        plan: CoordinationPlan,
        worker_factory: CoordinationWorkerFactory,
        max_concurrent_worker_executions: int,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> CoordinationExecutionReport:
        """Execute bounded assignments without acquiring parent task authority."""
        if max_concurrent_worker_executions < 1:
            raise ValueError("max concurrent worker executions must be at least one")

        if plan.mode is CoordinationMode.SOLO:
            return CoordinationExecutionReport(
                task_id=plan.task_id,
                coordination_basis_fingerprint=plan.coordination_basis_fingerprint,
                mode=plan.mode,
                status=CoordinationExecutionStatus.SOLO,
                max_concurrent_worker_executions=max_concurrent_worker_executions,
                reason_codes=("solo_plan_executes_no_coordination_workers",),
            )

        if (
            plan.mode is CoordinationMode.PARALLEL_WORKERS
            and max_concurrent_worker_executions < 2
        ):
            return CoordinationExecutionReport(
                task_id=plan.task_id,
                coordination_basis_fingerprint=plan.coordination_basis_fingerprint,
                mode=plan.mode,
                status=CoordinationExecutionStatus.RESOURCE_BLOCKED,
                max_concurrent_worker_executions=max_concurrent_worker_executions,
                reason_codes=("parallel_worker_capacity_below_two",),
            )

        if cancellation_requested is not None and cancellation_requested():
            return CoordinationExecutionReport(
                task_id=plan.task_id,
                coordination_basis_fingerprint=plan.coordination_basis_fingerprint,
                mode=plan.mode,
                status=CoordinationExecutionStatus.CANCELLED,
                max_concurrent_worker_executions=max_concurrent_worker_executions,
                reason_codes=("coordination_cancelled_before_worker_start",),
            )

        result_by_assignment: dict[str, WorkerResult] = {}
        worker_ids_by_assignment: dict[str, str] = {}
        seen_worker_ids: set[str] = set()
        seen_worker_objects: list[CoordinationWorker] = []
        cancelled = False

        pending_assignments = iter(plan.assignments)

        with ThreadPoolExecutor(
            max_workers=min(
                max_concurrent_worker_executions,
                len(plan.assignments),
            )
        ) as pool:
            futures: dict[Future[WorkerResult], WorkerAssignment] = {}

            def submit_available() -> None:
                nonlocal cancelled

                while len(futures) < max_concurrent_worker_executions:
                    if cancellation_requested is not None and cancellation_requested():
                        cancelled = True
                        return

                    try:
                        assignment = next(pending_assignments)
                    except StopIteration:
                        return

                    try:
                        worker = worker_factory.create(assignment)
                    except Exception:
                        result_by_assignment[assignment.assignment_id] = (
                            self._reconciler.result(
                                assignment=assignment,
                                status=WorkerResultStatus.FAILED,
                                blocker_refs=("coordination:worker_creation_failed",),
                                provenance_refs=(
                                    f"task:{assignment.task_id}",
                                    assignment.assignment_id,
                                ),
                            )
                        )
                        continue

                    if any(worker is previous for previous in seen_worker_objects):
                        raise CoordinationRuntimeError(
                            "coordination worker factory must return distinct worker objects"
                        )

                    try:
                        worker_id = worker.worker_id.strip()
                    except Exception:
                        result = self._failed_result(
                            assignment=assignment,
                            blocker="coordination:worker_identity_failed",
                        )
                        try:
                            worker.close()
                        except Exception:
                            result = self._failed_result(
                                assignment=assignment,
                                blocker="coordination:worker_cleanup_failed",
                                previous=result,
                            )
                        result_by_assignment[assignment.assignment_id] = result
                        continue

                    if not worker_id:
                        with suppress(Exception):
                            worker.close()
                        raise CoordinationRuntimeError(
                            "coordination worker ID cannot be blank"
                        )

                    if worker_id in seen_worker_ids:
                        with suppress(Exception):
                            worker.close()
                        raise CoordinationRuntimeError(
                            "coordination worker factory must return unique worker identities"
                        )

                    seen_worker_objects.append(worker)
                    seen_worker_ids.add(worker_id)
                    worker_ids_by_assignment[assignment.assignment_id] = worker_id

                    if (
                        cancellation_requested is not None
                        and cancellation_requested()
                    ):
                        cancelled = True
                        try:
                            worker.close()
                        except Exception:
                            result_by_assignment[assignment.assignment_id] = (
                                self._failed_result(
                                    assignment=assignment,
                                    blocker="coordination:worker_cleanup_failed",
                                    worker_id=worker_id,
                                )
                            )
                        else:
                            result_by_assignment[assignment.assignment_id] = (
                                self._reconciler.result(
                                    assignment=assignment,
                                    status=WorkerResultStatus.BLOCKED,
                                    blocker_refs=(
                                        "coordination:cancelled_before_worker_start",
                                    ),
                                    provenance_refs=(
                                        f"task:{assignment.task_id}",
                                        assignment.assignment_id,
                                        f"worker:{worker_id}",
                                    ),
                                )
                            )
                        return

                    future = pool.submit(
                        self._execute_one,
                        assignment=assignment,
                        worker=worker,
                        worker_id=worker_id,
                    )
                    futures[future] = assignment

            submit_available()

            while futures:
                completed = next(as_completed(tuple(futures)))
                assignment = futures.pop(completed)
                result_by_assignment[assignment.assignment_id] = completed.result()
                submit_available()

        if cancelled:
            for assignment in plan.assignments:
                if assignment.assignment_id in result_by_assignment:
                    continue

                result_by_assignment[assignment.assignment_id] = self._reconciler.result(
                    assignment=assignment,
                    status=WorkerResultStatus.BLOCKED,
                    blocker_refs=("coordination:cancelled_before_worker_start",),
                    provenance_refs=(
                        f"task:{assignment.task_id}",
                        assignment.assignment_id,
                    ),
                )

        ordered_results = tuple(
            result_by_assignment[assignment.assignment_id]
            for assignment in plan.assignments
        )

        worker_ids = tuple(
            worker_ids_by_assignment[assignment.assignment_id]
            for assignment in plan.assignments
            if assignment.assignment_id in worker_ids_by_assignment
        )

        status = (
            CoordinationExecutionStatus.CANCELLED
            if cancelled
            else CoordinationExecutionStatus.COLLECTED
        )
        reasons = (
            ("coordination_cancelled_at_safe_worker_boundary",)
            if cancelled
            else ("bounded_worker_results_collected",)
        )

        return CoordinationExecutionReport(
            task_id=plan.task_id,
            coordination_basis_fingerprint=plan.coordination_basis_fingerprint,
            mode=plan.mode,
            status=status,
            max_concurrent_worker_executions=max_concurrent_worker_executions,
            worker_ids=tuple(worker_ids),
            results=ordered_results,
            reason_codes=reasons,
        )
