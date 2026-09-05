"""S4 root-owned orchestration for zero-to-three interruptible read-only workers."""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from threading import Event, RLock
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.context import RootContextExtensionIntegrityError
from luna.contracts import TaskState
from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.parallel_cognition.admission import (
    AdmissionDecision,
    AdmissionDisposition,
    AdmittedPlan,
    authoritative_model_sha256,
)
from luna.parallel_cognition.context_broker import FocusedContextBroker
from luna.parallel_cognition.controls import (
    AttemptRuntimeBinding,
    ControlClock,
    ControlDisposition,
    ControlExpectation,
    ControlFenceController,
    ControlFencePhase,
    CurrentControlProvider,
    FenceDecision,
    ResultQuarantineRecord,
    evaluate_control_fence,
)
from luna.parallel_cognition.events import RootLeaseHandle
from luna.parallel_cognition.live import (
    FocusedContextBundle,
    LiveBackendRequest,
    LiveBackendResult,
    LiveInvocationState,
    S4IntegrationStatus,
    S4RuntimePolicy,
)
from luna.parallel_cognition.live_store import SQLiteLiveInvocationJournal
from luna.parallel_cognition.models import (
    AdoptionDecision,
    AdoptionDisposition,
    AdoptionReceipt,
    AgentExecutionAttempt,
    AgentExecutionReceipt,
    AgentLifecycleState,
    AssignmentSemanticSpec,
    CleanupState,
    DistilledHandoff,
    IsolationReferences,
    contract_sha256,
    validate_c011_contract_chain,
)
from luna.parallel_cognition.store import SQLiteCoordinationStore
from luna.parallel_cognition.subprocess_backend import InterruptibleWorkerBackend


class S4IntegrityError(RootContextExtensionIntegrityError):
    """Material S4 provenance or control failure requiring STOP/VERIFY."""


@dataclass(frozen=True, slots=True)
class LiveExecutionAuthorization:
    """Root-only S3 admission result plus its ephemeral lease bearer."""

    decision: AdmissionDecision
    lease: RootLeaseHandle

    def __post_init__(self) -> None:
        if self.decision.task_id is not None and (
            self.decision.task_id != self.lease.record.task_id
        ):
            raise ValueError("S4 authorization decision and lease tasks differ")
        if self.decision.root_coordination_epoch is not None and (
            self.decision.root_coordination_epoch != self.lease.record.epoch
        ):
            raise ValueError("S4 authorization decision and lease epochs differ")


class LivePlanProvider(Protocol):
    """Root-owned bridge that rebuilds S3 admission from current TaskState."""

    def authorization_for(self, state: TaskState) -> LiveExecutionAuthorization:
        """Return the current whole-plan admission decision and root lease."""


class RootHandoffQualifier(Protocol):
    """Authoritative root resolver; worker output cannot implement this boundary."""

    def qualify(
        self,
        *,
        assignment: AssignmentSemanticSpec,
        cleanup_attempt: AgentExecutionAttempt,
        result: LiveBackendResult,
        receipt: AgentExecutionReceipt,
        qualified_at: datetime,
    ) -> DistilledHandoff | None:
        """Return a fully qualified handoff or reject the worker payload."""


class LiveHandoffReuseFenceController:
    """Freshly evaluate reuse and append it to the S4 journal, not S3 history."""

    def __init__(
        self,
        *,
        provider: CurrentControlProvider,
        clock: ControlClock,
        journal: SQLiteLiveInvocationJournal,
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._journal = journal

    def check(
        self,
        *,
        expectation: ControlExpectation,
        invocation_key: str,
        attempt_binding: AttemptRuntimeBinding,
        subject_artifact_sha256: str,
    ) -> FenceDecision:
        """Capture current authority and durably bind one handoff consideration."""

        current = self._provider.current_control_snapshot(
            expectation.task_id,
            attempt_binding.attempt_id,
        )
        checked_at = require_utc(self._clock.now())
        decision = evaluate_control_fence(
            phase=ControlFencePhase.PRE_ADOPTION,
            expectation=expectation,
            current=current,
            checked_at=checked_at,
            attempt_id=attempt_binding.attempt_id,
            attempt_binding=attempt_binding,
            subject_artifact_sha256=subject_artifact_sha256,
        )
        return self._journal.record_reuse_fence(
            invocation_key=invocation_key,
            decision=decision,
        )


class RuntimeKillSwitch:
    """Root-owned dynamic kill switch sampled before and during every attempt."""

    def __init__(self, *, engaged: bool = False) -> None:
        self._event = Event()
        if engaged:
            self._event.set()

    def engage(self) -> None:
        self._event.set()

    @property
    def engaged(self) -> bool:
        return self._event.is_set()


class S4AttemptReport(LunaContractModel):
    """Bounded root-facing execution summary without raw worker scratch."""

    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    attempt_id: str | None = Field(default=None, max_length=208)
    outcome_state: AgentLifecycleState | None = None
    receipt_id: str | None = Field(default=None, max_length=200)
    handoff_id: str | None = Field(default=None, max_length=200)
    reused_durable_result: bool = False
    in_doubt_no_replay: bool = False
    reason: str = Field(min_length=1, max_length=2000)


class S4RootIntegration(LunaContractModel):
    """Only S4 artifact allowed to cross into the root model context."""

    status: S4IntegrationStatus
    task_id: UUID
    source_task_revision: int = Field(ge=0)
    plan_seal_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    handoffs: tuple[DistilledHandoff, ...] = Field(default=(), max_length=3)
    consideration_receipts: tuple[AdoptionReceipt, ...] = Field(default=(), max_length=3)
    attempts: tuple[S4AttemptReport, ...] = Field(default=(), max_length=3)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=32)
    generated_at: datetime
    raw_worker_output_in_root_context: Literal[False] = False
    task_state_mutated: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator("generated_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("handoffs")
    @classmethod
    def normalize_handoffs(
        cls, values: tuple[DistilledHandoff, ...]
    ) -> tuple[DistilledHandoff, ...]:
        ids = tuple(item.handoff_id for item in values)
        if len(ids) != len(set(ids)):
            raise ValueError("S4 root integration handoffs must be unique")
        return tuple(sorted(values, key=lambda item: item.assignment_id))

    @field_validator("consideration_receipts")
    @classmethod
    def normalize_consideration_receipts(
        cls, values: tuple[AdoptionReceipt, ...]
    ) -> tuple[AdoptionReceipt, ...]:
        ids = tuple(item.adoption_receipt_id for item in values)
        if len(ids) != len(set(ids)):
            raise ValueError("S4 root consideration receipts must be unique")
        return tuple(sorted(values, key=lambda item: item.handoff_id))

    @field_validator("attempts")
    @classmethod
    def normalize_attempts(
        cls, values: tuple[S4AttemptReport, ...]
    ) -> tuple[S4AttemptReport, ...]:
        assignments = tuple(item.assignment_id for item in values)
        if len(assignments) != len(set(assignments)):
            raise ValueError("S4 root attempt reports must address unique assignments")
        return tuple(sorted(values, key=lambda item: item.assignment_id))

    @field_validator("reason_codes")
    @classmethod
    def normalize_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in values)
        if any(not item for item in cleaned):
            raise ValueError("S4 integration reasons cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("S4 integration reasons must be unique")
        return tuple(sorted(cleaned))

    @model_validator(mode="after")
    def validate_bindings(self) -> S4RootIntegration:
        if any(
            item.task_id != self.task_id
            or item.source_task_revision != self.source_task_revision
            for item in self.handoffs
        ):
            raise ValueError("S4 handoff task binding differs from root integration")
        handoff_ids = {item.handoff_id for item in self.handoffs}
        if {item.handoff_id for item in self.consideration_receipts} != handoff_ids:
            raise ValueError("S4 consideration receipts must exactly cover handoffs")
        if any(item.task_id != self.task_id for item in self.consideration_receipts):
            raise ValueError("S4 consideration receipt belongs to another task")
        if self.status is S4IntegrationStatus.COMPLETE and not self.attempts:
            raise ValueError("completed S4 integration requires attempt reports")
        if self.handoffs and self.status is not S4IntegrationStatus.COMPLETE:
            raise ValueError("only a completed S4 integration may expose handoffs")
        return self

    @property
    def context_available(self) -> bool:
        """Expose only qualified handoffs to the generic root-context boundary."""

        return bool(self.handoffs)

    @property
    def context_locator(self) -> str:
        """Return a stable provenance locator without granting control authority."""

        suffix = self.plan_seal_sha256 or self.status.value.casefold()
        return f"runtime://parallel-cognition/{suffix}"

    def render_for_root_context(self) -> str:
        """Render qualified artifacts only; raw summaries and scratch are absent."""

        payload = {
            "status": self.status.value,
            "task_id": str(self.task_id),
            "source_task_revision": self.source_task_revision,
            "plan_seal_sha256": self.plan_seal_sha256,
            "handoffs": [item.model_dump(mode="json") for item in self.handoffs],
            "root_consideration_receipts": [
                item.model_dump(mode="json") for item in self.consideration_receipts
            ],
            "authority": {
                "task_state_mutation": False,
                "completion": False,
                "user_facing_voice": False,
            },
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class _PreparedAttempt:
    assignment: AssignmentSemanticSpec
    expectation: ControlExpectation
    context: FocusedContextBundle
    request: LiveBackendRequest
    invocation_key: str


@dataclass(frozen=True, slots=True)
class _CompletedAttempt:
    report: S4AttemptReport
    handoff: DistilledHandoff | None


class ParallelCognitionRuntimeService:
    """Execute only current S3-admitted plans and return root-only handoffs."""

    def __init__(
        self,
        *,
        policy: S4RuntimePolicy,
        kill_switch: RuntimeKillSwitch,
        plan_provider: LivePlanProvider,
        context_broker: FocusedContextBroker,
        backend: InterruptibleWorkerBackend,
        qualifier: RootHandoffQualifier,
        control_fences: ControlFenceController,
        reuse_fences: LiveHandoffReuseFenceController,
        coordination_store: SQLiteCoordinationStore,
        live_journal: SQLiteLiveInvocationJournal,
    ) -> None:
        self._policy = policy
        self._kill_switch = kill_switch
        self._plan_provider = plan_provider
        self._context_broker = context_broker
        self._backend = backend
        self._qualifier = qualifier
        self._control_fences = control_fences
        self._reuse_fences = reuse_fences
        self._coordination_store = coordination_store
        self._live_journal = live_journal
        self._coordination_lock = RLock()

    @property
    def enabled(self) -> bool:
        return self._policy.active and not self._kill_switch.engaged

    @staticmethod
    def _invocation_key(plan: AdmittedPlan, assignment: AssignmentSemanticSpec) -> str:
        basis = (
            f"{plan.seal.task_id}:{plan.seal.root_coordination_epoch}:"
            f"{plan.plan_seal_sha256}:{assignment.assignment_id}"
        )
        return "c011-s4:" + sha256(basis.encode("utf-8")).hexdigest()

    @staticmethod
    def _expectation(
        plan: AdmittedPlan,
        assignment: AssignmentSemanticSpec,
    ) -> ControlExpectation:
        context_sha256 = plan.seal.context_manifest_sha256
        if context_sha256 is None:
            raise S4IntegrityError("worker plan has no sealed context")
        return ControlExpectation(
            task_id=plan.seal.task_id,
            source_task_revision=plan.seal.source_task_revision,
            task_state_sha256=plan.seal.task_state_sha256,
            autonomy_policy_sha256=plan.seal.autonomy_policy_sha256,
            tool_policy_sha256=plan.seal.tool_policy_sha256,
            context_manifest_sha256=context_sha256,
            plan_seal_sha256=plan.plan_seal_sha256,
            assignment_id=assignment.assignment_id,
            root_coordination_epoch=plan.seal.root_coordination_epoch,
            cancellation_generation=plan.seal.cancellation_generation,
            deadline_at=assignment.budget.deadline_at,
        )

    @staticmethod
    def _attempt_snapshot(
        *,
        assignment: AssignmentSemanticSpec,
        attempt_id: str,
        created_at: datetime,
        state: AgentLifecycleState,
        runtime_session_id: str | None = None,
        backend_id: str | None = None,
        profile_id: str | None = None,
        started_at: datetime | None = None,
        cancellation_epoch: int = 0,
    ) -> AgentExecutionAttempt:
        provisioned = runtime_session_id is not None
        return AgentExecutionAttempt(
            attempt_id=attempt_id,
            task_id=assignment.task_id,
            source_task_revision=assignment.source_task_revision,
            assignment_id=assignment.assignment_id,
            context_manifest_sha256=assignment.context_manifest_sha256,
            runtime_session_id=runtime_session_id,
            backend_id=backend_id,
            profile_id=profile_id,
            root_coordination_epoch=assignment.root_coordination_epoch,
            cancellation_epoch=cancellation_epoch,
            created_at=created_at,
            started_at=started_at,
            deadline_at=assignment.budget.deadline_at,
            isolation=(
                IsolationReferences(
                    process_ref=f"s4-process-boundary:{runtime_session_id}",
                    session_ref=f"s4-session:{runtime_session_id}",
                    context_ref=f"s4-focused-context:{assignment.context_manifest_sha256}",
                )
                if provisioned
                else None
            ),
            lifecycle_state=state,
        )

    @staticmethod
    def _transition(
        previous: AgentExecutionAttempt,
        state: AgentLifecycleState,
    ) -> AgentExecutionAttempt:
        raw = previous.model_dump(mode="json")
        raw.pop("attempt_integrity_id", None)
        raw["lifecycle_state"] = state.value
        if state is AgentLifecycleState.CANCEL_REQUESTED:
            raw["cancellation_epoch"] = previous.cancellation_epoch + 1
        return AgentExecutionAttempt.model_validate(raw)

    def _record_transition(
        self,
        *,
        lease: RootLeaseHandle,
        attempt: AgentExecutionAttempt,
        invocation_key: str,
        suffix: str,
        reason: str,
    ) -> None:
        self._coordination_store.record_attempt_transition(
            lease,
            attempt,
            idempotency_key=f"{invocation_key}:{suffix}",
            reason=reason,
        )

    def _prepare_attempt(
        self,
        *,
        plan: AdmittedPlan,
        assignment: AssignmentSemanticSpec,
        lease: RootLeaseHandle,
    ) -> _PreparedAttempt | S4AttemptReport:
        invocation_key = self._invocation_key(plan, assignment)
        prior = self._live_journal.load(invocation_key)
        if prior is not None:
            record = prior.record
            if record.state is LiveInvocationState.RESERVED:
                return S4AttemptReport(
                    assignment_id=assignment.assignment_id,
                    attempt_id=record.request.attempt.attempt_id,
                    in_doubt_no_replay=True,
                    reason="durable live reservation is in doubt; blind replay denied",
                )
            result = record.result
            assert result is not None
            handoff = record.handoff
            reuse_reason = "durable terminal worker result reused without replay"
            if handoff is not None:
                current_attempt = self._coordination_store.load_attempt(
                    result.request.attempt.attempt_id
                )
                expectation = self._expectation(plan, assignment)
                with self._coordination_lock:
                    current_fence = self._reuse_fences.check(
                        expectation=expectation,
                        invocation_key=invocation_key,
                        attempt_binding=AttemptRuntimeBinding.from_attempt(
                            current_attempt
                        ),
                        subject_artifact_sha256=contract_sha256(handoff),
                    )
                if not isinstance(current_fence, FenceDecision):
                    raise S4IntegrityError(
                        "durable handoff reuse returned a quarantine artifact"
                    )
                if current_fence.disposition is ControlDisposition.ALLOW:
                    reuse_reason = (
                        "durable qualified handoff reused after a fresh S3 fence"
                    )
                else:
                    handoff = None
                    reuse_reason = (
                        "durable handoff reuse blocked by current S3 fence: "
                        + ",".join(current_fence.reasons)
                    )
            return S4AttemptReport(
                assignment_id=assignment.assignment_id,
                attempt_id=result.request.attempt.attempt_id,
                outcome_state=result.outcome_state,
                receipt_id=None if prior.receipt is None else prior.receipt.receipt_id,
                handoff_id=None if handoff is None else handoff.handoff_id,
                reused_durable_result=True,
                reason=reuse_reason,
            )

        assert plan.context_manifest is not None
        try:
            focused = self._context_broker.materialize(
                assignment=assignment,
                manifest=plan.context_manifest,
            )
        except ValueError as exc:
            return S4AttemptReport(
                assignment_id=assignment.assignment_id,
                reason=f"focused context denied: {exc}",
            )

        created_at = utc_now()
        attempt_id = f"attempt:s4:{uuid4().hex}"
        session_id = f"session:s4:{uuid4().hex}"
        expectation = self._expectation(plan, assignment)
        proposed = self._attempt_snapshot(
            assignment=assignment,
            attempt_id=attempt_id,
            created_at=created_at,
            state=AgentLifecycleState.PROPOSED,
        )
        admitted = self._transition(proposed, AgentLifecycleState.ADMITTED)
        with self._coordination_lock:
            self._record_transition(
                lease=lease,
                attempt=proposed,
                invocation_key=invocation_key,
                suffix="proposed",
                reason="S4 root proposed one admitted read-only lane",
            )
            self._record_transition(
                lease=lease,
                attempt=admitted,
                invocation_key=invocation_key,
                suffix="admitted",
                reason="S4 root bound the lane to the current S3 plan",
            )
            before_creation = self._control_fences.check(
                phase=ControlFencePhase.BEFORE_CREATION,
                expectation=expectation,
                lease=lease,
                idempotency_key=f"{invocation_key}:fence-before-creation",
                attempt_id=attempt_id,
            )
        if not isinstance(before_creation, FenceDecision):
            raise S4IntegrityError("pre-creation fence returned a quarantine artifact")
        if before_creation.disposition is not ControlDisposition.ALLOW:
            return S4AttemptReport(
                assignment_id=assignment.assignment_id,
                attempt_id=attempt_id,
                reason=(
                    "S3 pre-creation fence denied: "
                    + ",".join(before_creation.reasons)
                ),
            )

        created = self._attempt_snapshot(
            assignment=assignment,
            attempt_id=attempt_id,
            created_at=created_at,
            state=AgentLifecycleState.CREATED,
            runtime_session_id=session_id,
            backend_id=self._backend.backend_id,
            profile_id=self._backend.profile_id,
        )
        with self._coordination_lock:
            self._record_transition(
                lease=lease,
                attempt=created,
                invocation_key=invocation_key,
                suffix="created",
                reason="S4 root provisioned bounded subprocess isolation",
            )
            before_execution = self._control_fences.check(
                phase=ControlFencePhase.BEFORE_EXECUTION,
                expectation=expectation,
                lease=lease,
                idempotency_key=f"{invocation_key}:fence-before-execution",
                attempt_id=attempt_id,
                attempt_binding=AttemptRuntimeBinding.from_attempt(created),
            )
        if not isinstance(before_execution, FenceDecision):
            raise S4IntegrityError("pre-execution fence returned a quarantine artifact")
        if before_execution.disposition is not ControlDisposition.ALLOW:
            return S4AttemptReport(
                assignment_id=assignment.assignment_id,
                attempt_id=attempt_id,
                reason=(
                    "S3 pre-execution fence denied: "
                    + ",".join(before_execution.reasons)
                ),
            )

        started_at = utc_now()
        if started_at >= assignment.budget.deadline_at:
            raise S4IntegrityError("S4 attempt deadline elapsed after execution fence")
        started = self._attempt_snapshot(
            assignment=assignment,
            attempt_id=attempt_id,
            created_at=created_at,
            state=AgentLifecycleState.STARTED,
            runtime_session_id=session_id,
            backend_id=self._backend.backend_id,
            profile_id=self._backend.profile_id,
            started_at=started_at,
        )
        with self._coordination_lock:
            self._record_transition(
                lease=lease,
                attempt=started,
                invocation_key=invocation_key,
                suffix="started",
                reason="S4 root started the interruptible driver boundary",
            )
        request = LiveBackendRequest(
            assignment=assignment,
            attempt=started,
            context=plan.context_manifest,
            focused_context_id=focused.focused_context_id,
            focused_context_sha256=contract_sha256(focused),
            requested_at=started_at,
        )
        self._live_journal.reserve(
            invocation_key=invocation_key,
            request=request,
        )
        return _PreparedAttempt(
            assignment=assignment,
            expectation=expectation,
            context=focused,
            request=request,
            invocation_key=invocation_key,
        )

    def _record_outcome_path(
        self,
        *,
        prepared: _PreparedAttempt,
        result: LiveBackendResult,
        lease: RootLeaseHandle,
    ) -> AgentExecutionAttempt:
        current = prepared.request.attempt
        if result.outcome_state in {
            AgentLifecycleState.CANCELLED,
            AgentLifecycleState.TERMINATED,
        }:
            current = self._transition(current, AgentLifecycleState.CANCEL_REQUESTED)
            self._record_transition(
                lease=lease,
                attempt=current,
                invocation_key=prepared.invocation_key,
                suffix="cancel-requested",
                reason="S4 root requested bounded worker cancellation",
            )
        current = self._transition(current, result.outcome_state)
        self._record_transition(
            lease=lease,
            attempt=current,
            invocation_key=prepared.invocation_key,
            suffix=f"outcome-{result.outcome_state.value.lower()}",
            reason=result.reason or "S4 root observed one worker result",
        )
        cleanup_lifecycle = AgentLifecycleState(result.cleanup_state.value)
        current = self._transition(current, cleanup_lifecycle)
        self._record_transition(
            lease=lease,
            attempt=current,
            invocation_key=prepared.invocation_key,
            suffix=f"cleanup-{cleanup_lifecycle.value.lower()}",
            reason="S4 root observed worker process and scratch cleanup",
        )
        return current

    def _receipt(
        self,
        *,
        prepared: _PreparedAttempt,
        result: LiveBackendResult,
        cleanup_attempt: AgentExecutionAttempt,
    ) -> AgentExecutionReceipt:
        events = self._coordination_store.events_for_attempt(
            prepared.request.attempt.attempt_id
        )
        if not events:
            raise S4IntegrityError("S4 execution receipt has no durable event prefix")
        return AgentExecutionReceipt(
            task_id=prepared.assignment.task_id,
            source_task_revision=prepared.assignment.source_task_revision,
            assignment_id=prepared.assignment.assignment_id,
            attempt_id=cleanup_attempt.attempt_id,
            attempt_integrity_id=cleanup_attempt.attempt_integrity_id,
            context_manifest_sha256=prepared.assignment.context_manifest_sha256,
            payload_id=result.payload.payload_id,
            payload_sha256=contract_sha256(result.payload),
            runtime_session_id=cleanup_attempt.runtime_session_id or "",
            backend_id=result.backend_id,
            profile_id=result.profile_id,
            root_coordination_epoch=cleanup_attempt.root_coordination_epoch,
            cancellation_epoch=cleanup_attempt.cancellation_epoch,
            budget=prepared.assignment.budget,
            usage=result.usage,
            started_at=prepared.request.attempt.started_at or prepared.request.requested_at,
            outcome_at=result.outcome_at,
            deadline_at=prepared.assignment.budget.deadline_at,
            cancel_requested_at=result.cancel_requested_at,
            cleanup_at=result.cleanup_at,
            outcome_state=result.outcome_state,
            cleanup_state=result.cleanup_state,
            late_result=(
                result.outcome_state is AgentLifecycleState.RESULT_RECEIVED
                and result.outcome_at > prepared.assignment.budget.deadline_at
            ),
            event_refs=tuple(sorted(item.event_ref for item in events)),
        )

    def _complete_attempt(
        self,
        *,
        prepared: _PreparedAttempt,
        result: LiveBackendResult,
        lease: RootLeaseHandle,
    ) -> _CompletedAttempt:
        with self._coordination_lock:
            result_fence = self._control_fences.check(
                phase=ControlFencePhase.RESULT_ADMISSION,
                expectation=prepared.expectation,
                lease=lease,
                idempotency_key=f"{prepared.invocation_key}:fence-result",
                attempt_id=prepared.request.attempt.attempt_id,
                attempt_binding=AttemptRuntimeBinding.from_attempt(
                    prepared.request.attempt
                ),
                result=result,
            )
            result_decision = (
                result_fence.decision
                if isinstance(result_fence, ResultQuarantineRecord)
                else result_fence
            )
            cleanup_attempt = self._record_outcome_path(
                prepared=prepared,
                result=result,
                lease=lease,
            )
        receipt = self._receipt(
            prepared=prepared,
            result=result,
            cleanup_attempt=cleanup_attempt,
        )
        handoff: DistilledHandoff | None = None
        qualification_reason = result.reason or "worker result was not eligible"
        if (
            result_decision.disposition is ControlDisposition.ALLOW
            and result.outcome_state is AgentLifecycleState.RESULT_RECEIVED
            and result.cleanup_state is CleanupState.CLEANUP_COMPLETE
            and not receipt.late_result
        ):
            try:
                candidate = self._qualifier.qualify(
                    assignment=prepared.assignment,
                    cleanup_attempt=cleanup_attempt,
                    result=result,
                    receipt=receipt,
                    qualified_at=utc_now(),
                )
                if candidate is not None:
                    validate_c011_contract_chain(
                        context=prepared.request.context,
                        assignment=prepared.assignment,
                        attempt=cleanup_attempt,
                        payload=result.payload,
                        receipt=receipt,
                        claims=candidate.qualified_claims,
                        handoff=candidate,
                    )
                    with self._coordination_lock:
                        pre_adoption = self._control_fences.check(
                            phase=ControlFencePhase.PRE_ADOPTION,
                            expectation=prepared.expectation,
                            lease=lease,
                            idempotency_key=(
                                f"{prepared.invocation_key}:fence-pre-adoption"
                            ),
                            attempt_id=cleanup_attempt.attempt_id,
                            attempt_binding=AttemptRuntimeBinding.from_attempt(
                                cleanup_attempt
                            ),
                            subject_artifact_sha256=contract_sha256(candidate),
                        )
                    if not isinstance(pre_adoption, FenceDecision):
                        raise S4IntegrityError(
                            "pre-adoption fence returned a quarantine artifact"
                        )
                    if pre_adoption.disposition is ControlDisposition.ALLOW:
                        handoff = candidate
                        qualification_reason = "qualified handoff admitted to root context"
                    else:
                        qualification_reason = (
                            "S3 pre-adoption fence blocked handoff: "
                            + ",".join(pre_adoption.reasons)
                        )
            except Exception as exc:
                raise S4IntegrityError(
                    "root handoff qualification or provenance validation failed"
                ) from exc

        projection = self._live_journal.complete(
            invocation_key=prepared.invocation_key,
            result=result,
            receipt=receipt,
            cleanup_attempt=cleanup_attempt,
            handoff=handoff,
        )
        if projection.receipt != receipt:
            raise S4IntegrityError("S4 durable receipt readback changed")

        with self._coordination_lock:
            if handoff is not None:
                reconciled = self._transition(
                    cleanup_attempt,
                    AgentLifecycleState.RECONCILED,
                )
                self._record_transition(
                    lease=lease,
                    attempt=reconciled,
                    invocation_key=prepared.invocation_key,
                    suffix="reconciled",
                    reason="S4 qualified handoff is eligible for root consideration",
                )
            else:
                closed = self._transition(cleanup_attempt, AgentLifecycleState.CLOSED)
                self._record_transition(
                    lease=lease,
                    attempt=closed,
                    invocation_key=prepared.invocation_key,
                    suffix="closed",
                    reason="S4 attempt closed without a root-context handoff",
                )
        return _CompletedAttempt(
            report=S4AttemptReport(
                assignment_id=prepared.assignment.assignment_id,
                attempt_id=prepared.request.attempt.attempt_id,
                outcome_state=result.outcome_state,
                receipt_id=receipt.receipt_id,
                handoff_id=None if handoff is None else handoff.handoff_id,
                reason=qualification_reason,
            ),
            handoff=handoff,
        )

    @staticmethod
    def _consideration_receipt(
        *,
        handoff: DistilledHandoff,
        plan: AdmittedPlan,
        root_owner_ref: str,
        generated_at: datetime,
    ) -> AdoptionReceipt:
        decisions = tuple(
            AdoptionDecision(
                claim_record_id=claim.claim_record_id,
                disposition=AdoptionDisposition.VERIFY_REQUIRED,
                reason=(
                    "qualified worker claim is root context only; Main Luna retains "
                    "all state mutation and completion judgment"
                ),
                evidence_refs=tuple(
                    item.evidence_ref for item in claim.evidence_lineage
                ),
            )
            for claim in handoff.qualified_claims
        )
        return AdoptionReceipt(
            task_id=handoff.task_id,
            root_coordination_epoch=plan.seal.root_coordination_epoch,
            handoff_id=handoff.handoff_id,
            handoff_sha256=contract_sha256(handoff),
            considered_claim_ids=tuple(
                item.claim_record_id for item in handoff.qualified_claims
            ),
            decisions=decisions,
            current_root_state_revision=handoff.source_task_revision,
            authoritative_evidence_basis=(
                handoff.receipt_id,
                f"c011-plan-seal:{plan.plan_seal_sha256}",
            ),
            root_owner_ref=root_owner_ref,
            adopted_at=generated_at,
        )

    @staticmethod
    def _inactive(
        *,
        status: S4IntegrationStatus,
        state: TaskState,
        reason: str,
    ) -> S4RootIntegration:
        return S4RootIntegration(
            status=status,
            task_id=state.task_id,
            source_task_revision=state.revision,
            reason_codes=(reason,),
            generated_at=utc_now(),
        )

    def collect_for_root(
        self,
        *,
        state: TaskState,
        root_owner_ref: str,
        cancellation_probe: Callable[[], bool],
    ) -> S4RootIntegration:
        """Run one current plan; return no raw output and never mutate TaskState."""

        if not self._policy.enabled:
            return self._inactive(
                status=S4IntegrationStatus.DISABLED,
                state=state,
                reason="S4_FEATURE_DISABLED",
            )
        if self._policy.kill_switch_engaged or self._kill_switch.engaged:
            return self._inactive(
                status=S4IntegrationStatus.KILL_SWITCHED,
                state=state,
                reason="S4_KILL_SWITCH_ENGAGED",
            )
        if not self._backend.safety_capabilities.accepted:
            return self._inactive(
                status=S4IntegrationStatus.DENIED,
                state=state,
                reason="S4_BACKEND_SAFETY_CAPABILITIES_INCOMPLETE",
            )
        before_state_sha256 = authoritative_model_sha256(state)
        try:
            authorization = self._plan_provider.authorization_for(state)
        except Exception as exc:
            raise S4IntegrityError("S4 current admission provider failed") from exc
        decision = authorization.decision
        if decision.disposition is not AdmissionDisposition.ADMIT or decision.plan is None:
            denial_reasons = tuple(item.value for item in decision.reason_codes)
            return S4RootIntegration(
                status=S4IntegrationStatus.DENIED,
                task_id=state.task_id,
                source_task_revision=state.revision,
                reason_codes=denial_reasons,
                generated_at=utc_now(),
            )
        plan = decision.plan
        if (
            plan.seal.task_id != state.task_id
            or plan.seal.source_task_revision != state.revision
            or plan.seal.task_state_sha256 != before_state_sha256
            or authorization.lease.record.task_id != state.task_id
            or authorization.lease.record.epoch != plan.seal.root_coordination_epoch
            or authorization.lease.record.root_owner_ref != root_owner_ref
        ):
            raise S4IntegrityError("S4 admission is not bound to current root state")
        if plan.worker_count == 0:
            return S4RootIntegration(
                status=S4IntegrationStatus.NO_DELEGATION,
                task_id=state.task_id,
                source_task_revision=state.revision,
                plan_seal_sha256=plan.plan_seal_sha256,
                reason_codes=("NO_INDEPENDENT_VALUE",),
                generated_at=utc_now(),
            )
        if (
            plan.worker_count > self._policy.max_workers
            or plan.budget.max_concurrent_workers
            > self._policy.max_concurrent_workers
        ):
            return S4RootIntegration(
                status=S4IntegrationStatus.DENIED,
                task_id=state.task_id,
                source_task_revision=state.revision,
                plan_seal_sha256=plan.plan_seal_sha256,
                reason_codes=("S4_POLICY_WORKER_CEILING_EXCEEDED",),
                generated_at=utc_now(),
            )

        prepared: list[_PreparedAttempt] = []
        reports: list[S4AttemptReport] = []
        durable_handoffs: list[DistilledHandoff] = []
        for assignment in plan.assignments:
            item = self._prepare_attempt(
                plan=plan,
                assignment=assignment,
                lease=authorization.lease,
            )
            if isinstance(item, S4AttemptReport):
                reports.append(item)
                if item.reused_durable_result and item.handoff_id is not None:
                    prior = self._live_journal.load(
                        self._invocation_key(plan, assignment)
                    )
                    if prior is None or prior.record.handoff is None:
                        raise S4IntegrityError("S4 durable handoff readback is missing")
                    durable_handoffs.append(prior.record.handoff)
            else:
                prepared.append(item)

        def cancelled() -> bool:
            return (
                self._kill_switch.engaged
                or cancellation_probe()
            )

        completed: list[_CompletedAttempt] = []
        if prepared:
            workers = min(
                len(prepared),
                self._policy.max_concurrent_workers,
                plan.budget.max_concurrent_workers,
            )
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="luna-c011-s4-driver",
            ) as executor:
                future_by_assignment = {
                    item.assignment.assignment_id: executor.submit(
                        self._backend.execute,
                        request=item.request,
                        context=item.context,
                        policy=self._policy,
                        cancellation_probe=cancelled,
                    )
                    for item in prepared
                }
                result_by_assignment: dict[str, LiveBackendResult] = {}
                for assignment_id, future in future_by_assignment.items():
                    try:
                        result_by_assignment[assignment_id] = future.result()
                    except Exception as exc:
                        raise S4IntegrityError(
                            "certified S4 backend escaped its bounded result contract"
                        ) from exc
            for item in prepared:
                completed.append(
                    self._complete_attempt(
                        prepared=item,
                        result=result_by_assignment[item.assignment.assignment_id],
                        lease=authorization.lease,
                    )
                )

        reports.extend(item.report for item in completed)
        handoffs = tuple(
            sorted(
                (*durable_handoffs, *(item.handoff for item in completed if item.handoff)),
                key=lambda item: item.assignment_id,
            )
        )
        after_state_sha256 = authoritative_model_sha256(state)
        if after_state_sha256 != before_state_sha256:
            raise S4IntegrityError("S4 worker path mutated authoritative TaskState")
        generated_at = utc_now()
        receipts = tuple(
            self._consideration_receipt(
                handoff=handoff,
                plan=plan,
                root_owner_ref=root_owner_ref,
                generated_at=generated_at,
            )
            for handoff in handoffs
        )
        completion_reasons = {"S4_ATTEMPTS_COMPLETE"}
        if any(item.in_doubt_no_replay for item in reports):
            completion_reasons.add("S4_IN_DOUBT_NO_REPLAY")
        if any(item.handoff_id is None for item in reports):
            completion_reasons.add("S4_RESULT_NOT_ADOPTED")
        return S4RootIntegration(
            status=S4IntegrationStatus.COMPLETE,
            task_id=state.task_id,
            source_task_revision=state.revision,
            plan_seal_sha256=plan.plan_seal_sha256,
            handoffs=handoffs,
            consideration_receipts=receipts,
            attempts=tuple(reports),
            reason_codes=tuple(sorted(completion_reasons)),
            generated_at=generated_at,
        )


__all__ = [
    "LiveExecutionAuthorization",
    "LiveHandoffReuseFenceController",
    "LivePlanProvider",
    "ParallelCognitionRuntimeService",
    "RootHandoffQualifier",
    "RuntimeKillSwitch",
    "S4AttemptReport",
    "S4IntegrityError",
    "S4RootIntegration",
]
