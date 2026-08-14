from __future__ import annotations

import time
from datetime import UTC, datetime
from threading import Barrier, Event, Thread
from uuid import uuid4

from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.tools import (
    ExecutionSettlement,
    ToolCapability,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    ToolSpec,
)
from luna.tools.lifecycle import ExecutionLifecycleController
from luna.tools.models import ToolArgumentValue
from luna.tools.registry import ToolExecutionContext, ToolExecutionOutput, ToolRegistry


class _RecordingHandler:
    def __init__(self) -> None:
        self.calls = 0
        self.lifecycle = None

    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del arguments
        self.calls += 1
        self.lifecycle = context.lifecycle
        return ToolExecutionOutput(stdout="executed")


class _CooperativeHandler(_RecordingHandler):
    def __init__(self, started: Event) -> None:
        super().__init__()
        self._started = started

    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del arguments
        self.calls += 1
        self.lifecycle = context.lifecycle
        self._started.set()
        while True:
            context.lifecycle.raise_if_cancelled()
            time.sleep(0.001)


class _SlowHandler(_RecordingHandler):
    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del arguments
        self.calls += 1
        self.lifecycle = context.lifecycle
        time.sleep(0.02)
        return ToolExecutionOutput(stdout="too late")


def _contract() -> TaskContract:
    return TaskContract(
        objective="Exercise one runtime-owned tool lifecycle.",
        required_conditions=("Tool policy remains authoritative.",),
        evidence_required=("Structured dispatch outcome.",),
        scope=TaskScope(workspace_root="."),
        risk_level=RiskLevel.LOW,
    )


def _dispatcher(handler: _RecordingHandler) -> ToolDispatcher:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="core.lifecycle_test",
            description="Synthetic read-only lifecycle test tool.",
            capabilities=(ToolCapability.READ,),
            default_timeout_ms=100,
            max_timeout_ms=1000,
        ),
        handler,
    )
    return ToolDispatcher(registry)


def _request(contract: TaskContract, *, timeout_ms: int = 100) -> ToolRequest:
    return ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="core.lifecycle_test",
        timeout_ms=timeout_ms,
    )


def _policy(*, allowed: bool = True) -> ToolPolicy:
    return ToolPolicy(
        allowed_tools=("core.lifecycle_test",) if allowed else (),
        max_timeout_ms=1000,
    )


def test_pending_cancellation_before_dispatch_calls_no_handler() -> None:
    handler = _RecordingHandler()
    task = _contract()

    outcome = _dispatcher(handler).dispatch(
        request=_request(task),
        task_contract=task,
        policy=_policy(),
        cancellation_probe=lambda: "owner cancelled before dispatch",
    )

    assert handler.calls == 0
    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert outcome.result.error_class == "ToolExecutionCancelled"


def test_cooperative_handler_observes_runtime_cancellation_and_stops() -> None:
    started = Event()
    cancelled = Event()
    handler = _CooperativeHandler(started)
    task = _contract()
    outcomes = []

    worker = Thread(
        target=lambda: outcomes.append(
            _dispatcher(handler).dispatch(
                request=_request(task, timeout_ms=500),
                task_contract=task,
                policy=_policy(),
                cancellation_probe=(
                    lambda: "owner cancelled running handler" if cancelled.is_set() else None
                ),
            )
        )
    )
    worker.start()
    assert started.wait(timeout=1)
    cancelled.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert handler.calls == 1
    assert len(outcomes) == 1
    assert outcomes[0].result.status is ToolResultStatus.FAILURE
    assert outcomes[0].result.error_class == "ToolExecutionCancelled"
    assert handler.lifecycle is not None
    assert handler.lifecycle.settlement is ExecutionSettlement.CANCELLED


def test_deadline_expiry_is_a_distinct_failed_outcome() -> None:
    handler = _SlowHandler()
    task = _contract()

    outcome = _dispatcher(handler).dispatch(
        request=_request(task, timeout_ms=5),
        task_contract=task,
        policy=_policy(),
    )

    assert handler.calls == 1
    assert outcome.result.status is ToolResultStatus.FAILURE
    assert outcome.result.exit_code == 124
    assert outcome.result.error_class == "ToolExecutionDeadlineExceeded"
    assert outcome.result.metadata["execution_lifecycle"] == "DEADLINE_EXCEEDED"


def test_completion_and_cancellation_race_settles_exactly_once() -> None:
    cancelled = Event()
    barrier = Barrier(3)
    controller = ExecutionLifecycleController.start(
        execution_id=uuid4(),
        timeout_ms=1000,
        cancellation_probe=lambda: "racing cancellation" if cancelled.is_set() else None,
        wall_clock=lambda: datetime(2026, 8, 14, tzinfo=UTC),
    )
    controller.mark_handler_started()
    settlements: list[ExecutionSettlement] = []

    def complete() -> None:
        barrier.wait()
        settlements.append(controller.settle_handler(failed=False))

    def cancel() -> None:
        barrier.wait()
        cancelled.set()
        stop = controller.lifecycle.stop
        settlements.append(
            controller.settle_handler(failed=False, observed_stop=stop)
        )

    threads = (Thread(target=complete), Thread(target=cancel))
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=1)

    assert all(not thread.is_alive() for thread in threads)
    assert len(settlements) == 2
    assert settlements[0] is settlements[1]
    assert controller.lifecycle.settlement is settlements[0]
    assert controller.close() is settlements[0]


def test_close_settles_an_unstarted_owned_lifecycle_once() -> None:
    controller = ExecutionLifecycleController.start(
        execution_id=uuid4(),
        timeout_ms=100,
    )

    assert controller.close() is ExecutionSettlement.CLOSED
    assert controller.settle_handler(failed=False) is ExecutionSettlement.CLOSED
    assert controller.lifecycle.settlement is ExecutionSettlement.CLOSED


def test_lifecycle_cannot_bypass_policy_or_expose_authority_mutators() -> None:
    handler = _RecordingHandler()
    task = _contract()

    outcome = _dispatcher(handler).dispatch(
        request=_request(task),
        task_contract=task,
        policy=_policy(allowed=False),
        cancellation_probe=lambda: None,
    )

    assert handler.calls == 0
    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert outcome.result.error_class == "ToolPolicyDenied"

    allowed = _dispatcher(handler).dispatch(
        request=_request(task),
        task_contract=task,
        policy=_policy(),
    )
    assert allowed.result.status is ToolResultStatus.SUCCESS
    assert handler.lifecycle is not None
    assert not hasattr(handler.lifecycle, "clear_cancellation")
    assert not hasattr(handler.lifecycle, "extend_deadline")
    assert not hasattr(handler.lifecycle, "policy")
    assert not hasattr(handler.lifecycle, "budget")
