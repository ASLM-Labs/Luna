"""Audited completion gate; model output cannot bypass this boundary."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from luna.audit.models import AuditEventKind
from luna.audit.session import AuditSession
from luna.contracts.base import stable_payload
from luna.contracts.enums import TaskPhase
from luna.contracts.evidence import Evidence
from luna.contracts.state import TaskState
from luna.contracts.task import TaskContract
from luna.verification.models import (
    CompletionDecision,
    CompletionGateResult,
    VerificationPolicy,
)
from luna.verification.verifier import DeterministicVerifier


class CompletionGateError(RuntimeError):
    """Raised when a completion decision cannot be safely audited."""


class CompletionGate:
    """Produce and persist one deterministic completion decision."""

    def __init__(
        self,
        audit: AuditSession,
        verifier: DeterministicVerifier | None = None,
    ) -> None:
        self._audit = audit
        self._verifier = verifier or DeterministicVerifier()

    def evaluate(
        self,
        *,
        contract: TaskContract,
        evidence: Iterable[Evidence],
        policy: VerificationPolicy,
        trace_id: UUID,
    ) -> CompletionGateResult:
        integrity = self._audit.verify_integrity()
        if not integrity.valid:
            raise CompletionGateError(
                f"completion gate requires valid audit integrity: "
                f"{integrity.first_error}"
            )

        report = self._verifier.verify(
            contract=contract,
            evidence=evidence,
            policy=policy,
        )
        verification_event = self._audit.ledger.append(
            kind=AuditEventKind.VERIFICATION_REPORT,
            task_id=contract.task_id,
            trace_id=trace_id,
            subject_id=str(report.report_id),
            payload=stable_payload(report),
        )
        decision = CompletionDecision(
            task_id=contract.task_id,
            report_id=report.report_id,
            status=report.completion_status,
            reasons=report.rationale,
        )
        completion_event = self._audit.ledger.append(
            kind=AuditEventKind.COMPLETION_DECISION,
            task_id=contract.task_id,
            trace_id=trace_id,
            subject_id=str(decision.decision_id),
            payload=stable_payload(decision),
        )
        return CompletionGateResult(
            report=report,
            decision=decision,
            verification_event_id=verification_event.event_id,
            completion_event_id=completion_event.event_id,
        )

    @staticmethod
    def apply_to_state(
        *,
        state: TaskState,
        result: CompletionGateResult,
    ) -> TaskState:
        """Move VERIFYING to REPORTING with the gate-owned status."""
        if state.phase is not TaskPhase.VERIFYING:
            raise CompletionGateError(
                "completion decision can only be applied from VERIFYING"
            )
        if state.task_id != result.decision.task_id:
            raise CompletionGateError("task state and completion decision do not match")
        return state.transition_to(
            TaskPhase.REPORTING,
            completion_status=result.decision.status,
        )
