"""In-memory tool registry with immutable serializable specs."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol

from luna.contracts.task import TaskContract
from luna.tools.lifecycle import ExecutionLifecycle
from luna.tools.models import ToolArgumentValue, ToolScalar, ToolSpec


class ToolExecutionDenied(RuntimeError):
    """Handler-level denial for a condition known only during execution."""


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Runtime-owned execution context supplied to handlers."""

    task_contract: TaskContract
    timeout_ms: int
    max_output_chars: int
    working_directory: str | None
    lifecycle: ExecutionLifecycle


@dataclass(frozen=True, slots=True)
class ToolExecutionOutput:
    """Raw handler output normalized by ToolDispatcher."""

    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    changed_files: tuple[str, ...] = ()
    metadata: dict[str, ToolScalar] = field(default_factory=dict)


class ToolHandler(Protocol):
    """Execution interface owned by the runtime, not by the model."""

    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        """Execute one already-authorized request."""
        ...


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    """Thread-safe registry whose reads return stable registration snapshots.

    Removal governs subsequent lookups; it does not revoke a handler that the
    dispatcher already obtained for an in-flight execution.
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._lock = RLock()

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        with self._lock:
            if spec.name in self._tools:
                raise ValueError(f"tool already registered: {spec.name}")
            self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def get(self, name: str) -> RegisteredTool | None:
        with self._lock:
            return self._tools.get(name)

    def unregister(self, name: str) -> RegisteredTool | None:
        """Remove a tool that is no longer available at its runtime source."""
        with self._lock:
            return self._tools.pop(name, None)

    def snapshot(self) -> tuple[RegisteredTool, ...]:
        """Return one coherent, name-sorted view of current registrations."""
        with self._lock:
            return tuple(self._tools[name] for name in sorted(self._tools))

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(registered.spec for registered in self.snapshot())
