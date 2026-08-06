"""Evidence creation and append-only recording without completion decisions."""

from __future__ import annotations

from uuid import UUID

from luna.audit.ledger import AppendOnlyAuditLedger
from luna.audit.models import AuditEvent, AuditEventKind
from luna.contracts.base import stable_payload
from luna.contracts.enums import (
    EvidenceResult,
    EvidenceSourceKind,
    ObservationStatus,
)
from luna.contracts.evidence import Evidence
from luna.contracts.observation import Observation


class EvidenceBuilder:
    """Create one evidence record from one current structured observation."""

    @staticmethod
    def from_observation(
        *,
        task_id: UUID,
        requirement_id: str,
        observation: Observation,
        environment_fingerprint: str,
        revision: str | None,
        freshness_seconds: int | None,
        reproducible: bool,
        confidence: float,
        details: str | None = None,
    ) -> Evidence:
        result_map = {
            ObservationStatus.SUCCESS: EvidenceResult.PASS,
            ObservationStatus.FAILURE: EvidenceResult.FAIL,
            ObservationStatus.PARTIAL: EvidenceResult.INCONCLUSIVE,
            ObservationStatus.BLOCKED: EvidenceResult.BLOCKED,
        }
        if observation.tests is not None:
            source_kind = EvidenceSourceKind.TEST_RESULT
        elif observation.changed_files:
            source_kind = EvidenceSourceKind.DIFF
        elif observation.measured_values:
            source_kind = EvidenceSourceKind.MEASUREMENT
        else:
            source_kind = EvidenceSourceKind.TOOL_OUTPUT
        return Evidence(
            task_id=task_id,
            requirement_id=requirement_id,
            source_kind=source_kind,
            source_ref=f"observation:{observation.observation_id}",
            result=result_map[observation.status],
            observed_at=observation.captured_at,
            environment_fingerprint=environment_fingerprint,
            revision=revision,
            freshness_seconds=freshness_seconds,
            reproducible=reproducible,
            confidence=confidence,
            details=details,
        )


class EvidenceLedger:
    """Append evidence with a common task and trace link."""

    def __init__(self, ledger: AppendOnlyAuditLedger) -> None:
        self._ledger = ledger

    def record(
        self,
        *,
        evidence: Evidence,
        trace_id: UUID,
        observation_id: UUID | None = None,
    ) -> AuditEvent:
        payload = stable_payload(evidence)
        if observation_id is not None:
            payload["observation_id"] = str(observation_id)
        return self._ledger.append(
            kind=AuditEventKind.EVIDENCE,
            task_id=evidence.task_id,
            trace_id=trace_id,
            subject_id=str(evidence.evidence_id),
            payload=payload,
        )
