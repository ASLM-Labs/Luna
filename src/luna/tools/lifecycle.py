"""Runtime-owned cooperative lifecycle for one authorized tool execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from threading import Lock
from time import monotonic
from uuid import UUID

from luna.contracts.base import utc_now

type CancellationProbe = Callable[[], str | None]
type MonotonicClock = Callable[[], float]
type WallClock = Callable[[], datetime]


class ExecutionStopKind(StrEnum):
    """Why cooperative execution was asked to stop."""

    CANCELLED = "CANCELLED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"


class ExecutionSettlement(StrEnum):
    """Exactly-once terminal state owned by the runtime controller."""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class ExecutionStop:
    """Bounded, non-authoritative cancellation/deadline observation."""

    kind: ExecutionStopKind
    reason: str


class ToolExecutionStopped(RuntimeError):
    """Base cooperative stop raised when a handler observes lifecycle state."""

    def __init__(self, stop: ExecutionStop) -> None:
        self.stop = stop
        super().__init__(stop.reason)


class ToolExecutionCancelled(ToolExecutionStopped):
    """Explicit runtime cancellation observed by a cooperative handler."""


class ToolExecutionDeadlineExceeded(ToolExecutionStopped):
    """Runtime deadline observed by a cooperative handler."""


@dataclass(slots=True)
class _ExecutionLifecycleState:
    execution_id: UUID
    deadline_at: datetime
    deadline_tick: float
    cancellation_probe: CancellationProbe | None
    clock: MonotonicClock
    lock: Lock = field(default_factory=Lock)
    stop: ExecutionStop | None = None
    settlement: ExecutionSettlement | None = None
    handler_started: bool = False


class ExecutionLifecycle:
    """Read-only lifecycle view supplied to an already-authorized handler."""

    __slots__ = ("_state",)

    def __init__(self, state: _ExecutionLifecycleState) -> None:
        self._state = state

    @property
    def execution_id(self) -> UUID:
        return self._state.execution_id

    @property
    def deadline_at(self) -> datetime:
        return self._state.deadline_at

    @property
    def remaining_ms(self) -> int:
        remaining = self._state.deadline_tick - self._state.clock()
        return max(0, int(remaining * 1000))

    @property
    def settlement(self) -> ExecutionSettlement | None:
        with self._state.lock:
            return self._state.settlement

    @property
    def stop(self) -> ExecutionStop | None:
        return self._observe_stop()

    @property
    def cancellation_requested(self) -> bool:
        return self._observe_stop() is not None

    @property
    def cancellation_reason(self) -> str | None:
        stop = self._observe_stop()
        return stop.reason if stop is not None else None

    def raise_if_cancelled(self) -> None:
        """Cooperatively stop without granting the handler lifecycle authority."""

        stop = self._observe_stop()
        if stop is None:
            return
        if stop.kind is ExecutionStopKind.DEADLINE_EXCEEDED:
            raise ToolExecutionDeadlineExceeded(stop)
        raise ToolExecutionCancelled(stop)

    def _observe_stop(self) -> ExecutionStop | None:
        with self._state.lock:
            if self._state.stop is not None:
                return self._state.stop
            if self._state.settlement is not None:
                return None

        reason = None
        if self._state.cancellation_probe is not None:
            reason = self._state.cancellation_probe()
        explicit_stop = (
            ExecutionStop(
                kind=ExecutionStopKind.CANCELLED,
                reason=_bounded_reason(reason, default="runtime cancellation requested"),
            )
            if reason is not None
            else None
        )
        deadline_stop = (
            ExecutionStop(
                kind=ExecutionStopKind.DEADLINE_EXCEEDED,
                reason="tool execution deadline exceeded",
            )
            if self._state.clock() >= self._state.deadline_tick
            else None
        )
        observed = explicit_stop or deadline_stop
        if observed is None:
            return None
        with self._state.lock:
            if self._state.settlement is not None:
                return self._state.stop
            if self._state.stop is None:
                self._state.stop = observed
            return self._state.stop


class ExecutionLifecycleController:
    """Runtime-only owner that starts and settles one handler lifecycle exactly once."""

    __slots__ = ("_lifecycle", "_state")

    def __init__(self, state: _ExecutionLifecycleState) -> None:
        self._state = state
        self._lifecycle = ExecutionLifecycle(state)

    @classmethod
    def start(
        cls,
        *,
        execution_id: UUID,
        timeout_ms: int,
        cancellation_probe: CancellationProbe | None = None,
        clock: MonotonicClock = monotonic,
        wall_clock: WallClock = utc_now,
    ) -> ExecutionLifecycleController:
        if timeout_ms < 1:
            raise ValueError("execution lifecycle timeout must be positive")
        now_tick = clock()
        now = wall_clock()
        state = _ExecutionLifecycleState(
            execution_id=execution_id,
            deadline_at=now + timedelta(milliseconds=timeout_ms),
            deadline_tick=now_tick + (timeout_ms / 1000),
            cancellation_probe=cancellation_probe,
            clock=clock,
        )
        return cls(state)

    @property
    def lifecycle(self) -> ExecutionLifecycle:
        return self._lifecycle

    def mark_handler_started(self) -> None:
        with self._state.lock:
            if self._state.settlement is not None:
                raise RuntimeError("settled execution lifecycle cannot start a handler")
            self._state.handler_started = True

    def settle_handler(
        self,
        *,
        failed: bool,
        observed_stop: ExecutionStop | None = None,
    ) -> ExecutionSettlement:
        stop = observed_stop or self._lifecycle._observe_stop()
        with self._state.lock:
            if self._state.settlement is not None:
                return self._state.settlement
            if stop is not None and self._state.stop is None:
                self._state.stop = stop
            if self._state.stop is not None:
                self._state.settlement = (
                    ExecutionSettlement.DEADLINE_EXCEEDED
                    if self._state.stop.kind is ExecutionStopKind.DEADLINE_EXCEEDED
                    else ExecutionSettlement.CANCELLED
                )
            else:
                self._state.settlement = (
                    ExecutionSettlement.FAILED if failed else ExecutionSettlement.COMPLETED
                )
            return self._state.settlement

    def close(self) -> ExecutionSettlement:
        """Settle an otherwise abandoned owned operation without orphaning a waiter."""

        with self._state.lock:
            if self._state.settlement is None:
                self._state.settlement = ExecutionSettlement.CLOSED
            return self._state.settlement


def _bounded_reason(reason: str | None, *, default: str) -> str:
    cleaned = (reason or "").strip()
    return (cleaned or default)[:2000]
