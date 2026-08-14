"""Phase 12E single policy-agent runtime loop.

This module wires task preparation, layered context, model policy, action resolution,
deterministic tool execution, observation, recovery, checkpointing, side-effect replay
protection, and the optional Phase 12F verification/reporting handoff into one
authoritative loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock
from time import monotonic
from uuid import UUID, uuid4

from luna.actions import ActionProposal, ActionResolutionStatus
from luna.context import (
    ContextInterpretation,
    ContextLayer,
    ContextSourceKind,
    LayeredContextBundle,
    LayeredContextCandidate,
    LayeredContextPolicy,
    ReadinessDecision,
)
from luna.continuity import ResumePolicy, ResumeStatus
from luna.contracts import (
    CompletionStatus,
    ObservationStatus,
    PlanStep,
    PlanStepStatus,
    TaskContract,
    TaskState,
)
from luna.contracts.base import SCHEMA_VERSION as CONTRACT_SCHEMA_VERSION
from luna.contracts.base import utc_now
from luna.contracts.enums import TaskPhase
from luna.contracts.evidence import Evidence
from luna.contracts.plan import ExpectedObservation
from luna.modeling import ProviderRetryCoordinator, ProviderRetryEvidence
from luna.planning import AttemptBasis, AttemptRecord, ExpectationEvaluator
from luna.recovery import ChangeEstimate, IsolationMode, RecoveryAction
from luna.runtime.budgets import RuntimeBudget
from luna.runtime.change_inspector import ChangeInspection, ChangeInspectionError
from luna.runtime.dependencies import RuntimeLoopDependencies
from luna.runtime.fingerprints import build_task_fingerprint
from luna.runtime.isolation import IsolationLease, WorkspaceIsolationError
from luna.runtime.journal import (
    RuntimeControlCommand,
    RuntimeControlRecord,
    SideEffectReceipt,
    SideEffectStage,
)
from luna.runtime.models import (
    RuntimeMode,
    RuntimeOutcome,
    RuntimeRequest,
    RuntimeStopReason,
    RuntimeUsage,
)
from luna.runtime.policy_agent import (
    ModelPolicyAgent,
    ModelRequestWindowBlocked,
    PolicyTurnStatus,
)
from luna.tools import (
    ToolCapability,
    ToolDisclosureDecision,
    ToolDisclosureProjector,
    ToolDisclosureState,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    ToolVisibilityProjection,
)
from luna.verification import VerificationPolicy, VerificationStrategySelector

_SIDE_EFFECT_CAPABILITIES = {
    ToolCapability.WRITE,
    ToolCapability.PROCESS,
    ToolCapability.NETWORK,
}

_RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

_ITERATION_EXHAUSTION_REASONS = {
    "steps",
    "model_calls",
    "tool_calls",
    "replans",
    "elapsed_seconds",
    "model_input_tokens",
    "model_output_tokens",
}


@dataclass(slots=True)
class _UsageCounter:
    budget: RuntimeBudget
    started: float
    steps: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    replans: int = 0
    model_input_tokens: int = 0
    model_output_tokens: int = 0
    changed_files: int = 0
    added_lines: int = 0
    deleted_lines: int = 0
    questions: int = 0
    network_requests: int = 0
    provider_retry_evidence: list[ProviderRetryEvidence] = field(default_factory=list)

    def snapshot(self) -> RuntimeUsage:
        return RuntimeUsage(
            budget=self.budget,
            steps=self.steps,
            model_calls=self.model_calls,
            tool_calls=self.tool_calls,
            replans=self.replans,
            elapsed_ms=max(0, int((monotonic() - self.started) * 1000)),
            model_input_tokens=self.model_input_tokens,
            model_output_tokens=self.model_output_tokens,
            changed_files=self.changed_files,
            added_lines=self.added_lines,
            deleted_lines=self.deleted_lines,
            questions=self.questions,
            network_requests=self.network_requests,
            provider_retry_evidence=tuple(self.provider_retry_evidence),
        )


class LunaRuntime:
    """One Luna identity, one TaskState, one action-observation loop."""

    def __init__(self, dependencies: RuntimeLoopDependencies) -> None:
        self._deps = dependencies
        self._policy_agent = ModelPolicyAgent(
            backend=dependencies.core.model_backend,
            selector=dependencies.action_resolver.selector,
        )
        self._provider_retry = ProviderRetryCoordinator()
        self._tool_selector = dependencies.action_resolver.selector
        self._tool_disclosure_projector = ToolDisclosureProjector()
        self._tool_disclosure_states: dict[UUID, ToolDisclosureState] = {}
        self._tool_disclosure_lock = RLock()
        self._expectations = ExpectationEvaluator()
        self._verification_strategy = VerificationStrategySelector()

    def suspend(
        self,
        *,
        task_id: UUID,
        reason: str = "owner requested suspension",
    ) -> RuntimeControlRecord:
        """Durably request suspension; the running loop acknowledges it only at a safe point."""
        return self._deps.runtime_journal.request_control(
            task_id=task_id,
            command=RuntimeControlCommand.SUSPEND,
            reason=reason,
        )

    def cancel(
        self,
        *,
        task_id: UUID,
        reason: str = "owner requested cancellation",
    ) -> RuntimeControlRecord:
        """Durably request cancellation; no in-flight handler is force-killed."""
        return self._deps.runtime_journal.request_control(
            task_id=task_id,
            command=RuntimeControlCommand.CANCEL,
            reason=reason,
        )

    def configure_tool_disclosure(
        self,
        *,
        task_id: UUID,
        deferred_tools: tuple[str, ...],
    ) -> ToolDisclosureState:
        """Configure task-scoped deferred schemas without changing tool authority."""
        registered = tuple(spec.name for spec in self._tool_selector.specs())
        state = self._tool_disclosure_projector.configure(
            task_id=task_id,
            deferred_tools=deferred_tools,
            registered_tools=registered,
        )
        with self._tool_disclosure_lock:
            self._tool_disclosure_states[task_id] = state.model_copy(deep=True)
        return state

    def request_tool_disclosure(
        self,
        *,
        task_id: UUID,
        tool_names: tuple[str, ...],
    ) -> ToolDisclosureDecision:
        """Stage deferred schemas for the next model-request boundary."""
        with self._tool_disclosure_lock:
            state = self._tool_disclosure_states.get(task_id)
            if state is None:
                raise ValueError("tool disclosure is not configured for this task")
            registered = tuple(spec.name for spec in self._tool_selector.specs())
            decision = self._tool_disclosure_projector.request(
                state,
                tool_names=tool_names,
                registered_tools=registered,
            )
            self._tool_disclosure_states[task_id] = decision.state.model_copy(deep=True)
            return decision

    def reset_tool_disclosure(self, *, task_id: UUID) -> ToolDisclosureState:
        """Remove disclosed and pending schemas while preserving registration."""
        with self._tool_disclosure_lock:
            state = self._tool_disclosure_states.get(task_id)
            if state is None:
                raise ValueError("tool disclosure is not configured for this task")
            reset = self._tool_disclosure_projector.reset(state)
            self._tool_disclosure_states[task_id] = reset.model_copy(deep=True)
            return reset

    def tool_disclosure_state(self, *, task_id: UUID) -> ToolDisclosureState | None:
        """Return an isolated snapshot of current model-visibility state."""
        with self._tool_disclosure_lock:
            state = self._tool_disclosure_states.get(task_id)
            return state.model_copy(deep=True) if state is not None else None

    def _tool_visibility_projection(
        self,
        *,
        task_id: UUID,
        basis_fingerprint: str,
        policy: ToolPolicy,
    ) -> ToolVisibilityProjection | None:
        with self._tool_disclosure_lock:
            state = self._tool_disclosure_states.get(task_id)
            if state is None:
                return None
            registered = tuple(spec.name for spec in self._tool_selector.specs())
            updated, projection = self._tool_disclosure_projector.project(
                state,
                basis_fingerprint=basis_fingerprint,
                registered_tools=registered,
                policy_allowed_tools=policy.allowed_tools,
            )
            self._tool_disclosure_states[task_id] = updated
            return projection

    def _pending_cancellation_reason(self, task_id: UUID) -> str | None:
        control = self._deps.runtime_journal.pending_control(task_id)
        if control is None or control.command is not RuntimeControlCommand.CANCEL:
            return None
        return control.reason

    def record_evidence(
        self,
        *,
        evidence: Evidence,
        trace_id: UUID | None = None,
        observation_id: UUID | None = None,
    ) -> Evidence:
        """Persist externally produced deterministic evidence for the Phase 12F gate."""
        if self._deps.phase12f is None:
            raise RuntimeError("Phase 12F evidence services are not configured")
        return self._deps.phase12f.evidence_registry.record(
            evidence=evidence,
            trace_id=trace_id,
            observation_id=observation_id,
        )

    def run(self, *, request: RuntimeRequest, tool_policy: ToolPolicy) -> RuntimeOutcome:
        """Start a new single-policy-agent task invocation."""
        if request.mode is RuntimeMode.RESUME:
            raise ValueError("run() cannot accept RESUME mode")
        self._validate_policy_boundary(request=request, policy=tool_policy)
        started_at = utc_now()
        usage = _UsageCounter(request.runtime_budget, monotonic())

        preparation = self._deps.core.task_preparer.prepare(
            request=request.raw_request,
            scope=request.scope,
            context_candidates=request.context_candidates,
            context_budget=request.context_budget,
            required_conditions=request.required_conditions,
            forbidden_outcomes=request.forbidden_outcomes,
            evidence_required=request.evidence_required,
            risk_level=request.risk_level,
            owner=request.actor.actor_id,
            task_id=request.task_id,
        )
        if preparation.contract is None:
            raise ValueError(
                "Phase 12E runtime requires a finalized TaskContract before TaskState creation: "
                + "; ".join(preparation.reasons)
            )

        state = TaskState(
            task_id=request.task_id,
            contract=preparation.contract,
            decision_state=self._deps.decision_state_service.ensure(request.task_id, None),
        )
        state = state.transition_to(TaskPhase.CONTRACTED)

        context = self._compose_context(request=request, state=state)
        readiness, state = self._deps.context_integrity_gate.evaluate(
            state=state,
            bundle=context,
            claims=request.context_claims,
            requirements=request.context_requirements,
        )
        if readiness.decision is not ReadinessDecision.READY:
            stop_reason = (
                RuntimeStopReason.CONFLICTING_EVIDENCE
                if (
                    readiness.conflicting_critical_keys
                    or readiness.contradicted_assumption_ids
                )
                else RuntimeStopReason.CONTEXT_INCOMPLETE
            )
            return self._checkpoint_outcome(
                request=request,
                state=state,
                usage=usage,
                stop_reason=stop_reason,
                reasons=(
                    *readiness.reasons,
                    *(f"missing_context:{item}" for item in readiness.raw_missing_sources),
                    *(
                        f"unresolved_context:{item}"
                        for item in readiness.unresolved_critical_keys
                    ),
                    *(
                        f"conflicting_context:{item}"
                        for item in readiness.conflicting_critical_keys
                    ),
                    *(
                        f"blocking_assumption:{item}"
                        for item in readiness.blocking_assumption_ids
                    ),
                    *(
                        f"invalidated_decision:{item}"
                        for item in readiness.invalidated_decision_ids
                    ),
                ),
                resume_phase=TaskPhase.CONTEXT_READY,
                next_step="reconcile required context",
                started_at=started_at,
            )

        state = state.transition_to(TaskPhase.CONTEXT_READY)
        task_plan = self._deps.core.planner.plan(preparation)
        state = state.revise(plan=task_plan.steps)
        state = state.transition_to(TaskPhase.PLANNED)
        return self._drive(
            request=request,
            tool_policy=tool_policy,
            state=state,
            usage=usage,
            started_at=started_at,
        )

    def resume(self, *, request: RuntimeRequest, tool_policy: ToolPolicy) -> RuntimeOutcome:
        """Resume only from durable evidence; never replay an ambiguous side effect."""
        if request.mode is not RuntimeMode.RESUME:
            raise ValueError("resume() requires RuntimeMode.RESUME")
        self._validate_policy_boundary(request=request, policy=tool_policy)
        started_at = utc_now()
        usage = _UsageCounter(request.runtime_budget, monotonic())

        recoverable = self._deps.runtime_journal.latest_recoverable(request.task_id)
        if recoverable is not None:
            reconciled = self._reconcile_receipt(
                request=request,
                policy=tool_policy,
                receipt=recoverable,
                usage=usage,
                started_at=started_at,
            )
            if isinstance(reconciled, RuntimeOutcome):
                return reconciled

        latest_control = self._deps.runtime_journal.latest_control(request.task_id)
        if latest_control is not None and latest_control.command is RuntimeControlCommand.CANCEL:
            if latest_control.acknowledged_at is None:
                cleanup_error = self._cleanup_task_isolation(request.task_id)
                if cleanup_error is not None:
                    state = self._latest_persisted_state(request.task_id)
                    return self._outcome(
                        request=request,
                        state=state,
                        usage=usage.snapshot(),
                        stop_reason=RuntimeStopReason.INTEGRITY_FAILURE,
                        reasons=(cleanup_error,),
                        started_at=started_at,
                    )
                self._deps.runtime_journal.acknowledge_control(latest_control.control_id)
            state = self._latest_persisted_state(request.task_id)
            return self._outcome(
                request=request,
                state=state,
                usage=usage.snapshot(),
                stop_reason=RuntimeStopReason.CANCELLED,
                reasons=(latest_control.reason,),
                started_at=started_at,
            )

        stored = self._deps.core.continuity_service.store.load_latest(request.task_id)
        policy = self._current_resume_policy(
            task_contract=stored.envelope.state.contract,
            workspace_root=self._effective_workspace_root(
                request.task_id,
                fallback_root=stored.envelope.state.contract.scope.workspace_root,
            ),
        )
        decision = self._deps.core.continuity_service.resume_latest(
            task_id=request.task_id,
            policy=policy,
            trace_id=request.trace_id,
        )
        if decision.status is not ResumeStatus.READY or decision.resumed_state is None:
            return self._outcome(
                request=request,
                state=stored.envelope.state,
                usage=usage.snapshot(),
                stop_reason=RuntimeStopReason.INTERRUPTED,
                reasons=decision.reasons,
                started_at=started_at,
            )

        state = decision.resumed_state
        context = self._compose_context(request=request, state=state)
        readiness, state = self._deps.context_integrity_gate.evaluate(
            state=state,
            bundle=context,
            claims=request.context_claims,
            requirements=request.context_requirements,
        )
        if readiness.decision is not ReadinessDecision.READY:
            stop_reason = (
                RuntimeStopReason.CONFLICTING_EVIDENCE
                if (
                    readiness.conflicting_critical_keys
                    or readiness.contradicted_assumption_ids
                )
                else RuntimeStopReason.CONTEXT_INCOMPLETE
            )
            return self._checkpoint_outcome(
                request=request,
                state=state,
                usage=usage,
                stop_reason=stop_reason,
                reasons=(
                    *readiness.reasons,
                    *(f"missing_context:{item}" for item in readiness.raw_missing_sources),
                    *(
                        f"unresolved_context:{item}"
                        for item in readiness.unresolved_critical_keys
                    ),
                    *(
                        f"conflicting_context:{item}"
                        for item in readiness.conflicting_critical_keys
                    ),
                    *(
                        f"blocking_assumption:{item}"
                        for item in readiness.blocking_assumption_ids
                    ),
                    *(
                        f"invalidated_decision:{item}"
                        for item in readiness.invalidated_decision_ids
                    ),
                ),
                resume_phase=state.phase,
                next_step="reconcile required context before resume",
                started_at=started_at,
            )

        if state.phase is TaskPhase.VERIFYING:
            return self._phase12f_or_pending(
                request=request,
                state=state,
                usage=usage,
                started_at=started_at,
            )
        if state.phase is TaskPhase.CONTEXT_READY and not state.plan:
            return self._outcome(
                request=request,
                state=state,
                usage=usage.snapshot(),
                stop_reason=RuntimeStopReason.BLOCKED,
                reasons=("checkpoint resumed before a durable plan existed",),
                started_at=started_at,
            )
        if state.phase is not TaskPhase.PLANNED:
            return self._outcome(
                request=request,
                state=state,
                usage=usage.snapshot(),
                stop_reason=RuntimeStopReason.INTERRUPTED,
                reasons=(f"unsupported safe resume phase: {state.phase.value}",),
                started_at=started_at,
            )
        return self._drive(
            request=request,
            tool_policy=tool_policy,
            state=state,
            usage=usage,
            started_at=started_at,
        )

    def _drive(
        self,
        *,
        request: RuntimeRequest,
        tool_policy: ToolPolicy,
        state: TaskState,
        usage: _UsageCounter,
        started_at: datetime,
    ) -> RuntimeOutcome:
        while True:
            control = self._deps.runtime_journal.pending_control(request.task_id)
            if control is not None:
                if control.command is RuntimeControlCommand.CANCEL:
                    cleanup_error = self._cleanup_task_isolation(request.task_id)
                    if cleanup_error is not None:
                        return self._integrity_stop(
                            request=request,
                            state=state,
                            usage=usage,
                            reason=cleanup_error,
                            started_at=started_at,
                        )
                self._deps.runtime_journal.acknowledge_control(control.control_id)
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=(
                        RuntimeStopReason.CANCELLED
                        if control.command is RuntimeControlCommand.CANCEL
                        else RuntimeStopReason.SUSPENDED
                    ),
                    reasons=(control.reason,),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="resume policy-agent loop",
                    started_at=started_at,
                )

            budget_stop = self._budget_stop(
                request=request,
                state=state,
                usage=usage,
                started_at=started_at,
            )
            if budget_stop is not None:
                return budget_stop

            step = self._next_pending_step(state)
            if step is None:
                failed = tuple(
                    item
                    for item in state.plan
                    if item.status in {PlanStepStatus.FAILED, PlanStepStatus.BLOCKED}
                )
                if failed:
                    return self._checkpoint_outcome(
                        request=request,
                        state=state,
                        usage=usage,
                        stop_reason=RuntimeStopReason.BLOCKED,
                        reasons=(
                            "plan contains failed or blocked steps; explicit replan is required",
                        ),
                        resume_phase=TaskPhase.PLANNED,
                        next_step="explicitly replan from failed-step evidence",
                        started_at=started_at,
                    )
                if state.phase is TaskPhase.PLANNED:
                    state = state.transition_to(TaskPhase.ACTING)
                    state = state.transition_to(TaskPhase.OBSERVING)
                if state.phase is TaskPhase.OBSERVING:
                    state = state.transition_to(TaskPhase.VERIFYING)
                return self._phase12f_or_pending(
                    request=request,
                    state=state,
                    usage=usage,
                    started_at=started_at,
                )

            state = self._activate_step(state, step.step_id)
            active_step = self._active_step(state)
            if state.phase is TaskPhase.PLANNED or state.phase is TaskPhase.OBSERVING:
                state = state.transition_to(TaskPhase.ACTING)

            context = self._compose_context(request=request, state=state)
            if not context.ready:
                state = self._deactivate_step(state, reason=None)
                state = state.transition_to(TaskPhase.OBSERVING)
                return self._checkpoint_outcome(
                    request=request,
                    state=state,
                    usage=usage,
                    stop_reason=RuntimeStopReason.CONTEXT_INCOMPLETE,
                    reasons=tuple(f"missing_context:{item}" for item in context.missing_sources),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="refresh required context",
                    started_at=started_at,
                )

            if request.runtime_budget.max_model_calls == 0:
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=RuntimeStopReason.BLOCKED,
                    reasons=("runtime budget disables model calls",),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner budget decision required",
                    started_at=started_at,
                )
            if usage.model_calls >= request.runtime_budget.max_model_calls:
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=RuntimeStopReason.BUDGET_EXHAUSTED,
                    reasons=("runtime budget exhausted: model_calls",),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner budget decision required",
                    started_at=started_at,
                )
            if request.runtime_budget.max_model_input_tokens == 0:
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=RuntimeStopReason.BLOCKED,
                    reasons=("runtime budget disables model input tokens",),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner budget decision required",
                    started_at=started_at,
                )
            if request.runtime_budget.max_model_request_estimated_tokens == 0:
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=RuntimeStopReason.BLOCKED,
                    reasons=("runtime budget disables estimated model request tokens",),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner budget decision required",
                    started_at=started_at,
                )
            if request.runtime_budget.max_model_output_tokens == 0:
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=RuntimeStopReason.BLOCKED,
                    reasons=("runtime budget disables model output tokens",),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner budget decision required",
                    started_at=started_at,
                )
            if (
                usage.model_output_tokens
                >= request.runtime_budget.max_model_output_tokens
            ):
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=RuntimeStopReason.BUDGET_EXHAUSTED,
                    reasons=("runtime budget exhausted: model_output_tokens",),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner budget decision required",
                    started_at=started_at,
                )
            remaining_output = max(
                1,
                request.runtime_budget.max_model_output_tokens - usage.model_output_tokens,
            )
            provider_history: tuple[AttemptRecord, ...] = ()
            provider_basis: AttemptBasis | None = None
            provider_retry_terminal_reason: str | None = None
            cancelled_during_backoff = False
            provider_attempt = 0
            scope_payload = json.dumps(
                state.contract.scope.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            provider_scope_fingerprint = sha256(scope_payload.encode("utf-8")).hexdigest()
            while True:
                provider_attempt += 1
                tool_visibility = self._tool_visibility_projection(
                    task_id=request.task_id,
                    basis_fingerprint=context.fingerprint(),
                    policy=tool_policy,
                )
                try:
                    turn = self._policy_agent.decide(
                        task_id=request.task_id,
                        trace_id=request.trace_id,
                        raw_request=request.raw_request,
                        state=state,
                        step=active_step,
                        context=context,
                        policy=tool_policy,
                        max_output_tokens=min(32768, remaining_output),
                        tool_visibility=tool_visibility,
                        max_input_estimated_tokens=(
                            request.runtime_budget.max_model_request_estimated_tokens
                        ),
                    )
                except ModelRequestWindowBlocked as exc:
                    projection = exc.projection
                    reason = (
                        projection.block_reason.value
                        if projection.block_reason is not None
                        else "UNKNOWN"
                    )
                    return self._checkpoint_outcome(
                        request=request,
                        state=self._safe_checkpoint_state(state),
                        usage=usage,
                        stop_reason=RuntimeStopReason.BLOCKED,
                        reasons=(
                            "model request cannot fit within per-request estimated window: "
                            f"{reason}; limit={projection.max_estimated_tokens}",
                        ),
                        resume_phase=TaskPhase.PLANNED,
                        next_step="increase model request window or reduce model-visible input",
                        started_at=started_at,
                    )
                usage.model_calls += 1
                usage.steps += 1
                usage.model_input_tokens += turn.usage.input_tokens
                usage.model_output_tokens += turn.usage.output_tokens

                if turn.status is not PolicyTurnStatus.BACKEND_FAILURE:
                    break
                assert turn.backend_error_code is not None
                assert turn.backend_error_backend_id is not None
                if not self._provider_retry.is_retryable(
                    code=turn.backend_error_code,
                    classified_retryable=turn.backend_retryable,
                ):
                    provider_retry_terminal_reason = (
                        "provider retry denied by semantic failure classification"
                    )
                    break
                if provider_attempt >= self._provider_retry.policy.max_attempts:
                    provider_retry_terminal_reason = (
                        "provider retry attempts exhausted: "
                        f"{provider_attempt}/{self._provider_retry.policy.max_attempts}"
                    )
                    break
                budget_stop = self._budget_stop(
                    request=request,
                    state=state,
                    usage=usage,
                    started_at=started_at,
                )
                if budget_stop is not None:
                    return budget_stop
                if provider_basis is None:
                    provider_basis = self._provider_retry.initial_basis(
                        backend_id=turn.backend_error_backend_id,
                        request_fingerprint=turn.model_request_fingerprint,
                        scope_fingerprint=provider_scope_fingerprint,
                        assumption_revision=(
                            state.decision_state.revision
                            if state.decision_state is not None
                            else 0
                        ),
                    )
                retry_plan = self._provider_retry.plan(
                    task_id=request.task_id,
                    step_id=active_step.step_id,
                    attempt_number=provider_attempt,
                    code=turn.backend_error_code,
                    backend_id=turn.backend_error_backend_id,
                    request_fingerprint=turn.model_request_fingerprint,
                    retry_after_seconds=turn.backend_retry_after_seconds,
                    failure_ref=uuid4(),
                    current_basis=provider_basis,
                    history=provider_history,
                )
                provider_history = (*provider_history, retry_plan.failed_attempt)
                if retry_plan.evidence is None:
                    provider_retry_terminal_reason = (
                        "provider retry blocked by unchanged basis: "
                        f"{retry_plan.decision.reason.value}"
                    )
                    break
                remaining_elapsed_seconds = max(
                    0.0,
                    request.runtime_budget.max_elapsed_seconds
                    - (monotonic() - usage.started),
                )
                if retry_plan.evidence.delay_seconds >= remaining_elapsed_seconds:
                    provider_retry_terminal_reason = (
                        "provider retry delay exceeds remaining runtime elapsed budget"
                    )
                    break
                usage.provider_retry_evidence.append(retry_plan.evidence)
                cancellation = self._provider_retry.wait(
                    retry_plan.evidence.delay_seconds,
                    cancellation_probe=lambda: self._pending_cancellation_reason(
                        request.task_id
                    ),
                )
                if cancellation is not None:
                    cancelled_during_backoff = True
                    break
                budget_stop = self._budget_stop(
                    request=request,
                    state=state,
                    usage=usage,
                    started_at=started_at,
                )
                if budget_stop is not None:
                    return budget_stop
                provider_basis = retry_plan.candidate_basis

            if cancelled_during_backoff:
                continue

            token_overruns = tuple(
                reason
                for reason in usage.snapshot().exceeded_reasons()
                if reason in {"model_input_tokens", "model_output_tokens"}
            )
            if token_overruns:
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=RuntimeStopReason.BUDGET_EXHAUSTED,
                    reasons=(
                        "runtime budget exceeded by model response: "
                        + ", ".join(token_overruns),
                    ),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner budget decision required",
                    started_at=started_at,
                )

            if turn.status is PolicyTurnStatus.BACKEND_FAILURE:
                assert turn.backend_error_code is not None
                reason = turn.invalid_reason or "model backend failure"
                state = self._deactivate_step(state, reason=None)
                state = state.transition_to(TaskPhase.OBSERVING)
                semantic_retryable = self._provider_retry.is_retryable(
                    code=turn.backend_error_code,
                    classified_retryable=turn.backend_retryable,
                )
                stop_reason = (
                    RuntimeStopReason.RESOURCE_SUSPENDED
                    if semantic_retryable
                    else RuntimeStopReason.BLOCKED
                )
                next_step = (
                    "resume only after model backend health or availability changes"
                    if semantic_retryable
                    else "owner model rollout or adapter decision required"
                )
                return self._checkpoint_outcome(
                    request=request,
                    state=state,
                    usage=usage,
                    stop_reason=stop_reason,
                    reasons=(
                        f"model_backend:{turn.backend_error_code.value}",
                        reason,
                        provider_retry_terminal_reason
                        or "provider retry ended without changed-basis authority",
                    ),
                    resume_phase=TaskPhase.PLANNED,
                    next_step=next_step,
                    started_at=started_at,
                )

            if turn.status is PolicyTurnStatus.INCOMPLETE:
                state = self._deactivate_step(state, reason=None)
                state = state.transition_to(TaskPhase.OBSERVING)
                output_budget_exhausted = (
                    "model_output_tokens" in usage.snapshot().exhausted_reasons()
                )
                return self._checkpoint_outcome(
                    request=request,
                    state=state,
                    usage=usage,
                    stop_reason=(
                        RuntimeStopReason.BUDGET_EXHAUSTED
                        if output_budget_exhausted
                        else RuntimeStopReason.BLOCKED
                    ),
                    reasons=(
                        "model response ended with LENGTH and is incomplete",
                        "incomplete model output is never executed or treated as completion",
                        "incomplete model output is never blindly retried",
                    ),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner/model output-budget or strategy decision required",
                    started_at=started_at,
                )

            if turn.status is PolicyTurnStatus.YIELD:
                state = self._deactivate_step(state, reason=None)
                state = state.transition_to(TaskPhase.OBSERVING)
                return self._checkpoint_outcome(
                    request=request,
                    state=state,
                    usage=usage,
                    stop_reason=RuntimeStopReason.BLOCKED,
                    reasons=("policy model yielded without proposing an action",),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="resume after owner/model input changes",
                    started_at=started_at,
                )

            if turn.status is PolicyTurnStatus.INVALID or turn.proposal is None:
                reason = turn.invalid_reason or "invalid policy-agent turn"
                state = self._fail_active_step(state, reason=reason)
                state = state.transition_to(TaskPhase.OBSERVING)
                return self._checkpoint_outcome(
                    request=request,
                    state=state,
                    usage=usage,
                    stop_reason=RuntimeStopReason.BLOCKED,
                    reasons=(reason, "invalid action is never blindly retried"),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="replan from invalid action evidence",
                    started_at=started_at,
                )

            proposal, state = self._ensure_expectation(turn.proposal, state)
            resolution = self._deps.action_resolver.resolve(
                proposal=proposal,
                task_contract=state.contract,
                policy=tool_policy,
            )
            if resolution.status is ActionResolutionStatus.DENIED:
                assert resolution.denial is not None
                assert resolution.observation is not None
                state = self._observe(state, resolution.observation.observation_id)
                failure = self._deps.failure_classifier.from_action_denial(resolution.denial)
                recovery = self._deps.recovery_policy.decide(failure=failure)
                state = self._fail_active_step(state, reason=recovery.reason)
                if state.phase is TaskPhase.ACTING:
                    state = state.transition_to(TaskPhase.OBSERVING)
                stop = (
                    RuntimeStopReason.PERMISSION_DENIED
                    if recovery.action is RecoveryAction.REQUEST_APPROVAL
                    else RuntimeStopReason.BLOCKED
                )
                return self._checkpoint_outcome(
                    request=request,
                    state=state,
                    usage=usage,
                    stop_reason=stop,
                    reasons=(recovery.reason,),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner approval or revised action required",
                    started_at=started_at,
                )

            tool_request = self._deps.action_resolver.to_tool_request(resolution)
            return_or_state = self._execute_one(
                request=request,
                tool_policy=tool_policy,
                proposal=proposal,
                tool_request=tool_request,
                context_fingerprint=context.fingerprint(),
                state=state,
                usage=usage,
                started_at=started_at,
            )
            if isinstance(return_or_state, RuntimeOutcome):
                return return_or_state
            state = return_or_state

    def _execute_one(
        self,
        *,
        request: RuntimeRequest,
        tool_policy: ToolPolicy,
        proposal: ActionProposal,
        tool_request: ToolRequest,
        context_fingerprint: str,
        state: TaskState,
        usage: _UsageCounter,
        started_at: datetime,
    ) -> TaskState | RuntimeOutcome:
        if request.runtime_budget.max_tool_calls == 0:
            return self._checkpoint_outcome(
                request=request,
                state=self._safe_checkpoint_state(state),
                usage=usage,
                stop_reason=RuntimeStopReason.BLOCKED,
                reasons=("runtime budget disables tool calls",),
                resume_phase=TaskPhase.PLANNED,
                next_step="owner budget decision required",
                started_at=started_at,
            )
        if usage.tool_calls >= request.runtime_budget.max_tool_calls:
            return self._checkpoint_outcome(
                request=request,
                state=self._safe_checkpoint_state(state),
                usage=usage,
                stop_reason=RuntimeStopReason.BUDGET_EXHAUSTED,
                reasons=("runtime budget exhausted: tool_calls",),
                resume_phase=TaskPhase.PLANNED,
                next_step="owner budget decision required",
                started_at=started_at,
            )
        if ToolCapability.NETWORK in proposal.required_capabilities:
            if request.runtime_budget.max_network_requests == 0:
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=RuntimeStopReason.BLOCKED,
                    reasons=("runtime budget disables network requests",),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner budget decision required",
                    started_at=started_at,
                )
            if usage.network_requests >= request.runtime_budget.max_network_requests:
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=RuntimeStopReason.BUDGET_EXHAUSTED,
                    reasons=("runtime budget exhausted: network_requests",),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner budget decision required",
                    started_at=started_at,
                )

        effective_root = self._effective_workspace_root(
            request.task_id,
            fallback_root=state.contract.scope.workspace_root,
        )
        execution_contract = self._contract_for_workspace(state.contract, effective_root)
        approval_workspace_root = effective_root
        approval_contract = execution_contract
        approval_basis_fingerprint = self._approval_basis_fingerprint(
            state=state,
            task_contract=approval_contract,
            workspace_root=approval_workspace_root,
        )
        authorization = self._deps.core.tool_dispatcher.authorize(
            request=tool_request,
            task_contract=execution_contract,
            policy=tool_policy,
            approval_basis_fingerprint=approval_basis_fingerprint,
        )
        if not authorization.allowed:
            return self._checkpoint_outcome(
                request=request,
                state=self._safe_checkpoint_state(state),
                usage=usage,
                stop_reason=RuntimeStopReason.PERMISSION_DENIED,
                reasons=(
                    authorization.reason,
                    (
                        "execution authority is rechecked at dispatch against "
                        "the same exact-call basis"
                    ),
                ),
                resume_phase=TaskPhase.PLANNED,
                next_step="owner exact-call approval or revised action required",
                started_at=started_at,
            )
        inspection: ChangeInspection | None = None
        lease = IsolationLease(
            mode=IsolationMode.NONE,
            workspace_root=effective_root,
        )

        if ToolCapability.WRITE in proposal.required_capabilities:
            try:
                inspection = self._deps.change_inspector.inspect_declared(
                    proposal=proposal,
                    task_contract=execution_contract,
                )
            except ChangeInspectionError as exc:
                return self._integrity_stop(
                    request=request,
                    state=state,
                    usage=usage,
                    reason=str(exc),
                    started_at=started_at,
                )
            if inspection is not None:
                budget_violation = self._projected_change_budget_violation(
                    usage=usage,
                    estimate=inspection.estimate,
                    budget=request.runtime_budget,
                )
                if budget_violation is not None:
                    return self._checkpoint_outcome(
                        request=request,
                        state=self._safe_checkpoint_state(state),
                        usage=usage,
                        stop_reason=RuntimeStopReason.BLOCKED,
                        reasons=(budget_violation,),
                        resume_phase=TaskPhase.PLANNED,
                        next_step="owner change-budget decision required",
                        started_at=started_at,
                    )
                minimal = self._deps.minimal_change_policy.evaluate_declared(
                    estimate=inspection.estimate,
                    scope=execution_contract.scope,
                    budget=request.runtime_budget,
                )
                if not minimal.allowed:
                    return self._integrity_stop(
                        request=request,
                        state=state,
                        usage=usage,
                        reason=minimal.reason,
                        started_at=started_at,
                    )
                available = self._deps.isolation_manager.worktree_available(state.contract)
                isolation = self._deps.isolation_policy.plan(
                    task_contract=state.contract,
                    change=inspection.estimate,
                    worktree_available=available,
                )
                if not isolation.allowed:
                    failure = self._deps.failure_classifier.resource_unavailable(
                        task_id=request.task_id,
                        trace_id=request.trace_id,
                        reason=isolation.reason,
                    )
                    recovery = self._deps.recovery_policy.decide(failure=failure)
                    return self._checkpoint_outcome(
                        request=request,
                        state=self._safe_checkpoint_state(state),
                        usage=usage,
                        stop_reason=RuntimeStopReason.RESOURCE_SUSPENDED,
                        reasons=(recovery.reason,),
                        resume_phase=TaskPhase.PLANNED,
                        next_step="retry only when required isolation becomes available",
                        started_at=started_at,
                    )
                try:
                    lease = self._deps.isolation_manager.acquire(
                        task_contract=state.contract,
                        decision=isolation,
                        task_id=request.task_id,
                    )
                except WorkspaceIsolationError as exc:
                    return self._checkpoint_outcome(
                        request=request,
                        state=self._safe_checkpoint_state(state),
                        usage=usage,
                        stop_reason=RuntimeStopReason.RESOURCE_SUSPENDED,
                        reasons=(str(exc),),
                        resume_phase=TaskPhase.PLANNED,
                        next_step="retry only after isolation resource changes",
                        started_at=started_at,
                    )
                if Path(lease.workspace_root).resolve() != Path(
                    execution_contract.scope.workspace_root
                ).resolve():
                    try:
                        self._deps.isolation_manager.align_text_baseline(
                            source_workspace_root=execution_contract.scope.workspace_root,
                            isolated_workspace_root=lease.workspace_root,
                            relative_path=inspection.relative_path,
                        )
                    except WorkspaceIsolationError as exc:
                        return self._integrity_stop(
                            request=request,
                            state=state,
                            usage=usage,
                            reason=str(exc),
                            started_at=started_at,
                        )
                    execution_contract = self._contract_for_workspace(
                        state.contract,
                        lease.workspace_root,
                    )
                    inspection = self._deps.change_inspector.inspect_declared(
                        proposal=proposal,
                        task_contract=execution_contract,
                    )
                    if inspection is not None:
                        budget_violation = self._projected_change_budget_violation(
                            usage=usage,
                            estimate=inspection.estimate,
                            budget=request.runtime_budget,
                        )
                        if budget_violation is not None:
                            return self._checkpoint_outcome(
                                request=request,
                                state=self._safe_checkpoint_state(state),
                                usage=usage,
                                stop_reason=RuntimeStopReason.BLOCKED,
                                reasons=(budget_violation,),
                                resume_phase=TaskPhase.PLANNED,
                                next_step="owner change-budget decision required",
                                started_at=started_at,
                            )
                        isolated_minimal = self._deps.minimal_change_policy.evaluate_declared(
                            estimate=inspection.estimate,
                            scope=execution_contract.scope,
                            budget=request.runtime_budget,
                        )
                        if not isolated_minimal.allowed:
                            return self._integrity_stop(
                                request=request,
                                state=state,
                                usage=usage,
                                reason=isolated_minimal.reason,
                                started_at=started_at,
                            )

        # Recompute immediately before execution preparation so state changes that happened
        # after the early permission preflight invalidate stale exact-call approval.
        approval_basis_fingerprint = self._approval_basis_fingerprint(
            state=state,
            task_contract=approval_contract,
            workspace_root=approval_workspace_root,
        )
        authorization = self._deps.core.tool_dispatcher.authorize(
            request=tool_request,
            task_contract=execution_contract,
            policy=tool_policy,
            approval_basis_fingerprint=approval_basis_fingerprint,
        )
        if not authorization.allowed:
            return self._checkpoint_outcome(
                request=request,
                state=self._safe_checkpoint_state(state),
                usage=usage,
                stop_reason=RuntimeStopReason.PERMISSION_DENIED,
                reasons=(
                    authorization.reason,
                    "exact-call authority changed before execution preparation",
                ),
                resume_phase=TaskPhase.PLANNED,
                next_step="owner exact-call reapproval or revised action required",
                started_at=started_at,
            )

        side_effect = bool(set(proposal.required_capabilities) & _SIDE_EFFECT_CAPABILITIES)
        basis = self._attempt_basis(
            request=request,
            state=state,
            proposal=proposal,
            tool_request=tool_request,
            context_fingerprint=context_fingerprint,
        )
        receipt: SideEffectReceipt | None = None
        semantic = self._semantic_fingerprint(tool_request)
        idempotency_key = self._idempotency_key(
            task_id=request.task_id,
            step_id=self._active_step(state).step_id,
            semantic_fingerprint=semantic,
        )

        if side_effect:
            history = self._deps.runtime_journal.semantic_history(
                task_id=request.task_id,
                semantic_fingerprint=semantic,
            )
            active_step_id = self._active_step(state).step_id
            if any(
                item.step_id == active_step_id
                and item.stage is not SideEffectStage.ABORTED
                for item in history
            ):
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=RuntimeStopReason.INTERRUPTED,
                    reasons=(
                        "identical side effect already has a durable receipt; "
                        "blind replay blocked",
                    ),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="reconcile prior side effect before any retry",
                    started_at=started_at,
                )
            receipt = SideEffectReceipt(
                idempotency_key=idempotency_key,
                semantic_fingerprint=semantic,
                task_id=request.task_id,
                trace_id=request.trace_id,
                step_id=self._active_step(state).step_id,
                proposal_id=proposal.proposal_id,
                request=tool_request,
                attempt_basis=basis,
                approval_basis_fingerprint=approval_basis_fingerprint,
                approval_workspace_root=effective_root,
                pre_action_state=state,
                execution_workspace_root=lease.workspace_root,
                isolation_mode=lease.mode.value,
            )
            receipt = self._deps.runtime_journal.reserve(receipt)
            control = self._deps.runtime_journal.pending_control(request.task_id)
            if control is not None:
                if control.command is RuntimeControlCommand.CANCEL:
                    self._deps.runtime_journal.abort_prepared(
                        idempotency_key=receipt.idempotency_key,
                        reason=control.reason,
                    )
                    cleanup_error = self._cleanup_task_isolation(request.task_id)
                    if cleanup_error is not None:
                        return self._integrity_stop(
                            request=request,
                            state=state,
                            usage=usage,
                            reason=cleanup_error,
                            started_at=started_at,
                            receipt=receipt,
                        )
                self._deps.runtime_journal.acknowledge_control(control.control_id)
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(state),
                    usage=usage,
                    stop_reason=(
                        RuntimeStopReason.CANCELLED
                        if control.command is RuntimeControlCommand.CANCEL
                        else RuntimeStopReason.SUSPENDED
                    ),
                    reasons=(control.reason,),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="resume prepared action only after safe control release",
                    started_at=started_at,
                )
            self._deps.runtime_journal.mark_started(receipt.idempotency_key)

        outcome = self._deps.core.tool_dispatcher.dispatch(
            request=tool_request,
            task_contract=execution_contract,
            policy=tool_policy,
            cancellation_probe=lambda: self._pending_cancellation_reason(request.task_id),
            approval_basis_fingerprint=approval_basis_fingerprint,
        )
        usage.tool_calls += 1
        if ToolCapability.NETWORK in proposal.required_capabilities:
            usage.network_requests += 1
        if receipt is not None:
            self._deps.runtime_journal.mark_completed(
                idempotency_key=receipt.idempotency_key,
                outcome=outcome,
            )
        self._deps.runtime_journal.record_outcome(outcome)

        state = self._observe(state, outcome.observation.observation_id)
        if receipt is not None:
            self._deps.runtime_journal.mark_observed(
                idempotency_key=receipt.idempotency_key,
                post_action_state=state,
            )

        if inspection is not None and outcome.result.status is ToolResultStatus.SUCCESS:
            observed_change = self._deps.change_inspector.inspect_observed(inspection)
            observed_policy = self._deps.minimal_change_policy.evaluate_observed(
                approved=inspection.estimate,
                observed=observed_change,
                scope=execution_contract.scope,
                budget=request.runtime_budget,
            )
            usage.changed_files += observed_change.changed_files
            usage.added_lines += observed_change.added_lines
            usage.deleted_lines += observed_change.deleted_lines
            if not observed_policy.allowed:
                return self._integrity_stop(
                    request=request,
                    state=state,
                    usage=usage,
                    reason=observed_policy.reason,
                    started_at=started_at,
                    receipt=receipt,
                )
            if (
                lease.mode is IsolationMode.SNAPSHOT
                and not outcome.result.metadata.get("snapshot_id")
            ):
                return self._integrity_stop(
                    request=request,
                    state=state,
                    usage=usage,
                    reason="snapshot isolation succeeded without a durable snapshot_id",
                    started_at=started_at,
                    receipt=receipt,
                )

        active = self._active_step(state)
        expectation = active.expectation
        lifecycle_error = outcome.result.error_class
        if lifecycle_error in {
            "ToolExecutionCancelled",
            "ToolExecutionCancellationAmbiguous",
            "ToolExecutionDeadlineExceeded",
            "ToolExecutionDeadlineAmbiguous",
        }:
            ambiguous = lifecycle_error in {
                "ToolExecutionCancellationAmbiguous",
                "ToolExecutionDeadlineAmbiguous",
            }
            cancelled = lifecycle_error in {
                "ToolExecutionCancelled",
                "ToolExecutionCancellationAmbiguous",
            }
            reason = (
                "tool execution cancellation was observed after a side effect may have started; "
                "automatic replay is forbidden"
                if ambiguous and cancelled
                else "tool execution deadline expired after a side effect may have started; "
                "automatic replay is forbidden"
                if ambiguous
                else "tool execution was cooperatively cancelled"
                if cancelled
                else "tool execution deadline expired"
            )
            state = self._fail_active_step(state, reason=reason)
            if state.phase is TaskPhase.ACTING:
                state = state.transition_to(TaskPhase.OBSERVING)
            if cancelled:
                control = self._deps.runtime_journal.pending_control(request.task_id)
                if control is not None and control.command is RuntimeControlCommand.CANCEL:
                    self._deps.runtime_journal.acknowledge_control(control.control_id)
            return self._checkpoint_and_fence(
                request=request,
                state=state,
                usage=usage,
                stop_reason=(
                    RuntimeStopReason.INTERRUPTED
                    if ambiguous
                    else RuntimeStopReason.CANCELLED
                    if cancelled
                    else RuntimeStopReason.BLOCKED
                ),
                reasons=(reason,),
                resume_phase=TaskPhase.PLANNED,
                next_step=(
                    "reconcile the prior side effect before any retry"
                    if ambiguous
                    else "resume only after a fresh runtime decision"
                ),
                started_at=started_at,
                receipt=receipt,
            )
        if outcome.result.status is not ToolResultStatus.SUCCESS:
            failure = self._deps.failure_classifier.from_tool_result(
                task_id=request.task_id,
                trace_id=request.trace_id,
                result=outcome.result,
            )
            recovery = self._deps.recovery_policy.decide(
                failure=failure,
                mutation_active=bool(outcome.observation.changed_files),
            )
            state = self._fail_active_step(state, reason=recovery.reason)
            if state.phase is TaskPhase.ACTING:
                state = state.transition_to(TaskPhase.OBSERVING)
            stop_reason = (
                RuntimeStopReason.PERMISSION_DENIED
                if recovery.action is RecoveryAction.REQUEST_APPROVAL
                else RuntimeStopReason.RESOURCE_SUSPENDED
                if recovery.action is RecoveryAction.SUSPEND
                else RuntimeStopReason.BLOCKED
            )
            return self._checkpoint_and_fence(
                request=request,
                state=state,
                usage=usage,
                stop_reason=stop_reason,
                reasons=(recovery.reason,),
                resume_phase=TaskPhase.PLANNED,
                next_step="recover from observed tool failure",
                started_at=started_at,
                receipt=receipt,
                attempt=AttemptRecord(
                    task_id=request.task_id,
                    step_id=active.step_id,
                    basis=basis,
                    observation_id=outcome.observation.observation_id,
                    outcome=outcome.observation.status,
                ),
            )

        if expectation is not None:
            assessment = self._expectations.assess(expectation, outcome.observation)
            if not assessment.matched:
                failure = self._deps.failure_classifier.verification_failure(
                    task_id=request.task_id,
                    trace_id=request.trace_id,
                    reason="; ".join(assessment.mismatches),
                )
                recovery = self._deps.recovery_policy.decide(
                    failure=failure,
                    mutation_active=bool(outcome.observation.changed_files),
                )
                state = self._fail_active_step(state, reason=recovery.reason)
                if state.phase is TaskPhase.ACTING:
                    state = state.transition_to(TaskPhase.OBSERVING)
                return self._checkpoint_and_fence(
                    request=request,
                    state=state,
                    usage=usage,
                    stop_reason=RuntimeStopReason.BLOCKED,
                    reasons=(recovery.reason, *assessment.mismatches),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="replan from expectation mismatch",
                    started_at=started_at,
                    receipt=receipt,
                    attempt=AttemptRecord(
                        task_id=request.task_id,
                        step_id=active.step_id,
                        basis=basis,
                        observation_id=outcome.observation.observation_id,
                        outcome=outcome.observation.status,
                    ),
                )

        state = self._complete_active_step(state)
        if state.phase is TaskPhase.ACTING:
            state = state.transition_to(TaskPhase.OBSERVING)
        attempt = AttemptRecord(
            task_id=request.task_id,
            step_id=active.step_id,
            basis=basis,
            observation_id=outcome.observation.observation_id,
            outcome=outcome.observation.status,
        )
        if self._next_pending_step(state) is None:
            state = state.transition_to(TaskPhase.VERIFYING)
            checkpointed, checkpoint_id = self._checkpoint(
                request=request,
                state=state,
                resume_phase=TaskPhase.VERIFYING,
                next_step="Phase 12F deterministic verification",
                attempts=(attempt,),
            )
            if receipt is not None:
                current = self._deps.runtime_journal.load(receipt.idempotency_key)
                if current.stage is SideEffectStage.OBSERVED:
                    self._deps.runtime_journal.mark_checkpointed(
                        idempotency_key=current.idempotency_key,
                        checkpoint_id=checkpoint_id,
                    )
            resume_policy = self._current_resume_policy(
                task_contract=checkpointed.contract,
                workspace_root=self._effective_workspace_root(
                    request.task_id,
                    fallback_root=checkpointed.contract.scope.workspace_root,
                ),
            )
            decision = self._deps.core.continuity_service.resume_latest(
                task_id=request.task_id,
                policy=resume_policy,
                trace_id=request.trace_id,
            )
            if decision.status is not ResumeStatus.READY or decision.resumed_state is None:
                return self._outcome(
                    request=request,
                    state=checkpointed,
                    usage=usage.snapshot(),
                    stop_reason=RuntimeStopReason.INTERRUPTED,
                    reasons=decision.reasons,
                    started_at=started_at,
                )
            return self._phase12f_or_pending(
                request=request,
                state=decision.resumed_state,
                usage=usage,
                started_at=started_at,
            )

        checkpointed, checkpoint_id = self._checkpoint(
            request=request,
            state=state,
            resume_phase=TaskPhase.PLANNED,
            next_step="continue with next pending plan step",
            attempts=(attempt,),
        )
        if receipt is not None:
            self._deps.runtime_journal.mark_checkpointed(
                idempotency_key=receipt.idempotency_key,
                checkpoint_id=checkpoint_id,
            )
        resume_policy = self._current_resume_policy(
            task_contract=checkpointed.contract,
            workspace_root=self._effective_workspace_root(
                request.task_id,
                fallback_root=checkpointed.contract.scope.workspace_root,
            ),
        )
        decision = self._deps.core.continuity_service.resume_latest(
            task_id=request.task_id,
            policy=resume_policy,
            trace_id=request.trace_id,
        )
        if decision.status is not ResumeStatus.READY or decision.resumed_state is None:
            return self._outcome(
                request=request,
                state=checkpointed,
                usage=usage.snapshot(),
                stop_reason=RuntimeStopReason.INTERRUPTED,
                reasons=decision.reasons,
                started_at=started_at,
            )
        return decision.resumed_state

    def _reconcile_receipt(
        self,
        *,
        request: RuntimeRequest,
        policy: ToolPolicy,
        receipt: SideEffectReceipt,
        usage: _UsageCounter,
        started_at: datetime,
    ) -> RuntimeOutcome | None:
        if receipt.stage is SideEffectStage.STARTED:
            return self._outcome(
                request=request,
                state=receipt.pre_action_state,
                usage=usage.snapshot(),
                stop_reason=RuntimeStopReason.INTERRUPTED,
                reasons=(
                    "side-effect handler may have started before interruption; "
                    "automatic replay is forbidden",
                ),
                started_at=started_at,
            )
        if receipt.stage is SideEffectStage.PREPARED:
            control = self._deps.runtime_journal.pending_control(request.task_id)
            if control is not None:
                if control.command is RuntimeControlCommand.CANCEL:
                    self._deps.runtime_journal.abort_prepared(
                        idempotency_key=receipt.idempotency_key,
                        reason=control.reason,
                    )
                    cleanup_error = self._cleanup_task_isolation(request.task_id)
                    if cleanup_error is not None:
                        return self._integrity_stop(
                            request=request,
                            state=receipt.pre_action_state,
                            usage=usage,
                            reason=cleanup_error,
                            started_at=started_at,
                            receipt=receipt,
                        )
                self._deps.runtime_journal.acknowledge_control(control.control_id)
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(receipt.pre_action_state),
                    usage=usage,
                    stop_reason=(
                        RuntimeStopReason.CANCELLED
                        if control.command is RuntimeControlCommand.CANCEL
                        else RuntimeStopReason.SUSPENDED
                    ),
                    reasons=(control.reason,),
                    resume_phase=TaskPhase.PLANNED,
                    next_step=(
                        "task cancelled before prepared side effect started"
                        if control.command is RuntimeControlCommand.CANCEL
                        else "resume prepared side effect after suspension"
                    ),
                    started_at=started_at,
                )
            execution_contract = receipt.pre_action_state.contract.model_copy(
                update={
                    "scope": receipt.pre_action_state.contract.scope.model_copy(
                        update={"workspace_root": receipt.execution_workspace_root}
                    )
                }
            )
            approval_workspace_root = (
                receipt.approval_workspace_root
                or receipt.pre_action_state.contract.scope.workspace_root
            )
            approval_contract = self._contract_for_workspace(
                receipt.pre_action_state.contract,
                approval_workspace_root,
            )
            current_approval_basis = self._approval_basis_fingerprint(
                state=receipt.pre_action_state,
                task_contract=approval_contract,
                workspace_root=approval_workspace_root,
            )
            authorization = self._deps.core.tool_dispatcher.authorize(
                request=receipt.request,
                task_contract=execution_contract,
                policy=policy,
                approval_basis_fingerprint=current_approval_basis,
            )
            if not authorization.allowed:
                return self._checkpoint_outcome(
                    request=request,
                    state=self._safe_checkpoint_state(receipt.pre_action_state),
                    usage=usage,
                    stop_reason=RuntimeStopReason.PERMISSION_DENIED,
                    reasons=(
                        authorization.reason,
                        "prepared side effect remains fenced until exact-call reapproval",
                    ),
                    resume_phase=TaskPhase.PLANNED,
                    next_step="owner exact-call reapproval or revised action required",
                    started_at=started_at,
                )
            self._deps.runtime_journal.mark_started(receipt.idempotency_key)
            outcome = self._deps.core.tool_dispatcher.dispatch(
                request=receipt.request,
                task_contract=execution_contract,
                policy=policy,
                cancellation_probe=lambda: self._pending_cancellation_reason(request.task_id),
                approval_basis_fingerprint=current_approval_basis,
            )
            usage.tool_calls += 1
            self._deps.runtime_journal.mark_completed(
                idempotency_key=receipt.idempotency_key,
                outcome=outcome,
            )
            self._deps.runtime_journal.record_outcome(outcome)
            state = self._observe(
                receipt.pre_action_state,
                outcome.observation.observation_id,
            )
            self._deps.runtime_journal.mark_observed(
                idempotency_key=receipt.idempotency_key,
                post_action_state=state,
            )
            return self._checkpoint_and_fence(
                request=request,
                state=self._safe_checkpoint_state(state),
                usage=usage,
                stop_reason=RuntimeStopReason.INTERRUPTED,
                reasons=("prepared side effect executed once during resume and was fenced",),
                resume_phase=TaskPhase.PLANNED,
                next_step="reevaluate observation before another action",
                started_at=started_at,
                receipt=self._deps.runtime_journal.load(receipt.idempotency_key),
            )
        if receipt.stage is SideEffectStage.COMPLETED:
            assert receipt.outcome is not None
            self._deps.runtime_journal.record_outcome(receipt.outcome)
            state = self._observe(
                receipt.pre_action_state,
                receipt.outcome.observation.observation_id,
            )
            self._deps.runtime_journal.mark_observed(
                idempotency_key=receipt.idempotency_key,
                post_action_state=state,
            )
            receipt = self._deps.runtime_journal.load(receipt.idempotency_key)
        if receipt.stage is SideEffectStage.OBSERVED:
            assert receipt.post_action_state is not None
            return self._checkpoint_and_fence(
                request=request,
                state=self._safe_checkpoint_state(receipt.post_action_state),
                usage=usage,
                stop_reason=RuntimeStopReason.INTERRUPTED,
                reasons=("completed side effect reconciled from durable receipt without replay",),
                resume_phase=TaskPhase.PLANNED,
                next_step="reevaluate reconciled observation",
                started_at=started_at,
                receipt=receipt,
            )
        return None

    def _compose_context(
        self,
        *,
        request: RuntimeRequest,
        state: TaskState,
    ) -> LayeredContextBundle:
        candidates = list(request.layered_context_candidates)
        candidates.extend(
            LayeredContextCandidate.from_candidate(candidate)
            for candidate in request.context_candidates
        )
        candidates.extend(
            (
                LayeredContextCandidate.from_text(
                    layer=ContextLayer.TASK,
                    kind=ContextSourceKind.PROJECT_STATE,
                    locator="runtime://task-contract",
                    text=json.dumps(
                        state.contract.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    priority=100,
                    required=True,
                    interpretation=ContextInterpretation.CONTROL,
                    verified=True,
                ),
                LayeredContextCandidate.from_text(
                    layer=ContextLayer.RUNTIME_CONTINUITY,
                    kind=ContextSourceKind.PROJECT_STATE,
                    locator="runtime://task-state",
                    text=json.dumps(
                        state.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    priority=100,
                    required=True,
                    interpretation=ContextInterpretation.CONTROL,
                    verified=True,
                ),
            )
        )
        for record in self._deps.runtime_journal.list_observations(
            request.task_id,
            limit=4,
        ):
            outcome = record.outcome
            evidence = {
                "observation_id": str(record.observation_id),
                "tool_name": outcome.request.tool_name,
                "request_id": str(outcome.request.request_id),
                "result": outcome.result.model_dump(mode="json"),
                "observation": outcome.observation.model_dump(mode="json"),
            }
            candidates.append(
                LayeredContextCandidate.from_text(
                    layer=ContextLayer.RUNTIME_CONTINUITY,
                    kind=ContextSourceKind.COMMAND_OUTPUT,
                    locator=f"runtime://observation/{record.observation_id}",
                    text=json.dumps(
                        evidence,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    priority=95,
                    required=False,
                    interpretation=ContextInterpretation.DATA_ONLY,
                    verified=True,
                    observed_at=outcome.observation.captured_at,
                )
            )
        return self._deps.context_composer.compose(
            task_id=request.task_id,
            candidates=tuple(candidates),
            policy=LayeredContextPolicy(overall_budget=request.context_budget),
        )

    @staticmethod
    def _validate_policy_boundary(*, request: RuntimeRequest, policy: ToolPolicy) -> None:
        if policy.autonomy_level.number > request.autonomy.level.number:
            raise ValueError("tool policy cannot exceed RuntimeRequest autonomy level")
        if not set(policy.allowed_tools).issubset(request.autonomy.allowed_tools):
            raise ValueError("tool policy cannot grant tools absent from RuntimeRequest autonomy")
        if _RISK_RANK[policy.max_risk.value] > _RISK_RANK[request.autonomy.max_risk.value]:
            raise ValueError("tool policy cannot raise RuntimeRequest risk ceiling")

    @staticmethod
    def _next_pending_step(state: TaskState) -> PlanStep | None:
        completed = {
            item.step_id
            for item in state.plan
            if item.status in {PlanStepStatus.COMPLETE, PlanStepStatus.SKIPPED_WITH_REASON}
        }
        for step in sorted(state.plan, key=lambda item: item.sequence):
            if step.status is PlanStepStatus.PENDING and set(step.depends_on).issubset(completed):
                return step
        return None

    @staticmethod
    def _active_step(state: TaskState) -> PlanStep:
        active = tuple(item for item in state.plan if item.status is PlanStepStatus.ACTIVE)
        if len(active) != 1:
            raise ValueError("single policy-agent loop requires exactly one ACTIVE plan step")
        return active[0]

    @staticmethod
    def _replace_step(state: TaskState, step: PlanStep) -> TaskState:
        plan = tuple(step if item.step_id == step.step_id else item for item in state.plan)
        return state.revise(plan=plan)

    def _activate_step(self, state: TaskState, step_id: UUID) -> TaskState:
        if any(item.status is PlanStepStatus.ACTIVE for item in state.plan):
            raise ValueError("only one plan step may be ACTIVE")
        target = next(item for item in state.plan if item.step_id == step_id)
        if target.status is not PlanStepStatus.PENDING:
            raise ValueError("only PENDING step may activate")
        return self._replace_step(
            state,
            target.model_copy(update={"status": PlanStepStatus.ACTIVE, "status_reason": None}),
        )

    def _deactivate_step(self, state: TaskState, *, reason: str | None) -> TaskState:
        target = self._active_step(state)
        return self._replace_step(
            state,
            target.model_copy(update={"status": PlanStepStatus.PENDING, "status_reason": reason}),
        )

    def _complete_active_step(self, state: TaskState) -> TaskState:
        target = self._active_step(state)
        return self._replace_step(
            state,
            target.model_copy(update={"status": PlanStepStatus.COMPLETE, "status_reason": None}),
        )

    def _fail_active_step(self, state: TaskState, *, reason: str) -> TaskState:
        target = self._active_step(state)
        return self._replace_step(
            state,
            target.model_copy(update={"status": PlanStepStatus.FAILED, "status_reason": reason}),
        )

    def _safe_checkpoint_state(self, state: TaskState) -> TaskState:
        if any(item.status is PlanStepStatus.ACTIVE for item in state.plan):
            state = self._deactivate_step(state, reason=None)
        if state.phase is TaskPhase.ACTING:
            state = state.transition_to(TaskPhase.OBSERVING)
        return state

    @staticmethod
    def _observe(state: TaskState, observation_id: UUID) -> TaskState:
        if observation_id in state.observation_ids:
            return state
        return state.revise(observation_ids=(*state.observation_ids, observation_id))

    def _ensure_expectation(
        self,
        proposal: ActionProposal,
        state: TaskState,
    ) -> tuple[ActionProposal, TaskState]:
        if not proposal.has_side_effects or proposal.expectation_id is not None:
            return proposal, state
        active = self._active_step(state)
        path = proposal.arguments.get("path")
        expected_paths = (path,) if isinstance(path, str) else ()
        expectation = ExpectedObservation(
            summary="The proposed side effect should succeed inside its declared scope.",
            expected_status=ObservationStatus.SUCCESS,
            expected_exit_codes=(
                (0,) if ToolCapability.PROCESS in proposal.required_capabilities else ()
            ),
            expected_changed_paths=(
                expected_paths
                if ToolCapability.WRITE in proposal.required_capabilities
                else ()
            ),
            failure_signals=(
                "protected_path_changed",
                "scope_violation",
                "non_zero_exit",
                "test_failure",
            ),
            verification_method=(
                "Compare the structured tool observation with the pre-action expectation."
            ),
            high_impact=True,
        )
        state = self._replace_step(state, active.model_copy(update={"expectation": expectation}))
        return proposal.model_copy(update={"expectation_id": expectation.expectation_id}), state

    @staticmethod
    def _semantic_fingerprint(request: ToolRequest) -> str:
        payload = request.model_dump(
            mode="json",
            exclude={"request_id", "trace_id", "requested_at", "expectation_id"},
        )
        return sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _idempotency_key(*, task_id: UUID, step_id: UUID, semantic_fingerprint: str) -> str:
        return sha256(f"{task_id}:{step_id}:{semantic_fingerprint}".encode()).hexdigest()

    def _approval_basis_fingerprint(
        self,
        *,
        state: TaskState,
        task_contract: TaskContract,
        workspace_root: str,
    ) -> str:
        """Bind approval to fresh runtime-owned state without model-window churn."""
        scope_payload = json.dumps(
            task_contract.scope.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload = {
            "assumption_revision": (
                state.decision_state.revision
                if state.decision_state is not None
                else 0
            ),
            "environment_fingerprint": (
                self._deps.fingerprint_provider.environment_fingerprint()
            ),
            "runtime_revision": self._deps.fingerprint_provider.runtime_revision,
            "scope_fingerprint": sha256(scope_payload.encode("utf-8")).hexdigest(),
            "workspace_fingerprint": (
                self._deps.fingerprint_provider.workspace_fingerprint(
                    task_contract=task_contract,
                    workspace_root=workspace_root,
                )
            ),
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(
            b"luna-exact-call-approval-basis-v1\0"
            + serialized.encode("utf-8")
        ).hexdigest()

    def _attempt_basis(
        self,
        *,
        request: RuntimeRequest,
        state: TaskState,
        proposal: ActionProposal,
        tool_request: ToolRequest,
        context_fingerprint: str,
    ) -> AttemptBasis:
        scope_payload = json.dumps(
            state.contract.scope.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        active = self._active_step(state)
        strategy = self._verification_strategy.select(
            contract=state.contract,
            step=active,
        )
        verification_method = (
            active.expectation.verification_method
            if active.expectation is not None
            else "structured observation"
        )
        verification = f"{strategy.depth.value}:{verification_method}"
        return AttemptBasis(
            action_key=f"{proposal.kind.value}:{tool_request.tool_name}",
            context_fingerprint=context_fingerprint,
            evidence_refs=tuple(str(value) for value in state.observation_ids[-8:]),
            assumption_revision=(
                state.decision_state.revision
                if state.decision_state is not None
                else 0
            ),
            execution_strategy=tool_request.tool_name,
            verification_strategy=verification,
            scope_fingerprint=sha256(scope_payload.encode("utf-8")).hexdigest(),
        )

    def _phase12f_or_pending(
        self,
        *,
        request: RuntimeRequest,
        state: TaskState,
        usage: _UsageCounter,
        started_at: datetime,
    ) -> RuntimeOutcome:
        if state.phase is not TaskPhase.VERIFYING:
            raise ValueError("Phase 12F handoff requires VERIFYING TaskState")
        services = self._deps.phase12f
        if services is None:
            return self._checkpoint_outcome(
                request=request,
                state=state,
                usage=usage,
                stop_reason=RuntimeStopReason.VERIFICATION_PENDING,
                reasons=("Phase 12F verification services are not configured",),
                resume_phase=TaskPhase.VERIFYING,
                next_step="Phase 12F deterministic verification",
                started_at=started_at,
            )
        if not services.evidence_registry.verify_integrity():
            return self._integrity_stop(
                request=request,
                state=state,
                usage=usage,
                reason="Phase 12F evidence registry integrity check failed",
                started_at=started_at,
            )

        evidence = services.evidence_registry.list_for_task(request.task_id)
        if not evidence:
            return self._checkpoint_outcome(
                request=request,
                state=state,
                usage=usage,
                stop_reason=RuntimeStopReason.VERIFICATION_PENDING,
                reasons=("no durable evidence is available for deterministic verification",),
                resume_phase=TaskPhase.VERIFYING,
                next_step="collect runtime-owned evidence for current claims",
                started_at=started_at,
            )

        workspace_root = self._effective_workspace_root(
            request.task_id,
            fallback_root=state.contract.scope.workspace_root,
        )
        workspace_revision = self._deps.fingerprint_provider.workspace_fingerprint(
            task_contract=state.contract,
            workspace_root=workspace_root,
        )
        environment = self._deps.fingerprint_provider.environment_fingerprint()
        strategy = self._verification_strategy.select(contract=state.contract)
        policy = VerificationPolicy(
            current_revision=workspace_revision,
            expected_environment_fingerprint=environment,
            minimum_strength=strategy.minimum_strength_floor,
        )
        observations = self._deps.runtime_journal.list_observations(
            request.task_id,
            limit=max(8, request.runtime_budget.max_steps + 4),
        )
        performed = tuple(
            dict.fromkeys(
                f"{record.outcome.request.tool_name}: {record.outcome.result.status.value}"
                for record in observations
            )
        )
        changed = tuple(
            dict.fromkeys(
                path
                for record in observations
                for path in record.outcome.observation.changed_files
            )
        )
        finalization = services.verification_coordinator.finalize(
            state=state,
            evidence=evidence,
            policy=policy,
            trace_id=request.trace_id,
            performed=performed,
            changed=changed,
        )
        status = finalization.gate_result.decision.status
        stop_reason_by_status = {
            CompletionStatus.VERIFIED_COMPLETE: RuntimeStopReason.COMPLETED,
            CompletionStatus.UNVERIFIED: RuntimeStopReason.UNVERIFIED,
            CompletionStatus.INCONCLUSIVE: RuntimeStopReason.INCONCLUSIVE,
            CompletionStatus.BLOCKED: RuntimeStopReason.BLOCKED,
            CompletionStatus.FAILED: RuntimeStopReason.FAILED,
            CompletionStatus.CONFLICTING_EVIDENCE: RuntimeStopReason.CONFLICTING_EVIDENCE,
        }
        learning_candidate_ids = tuple(
            item.candidate_id for item in finalization.learning_candidates.candidates
        )
        if status in {
            CompletionStatus.UNVERIFIED,
            CompletionStatus.INCONCLUSIVE,
            CompletionStatus.BLOCKED,
            CompletionStatus.CONFLICTING_EVIDENCE,
        }:
            checkpointed, _ = self._checkpoint(
                request=request,
                state=finalization.reporting_state,
                resume_phase=TaskPhase.VERIFYING,
                next_step="collect or reconcile stronger current verification evidence",
            )
            return self._outcome(
                request=request,
                state=checkpointed,
                usage=usage.snapshot(),
                stop_reason=stop_reason_by_status[status],
                reasons=finalization.gate_result.decision.reasons,
                started_at=started_at,
                verification_report_id=finalization.gate_result.report.report_id,
                final_report_id=finalization.final_report.final_report_id,
                learning_candidate_ids=learning_candidate_ids,
            )

        closed = finalization.reporting_state.transition_to(
            TaskPhase.CLOSED,
            completion_status=status,
        )
        resume_policy = self._current_resume_policy(
            task_contract=closed.contract,
            workspace_root=workspace_root,
        )
        terminal = self._deps.core.continuity_service.create_checkpoint(
            state=closed,
            workspace_fingerprint=resume_policy.workspace_fingerprint,
            environment_fingerprint=resume_policy.environment_fingerprint,
            runtime_revision=resume_policy.runtime_revision,
            compatibility_vector=resume_policy.compatibility_vector,
            next_step=None,
            trace_id=request.trace_id,
        )
        if not terminal.envelope.terminal:
            raise RuntimeError("closed Phase 12F state did not produce a terminal checkpoint")

        return self._outcome(
            request=request,
            state=closed,
            usage=usage.snapshot(),
            stop_reason=stop_reason_by_status[status],
            reasons=finalization.gate_result.decision.reasons,
            started_at=started_at,
            verification_report_id=finalization.gate_result.report.report_id,
            final_report_id=finalization.final_report.final_report_id,
            learning_candidate_ids=learning_candidate_ids,
        )

    def _current_resume_policy(
        self,
        *,
        task_contract: TaskContract,
        workspace_root: str | None,
    ) -> ResumePolicy:
        """Bind fresh component-owned versions into one non-authoritative vector."""
        return self._deps.fingerprint_provider.resume_policy(
            task_contract=task_contract,
            workspace_root=workspace_root,
            continuity_schema_version=(
                self._deps.core.continuity_service.store.schema_version()
            ),
            runtime_journal_schema_version=self._deps.runtime_journal.schema_version(),
            contract_schema_version=CONTRACT_SCHEMA_VERSION,
        )

    def _checkpoint(
        self,
        *,
        request: RuntimeRequest,
        state: TaskState,
        resume_phase: TaskPhase,
        next_step: str,
        attempts: tuple[AttemptRecord, ...] = (),
    ) -> tuple[TaskState, UUID]:
        resume_policy = self._current_resume_policy(
            task_contract=state.contract,
            workspace_root=self._effective_workspace_root(
                request.task_id,
                fallback_root=state.contract.scope.workspace_root,
            ),
        )
        stored = self._deps.core.continuity_service.create_checkpoint(
            state=state,
            workspace_fingerprint=resume_policy.workspace_fingerprint,
            environment_fingerprint=resume_policy.environment_fingerprint,
            runtime_revision=resume_policy.runtime_revision,
            compatibility_vector=resume_policy.compatibility_vector,
            next_step=next_step,
            attempts=attempts,
            resume_phase=resume_phase,
            trace_id=request.trace_id,
        )
        return stored.envelope.state, stored.envelope.checkpoint.checkpoint_id

    def _checkpoint_outcome(
        self,
        *,
        request: RuntimeRequest,
        state: TaskState,
        usage: _UsageCounter,
        stop_reason: RuntimeStopReason,
        reasons: tuple[str, ...],
        resume_phase: TaskPhase,
        next_step: str,
        started_at: datetime,
    ) -> RuntimeOutcome:
        checkpointed, _ = self._checkpoint(
            request=request,
            state=state,
            resume_phase=resume_phase,
            next_step=next_step,
        )
        return self._outcome(
            request=request,
            state=checkpointed,
            usage=usage.snapshot(),
            stop_reason=stop_reason,
            reasons=reasons,
            started_at=started_at,
        )

    def _checkpoint_and_fence(
        self,
        *,
        request: RuntimeRequest,
        state: TaskState,
        usage: _UsageCounter,
        stop_reason: RuntimeStopReason,
        reasons: tuple[str, ...],
        resume_phase: TaskPhase,
        next_step: str,
        started_at: datetime,
        receipt: SideEffectReceipt | None,
        attempt: AttemptRecord | None = None,
    ) -> RuntimeOutcome:
        checkpointed, checkpoint_id = self._checkpoint(
            request=request,
            state=state,
            resume_phase=resume_phase,
            next_step=next_step,
            attempts=(attempt,) if attempt is not None else (),
        )
        if receipt is not None:
            current = self._deps.runtime_journal.load(receipt.idempotency_key)
            if current.stage is SideEffectStage.OBSERVED:
                self._deps.runtime_journal.mark_checkpointed(
                    idempotency_key=current.idempotency_key,
                    checkpoint_id=checkpoint_id,
                )
        return self._outcome(
            request=request,
            state=checkpointed,
            usage=usage.snapshot(),
            stop_reason=stop_reason,
            reasons=reasons,
            started_at=started_at,
        )

    def _integrity_stop(
        self,
        *,
        request: RuntimeRequest,
        state: TaskState,
        usage: _UsageCounter,
        reason: str,
        started_at: datetime,
        receipt: SideEffectReceipt | None = None,
    ) -> RuntimeOutcome:
        state = self._safe_checkpoint_state(state)
        return self._checkpoint_and_fence(
            request=request,
            state=state,
            usage=usage,
            stop_reason=RuntimeStopReason.INTEGRITY_FAILURE,
            reasons=(reason,),
            resume_phase=TaskPhase.PLANNED,
            next_step="owner/runtime integrity review",
            started_at=started_at,
            receipt=receipt,
        )

    def _budget_stop(
        self,
        *,
        request: RuntimeRequest,
        state: TaskState,
        usage: _UsageCounter,
        started_at: datetime,
    ) -> RuntimeOutcome | None:
        snapshot = usage.snapshot()
        exhausted = tuple(
            reason
            for reason in snapshot.exhausted_reasons()
            if reason in _ITERATION_EXHAUSTION_REASONS
        )
        if not exhausted:
            return None
        return self._checkpoint_outcome(
            request=request,
            state=self._safe_checkpoint_state(state),
            usage=usage,
            stop_reason=RuntimeStopReason.BUDGET_EXHAUSTED,
            reasons=("runtime budget exhausted: " + ", ".join(exhausted),),
            resume_phase=TaskPhase.PLANNED,
            next_step="owner budget decision required",
            started_at=started_at,
        )

    @staticmethod
    def _projected_change_budget_violation(
        *,
        usage: _UsageCounter,
        estimate: ChangeEstimate,
        budget: RuntimeBudget,
    ) -> str | None:
        projected = (
            (
                "changed_files",
                usage.changed_files + estimate.changed_files,
                budget.max_changed_files,
            ),
            ("added_lines", usage.added_lines + estimate.added_lines, budget.max_added_lines),
            (
                "deleted_lines",
                usage.deleted_lines + estimate.deleted_lines,
                budget.max_deleted_lines,
            ),
        )
        exceeded = tuple(name for name, value, limit in projected if value > limit)
        if not exceeded:
            return None
        return "proposed change exceeds remaining runtime budget: " + ", ".join(exceeded)

    @staticmethod
    def _contract_for_workspace(contract: TaskContract, workspace_root: str) -> TaskContract:
        if Path(contract.scope.workspace_root).resolve() == Path(workspace_root).resolve():
            return contract
        return contract.model_copy(
            update={
                "scope": contract.scope.model_copy(
                    update={"workspace_root": workspace_root}
                )
            }
        )

    def _effective_workspace_root(self, task_id: UUID, *, fallback_root: str) -> str:
        receipts = self._deps.runtime_journal.list_for_task(task_id)
        for receipt in reversed(receipts):
            if (
                receipt.isolation_mode == IsolationMode.WORKTREE.value
                and receipt.stage is not SideEffectStage.ABORTED
                and Path(receipt.execution_workspace_root).is_dir()
            ):
                return receipt.execution_workspace_root
        return fallback_root

    def _cleanup_task_isolation(self, task_id: UUID) -> str | None:
        receipts = self._deps.runtime_journal.list_for_task(task_id)
        worktree_receipt = next(
            (
                item
                for item in reversed(receipts)
                if item.isolation_mode == IsolationMode.WORKTREE.value
            ),
            None,
        )
        if worktree_receipt is None:
            return None
        try:
            self._deps.isolation_manager.cleanup(
                task_contract=worktree_receipt.pre_action_state.contract,
                task_id=task_id,
            )
        except WorkspaceIsolationError as exc:
            return f"task worktree cleanup failed: {exc}"
        return None

    def _latest_persisted_state(self, task_id: UUID) -> TaskState:
        return self._deps.core.continuity_service.store.load_task_state(task_id)

    @staticmethod
    def _outcome(
        *,
        request: RuntimeRequest,
        state: TaskState,
        usage: RuntimeUsage,
        stop_reason: RuntimeStopReason,
        reasons: tuple[str, ...],
        started_at: datetime,
        verification_report_id: UUID | None = None,
        final_report_id: UUID | None = None,
        learning_candidate_ids: tuple[UUID, ...] = (),
    ) -> RuntimeOutcome:
        return RuntimeOutcome(
            request_id=request.request_id,
            task_id=request.task_id,
            trace_id=request.trace_id,
            task_fingerprint=build_task_fingerprint(request).digest,
            state=state,
            stop_reason=stop_reason,
            completion_status=state.completion_status,
            verification_report_id=verification_report_id,
            final_report_id=final_report_id,
            checkpoint_id=state.checkpoint_id,
            observation_ids=state.observation_ids,
            evidence_ids=state.evidence_ids,
            learning_candidate_ids=learning_candidate_ids,
            usage=usage,
            reasons=reasons,
            started_at=started_at,
        )
