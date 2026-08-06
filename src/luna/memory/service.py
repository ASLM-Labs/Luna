"""Verified-memory candidate, commit, retrieval, supersession, and forgetting flow."""

from __future__ import annotations

from uuid import UUID

from luna.audit import AuditEventKind, AuditSession
from luna.contracts.base import utc_now
from luna.memory.models import (
    MemoryCandidate,
    MemoryCommitDecision,
    MemoryDecisionStatus,
    MemoryPolicy,
    MemoryQuery,
    MemoryRecord,
    MemoryRejectionCode,
    MemoryRetrieval,
)
from luna.memory.policy import MemoryPolicyEvaluator
from luna.memory.store import MemoryConflictError, MemoryNotFoundError, SQLiteMemoryStore


class VerifiedMemoryService:
    """Apply policy before any durable memory write or retrieval."""

    def __init__(
        self,
        store: SQLiteMemoryStore,
        audit: AuditSession | None = None,
        *,
        explicit_secrets: tuple[str, ...] = (),
    ) -> None:
        self.store = store
        self.audit = audit
        self._evaluator = MemoryPolicyEvaluator(explicit_secrets)

    def commit_candidate(
        self,
        *,
        candidate: MemoryCandidate,
        policy: MemoryPolicy,
        trace_id: UUID | None = None,
    ) -> MemoryCommitDecision:
        if self.audit is not None and trace_id is None:
            raise ValueError("audited memory commit requires trace_id")
        self._record_candidate(candidate=candidate, trace_id=trace_id)
        policy_decision = self._evaluator.evaluate(candidate, policy)
        if policy_decision.status is MemoryDecisionStatus.REJECT:
            decision = MemoryCommitDecision(
                candidate_id=candidate.candidate_id,
                status=MemoryDecisionStatus.REJECT,
                rejection_codes=policy_decision.rejection_codes,
                reasons=policy_decision.reasons,
            )
            self._record_decision(
                candidate=candidate,
                decision=decision,
                trace_id=trace_id,
            )
            return decision

        assert policy_decision.sanitized_statement is not None
        now = utc_now()
        record = MemoryRecord(
            candidate_id=candidate.candidate_id,
            task_id=candidate.task_id,
            memory_type=candidate.memory_type,
            statement=policy_decision.sanitized_statement,
            source_kind=candidate.source_kind,
            source_ref=candidate.source_ref,
            observed_at=candidate.observed_at,
            created_at=now,
            last_verified_at=max(now, candidate.observed_at),
            confidence=candidate.confidence,
            scope=candidate.scope,
            sensitivity=candidate.sensitivity,
            expires_at=candidate.expires_at,
            supersedes=candidate.supersedes,
            secret_ref=candidate.secret_ref,
        )
        try:
            self.store.save(record)
        except (MemoryConflictError, MemoryNotFoundError) as exc:
            decision = MemoryCommitDecision(
                candidate_id=candidate.candidate_id,
                status=MemoryDecisionStatus.REJECT,
                rejection_codes=(MemoryRejectionCode.SUPERSEDE_TARGET_INVALID,),
                reasons=(str(exc),),
            )
            self._record_decision(
                candidate=candidate,
                decision=decision,
                trace_id=trace_id,
            )
            return decision

        decision = MemoryCommitDecision(
            candidate_id=candidate.candidate_id,
            status=MemoryDecisionStatus.COMMIT,
            record=record,
        )
        self._record_decision(candidate=candidate, decision=decision, trace_id=trace_id)
        self._record_committed(record=record, trace_id=trace_id)
        return decision

    def retrieve(
        self,
        *,
        query: MemoryQuery,
        task_id: UUID | None = None,
        trace_id: UUID | None = None,
    ) -> MemoryRetrieval:
        if self.audit is not None and (task_id is None or trace_id is None):
            raise ValueError("audited retrieval requires task_id and trace_id")
        records, excluded_count = self.store.retrieve(query)
        retrieval = MemoryRetrieval(
            query=query,
            records=records,
            excluded_count=excluded_count,
        )
        if self.audit is not None:
            assert task_id is not None
            assert trace_id is not None
            self.audit.ledger.append(
                kind=AuditEventKind.MEMORY_RETRIEVAL,
                task_id=task_id,
                trace_id=trace_id,
                subject_id=str(task_id),
                payload={
                    "scope": query.scope.value,
                    "memory_types": [item.value for item in query.memory_types],
                    "minimum_confidence": query.minimum_confidence,
                    "limit": query.limit,
                    "record_ids": [str(record.memory_id) for record in records],
                    "excluded_count": excluded_count,
                },
            )
        return retrieval

    def forget(
        self,
        *,
        memory_id: UUID,
        task_id: UUID,
        trace_id: UUID | None = None,
    ) -> None:
        if self.audit is not None and trace_id is None:
            raise ValueError("audited forgetting requires trace_id")
        self.store.forget(memory_id)
        if self.audit is not None:
            assert trace_id is not None
            self.audit.ledger.append(
                kind=AuditEventKind.MEMORY_FORGOTTEN,
                task_id=task_id,
                trace_id=trace_id,
                subject_id=str(memory_id),
                payload={"memory_id": str(memory_id)},
            )

    def _record_candidate(
        self,
        *,
        candidate: MemoryCandidate,
        trace_id: UUID | None,
    ) -> None:
        if self.audit is None:
            return
        if trace_id is None:
            raise ValueError("audited memory candidate requires trace_id")
        self.audit.ledger.append(
            kind=AuditEventKind.MEMORY_CANDIDATE,
            task_id=candidate.task_id,
            trace_id=trace_id,
            subject_id=str(candidate.candidate_id),
            payload={
                "candidate_id": str(candidate.candidate_id),
                "memory_type": candidate.memory_type.value,
                "source_kind": candidate.source_kind.value,
                "source_ref": candidate.source_ref,
                "observed_at": candidate.observed_at.isoformat(),
                "confidence": candidate.confidence,
                "scope": candidate.scope.value,
                "sensitivity": candidate.sensitivity.value,
                "expires_at": (
                    candidate.expires_at.isoformat()
                    if candidate.expires_at is not None
                    else None
                ),
                "supersedes": (
                    str(candidate.supersedes)
                    if candidate.supersedes is not None
                    else None
                ),
                "occurrence_count": candidate.occurrence_count,
                "explicit_persistence": candidate.explicit_persistence,
                "statement_sha256_only": True,
                "secret_ref_present": candidate.secret_ref is not None,
            },
        )

    def _record_decision(
        self,
        *,
        candidate: MemoryCandidate,
        decision: MemoryCommitDecision,
        trace_id: UUID | None,
    ) -> None:
        if self.audit is None:
            return
        if trace_id is None:
            raise ValueError("audited memory decision requires trace_id")
        self.audit.ledger.append(
            kind=AuditEventKind.MEMORY_DECISION,
            task_id=candidate.task_id,
            trace_id=trace_id,
            subject_id=str(candidate.candidate_id),
            payload={
                "candidate_id": str(candidate.candidate_id),
                "status": decision.status.value,
                "rejection_codes": [code.value for code in decision.rejection_codes],
                "reasons": list(decision.reasons),
                "memory_id": (
                    str(decision.record.memory_id) if decision.record is not None else None
                ),
            },
        )

    def _record_committed(
        self,
        *,
        record: MemoryRecord,
        trace_id: UUID | None,
    ) -> None:
        if self.audit is None:
            return
        if trace_id is None:
            raise ValueError("audited memory commit requires trace_id")
        self.audit.ledger.append(
            kind=AuditEventKind.MEMORY_COMMITTED,
            task_id=record.task_id,
            trace_id=trace_id,
            subject_id=str(record.memory_id),
            payload={
                "memory_id": str(record.memory_id),
                "candidate_id": str(record.candidate_id),
                "memory_type": record.memory_type.value,
                "scope": record.scope.value,
                "sensitivity": record.sensitivity.value,
                "source_kind": record.source_kind.value,
                "source_ref": record.source_ref,
                "confidence": record.confidence,
                "expires_at": (
                    record.expires_at.isoformat()
                    if record.expires_at is not None
                    else None
                ),
                "supersedes": (
                    str(record.supersedes) if record.supersedes is not None else None
                ),
                "secret_ref_present": record.secret_ref is not None,
                "statement_sha256_only": True,
            },
        )
