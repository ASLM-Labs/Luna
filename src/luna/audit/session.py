"""Audit session integrating output capture, tool traces, and evidence."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from luna.audit.evidence import EvidenceLedger
from luna.audit.ledger import AppendOnlyAuditLedger
from luna.audit.models import (
    AuditEvent,
    AuditEventKind,
    AuditVerification,
    CapturedOutput,
)
from luna.audit.redaction import SecretRedactor
from luna.audit.store import ContentAddressedLogStore
from luna.contracts.base import stable_payload
from luna.contracts.evidence import Evidence
from luna.contracts.task import TaskContract
from luna.tools.models import DispatchOutcome, ToolRequest


class AuditSession:
    """One persistent append-only audit boundary for a runtime root."""

    def __init__(
        self,
        root: str | Path,
        *,
        explicit_secrets: tuple[str, ...] = (),
    ) -> None:
        self.root = Path(root).resolve()
        redactor = SecretRedactor(explicit_secrets)
        self.ledger = AppendOnlyAuditLedger(self.root, redactor)
        self.logs = ContentAddressedLogStore(self.root, redactor)
        self.evidence = EvidenceLedger(self.ledger)

    def capture_output(self, *, stream_name: str, text: str) -> CapturedOutput:
        return self.logs.capture(stream_name=stream_name, text=text)

    def record_task_contract(
        self,
        *,
        contract: TaskContract,
        trace_id: UUID,
    ) -> AuditEvent:
        return self.ledger.append(
            kind=AuditEventKind.TASK_CONTRACT,
            task_id=contract.task_id,
            trace_id=trace_id,
            subject_id=str(contract.task_id),
            payload=stable_payload(contract),
        )

    def record_tool_request(self, request: ToolRequest) -> AuditEvent:
        return self.ledger.append(
            kind=AuditEventKind.TOOL_REQUEST,
            task_id=request.task_id,
            trace_id=request.trace_id,
            subject_id=str(request.request_id),
            payload=stable_payload(request),
        )

    def record_dispatch_outcome(self, outcome: DispatchOutcome) -> tuple[AuditEvent, ...]:
        request = outcome.request
        return (
            self.ledger.append(
                kind=AuditEventKind.TOOL_RESULT,
                task_id=request.task_id,
                trace_id=request.trace_id,
                subject_id=str(outcome.result.result_id),
                payload=stable_payload(outcome.result),
            ),
            self.ledger.append(
                kind=AuditEventKind.TOOL_EVENT,
                task_id=request.task_id,
                trace_id=request.trace_id,
                subject_id=str(outcome.event.event_id),
                payload=stable_payload(outcome.event),
            ),
            self.ledger.append(
                kind=AuditEventKind.OBSERVATION,
                task_id=request.task_id,
                trace_id=request.trace_id,
                subject_id=str(outcome.observation.observation_id),
                payload=stable_payload(outcome.observation),
            ),
        )

    def record_evidence(
        self,
        *,
        evidence: Evidence,
        trace_id: UUID,
        observation_id: UUID | None = None,
    ) -> AuditEvent:
        return self.evidence.record(
            evidence=evidence,
            trace_id=trace_id,
            observation_id=observation_id,
        )

    def events_for_task(self, task_id: UUID) -> tuple[AuditEvent, ...]:
        return self.ledger.events_for_task(task_id)

    def verify_integrity(self) -> AuditVerification:
        return self.ledger.verify_integrity()
