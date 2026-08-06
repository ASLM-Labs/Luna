from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from luna.audit import AuditEventKind, AuditSession
from luna.memory import (
    MemoryCandidate,
    MemoryDecisionStatus,
    MemoryPolicy,
    MemoryQuery,
    MemoryRecord,
    MemoryRecordStatus,
    MemoryScope,
    MemorySourceKind,
    MemoryType,
    SQLiteMemoryStore,
    VerifiedMemoryService,
)


def _commit(
    service: VerifiedMemoryService,
    *,
    statement: str,
    scope: MemoryScope = MemoryScope.PROJECT,
    memory_type: MemoryType = MemoryType.PROJECT_DECISION,
    expires_at: datetime | None = None,
    supersedes: UUID | None = None,
) -> MemoryRecord:
    candidate = MemoryCandidate(
        task_id=uuid4(),
        memory_type=memory_type,
        statement=statement,
        source_kind=MemorySourceKind.USER_CONFIRMATION,
        source_ref=f"conversation:{uuid4()}",
        confidence=0.95,
        scope=scope,
        expires_at=expires_at,
        supersedes=supersedes,
        occurrence_count=2,
    )
    decision = service.commit_candidate(candidate=candidate, policy=MemoryPolicy())
    assert decision.status is MemoryDecisionStatus.COMMIT
    assert decision.record is not None
    return decision.record


def test_sqlite_wal_schema_integrity_and_windows_handle_release(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    store = SQLiteMemoryStore(root / "memory.sqlite3")
    service = VerifiedMemoryService(store)
    _commit(service, statement="The quality gate is deterministic.")

    assert store.journal_mode() == "wal"
    assert store.schema_version() == 1
    integrity = store.verify_integrity()
    assert integrity.valid
    assert integrity.record_count == 1

    shutil.rmtree(root)
    assert not root.exists()


def test_supersede_marks_old_record_and_retrieval_uses_new_record(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    service = VerifiedMemoryService(store)
    old = _commit(service, statement="Use the desktop working copy.")
    new = _commit(
        service,
        statement="Use the Documents Git repository.",
        supersedes=old.memory_id,
    )

    loaded_old = store.load(old.memory_id)
    loaded_new = store.load(new.memory_id)

    assert loaded_old.status is MemoryRecordStatus.SUPERSEDED
    assert loaded_old.superseded_by == new.memory_id
    assert loaded_new.supersedes == old.memory_id
    records, excluded = store.retrieve(
        MemoryQuery(scope=MemoryScope.PROJECT)
    )
    assert records == (loaded_new,)
    assert excluded == 1
    assert store.verify_integrity().valid


def test_expired_record_is_excluded_and_marked_expired(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    service = VerifiedMemoryService(store)
    now = datetime.now(UTC)
    record = _commit(
        service,
        statement="Patch window ends soon.",
        memory_type=MemoryType.RESEARCH_FACT,
        scope=MemoryScope.RESEARCH,
        expires_at=now + timedelta(minutes=1),
    )

    records, excluded = store.retrieve(
        MemoryQuery(scope=MemoryScope.RESEARCH),
        now=now + timedelta(minutes=2),
    )

    assert records == ()
    assert excluded == 1
    assert store.load(record.memory_id).status is MemoryRecordStatus.EXPIRED


def test_forgetting_active_superseding_record_restores_previous_record(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    service = VerifiedMemoryService(store)
    old = _commit(service, statement="Use preference A.")
    new = _commit(service, statement="Use preference B.", supersedes=old.memory_id)

    service.forget(memory_id=new.memory_id, task_id=new.task_id)

    restored = store.load(old.memory_id)
    assert restored.status is MemoryRecordStatus.ACTIVE
    assert restored.superseded_by is None
    assert store.verify_integrity().valid


def test_audited_forget_removes_record_and_records_event(tmp_path: Path) -> None:
    task_id = uuid4()
    trace_id = uuid4()
    audit = AuditSession(tmp_path / "audit")
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    service = VerifiedMemoryService(store, audit)
    decision = service.commit_candidate(
        candidate=MemoryCandidate(
            task_id=task_id,
            memory_type=MemoryType.FACT,
            statement="This verified record may be deleted by the user.",
            source_kind=MemorySourceKind.USER_CONFIRMATION,
            source_ref="conversation:user-delete",
            confidence=1.0,
            scope=MemoryScope.PRIVATE_USER,
        ),
        policy=MemoryPolicy(),
        trace_id=trace_id,
    )
    assert decision.record is not None

    service.forget(
        memory_id=decision.record.memory_id,
        task_id=task_id,
        trace_id=trace_id,
    )

    assert store.list_records() == ()
    assert AuditEventKind.MEMORY_FORGOTTEN in {
        event.kind for event in audit.events_for_task(task_id)
    }
    assert audit.verify_integrity().valid

