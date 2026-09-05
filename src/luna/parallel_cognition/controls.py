"""Fail-closed S3 control fences and durable quarantine contracts.

This module performs no worker, model, tool, network, process, or Luna-runtime
execution.  A caller may supply an expectation produced by admission, but the current
snapshot must come from the runtime-owned provider at every fence.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import ClassVar, Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import require_utc
from luna.parallel_cognition.events import FakeBackendResult, RootLeaseHandle
from luna.parallel_cognition.live import LiveBackendResult
from luna.parallel_cognition.models import (
    AgentExecutionAttempt,
    AgentLifecycleState,
    C011ContractModel,
    Sha256,
    contract_sha256,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class _S3ContentAddressedContract(C011ContractModel):
    _identity_field: ClassVar[str]
    _identity_prefix: ClassVar[str]

    @model_validator(mode="after")
    def validate_content_identity(self) -> Self:
        payload = self.model_dump(mode="json", exclude={self._identity_field})
        basis = {
            "contract_type": f"{type(self).__module__}.{type(self).__qualname__}",
            "schema_version": self.schema_version,
            "payload": payload,
        }
        expected = (
            self._identity_prefix + sha256(_canonical_json(basis).encode("utf-8")).hexdigest()
        )
        supplied = getattr(self, self._identity_field)
        if not supplied:
            object.__setattr__(self, self._identity_field, expected)
        elif supplied != expected:
            raise ValueError(f"{self._identity_field} does not match canonical contract content")
        return self


class ControlFencePhase(StrEnum):
    """The four RFC-C011 current-state recheck boundaries."""

    BEFORE_CREATION = "BEFORE_CREATION"
    BEFORE_EXECUTION = "BEFORE_EXECUTION"
    RESULT_ADMISSION = "RESULT_ADMISSION"
    PRE_ADOPTION = "PRE_ADOPTION"


class ControlDisposition(StrEnum):
    """Fail-closed result of one runtime-owned fence evaluation."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    QUARANTINE = "QUARANTINE"
    VERIFY = "VERIFY"


class ControlExpectation(C011ContractModel):
    """Admission-sealed values that every later fence must revalidate exactly."""

    task_id: UUID
    source_task_revision: int = Field(ge=0)
    task_state_sha256: Sha256
    autonomy_policy_sha256: Sha256
    tool_policy_sha256: Sha256
    context_manifest_sha256: Sha256
    plan_seal_sha256: Sha256
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    root_coordination_epoch: int = Field(ge=1)
    cancellation_generation: int = Field(ge=0)
    deadline_at: datetime

    @field_validator("deadline_at")
    @classmethod
    def validate_deadline(cls, value: datetime) -> datetime:
        return require_utc(value)


class AttemptRuntimeBinding(C011ContractModel):
    """Exact durable attempt-head identity used by execution and result fences."""

    attempt_id: str = Field(pattern=r"^attempt:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    attempt_integrity_id: str = Field(pattern=r"^c011-attempt-state:sha256:[0-9a-f]{64}$")
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    context_manifest_sha256: Sha256
    root_coordination_epoch: int = Field(ge=1)
    cancellation_epoch: int = Field(ge=0)
    runtime_session_id: str | None = Field(default=None, max_length=500)
    backend_id: str | None = Field(default=None, max_length=500)
    profile_id: str | None = Field(default=None, max_length=500)
    lifecycle_state: AgentLifecycleState

    @classmethod
    def from_attempt(cls, attempt: AgentExecutionAttempt) -> AttemptRuntimeBinding:
        """Revalidate and reduce one attempt snapshot to its exact fence identity."""

        current = AgentExecutionAttempt.model_validate(attempt.model_dump(mode="json"))
        return cls(
            attempt_id=current.attempt_id,
            attempt_integrity_id=current.attempt_integrity_id,
            assignment_id=current.assignment_id,
            context_manifest_sha256=current.context_manifest_sha256,
            root_coordination_epoch=current.root_coordination_epoch,
            cancellation_epoch=current.cancellation_epoch,
            runtime_session_id=current.runtime_session_id,
            backend_id=current.backend_id,
            profile_id=current.profile_id,
            lifecycle_state=current.lifecycle_state,
        )


class CurrentControlSnapshot(C011ContractModel):
    """One provider-authored view of the current authority and liveness basis."""

    task_id: UUID
    source_task_revision: int = Field(ge=0)
    task_state_sha256: Sha256
    autonomy_policy_sha256: Sha256
    tool_policy_sha256: Sha256
    context_manifest_sha256: Sha256
    plan_seal_sha256: Sha256
    root_coordination_epoch: int = Field(ge=1)
    cancellation_generation: int = Field(ge=0)
    cancellation_requested: bool
    root_lease_active: bool
    authority_ceiling_intact: bool
    sources_current: bool
    attempt_binding: AttemptRuntimeBinding | None = None
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, value: datetime) -> datetime:
        return require_utc(value)


class CurrentControlProvider(Protocol):
    """Runtime-owned current-state source; payloads and workers cannot implement it."""

    def current_control_snapshot(self, task_id: UUID, attempt_id: str) -> CurrentControlSnapshot:
        """Return a newly captured authoritative snapshot for ``task_id``."""


class ControlClock(Protocol):
    """Trusted clock boundary used instead of worker or caller timestamps."""

    def now(self) -> datetime:
        """Return the current timezone-aware runtime time."""


class ControlRecorder(Protocol):
    """Durable recorder boundary implemented by the coordination store."""

    def record_control_decision(
        self,
        lease: RootLeaseHandle,
        decision: FenceDecision,
        *,
        idempotency_key: str,
    ) -> FenceDecision:
        """Persist one exact fence decision."""

    def record_result_quarantine(
        self,
        lease: RootLeaseHandle,
        quarantine: ResultQuarantineRecord,
        *,
        idempotency_key: str,
    ) -> ResultQuarantineRecord:
        """Persist a result quarantine and its fence decision atomically."""

    def record_control_denial_and_close(
        self,
        lease: RootLeaseHandle,
        decision: FenceDecision,
        *,
        idempotency_key: str,
    ) -> FenceDecision:
        """Persist a denied fence and close its unstarted attempt atomically."""


class FenceDecision(_S3ContentAddressedContract):
    """Content-addressed evidence for one control-fence evaluation."""

    _identity_field = "decision_id"
    _identity_prefix = "c011-fence-decision:sha256:"

    decision_id: str = ""
    phase: ControlFencePhase
    expectation: ControlExpectation
    current: CurrentControlSnapshot
    attempt_id: str = Field(pattern=r"^attempt:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    attempt_binding: AttemptRuntimeBinding | None = None
    subject_artifact_sha256: Sha256 | None = None
    result_sha256: Sha256 | None = None
    disposition: ControlDisposition
    reasons: tuple[str, ...] = Field(min_length=1, max_length=32)
    checked_at: datetime
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator("checked_at")
    @classmethod
    def validate_checked_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("reasons")
    @classmethod
    def normalize_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in values)
        if any(not item for item in cleaned):
            raise ValueError("fence reasons cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("fence reasons must be unique")
        return tuple(sorted(cleaned))

    @model_validator(mode="after")
    def validate_decision_shape(self) -> Self:
        if self.attempt_binding is not None and (
            self.attempt_binding.attempt_id != self.attempt_id
            or self.attempt_binding.assignment_id != self.expectation.assignment_id
        ):
            raise ValueError("fence attempt subject does not match its expectation")
        if self.phase is ControlFencePhase.BEFORE_CREATION:
            if self.attempt_binding is not None:
                raise ValueError("pre-creation fence cannot bind an existing attempt")
        elif self.attempt_binding is None:
            raise ValueError("post-creation fence requires an exact attempt binding")
        if self.phase is ControlFencePhase.RESULT_ADMISSION:
            if self.result_sha256 is None:
                raise ValueError("result-admission fence requires an exact result binding")
        elif self.result_sha256 is not None:
            raise ValueError("only result-admission fence may bind a result")
        if self.phase is ControlFencePhase.PRE_ADOPTION:
            if self.subject_artifact_sha256 is None:
                raise ValueError("pre-adoption fence requires an exact handoff binding")
        elif self.subject_artifact_sha256 is not None:
            raise ValueError("only pre-adoption fence may bind a handoff artifact")
        if self.disposition is ControlDisposition.ALLOW and self.reasons != (
            "CURRENT_STATE_MATCH",
        ):
            raise ValueError("allowed fence requires the exact current-state reason")
        if self.disposition is ControlDisposition.ALLOW and (
            self.current.task_id != self.expectation.task_id
            or self.current.captured_at > self.checked_at
        ):
            raise ValueError("allowed fence requires a current same-task snapshot")
        if self.disposition is not ControlDisposition.ALLOW and self.reasons == (
            "CURRENT_STATE_MATCH",
        ):
            raise ValueError("blocked fence requires a material mismatch reason")
        return self


class ResultQuarantineRecord(_S3ContentAddressedContract):
    """Durably retain an ineligible raw result without admitting its claims."""

    _identity_field = "quarantine_id"
    _identity_prefix = "c011-result-quarantine:sha256:"

    quarantine_id: str = ""
    decision: FenceDecision
    result: FakeBackendResult | LiveBackendResult
    received_at: datetime
    quarantined: Literal[True] = True
    eligible_for_reconciliation: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False

    @field_validator("received_at")
    @classmethod
    def validate_received_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_quarantine_binding(self) -> Self:
        if self.decision.phase is not ControlFencePhase.RESULT_ADMISSION:
            raise ValueError("result quarantine requires a result-admission decision")
        if self.decision.disposition not in {
            ControlDisposition.QUARANTINE,
            ControlDisposition.VERIFY,
        }:
            raise ValueError("only an ineligible result may enter quarantine")
        if self.decision.result_sha256 != contract_sha256(self.result):
            raise ValueError("quarantine decision does not bind the raw result")
        if self.received_at != self.decision.checked_at:
            raise ValueError("quarantined result does not match its fence decision")
        return self


def evaluate_control_fence(
    *,
    phase: ControlFencePhase,
    expectation: ControlExpectation,
    current: CurrentControlSnapshot,
    checked_at: datetime,
    attempt_id: str,
    attempt_binding: AttemptRuntimeBinding | None = None,
    subject_artifact_sha256: Sha256 | None = None,
    result: FakeBackendResult | LiveBackendResult | None = None,
) -> FenceDecision:
    """Compare an admission seal with current authoritative state, never worker claims."""

    observed_at = require_utc(checked_at)
    if phase is not ControlFencePhase.BEFORE_CREATION and attempt_binding is None:
        raise ValueError("post-creation evaluation requires an exact attempt binding")
    if phase is ControlFencePhase.RESULT_ADMISSION and result is None:
        raise ValueError("result-admission evaluation requires a raw result")
    if phase is ControlFencePhase.PRE_ADOPTION and subject_artifact_sha256 is None:
        raise ValueError("pre-adoption evaluation requires an exact handoff binding")
    reasons: list[str] = []
    exact_pairs = (
        ("TASK", current.task_id, expectation.task_id),
        ("TASK_REVISION", current.source_task_revision, expectation.source_task_revision),
        ("TASK_STATE", current.task_state_sha256, expectation.task_state_sha256),
        ("AUTONOMY_POLICY", current.autonomy_policy_sha256, expectation.autonomy_policy_sha256),
        ("TOOL_POLICY", current.tool_policy_sha256, expectation.tool_policy_sha256),
        ("CONTEXT", current.context_manifest_sha256, expectation.context_manifest_sha256),
        ("PLAN_SEAL", current.plan_seal_sha256, expectation.plan_seal_sha256),
        ("ROOT_EPOCH", current.root_coordination_epoch, expectation.root_coordination_epoch),
        (
            "CANCELLATION_GENERATION",
            current.cancellation_generation,
            expectation.cancellation_generation,
        ),
    )
    reasons.extend(
        f"{label}_MISMATCH" for label, actual, expected in exact_pairs if actual != expected
    )
    if current.cancellation_requested:
        reasons.append("CANCELLATION_REQUESTED")
    if not current.root_lease_active:
        reasons.append("ROOT_LEASE_INACTIVE")
    if not current.authority_ceiling_intact:
        reasons.append("AUTHORITY_CEILING_CHANGED")
    if not current.sources_current:
        reasons.append("SOURCE_NOT_CURRENT")
    if observed_at >= expectation.deadline_at:
        reasons.append("DEADLINE_REACHED")
    if current.captured_at > observed_at:
        reasons.append("SNAPSHOT_FROM_FUTURE")

    if phase is ControlFencePhase.BEFORE_CREATION:
        if attempt_binding is not None:
            raise ValueError("pre-creation evaluation cannot bind an existing attempt")
        if current.attempt_binding is not None:
            reasons.append("ATTEMPT_ALREADY_EXISTS")
    else:
        assert attempt_binding is not None
        if attempt_binding.attempt_id != attempt_id:
            reasons.append("ATTEMPT_ID_MISMATCH")
        if attempt_binding.assignment_id != expectation.assignment_id:
            reasons.append("ATTEMPT_ASSIGNMENT_MISMATCH")
        if attempt_binding.context_manifest_sha256 != expectation.context_manifest_sha256:
            reasons.append("ATTEMPT_CONTEXT_MISMATCH")
        if attempt_binding.root_coordination_epoch != expectation.root_coordination_epoch:
            reasons.append("ATTEMPT_ROOT_EPOCH_MISMATCH")
        if attempt_binding.cancellation_epoch != expectation.cancellation_generation:
            reasons.append("ATTEMPT_CANCELLATION_GENERATION_MISMATCH")
        if current.attempt_binding != attempt_binding:
            reasons.append("CURRENT_ATTEMPT_BINDING_MISMATCH")

    if phase is ControlFencePhase.BEFORE_EXECUTION and (
        attempt_binding is None
        or attempt_binding.lifecycle_state is not AgentLifecycleState.CREATED
    ):
        reasons.append("ATTEMPT_NOT_CREATED")
    if phase is ControlFencePhase.PRE_ADOPTION:
        if attempt_binding is None or attempt_binding.lifecycle_state not in {
            AgentLifecycleState.CLEANUP_COMPLETE,
            AgentLifecycleState.RECONCILED,
        }:
            reasons.append("ATTEMPT_NOT_READY_FOR_ROOT_CONSIDERATION")
    elif subject_artifact_sha256 is not None:
        raise ValueError("handoff binding is valid only at the pre-adoption fence")

    result_sha256: str | None = None
    if phase is ControlFencePhase.RESULT_ADMISSION:
        assert result is not None
        assert attempt_binding is not None
        result_sha256 = contract_sha256(result)
        request = result.request
        result_binding = AttemptRuntimeBinding.from_attempt(request.attempt)
        if request.assignment.task_id != expectation.task_id:
            reasons.append("RESULT_TASK_MISMATCH")
        if request.assignment.assignment_id != expectation.assignment_id:
            reasons.append("RESULT_ASSIGNMENT_MISMATCH")
        if request.attempt.attempt_id != attempt_id:
            reasons.append("RESULT_ATTEMPT_MISMATCH")
        if result_binding != attempt_binding:
            reasons.append("RESULT_RUNTIME_BINDING_MISMATCH")
        if result_binding.lifecycle_state is not AgentLifecycleState.STARTED:
            reasons.append("RESULT_ATTEMPT_NOT_STARTED")
        if request.attempt.root_coordination_epoch != expectation.root_coordination_epoch:
            reasons.append("RESULT_ROOT_EPOCH_MISMATCH")
        if request.attempt.cancellation_epoch != expectation.cancellation_generation:
            reasons.append("RESULT_CANCELLATION_GENERATION_MISMATCH")
        if request.attempt.context_manifest_sha256 != expectation.context_manifest_sha256:
            reasons.append("RESULT_CONTEXT_MISMATCH")
        if result.outcome_at >= expectation.deadline_at:
            reasons.append("RESULT_DECLARED_LATE")
        if result.outcome_at > observed_at or result.cleanup_at > observed_at:
            reasons.append("RESULT_TIMESTAMP_FROM_FUTURE")
    elif result is not None:
        raise ValueError("raw result is valid only at the result-admission fence")

    unique_reasons = tuple(sorted(set(reasons)))
    if not unique_reasons:
        disposition = ControlDisposition.ALLOW
        unique_reasons = ("CURRENT_STATE_MATCH",)
    elif phase is ControlFencePhase.RESULT_ADMISSION:
        disposition = ControlDisposition.QUARANTINE
    elif phase is ControlFencePhase.PRE_ADOPTION:
        disposition = ControlDisposition.VERIFY
    else:
        disposition = ControlDisposition.DENY
    return FenceDecision(
        phase=phase,
        expectation=expectation,
        current=current,
        attempt_id=attempt_id,
        attempt_binding=attempt_binding,
        subject_artifact_sha256=subject_artifact_sha256,
        result_sha256=result_sha256,
        disposition=disposition,
        reasons=unique_reasons,
        checked_at=observed_at,
    )


class ControlFenceController:
    """Fetch current state and durably record every fence before returning."""

    def __init__(
        self,
        *,
        provider: CurrentControlProvider,
        recorder: ControlRecorder,
        clock: ControlClock,
    ) -> None:
        self._provider = provider
        self._recorder = recorder
        self._clock = clock

    def check(
        self,
        *,
        phase: ControlFencePhase,
        expectation: ControlExpectation,
        lease: RootLeaseHandle,
        idempotency_key: str,
        attempt_id: str,
        attempt_binding: AttemptRuntimeBinding | None = None,
        subject_artifact_sha256: Sha256 | None = None,
        result: FakeBackendResult | LiveBackendResult | None = None,
    ) -> FenceDecision | ResultQuarantineRecord:
        """Rebuild current state, evaluate once, and persist before releasing it."""

        current = self._provider.current_control_snapshot(expectation.task_id, attempt_id)
        checked_at = require_utc(self._clock.now())
        decision = evaluate_control_fence(
            phase=phase,
            expectation=expectation,
            current=current,
            checked_at=checked_at,
            attempt_id=attempt_id,
            attempt_binding=attempt_binding,
            subject_artifact_sha256=subject_artifact_sha256,
            result=result,
        )
        if (
            phase is ControlFencePhase.RESULT_ADMISSION
            and result is not None
            and decision.disposition in {ControlDisposition.QUARANTINE, ControlDisposition.VERIFY}
        ):
            quarantine = ResultQuarantineRecord(
                decision=decision,
                result=result,
                received_at=checked_at,
            )
            return self._recorder.record_result_quarantine(
                lease,
                quarantine,
                idempotency_key=idempotency_key,
            )
        if decision.disposition is ControlDisposition.DENY:
            return self._recorder.record_control_denial_and_close(
                lease,
                decision,
                idempotency_key=idempotency_key,
            )
        return self._recorder.record_control_decision(
            lease,
            decision,
            idempotency_key=idempotency_key,
        )


__all__ = [
    "AttemptRuntimeBinding",
    "ControlClock",
    "ControlDisposition",
    "ControlExpectation",
    "ControlFenceController",
    "ControlFencePhase",
    "ControlRecorder",
    "CurrentControlProvider",
    "CurrentControlSnapshot",
    "FenceDecision",
    "ResultQuarantineRecord",
    "evaluate_control_fence",
]
