"""Deterministic evidence-to-learning candidate extraction."""

from __future__ import annotations

from uuid import UUID

from luna.audit.models import AuditEventKind
from luna.audit.session import AuditSession
from luna.contracts.base import stable_payload
from luna.contracts.enums import CompletionStatus
from luna.contracts.state import TaskState
from luna.learning.models import (
    LearningCandidate,
    LearningCandidateBatch,
    LearningCandidateKind,
)
from luna.verification.models import VerificationReport


class LearningCandidateBuilder:
    """Extract review-only lessons without changing memory, policy, or source code."""

    def __init__(self, audit: AuditSession | None = None) -> None:
        self._audit = audit

    def build(
        self,
        *,
        state: TaskState,
        report: VerificationReport,
        trace_id: UUID | None = None,
    ) -> LearningCandidateBatch:
        if state.task_id != report.task_id:
            raise ValueError("task state and verification report must share task_id")
        if self._audit is not None and trace_id is None:
            raise ValueError("audited learning candidate generation requires trace_id")

        candidates: list[LearningCandidate] = []

        for assumption in state.failed_assumptions:
            candidates.append(
                LearningCandidate(
                    task_id=state.task_id,
                    kind=(
                        LearningCandidateKind.RECOVERY_PATTERN
                        if report.completion_status is CompletionStatus.VERIFIED_COMPLETE
                        else LearningCandidateKind.FAILED_ASSUMPTION
                    ),
                    statement=(
                        "Recovered task contained a failed assumption: " + assumption
                        if report.completion_status is CompletionStatus.VERIFIED_COMPLETE
                        else "Failed assumption requires review: " + assumption
                    ),
                    verification_report_id=report.report_id,
                    completion_status=report.completion_status,
                    evidence_ids=report.accepted_evidence_ids,
                    source_refs=(f"task-state:revision:{state.revision}",),
                    confidence=(
                        0.9
                        if report.completion_status is CompletionStatus.VERIFIED_COMPLETE
                        else 0.7
                    ),
                )
            )

        for disagreement in report.disagreements:
            candidates.append(
                LearningCandidate(
                    task_id=state.task_id,
                    kind=LearningCandidateKind.EVIDENCE_CONFLICT,
                    statement=(
                        "Unresolved evidence disagreement requires review for claim "
                        + disagreement.claim_id
                    ),
                    verification_report_id=report.report_id,
                    completion_status=report.completion_status,
                    evidence_ids=tuple(
                        dict.fromkeys(
                            (
                                *disagreement.supporting_evidence_ids,
                                *disagreement.contradicting_evidence_ids,
                            )
                        )
                    ),
                    source_refs=(f"verification-report:{report.report_id}",),
                    confidence=1.0,
                )
            )

        for rejection in report.rejected_evidence:
            candidates.append(
                LearningCandidate(
                    task_id=state.task_id,
                    kind=LearningCandidateKind.VERIFICATION_GAP,
                    statement=(
                        f"Evidence was rejected ({rejection.code.value}): {rejection.reason}"
                    ),
                    verification_report_id=report.report_id,
                    completion_status=report.completion_status,
                    evidence_ids=(rejection.evidence_id,),
                    source_refs=(f"verification-report:{report.report_id}",),
                    confidence=1.0,
                )
            )

        if (
            report.completion_status is not CompletionStatus.VERIFIED_COMPLETE
            and not candidates
        ):
            candidates.append(
                LearningCandidate(
                    task_id=state.task_id,
                    kind=LearningCandidateKind.VERIFICATION_GAP,
                    statement="Verification remained incomplete: " + "; ".join(report.rationale),
                    verification_report_id=report.report_id,
                    completion_status=report.completion_status,
                    evidence_ids=report.accepted_evidence_ids,
                    source_refs=(f"verification-report:{report.report_id}",),
                    confidence=1.0,
                )
            )

        batch = LearningCandidateBatch(
            task_id=state.task_id,
            verification_report_id=report.report_id,
            candidates=tuple(candidates),
            generated_at=report.generated_at,
        )
        if self._audit is not None:
            assert trace_id is not None
            for candidate in batch.candidates:
                self._audit.ledger.append(
                    kind=AuditEventKind.LEARNING_CANDIDATE,
                    task_id=state.task_id,
                    trace_id=trace_id,
                    subject_id=str(candidate.candidate_id),
                    payload=stable_payload(candidate),
                )
        return batch
