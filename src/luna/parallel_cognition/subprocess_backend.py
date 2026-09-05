"""Bounded subprocess driver for S4 read-only worker attempts.

The driver protocol is file based so worker output cannot block the root on an
unbounded pipe.  Every subprocess is started without a shell, with an explicit
environment, isolated ephemeral scratch, a cooperative cancellation token, and a
bounded terminate/kill sequence.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from typing import Protocol

from pydantic import ValidationError

from luna.contracts.base import utc_now
from luna.parallel_cognition.live import (
    BackendSafetyCapabilities,
    FocusedContextBundle,
    LiveBackendRequest,
    LiveBackendResult,
    LiveNativeTokenUsage,
    LiveWorkerDraft,
    S4RuntimePolicy,
)
from luna.parallel_cognition.models import (
    AgentLifecycleState,
    AgentPayload,
    AgentResourceUsage,
    CleanupState,
    ProposedClaim,
    canonical_contract_json,
    contract_sha256,
)
from luna.shell.runner import (
    OwnedProcessTree,
    start_owned_process,
    terminate_owned_process_tree,
)


class InterruptibleWorkerBackend(Protocol):
    """S4 backend boundary accepted only with complete safety capabilities."""

    @property
    def backend_id(self) -> str:
        """Stable backend route identifier."""

    @property
    def profile_id(self) -> str:
        """Stable model/profile route identifier."""

    @property
    def safety_capabilities(self) -> BackendSafetyCapabilities:
        """Declare the concrete root-liveness and isolation properties."""

    def execute(
        self,
        *,
        request: LiveBackendRequest,
        context: FocusedContextBundle,
        policy: S4RuntimePolicy,
        cancellation_probe: Callable[[], bool],
    ) -> LiveBackendResult:
        """Execute once and return only after process and scratch cleanup."""


@dataclass(frozen=True, slots=True)
class _ObservedProcessOutcome:
    state: AgentLifecycleState
    outcome_at: datetime
    cancel_requested_at: datetime | None
    hard_termination_used: bool
    reason: str | None
    draft: LiveWorkerDraft | None
    raw_output_sha256: str | None
    raw_output_size_bytes: int
    runtime_ms: int


class SubprocessWorkerBackend:
    """Run an explicitly configured S4 driver command in bounded scratch.

    ``command_template`` must use each of ``{request}``, ``{result}``, and
    ``{cancel}`` exactly once.  The executable must be absolute.  No ambient
    environment is inherited and ``shell`` is always disabled.
    """

    _PLACEHOLDERS = ("{request}", "{result}", "{cancel}")

    def __init__(
        self,
        *,
        command_template: tuple[str, ...],
        backend_id: str,
        profile_id: str,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not command_template:
            raise ValueError("S4 subprocess command cannot be empty")
        executable = Path(command_template[0])
        if not executable.is_absolute():
            raise ValueError("S4 subprocess executable must be an absolute path")
        if not backend_id.strip() or not profile_id.strip():
            raise ValueError("S4 backend and profile IDs cannot be blank")
        joined = "\n".join(command_template)
        if any(joined.count(item) != 1 for item in self._PLACEHOLDERS):
            raise ValueError("S4 command must bind each driver path exactly once")
        unbound = joined
        for placeholder in self._PLACEHOLDERS:
            unbound = unbound.replace(placeholder, "")
        if "{" in unbound or "}" in unbound:
            raise ValueError("S4 command contains an unknown placeholder")
        clean_environment: dict[str, str] = {}
        for key, value in (environment or {}).items():
            if not key or "=" in key or "\x00" in key or "\x00" in value:
                raise ValueError("S4 subprocess environment contains an invalid entry")
            clean_environment[str(key)] = str(value)
        self._command_template = tuple(command_template)
        self._backend_id = backend_id.strip()
        self._profile_id = profile_id.strip()
        self._environment = clean_environment
        self._capabilities = BackendSafetyCapabilities(
            bounded_driver_calls=True,
            cooperative_cancellation=True,
            hard_termination=True,
            isolated_ephemeral_scratch=True,
            explicit_environment_only=True,
            shell_disabled=True,
        )

    @property
    def backend_id(self) -> str:
        return self._backend_id

    @property
    def profile_id(self) -> str:
        return self._profile_id

    @property
    def safety_capabilities(self) -> BackendSafetyCapabilities:
        return self._capabilities

    @staticmethod
    def _driver_payload(
        request: LiveBackendRequest,
        context: FocusedContextBundle,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "request_id": request.request_id,
            "task_id": str(request.assignment.task_id),
            "assignment_id": request.assignment.assignment_id,
            "attempt_id": request.attempt.attempt_id,
            "worker_role": request.assignment.worker_role.value,
            "objective": request.assignment.objective,
            "deadline_at": request.attempt.deadline_at.isoformat(),
            "max_output_tokens": request.assignment.budget.max_tokens,
            "context": [item.model_dump(mode="json") for item in context.documents],
            "available_tools": [],
            "credentials": [],
            "inherited_memory": [],
            "authority": {
                "write": False,
                "network": False,
                "process": False,
                "tool": False,
                "external_action": False,
                "delegation": False,
                "memory_commit": False,
                "state_mutation": False,
                "completion": False,
                "user_facing_voice": False,
            },
            "output_contract": "summary_and_cited_claims_only_no_hidden_reasoning",
        }

    @staticmethod
    def _failure_payload(request: LiveBackendRequest, reason: str) -> AgentPayload:
        return AgentPayload(
            task_id=request.assignment.task_id,
            source_task_revision=request.assignment.source_task_revision,
            assignment_id=request.assignment.assignment_id,
            attempt_id=request.attempt.attempt_id,
            context_manifest_sha256=request.assignment.context_manifest_sha256,
            summary=f"Worker result was not admitted: {reason}"[:8000],
            uncertainty=(reason[:2000],),
        )

    @staticmethod
    def _payload_from_draft(
        request: LiveBackendRequest,
        draft: LiveWorkerDraft,
    ) -> AgentPayload:
        granted = set(request.assignment.granted_source_refs)
        if any(not set(item.source_refs).issubset(granted) for item in draft.claims):
            raise ValueError("worker draft cites a source outside focused context")
        claims = tuple(
            ProposedClaim(
                claim_key=item.claim_key,
                statement=item.statement,
                source_refs=item.source_refs,
                evidence_refs=item.evidence_refs,
                observation_refs=item.observation_refs,
            )
            for item in draft.claims
        )
        return AgentPayload(
            task_id=request.assignment.task_id,
            source_task_revision=request.assignment.source_task_revision,
            assignment_id=request.assignment.assignment_id,
            attempt_id=request.attempt.attempt_id,
            context_manifest_sha256=request.assignment.context_manifest_sha256,
            summary=draft.summary,
            claims=claims,
            cited_source_refs=tuple(sorted({ref for item in claims for ref in item.source_refs})),
            cited_evidence_refs=tuple(
                sorted({ref for item in claims for ref in item.evidence_refs})
            ),
            cited_observation_refs=tuple(
                sorted({ref for item in claims for ref in item.observation_refs})
            ),
            assumptions=draft.assumptions,
            uncertainty=draft.uncertainty,
            conflicts=draft.conflicts,
            recommended_next_action=draft.recommended_next_action,
        )


    def _observe_process(
        self,
        *,
        process: subprocess.Popen[bytes],
        tree: OwnedProcessTree,
        request: LiveBackendRequest,
        result_path: Path,
        cancel_path: Path,
        stderr_path: Path,
        policy: S4RuntimePolicy,
        cancellation_probe: Callable[[], bool],
        started_monotonic: float,
    ) -> _ObservedProcessOutcome:
        budget = request.assignment.budget
        absolute_deadline = min(
            started_monotonic + (budget.max_runtime_ms / 1000),
            started_monotonic
            + max(0.0, (budget.deadline_at - request.requested_at).total_seconds()),
        )
        driver_result_limit = budget.max_result_bytes + 65_536
        forced_reason: str | None = None
        cancellation = False
        timeout = False
        cancel_requested_at = None
        hard_termination_used = False

        while tree.is_alive():
            now_monotonic = monotonic()
            stderr_size = stderr_path.stat().st_size if stderr_path.exists() else 0
            result_size = result_path.stat().st_size if result_path.exists() else 0
            if stderr_size > policy.max_stderr_bytes:
                forced_reason = "worker stderr exceeded its bounded diagnostic ceiling"
            elif result_size > driver_result_limit:
                forced_reason = "worker result exceeded its bounded driver ceiling"
            elif cancellation_probe():
                cancellation = True
                forced_reason = "root cancellation or S4 kill switch requested"
            elif now_monotonic >= absolute_deadline:
                timeout = True
                forced_reason = "worker runtime deadline elapsed"

            if forced_reason is not None:
                cancel_requested_at = utc_now()
                with suppress(OSError):
                    cancel_path.write_text("cancel\n", encoding="utf-8")
                if not tree.wait_quiescent(
                    timeout_seconds=policy.cooperative_cancel_grace_ms / 1000,
                ):
                    hard_termination_used = terminate_owned_process_tree(
                        tree,
                        graceful_timeout_seconds=policy.terminate_grace_ms / 1000,
                        quiescence_timeout_seconds=policy.hard_kill_grace_ms / 1000,
                    )
                break
            sleep(policy.poll_interval_ms / 1000)

        # A direct root exit is not authoritative completion. Reap the root
        # only after the owned execution tree has reached quiescence.
        process.wait()
        outcome_at = utc_now()
        runtime_ms = max(0, int((monotonic() - started_monotonic) * 1000))
        runtime_ms = min(runtime_ms, budget.max_runtime_ms)
        raw = b""
        if result_path.exists():
            try:
                with result_path.open("rb") as stream:
                    raw = stream.read(driver_result_limit + 1)
            except OSError:
                forced_reason = forced_reason or "worker result could not be read"
        raw_digest = sha256(raw).hexdigest() if raw else None

        if forced_reason is not None:
            state = (
                AgentLifecycleState.TIMED_OUT
                if timeout
                else AgentLifecycleState.TERMINATED
                if hard_termination_used
                else AgentLifecycleState.CANCELLED
                if cancellation
                else AgentLifecycleState.FAILED
            )
            return _ObservedProcessOutcome(
                state=state,
                outcome_at=outcome_at,
                cancel_requested_at=cancel_requested_at,
                hard_termination_used=hard_termination_used,
                reason=forced_reason,
                draft=None,
                raw_output_sha256=raw_digest,
                raw_output_size_bytes=len(raw),
                runtime_ms=runtime_ms,
            )

        if process.returncode != 0:
            return _ObservedProcessOutcome(
                state=AgentLifecycleState.FAILED,
                outcome_at=outcome_at,
                cancel_requested_at=None,
                hard_termination_used=False,
                reason=f"worker driver exited with code {process.returncode}",
                draft=None,
                raw_output_sha256=raw_digest,
                raw_output_size_bytes=len(raw),
                runtime_ms=runtime_ms,
            )
        if not raw:
            return _ObservedProcessOutcome(
                state=AgentLifecycleState.FAILED,
                outcome_at=outcome_at,
                cancel_requested_at=None,
                hard_termination_used=False,
                reason="worker driver produced no result",
                draft=None,
                raw_output_sha256=None,
                raw_output_size_bytes=0,
                runtime_ms=runtime_ms,
            )
        if len(raw) > driver_result_limit:
            return _ObservedProcessOutcome(
                state=AgentLifecycleState.FAILED,
                outcome_at=outcome_at,
                cancel_requested_at=None,
                hard_termination_used=False,
                reason="worker result exceeded its bounded driver ceiling",
                draft=None,
                raw_output_sha256=raw_digest,
                raw_output_size_bytes=len(raw),
                runtime_ms=runtime_ms,
            )
        try:
            draft = LiveWorkerDraft.model_validate_json(raw)
        except (ValidationError, ValueError):
            return _ObservedProcessOutcome(
                state=AgentLifecycleState.FAILED,
                outcome_at=outcome_at,
                cancel_requested_at=None,
                hard_termination_used=False,
                reason="worker result failed the closed S4 output schema",
                draft=None,
                raw_output_sha256=raw_digest,
                raw_output_size_bytes=len(raw),
                runtime_ms=runtime_ms,
            )
        return _ObservedProcessOutcome(
            state=AgentLifecycleState.RESULT_RECEIVED,
            outcome_at=outcome_at,
            cancel_requested_at=None,
            hard_termination_used=False,
            reason=None,
            draft=draft,
            raw_output_sha256=raw_digest,
            raw_output_size_bytes=len(raw),
            runtime_ms=runtime_ms,
        )

    def execute(
        self,
        *,
        request: LiveBackendRequest,
        context: FocusedContextBundle,
        policy: S4RuntimePolicy,
        cancellation_probe: Callable[[], bool],
    ) -> LiveBackendResult:
        current_request = LiveBackendRequest.model_validate(request.model_dump(mode="json"))
        current_context = FocusedContextBundle.model_validate(context.model_dump(mode="json"))
        if current_request.attempt.backend_id != self.backend_id:
            raise ValueError("S4 request selected another backend")
        if current_request.attempt.profile_id != self.profile_id:
            raise ValueError("S4 request selected another profile")
        if (
            current_request.focused_context_id != current_context.focused_context_id
            or current_request.focused_context_sha256 != contract_sha256(current_context)
            or current_context.assignment_id != current_request.assignment.assignment_id
        ):
            raise ValueError("S4 request does not bind the focused context")
        if not policy.active:
            raise ValueError("S4 subprocess execution requires an active policy")

        scratch = TemporaryDirectory(prefix="luna-c011-s4-")
        root = Path(scratch.name)
        request_path = root / "request.json"
        result_path = root / "result.json"
        cancel_path = root / "cancel.requested"
        stderr_path = root / "stderr.log"
        process: subprocess.Popen[bytes] | None = None
        tree: OwnedProcessTree | None = None
        observation: _ObservedProcessOutcome | None = None
        cleanup_state = CleanupState.CLEANUP_COMPLETE
        started_monotonic = monotonic()
        try:
            request_path.write_text(
                json.dumps(
                    self._driver_payload(current_request, current_context),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                encoding="utf-8",
            )
            replacements = {
                "{request}": str(request_path),
                "{result}": str(result_path),
                "{cancel}": str(cancel_path),
            }
            command = tuple(replacements.get(part, part) for part in self._command_template)
            with stderr_path.open("wb") as stderr_stream:
                process, tree = start_owned_process(
                    argv=command,
                    cwd=root,
                    environment=self._environment,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr_stream,
                )
                observation = self._observe_process(
                    process=process,
                    tree=tree,
                    request=current_request,
                    result_path=result_path,
                    cancel_path=cancel_path,
                    stderr_path=stderr_path,
                    policy=policy,
                    cancellation_probe=cancellation_probe,
                    started_monotonic=started_monotonic,
                )
        except Exception as exc:
            hard_termination_used = False
            if tree is not None and tree.is_alive():
                hard_termination_used = terminate_owned_process_tree(
                    tree,
                    graceful_timeout_seconds=policy.terminate_grace_ms / 1000,
                    quiescence_timeout_seconds=policy.hard_kill_grace_ms / 1000,
                )
            if process is not None:
                process.wait()
            observation = _ObservedProcessOutcome(
                state=AgentLifecycleState.FAILED,
                outcome_at=utc_now(),
                cancel_requested_at=None,
                hard_termination_used=hard_termination_used,
                reason=f"worker driver boundary failed: {type(exc).__name__}",
                draft=None,
                raw_output_sha256=None,
                raw_output_size_bytes=0,
                runtime_ms=min(
                    max(0, int((monotonic() - started_monotonic) * 1000)),
                    current_request.assignment.budget.max_runtime_ms,
                ),
            )
        finally:
            try:
                if tree is not None:
                    try:
                        if tree.is_alive():
                            terminate_owned_process_tree(
                                tree,
                                graceful_timeout_seconds=policy.terminate_grace_ms / 1000,
                                quiescence_timeout_seconds=policy.hard_kill_grace_ms / 1000,
                            )
                        if process is not None:
                            process.wait()
                    finally:
                        # Windows KILL_ON_JOB_CLOSE remains the final fail-safe.
                        tree.close()
            finally:
                try:
                    scratch.cleanup()
                except OSError:
                    cleanup_state = CleanupState.CLEANUP_FAILED

        assert observation is not None
        reason = observation.reason
        payload: AgentPayload
        tokens = 0
        native_usage: LiveNativeTokenUsage | None = None
        if observation.draft is not None:
            try:
                payload = self._payload_from_draft(current_request, observation.draft)
                native_usage = observation.draft.native_usage
                tokens = (
                    native_usage.output_tokens
                    if native_usage is not None
                    else observation.draft.tokens
                )
                if len(payload.claims) > current_request.assignment.budget.max_claims:
                    raise ValueError("worker claim count exceeded assignment budget")
                if tokens > current_request.assignment.budget.max_tokens:
                    raise ValueError("worker token report exceeded assignment budget")
                payload_bytes = len(canonical_contract_json(payload).encode("utf-8"))
                if payload_bytes > current_request.assignment.budget.max_result_bytes:
                    raise ValueError("worker payload exceeded assignment result budget")
            except (ValidationError, ValueError) as exc:
                reason = str(exc)
                payload = self._failure_payload(current_request, reason)
                observation = _ObservedProcessOutcome(
                    state=AgentLifecycleState.FAILED,
                    outcome_at=observation.outcome_at,
                    cancel_requested_at=observation.cancel_requested_at,
                    hard_termination_used=observation.hard_termination_used,
                    reason=reason,
                    draft=None,
                    raw_output_sha256=observation.raw_output_sha256,
                    raw_output_size_bytes=observation.raw_output_size_bytes,
                    runtime_ms=observation.runtime_ms,
                )
                tokens = 0
                native_usage = None
        else:
            payload = self._failure_payload(
                current_request,
                reason or "worker result unavailable",
            )
        cleanup_at = utc_now()
        usage = AgentResourceUsage(
            context_bytes=current_request.context.total_size_bytes,
            result_bytes=len(canonical_contract_json(payload).encode("utf-8")),
            claims_count=len(payload.claims),
            tokens=tokens,
            runtime_ms=observation.runtime_ms,
        )
        return LiveBackendResult(
            request=current_request,
            payload=payload,
            backend_id=self.backend_id,
            profile_id=self.profile_id,
            usage=usage,
            native_usage=native_usage,
            outcome_state=observation.state,
            cleanup_state=cleanup_state,
            outcome_at=observation.outcome_at,
            cleanup_at=cleanup_at,
            cancel_requested_at=observation.cancel_requested_at,
            raw_output_sha256=observation.raw_output_sha256,
            raw_output_size_bytes=observation.raw_output_size_bytes,
            hard_termination_used=observation.hard_termination_used,
            reason=reason,
        )


__all__ = ["InterruptibleWorkerBackend", "SubprocessWorkerBackend"]
