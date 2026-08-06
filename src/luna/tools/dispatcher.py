"""Controlled dispatcher producing ToolResult, ToolEvent, and Observation."""

from __future__ import annotations

import time
from hashlib import sha256
from typing import Protocol

from luna.contracts.enums import ObservationStatus
from luna.contracts.observation import Observation
from luna.contracts.task import TaskContract
from luna.tools.arguments import ToolArgumentError, validate_tool_arguments
from luna.tools.models import (
    DispatchOutcome,
    ToolEvent,
    ToolEventDecision,
    ToolPolicy,
    ToolRequest,
    ToolResult,
    ToolResultStatus,
)
from luna.tools.paths import WorkspacePathError, path_is_allowed
from luna.tools.policy import PolicyDecision, evaluate_tool_policy
from luna.tools.registry import (
    RegisteredTool,
    ToolExecutionContext,
    ToolExecutionDenied,
    ToolExecutionOutput,
    ToolRegistry,
)

class CapturedOutputLike(Protocol):
    text: str
    digest: str
    ref: str
    redactions_applied: tuple[str, ...]


class OutputCapture(Protocol):
    """Optional persistent redaction boundary used by Phase 6."""

    def capture_output(self, *, stream_name: str, text: str) -> CapturedOutputLike:
        """Capture redacted output under a stable content reference."""
        ...



def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _bounded_excerpts(stdout: str, stderr: str, limit: int) -> tuple[str, str, bool]:
    stdout_excerpt = stdout[:limit]
    remaining = max(0, limit - len(stdout_excerpt))
    stderr_excerpt = stderr[:remaining]
    truncated = len(stdout) + len(stderr) > len(stdout_excerpt) + len(stderr_excerpt)
    return stdout_excerpt, stderr_excerpt, truncated


def _protected_changes(
    changed_files: tuple[str, ...],
    protected_paths: tuple[str, ...],
) -> tuple[str, ...]:
    protected: list[str] = []
    for path in changed_files:
        try:
            if protected_paths and path_is_allowed(path, protected_paths):
                protected.append(path)
        except WorkspacePathError:
            protected.append(path)
    return tuple(protected)


class ToolDispatcher:
    """Deny-by-default dispatcher; models may propose but cannot authorize calls."""

    def __init__(
        self,
        registry: ToolRegistry,
        output_capture: OutputCapture | None = None,
    ) -> None:
        self._registry = registry
        self._output_capture = output_capture

    def _capture(self, *, stream_name: str, text: str) -> tuple[str, str, str, tuple[str, ...]]:
        if self._output_capture is None:
            digest = _digest(text)
            return text, digest, f"sha256:{digest}", ()
        captured = self._output_capture.capture_output(stream_name=stream_name, text=text)
        return (
            captured.text,
            captured.digest,
            captured.ref,
            captured.redactions_applied,
        )

    def _blocked(
        self,
        *,
        request: ToolRequest,
        checks: tuple[str, ...],
        reason: str,
        error_class: str,
    ) -> DispatchOutcome:
        stdout_text, stdout_digest, stdout_ref, stdout_redactions = self._capture(
            stream_name="stdout", text=""
        )
        stderr_text, stderr_digest, stderr_ref, stderr_redactions = self._capture(
            stream_name="stderr", text=reason
        )
        result = ToolResult(
            request_id=request.request_id,
            tool_name=request.tool_name,
            status=ToolResultStatus.BLOCKED,
            stdout_digest=stdout_digest,
            stderr_digest=stderr_digest,
            output_chars=len(reason),
            duration_ms=0,
            error_class=error_class,
            stdout_excerpt=stdout_text,
            stderr_excerpt=stderr_text,
        )
        event = ToolEvent(
            request_id=request.request_id,
            result_id=result.result_id,
            task_id=request.task_id,
            trace_id=request.trace_id,
            tool_name=request.tool_name,
            decision=ToolEventDecision.BLOCKED,
            policy_checks=checks,
            reason=reason,
        )
        observation = Observation(
            trace_id=request.trace_id,
            tool_event_id=event.event_id,
            status=ObservationStatus.BLOCKED,
            errors=(f"{error_class}: {reason}",),
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
            measured_values={"output_chars": result.output_chars, "duration_ms": 0},
            redactions_applied=tuple(
                dict.fromkeys((*stdout_redactions, *stderr_redactions))
            ),
        )
        return DispatchOutcome(
            request=request,
            result=result,
            event=event,
            observation=observation,
        )

    def _execute(
        self,
        *,
        registered: RegisteredTool,
        request: ToolRequest,
        task_contract: TaskContract,
        decision: PolicyDecision,
    ) -> DispatchOutcome:
        context = ToolExecutionContext(
            task_contract=task_contract,
            timeout_ms=decision.timeout_ms,
            max_output_chars=decision.max_output_chars,
            working_directory=decision.working_directory,
        )
        started = time.perf_counter()
        error_class: str | None = None
        try:
            output = registered.handler.execute(request.arguments, context)
        except ToolExecutionDenied as exc:
            return self._blocked(
                request=request,
                checks=(*decision.checks, "handler_boundary:FAIL"),
                reason=str(exc),
                error_class=type(exc).__name__,
            )
        except Exception as exc:
            output = ToolExecutionOutput(
                exit_code=1,
                stderr=str(exc),
            )
            error_class = type(exc).__name__
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))

        stdout_text, stdout_digest, stdout_ref, stdout_redactions = self._capture(
            stream_name="stdout", text=output.stdout
        )
        stderr_text, stderr_digest, stderr_ref, stderr_redactions = self._capture(
            stream_name="stderr", text=output.stderr
        )
        stdout_excerpt, stderr_excerpt, truncated = _bounded_excerpts(
            stdout_text,
            stderr_text,
            decision.max_output_chars,
        )
        protected_changed = _protected_changes(
            output.changed_files,
            task_contract.scope.protected_paths,
        )
        if protected_changed:
            error_class = "ProtectedPathChanged"

        success = output.exit_code == 0 and error_class is None and not protected_changed
        status = ToolResultStatus.SUCCESS if success else ToolResultStatus.FAILURE
        result = ToolResult(
            request_id=request.request_id,
            tool_name=request.tool_name,
            status=status,
            exit_code=output.exit_code,
            stdout_excerpt=stdout_excerpt,
            stderr_excerpt=stderr_excerpt,
            stdout_digest=stdout_digest,
            stderr_digest=stderr_digest,
            output_chars=len(output.stdout) + len(output.stderr),
            truncated=truncated,
            duration_ms=duration_ms,
            error_class=error_class,
            metadata=output.metadata,
        )
        event_decision = (
            ToolEventDecision.EXECUTED if success else ToolEventDecision.FAILED
        )
        reason = (
            "tool executed successfully"
            if success
            else "tool execution produced failure evidence"
        )
        event = ToolEvent(
            request_id=request.request_id,
            result_id=result.result_id,
            task_id=request.task_id,
            trace_id=request.trace_id,
            tool_name=request.tool_name,
            decision=event_decision,
            policy_checks=(*decision.checks, "handler_boundary:PASS"),
            reason=reason,
        )
        errors: tuple[str, ...] = ()
        if not success:
            values: list[str] = []
            if error_class is not None:
                values.append(error_class)
            if output.stderr:
                values.append(output.stderr[:1000])
            if protected_changed:
                values.append("protected_path_changed")
            errors = tuple(dict.fromkeys(values or ["non_zero_exit"]))
        observation = Observation(
            trace_id=request.trace_id,
            tool_event_id=event.event_id,
            status=ObservationStatus.SUCCESS if success else ObservationStatus.FAILURE,
            exit_code=output.exit_code,
            changed_files=output.changed_files,
            protected_files_changed=protected_changed,
            errors=errors,
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
            measured_values={
                "duration_ms": duration_ms,
                "output_chars": result.output_chars,
                "truncated": truncated,
            },
            redactions_applied=tuple(
                dict.fromkeys((*stdout_redactions, *stderr_redactions))
            ),
        )
        return DispatchOutcome(
            request=request,
            result=result,
            event=event,
            observation=observation,
        )

    def dispatch(
        self,
        *,
        request: ToolRequest,
        task_contract: TaskContract,
        policy: ToolPolicy,
    ) -> DispatchOutcome:
        registered = self._registry.get(request.tool_name)
        if registered is None:
            return self._blocked(
                request=request,
                checks=("registration:FAIL",),
                reason="tool is not registered",
                error_class="UnregisteredTool",
            )

        try:
            validate_tool_arguments(registered.spec, request.arguments)
        except ToolArgumentError as exc:
            return self._blocked(
                request=request,
                checks=("registration:PASS", "argument_schema:FAIL"),
                reason=str(exc),
                error_class=type(exc).__name__,
            )

        decision = evaluate_tool_policy(
            spec=registered.spec,
            request=request,
            task_contract=task_contract,
            policy=policy,
        )
        if not decision.allowed:
            return self._blocked(
                request=request,
                checks=("registration:PASS", "argument_schema:PASS", *decision.checks),
                reason=decision.reason,
                error_class="ToolPolicyDenied",
            )

        decision = PolicyDecision(
            allowed=True,
            checks=("registration:PASS", "argument_schema:PASS", *decision.checks),
            reason=decision.reason,
            timeout_ms=decision.timeout_ms,
            max_output_chars=decision.max_output_chars,
            working_directory=decision.working_directory,
        )
        return self._execute(
            registered=registered,
            request=request,
            task_contract=task_contract,
            decision=decision,
        )
