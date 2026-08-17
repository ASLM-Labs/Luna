"""Phase 12F verification, reporting, and review-only learning coordination."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from luna.contracts.enums import TaskPhase
from luna.contracts.evidence import Evidence
from luna.contracts.state import TaskState
from luna.identity import IdentityProfile
from luna.learning import LearningCandidateBatch, LearningCandidateBuilder
from luna.reporting import FinalReport, FinalReportComposer, ReportRisk
from luna.verification.episode import (
    VerificationEpisodeManifest,
    build_verification_episode,
)
from luna.verification.gate import CompletionGate
from luna.verification.models import CompletionGateResult, VerificationPolicy


@dataclass(frozen=True, slots=True)
class VerificationFinalization:
    """Artifacts produced at the VERIFYING -> REPORTING boundary."""

    reporting_state: TaskState
    gate_result: CompletionGateResult
    verification_episode: VerificationEpisodeManifest
    final_report: FinalReport
    learning_candidates: LearningCandidateBatch


class VerificationCoordinator:
    """Join deterministic gate, truthful report, and review-gated learning output."""

    def __init__(
        self,
        *,
        completion_gate: CompletionGate,
        report_composer: FinalReportComposer,
        identity: IdentityProfile,
        learning_builder: LearningCandidateBuilder,
    ) -> None:
        self._completion_gate = completion_gate
        self._report_composer = report_composer
        self._identity = identity
        self._learning_builder = learning_builder

    def finalize(
        self,
        *,
        state: TaskState,
        evidence: Iterable[Evidence],
        policy: VerificationPolicy,
        trace_id: UUID,
        performed: tuple[str, ...] = (),
        changed: tuple[str, ...] = (),
        risks: tuple[ReportRisk, ...] = (),
    ) -> VerificationFinalization:
        if state.phase is not TaskPhase.VERIFYING:
            raise ValueError("Phase 12F finalization requires VERIFYING TaskState")

        evidence_records = tuple(evidence)

        gate_result = self._completion_gate.evaluate(
            contract=state.contract,
            evidence=evidence_records,
            policy=policy,
            trace_id=trace_id,
        )
        verification_episode = build_verification_episode(
            contract=state.contract,
            source_task_revision=state.revision,
            evidence=evidence_records,
            policy=policy,
            gate_result=gate_result,
            trace_id=trace_id,
        )
        evidence_state = state.revise(
            evidence_ids=gate_result.report.accepted_evidence_ids,
        )
        reporting_state = self._completion_gate.apply_to_state(
            state=evidence_state,
            result=gate_result,
        )
        final_report = self._report_composer.compose(
            contract=state.contract,
            gate_result=gate_result,
            identity=self._identity,
            performed=performed,
            changed=changed,
            risks=risks,
            trace_id=trace_id,
        )
        learning_candidates = self._learning_builder.build(
            state=reporting_state,
            report=gate_result.report,
            trace_id=trace_id,
        )
        return VerificationFinalization(
            reporting_state=reporting_state,
            gate_result=gate_result,
            verification_episode=verification_episode,
            final_report=final_report,
            learning_candidates=learning_candidates,
        )
