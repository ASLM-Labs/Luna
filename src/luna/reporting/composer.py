"""Deterministic final report composer bound to verified completion artifacts."""

from __future__ import annotations

from uuid import UUID

from luna.audit.models import AuditEventKind
from luna.audit.session import AuditSession
from luna.contracts.base import stable_payload
from luna.contracts.enums import CompletionStatus
from luna.contracts.task import TaskContract
from luna.identity import IdentityProfile
from luna.reporting.models import FinalReport, ReportRisk
from luna.verification import CompletionGateResult
from luna.verification.models import ClaimStatus


class FinalReportComposerError(RuntimeError):
    """Raised when a user report would contradict gate-owned facts."""


class FinalReportComposer:
    """Compose and optionally audit a report from authoritative gate output."""

    def __init__(self, audit: AuditSession | None = None) -> None:
        self._audit = audit

    def compose(
        self,
        *,
        contract: TaskContract,
        gate_result: CompletionGateResult,
        identity: IdentityProfile,
        performed: tuple[str, ...] = (),
        changed: tuple[str, ...] = (),
        risks: tuple[ReportRisk, ...] = (),
        trace_id: UUID | None = None,
    ) -> FinalReport:
        report = gate_result.report
        decision = gate_result.decision
        if contract.task_id != report.task_id or contract.task_id != decision.task_id:
            raise FinalReportComposerError("contract and completion artifacts must share task_id")
        if report.report_id != decision.report_id:
            raise FinalReportComposerError("completion decision must reference verification report")
        if report.completion_status is not decision.status:
            raise FinalReportComposerError("verification and completion statuses must match")

        verified_items = [
            f"{item.claim.kind.value}: {item.claim.text}"
            for item in report.claim_assessments
            if item.status is ClaimStatus.PASS
        ]
        verified_items.extend(
            f"EVIDENCE_REQUIREMENT: {item.requirement}"
            for item in report.evidence_requirement_assessments
            if item.status is ClaimStatus.PASS
        )
        unverified_items: list[str] = []
        unverified_items.extend(
            f"{item.status.value}: {item.claim.text}"
            for item in report.claim_assessments
            if item.status is not ClaimStatus.PASS
        )
        unverified_items.extend(
            f"{item.status.value}: {item.requirement}"
            for item in report.evidence_requirement_assessments
            if item.status is not ClaimStatus.PASS
        )
        unverified_items.extend(
            f"REJECTED_EVIDENCE {item.code.value}: {item.reason}"
            for item in report.rejected_evidence
        )
        unverified_items.extend(
            f"UNMATCHED_REQUIREMENT: {item}" for item in report.unmatched_requirement_ids
        )
        if decision.status is not CompletionStatus.VERIFIED_COMPLETE and not unverified_items:
            unverified_items.extend(decision.reasons)

        final = FinalReport(
            task_id=contract.task_id,
            verification_report_id=report.report_id,
            completion_decision_id=decision.decision_id,
            identity_profile_id=identity.profile_id,
            identity_version=identity.identity_version,
            objective=contract.objective,
            completion_status=decision.status,
            performed=performed,
            changed=changed,
            verified=tuple(dict.fromkeys(verified_items)),
            unverified=tuple(dict.fromkeys(unverified_items)),
            risks=risks,
            evidence_refs=tuple(
                f"evidence:{evidence_id}" for evidence_id in report.accepted_evidence_ids
            ),
        )
        if self._audit is not None:
            if trace_id is None:
                raise FinalReportComposerError("trace_id is required when final report is audited")
            self._audit.ledger.append(
                kind=AuditEventKind.FINAL_REPORT,
                task_id=contract.task_id,
                trace_id=trace_id,
                subject_id=str(final.final_report_id),
                payload=stable_payload(final),
            )
        return final
