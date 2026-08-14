"""In-memory tool registry with immutable serializable specs."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    """Unique registry; unregistered tools never reach a handler."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools[name].spec for name in sorted(self._tools))
