"""Controlled dispatcher producing ToolResult, ToolEvent, and Observation."""

from __future__ import annotations

from hashlib import sha256
import time

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
from luna.tools.policy import PolicyDecision, evaluate_tool_policy
from luna.tools.registry import (
    RegisteredTool,
    ToolExecutionContext,
    ToolExecutionDenied,
    ToolExecutionOutput,
    ToolRegistry,
)


_EMPTY_DIGEST = sha256(b"").hexdigest()


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
    protected = set(protected_paths)
    return tuple(path for path in changed_files if path in protected)


class ToolDispatcher:
    """Deny-by-default dispatcher; models may propose but cannot authorize calls."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @staticmethod
    def _blocked(
        *,
        request: ToolRequest,
        checks: tuple[str, ...],
        reason: str,
        error_class: str,
    ) -> DispatchOutcome:
        result = ToolResult(
            request_id=request.request_id,
            tool_name=request.tool_name,
            status=ToolResultStatus.BLOCKED,
            stdout_digest=_EMPTY_DIGEST,
            stderr_digest=_digest(reason),
            output_chars=len(reason),
            duration_ms=0,
            error_class=error_class,
            stderr_excerpt=reason,
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
            stdout_ref=f"sha256:{result.stdout_digest}",
            stderr_ref=f"sha256:{result.stderr_digest}",
            measured_values={"output_chars": result.output_chars, "duration_ms": 0},
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
                checks=decision.checks + ("handler_boundary:FAIL",),
                reason=str(exc),
                error_class=type(exc).__name__,
            )
        except Exception as exc:  # noqa: BLE001 - runtime converts handler faults to evidence
            output = ToolExecutionOutput(
                exit_code=1,
                stderr=str(exc),
            )
            error_class = type(exc).__name__
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))

        stdout_excerpt, stderr_excerpt, truncated = _bounded_excerpts(
            output.stdout,
            output.stderr,
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
            stdout_digest=_digest(output.stdout),
            stderr_digest=_digest(output.stderr),
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
            policy_checks=decision.checks + ("handler_boundary:PASS",),
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
            stdout_ref=f"sha256:{result.stdout_digest}",
            stderr_ref=f"sha256:{result.stderr_digest}",
            measured_values={
                "duration_ms": duration_ms,
                "output_chars": result.output_chars,
                "truncated": truncated,
            },
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
                checks=("registration:PASS", "argument_schema:PASS") + decision.checks,
                reason=decision.reason,
                error_class="ToolPolicyDenied",
            )

        decision = PolicyDecision(
            allowed=True,
            checks=("registration:PASS", "argument_schema:PASS") + decision.checks,
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
