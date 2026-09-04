"""Registered exact-argv process tool."""

from __future__ import annotations

from luna.shell.runner import SafeProcessError, run_bounded_argv
from luna.tools.models import ToolArgumentValue
from luna.tools.registry import (
    ToolExecutionContext,
    ToolExecutionDenied,
    ToolExecutionOutput,
)


def _argv(arguments: dict[str, ToolArgumentValue]) -> tuple[str, ...]:
    value = arguments["argv"]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError("validated argv is not a string list")
    return tuple(value)


class RunArgvTool:
    """Run one exact, owner-approved argv without a command shell."""

    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        if context.working_directory is None:
            raise ToolExecutionDenied("process tool requires a working directory")
        try:
            execution = run_bounded_argv(
                argv=_argv(arguments),
                working_directory=context.working_directory,
                timeout_ms=context.timeout_ms,
                max_output_chars=context.max_output_chars,
                stop_requested=lambda: context.lifecycle.cancellation_requested,
            )
        except SafeProcessError as exc:
            raise ToolExecutionDenied(str(exc)) from exc
        return ToolExecutionOutput(
            exit_code=execution.exit_code,
            stdout=execution.stdout,
            stderr=execution.stderr,
            metadata={
                "argv_sha256": execution.argv_digest,
                "timed_out": execution.timed_out,
                "output_limit_exceeded": execution.output_limit_exceeded,
                "shell": False,
            },
        )
