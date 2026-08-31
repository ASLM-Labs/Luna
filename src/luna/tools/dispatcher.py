"""Controlled dispatcher producing ToolResult, ToolEvent, and Observation."""

from __future__ import annotations

import time
from datetime import datetime
from hashlib import sha256
from typing import Protocol
from uuid import UUID, uuid4

from luna.applied_changes.models import (
    AppliedChangeBindingError,
    AppliedChangeBindingState,
    AppliedChangeOperation,
    AppliedChangeRecord,
    applied_change_manifest_sha256,
)
from luna.contracts.base import utc_now
from luna.contracts.enums import ObservationStatus
from luna.contracts.observation import Observation
from luna.contracts.task import TaskContract
from luna.tools.arguments import ToolArgumentError, validate_tool_arguments
from luna.tools.lifecycle import (
    CancellationProbe,
    ExecutionLifecycleController,
    ExecutionSettlement,
    ExecutionStop,
    ExecutionStopKind,
    ToolExecutionStopped,
)
from luna.tools.models import (
    DispatchOutcome,
    ToolCapability,
    ToolEvent,
    ToolEventDecision,
    ToolPolicy,
    ToolRequest,
    ToolResult,
    ToolResultStatus,
    ToolScalar,
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

_SIDE_EFFECT_CAPABILITIES = {
    ToolCapability.WRITE,
    ToolCapability.NETWORK,
    ToolCapability.PROCESS,
}


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


class AppliedChangeStoreLike(Protocol):
    """Minimal durable binding boundary used by the dispatcher."""

    def persist_many(
        self,
        records: tuple[
            AppliedChangeRecord,
            ...,
        ],
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        ...

    def list_for_result(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        ...


_APPLIED_CHANGE_METADATA_PREFIX = (
    "applied_change_"
)

_APPLIED_CHANGE_TOOL_OPERATIONS = {
    "filesystem.write_text": (
        AppliedChangeOperation.WRITE_TEXT
    ),
    "filesystem.replace_text": (
        AppliedChangeOperation.REPLACE_TEXT
    ),
}


def _metadata_without_applied_change_receipt(
    metadata: dict[str, ToolScalar],
) -> dict[str, ToolScalar]:
    """Remove handler-owned values from the reserved receipt namespace."""

    return {
        key: value
        for key, value in metadata.items()
        if not key.startswith(
            _APPLIED_CHANGE_METADATA_PREFIX
        )
    }


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


def _lifecycle_error_class(stop: ExecutionStop, *, ambiguous: bool) -> str:
    if stop.kind is ExecutionStopKind.DEADLINE_EXCEEDED:
        return (
            "ToolExecutionDeadlineAmbiguous"
            if ambiguous
            else "ToolExecutionDeadlineExceeded"
        )
    return "ToolExecutionCancellationAmbiguous" if ambiguous else "ToolExecutionCancelled"


def _lifecycle_failure_output(
    stop: ExecutionStop,
    *,
    ambiguous: bool,
    output: ToolExecutionOutput | None = None,
) -> ToolExecutionOutput:
    existing = output or ToolExecutionOutput()
    reason = stop.reason
    if ambiguous:
        reason = (
            f"{reason}; side-effect handler may have executed and must not be blindly replayed"
        )
    stderr = "\n".join(value for value in (existing.stderr, reason) if value)
    return ToolExecutionOutput(
        exit_code=124 if stop.kind is ExecutionStopKind.DEADLINE_EXCEEDED else 130,
        stdout=existing.stdout,
        stderr=stderr,
        changed_files=existing.changed_files,
        applied_changes=existing.applied_changes,
        metadata={
            **existing.metadata,
            "execution_lifecycle": stop.kind.value,
            "execution_may_have_occurred": ambiguous,
        },
    )


class ToolDispatcher:
    """Deny-by-default dispatcher; models may propose but cannot authorize calls."""

    def __init__(
        self,
        registry: ToolRegistry,
        output_capture: OutputCapture | None = None,
        applied_change_store: AppliedChangeStoreLike | None = None,
    ) -> None:
        self._registry = registry
        self._output_capture = output_capture
        self._applied_change_store = applied_change_store
        self._free_research_usage: dict[UUID, int] = {}
        self._free_research_started_at: dict[UUID, datetime] = {}

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

    def _result_metadata_with_applied_change_binding(
        self,
        *,
        request: ToolRequest,
        result_id: UUID,
        output: ToolExecutionOutput,
        base_metadata: dict[str, ToolScalar],
    ) -> dict[str, ToolScalar]:
        metadata = dict(base_metadata)

        candidates = output.applied_changes

        if not candidates:
            return metadata

        metadata[
            "applied_change_count"
        ] = len(candidates)

        def unavailable(
            reason: AppliedChangeBindingError,
        ) -> dict[str, ToolScalar]:
            metadata[
                "applied_change_binding_state"
            ] = (
                AppliedChangeBindingState
                .UNAVAILABLE.value
            )

            metadata[
                "applied_change_binding_error"
            ] = reason.value

            metadata.pop(
                "applied_change_manifest_sha256",
                None,
            )

            return metadata

        if any(
            candidate.task_id
            != request.task_id
            for candidate in candidates
        ):
            return unavailable(
                AppliedChangeBindingError
                .CANDIDATE_TASK_MISMATCH
            )

        expected_operation = (
            _APPLIED_CHANGE_TOOL_OPERATIONS
            .get(request.tool_name)
        )

        if (
            expected_operation is None
            or any(
                candidate.operation
                is not expected_operation
                for candidate in candidates
            )
        ):
            return unavailable(
                AppliedChangeBindingError
                .CANDIDATE_SOURCE_MISMATCH
            )

        candidate_paths = tuple(
            candidate.relative_path
            for candidate in candidates
        )

        changed_paths = (
            output.changed_files
        )

        if (
            len(candidate_paths)
            != len(set(candidate_paths))
            or len(changed_paths)
            != len(set(changed_paths))
            or set(candidate_paths)
            != set(changed_paths)
        ):
            return unavailable(
                AppliedChangeBindingError
                .CANDIDATE_PATH_MISMATCH
            )

        store = self._applied_change_store

        if store is None:
            return unavailable(
                AppliedChangeBindingError
                .STORE_NOT_CONFIGURED
            )

        recorded_at = utc_now()

        try:
            records = tuple(
                AppliedChangeRecord.build(
                    request_id=(
                        request.request_id
                    ),
                    result_id=result_id,
                    candidate=candidate,
                    recorded_at=recorded_at,
                )
                for candidate in candidates
            )

            persisted = (
                store.persist_many(
                    records
                )
            )

            if persisted != records:
                return unavailable(
                    AppliedChangeBindingError
                    .PERSISTED_SET_MISMATCH
                )

            durable = (
                store.list_for_result(
                    task_id=(
                        request.task_id
                    ),
                    request_id=(
                        request.request_id
                    ),
                    result_id=result_id,
                )
            )

            expected_durable = tuple(
                sorted(
                    records,
                    key=lambda record: (
                        record.candidate
                        .relative_path,
                        str(
                            record.record_id
                        ),
                    ),
                )
            )

            if durable != expected_durable:
                return unavailable(
                    AppliedChangeBindingError
                    .PERSISTED_SET_MISMATCH
                )

            manifest = (
                applied_change_manifest_sha256(
                    durable
                )
            )

        except Exception:
            return unavailable(
                AppliedChangeBindingError
                .PERSISTENCE_FAILED
            )

        metadata[
            "applied_change_binding_state"
        ] = (
            AppliedChangeBindingState
            .BOUND.value
        )

        metadata[
            "applied_change_count"
        ] = len(durable)

        metadata[
            "applied_change_manifest_sha256"
        ] = manifest

        metadata.pop(
            "applied_change_binding_error",
            None,
        )

        return metadata

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
        cancellation_probe: CancellationProbe | None,
    ) -> DispatchOutcome:
        lifecycle_owner = ExecutionLifecycleController.start(
            execution_id=request.request_id,
            timeout_ms=decision.timeout_ms,
            cancellation_probe=cancellation_probe,
        )
        lifecycle = lifecycle_owner.lifecycle
        pending_stop = lifecycle.stop
        if pending_stop is not None:
            lifecycle_owner.settle_handler(failed=True, observed_stop=pending_stop)
            lifecycle_owner.close()
            return self._blocked(
                request=request,
                checks=(*decision.checks, "execution_lifecycle:FAIL"),
                reason=pending_stop.reason,
                error_class=_lifecycle_error_class(pending_stop, ambiguous=False),
            )

        context = ToolExecutionContext(
            task_contract=task_contract,
            timeout_ms=decision.timeout_ms,
            max_output_chars=decision.max_output_chars,
            working_directory=decision.working_directory,
            lifecycle=lifecycle,
        )
        started = time.perf_counter()
        error_class: str | None = None
        handler_denial: ToolExecutionDenied | None = None
        observed_stop: ExecutionStop | None = None
        lifecycle_owner.mark_handler_started()
        try:
            output = registered.handler.execute(request.arguments, context)
        except ToolExecutionStopped as exc:
            observed_stop = exc.stop
            output = ToolExecutionOutput()
        except ToolExecutionDenied as exc:
            handler_denial = exc
            output = ToolExecutionOutput(exit_code=1, stderr=str(exc))
        except Exception as exc:
            output = ToolExecutionOutput(
                exit_code=1,
                stderr=str(exc),
            )
            error_class = type(exc).__name__
        settlement = lifecycle_owner.settle_handler(
            failed=(
                output.exit_code != 0
                or error_class is not None
                or handler_denial is not None
            ),
            observed_stop=observed_stop,
        )
        if settlement in {
            ExecutionSettlement.CANCELLED,
            ExecutionSettlement.DEADLINE_EXCEEDED,
        }:
            stop = lifecycle.stop
            if stop is None:
                raise RuntimeError("cancelled execution lifecycle lost its stop observation")
            ambiguous = bool(set(registered.spec.capabilities) & _SIDE_EFFECT_CAPABILITIES)
            output = _lifecycle_failure_output(
                stop,
                ambiguous=ambiguous,
                output=output,
            )
            error_class = _lifecycle_error_class(stop, ambiguous=ambiguous)
            handler_denial = None
        elif handler_denial is not None:
            lifecycle_owner.close()
            return self._blocked(
                request=request,
                checks=(*decision.checks, "handler_boundary:FAIL"),
                reason=str(handler_denial),
                error_class=type(handler_denial).__name__,
            )
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

        result_id = uuid4()

        base_result_metadata = (
            _metadata_without_applied_change_receipt(
                output.metadata
            )
        )

        result = ToolResult(
            result_id=result_id,
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
            metadata=base_result_metadata,
        )

        result_metadata = (
            self._result_metadata_with_applied_change_binding(
                request=request,
                result_id=result.result_id,
                output=output,
                base_metadata=base_result_metadata,
            )
        )

        result.metadata = result_metadata

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
        lifecycle_owner.close()
        return DispatchOutcome(
            request=request,
            result=result,
            event=event,
            observation=observation,
        )

    def _authorize(
        self,
        *,
        request: ToolRequest,
        task_contract: TaskContract,
        policy: ToolPolicy,
        approval_basis_fingerprint: str | None,
    ) -> tuple[RegisteredTool | None, PolicyDecision, str | None, datetime]:
        runtime_now = utc_now()
        registered = self._registry.get(request.tool_name)
        if registered is None:
            return (
                None,
                PolicyDecision(
                    allowed=False,
                    checks=("registration:FAIL",),
                    reason="tool is not registered",
                    timeout_ms=0,
                    max_output_chars=0,
                    working_directory=None,
                ),
                "UnregisteredTool",
                runtime_now,
            )

        try:
            validate_tool_arguments(registered.spec, request.arguments)
        except ToolArgumentError as exc:
            return (
                registered,
                PolicyDecision(
                    allowed=False,
                    checks=("registration:PASS", "argument_schema:FAIL"),
                    reason=str(exc),
                    timeout_ms=0,
                    max_output_chars=0,
                    working_directory=None,
                ),
                type(exc).__name__,
                runtime_now,
            )

        effective_policy = policy
        research_contract = policy.free_research_contract
        if research_contract is not None:
            contract_id = research_contract.contract_id
            used = max(
                policy.free_research_requests_used,
                self._free_research_usage.get(contract_id, 0),
            )
            started_at = self._free_research_started_at.get(
                contract_id,
                policy.free_research_session_started_at or runtime_now,
            )
            effective_policy = policy.model_copy(
                update={
                    "free_research_requests_used": used,
                    "free_research_session_started_at": started_at,
                }
            )

        decision = evaluate_tool_policy(
            spec=registered.spec,
            request=request,
            task_contract=task_contract,
            policy=effective_policy,
            now=runtime_now,
            approval_basis_fingerprint=approval_basis_fingerprint,
        )
        wrapped = PolicyDecision(
            allowed=decision.allowed,
            checks=("registration:PASS", "argument_schema:PASS", *decision.checks),
            reason=decision.reason,
            timeout_ms=decision.timeout_ms,
            max_output_chars=decision.max_output_chars,
            working_directory=decision.working_directory,
        )
        return (
            registered,
            wrapped,
            None if decision.allowed else "ToolPolicyDenied",
            runtime_now,
        )

    def authorize(
        self,
        *,
        request: ToolRequest,
        task_contract: TaskContract,
        policy: ToolPolicy,
        approval_basis_fingerprint: str | None = None,
    ) -> PolicyDecision:
        """Preflight without execution; dispatch re-authorizes before any handler call."""
        _, decision, _, _ = self._authorize(
            request=request,
            task_contract=task_contract,
            policy=policy,
            approval_basis_fingerprint=approval_basis_fingerprint,
        )
        return decision

    def dispatch(
        self,
        *,
        request: ToolRequest,
        task_contract: TaskContract,
        policy: ToolPolicy,
        cancellation_probe: CancellationProbe | None = None,
        approval_basis_fingerprint: str | None = None,
    ) -> DispatchOutcome:
        registered, decision, denial_class, runtime_now = self._authorize(
            request=request,
            task_contract=task_contract,
            policy=policy,
            approval_basis_fingerprint=approval_basis_fingerprint,
        )
        if not decision.allowed:
            return self._blocked(
                request=request,
                checks=decision.checks,
                reason=decision.reason,
                error_class=denial_class or "ToolPolicyDenied",
            )
        if registered is None:
            raise RuntimeError("authorized tool lost its registry entry")

        research_contract = policy.free_research_contract
        if research_contract is not None:
            contract_id = research_contract.contract_id
            self._free_research_started_at.setdefault(contract_id, runtime_now)
            self._free_research_usage[contract_id] = (
                self._free_research_usage.get(contract_id, 0) + 1
            )

        return self._execute(
            registered=registered,
            request=request,
            task_contract=task_contract,
            decision=decision,
            cancellation_probe=cancellation_probe,
        )
