from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from luna.audit import AuditEventKind, AuditSession
from luna.memory import (
    MemoryCandidate,
    MemoryDecisionStatus,
    MemoryPolicy,
    MemoryQuery,
    MemoryScope,
    MemorySourceKind,
    MemoryType,
    SQLiteMemoryStore,
    VerifiedMemoryService,
)


def _commit(
    service: VerifiedMemoryService,
    *,
    task_id: UUID,
    statement: str,
    scope: MemoryScope,
    source_ref: str,
    confidence: float,
) -> None:
    decision = service.commit_candidate(
        candidate=MemoryCandidate(
            task_id=task_id,
            memory_type=MemoryType.FACT,
            statement=statement,
            source_kind=MemorySourceKind.VERIFIED_OBSERVATION,
            source_ref=source_ref,
            confidence=confidence,
            scope=scope,
        ),
        policy=MemoryPolicy(minimum_confidence=0.7),
    )
    assert decision.status is MemoryDecisionStatus.COMMIT


def test_retrieval_is_scope_bound_and_preserves_source_and_confidence(
    tmp_path: Path,
) -> None:
    task_id = uuid4()
    service = VerifiedMemoryService(SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    _commit(
        service,
        task_id=task_id,
        statement="The Luna repository lives under Documents.",
        scope=MemoryScope.REPOSITORY,
        source_ref="filesystem:repository-root",
        confidence=1.0,
    )
    _commit(
        service,
        task_id=task_id,
        statement="Community members discuss game updates.",
        scope=MemoryScope.COMMUNITY,
        source_ref="discord:community",
        confidence=0.9,
    )

    retrieval = service.retrieve(
        query=MemoryQuery(
            scope=MemoryScope.REPOSITORY,
            terms=("documents",),
            minimum_confidence=0.8,
        )
    )

    assert len(retrieval.records) == 1
    record = retrieval.records[0]
    assert record.scope is MemoryScope.REPOSITORY
    assert record.source_ref == "filesystem:repository-root"
    assert record.confidence == 1.0
    assert "community" not in record.statement.casefold()


def test_audited_retrieval_records_only_ids_and_scope(tmp_path: Path) -> None:
    task_id = uuid4()
    trace_id = uuid4()
    audit = AuditSession(tmp_path / "audit")
    service = VerifiedMemoryService(
        SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        audit,
    )
    decision = service.commit_candidate(
        candidate=MemoryCandidate(
            task_id=task_id,
            memory_type=MemoryType.PROJECT_DECISION,
            statement="Use exact argv process execution.",
            source_kind=MemorySourceKind.USER_CONFIRMATION,
            source_ref="conversation:decision",
            confidence=1.0,
            scope=MemoryScope.PROJECT,
        ),
        policy=MemoryPolicy(),
        trace_id=trace_id,
    )
    assert decision.record is not None

    retrieval = service.retrieve(
        query=MemoryQuery(scope=MemoryScope.PROJECT),
        task_id=task_id,
        trace_id=trace_id,
    )

    assert retrieval.records == (decision.record,)
    events = audit.events_for_task(task_id)
    retrieval_event = next(
        event for event in events if event.kind is AuditEventKind.MEMORY_RETRIEVAL
    )
    assert retrieval_event.payload["record_ids"] == [str(decision.record.memory_id)]
    assert "statement" not in retrieval_event.payload
    assert audit.verify_integrity().valid
