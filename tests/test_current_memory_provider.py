"""G2-M exact current-memory provider contract tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import luna.memory as memory_package
from luna.memory.models import (
    MemoryRecord,
    MemoryRecordStatus,
    MemoryScope,
    MemorySensitivity,
    MemorySourceKind,
    MemoryType,
)
from luna.memory.service import CurrentMemoryProvider, VerifiedMemoryService
from luna.memory.store import (
    MemoryIntegrityError,
    MemoryNotFoundError,
    SQLiteMemoryStore,
)


def _record(
    *,
    statement: str = "Verified project fact.",
    expires_at: datetime | None = None,
    supersedes: UUID | None = None,
) -> MemoryRecord:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryRecord(
        candidate_id=uuid4(),
        task_id=uuid4(),
        memory_type=MemoryType.FACT,
        statement=statement,
        source_kind=MemorySourceKind.USER_CONFIRMATION,
        source_ref="g2-m:test",
        observed_at=now,
        created_at=now,
        last_verified_at=now,
        confidence=1.0,
        scope=MemoryScope.PROJECT,
        sensitivity=MemorySensitivity.PRIVATE,
        expires_at=expires_at,
        supersedes=supersedes,
    )


def test_current_memory_provider_is_publicly_exported() -> None:
    assert memory_package.CurrentMemoryProvider is CurrentMemoryProvider


def test_current_memory_returns_exact_active_record(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    record = _record()
    store.save(record)

    provider: CurrentMemoryProvider = VerifiedMemoryService(store)

    assert provider.current_memory(record.memory_id) == record


def test_current_memory_does_not_use_semantic_retrieval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    record = _record()
    store.save(record)

    def unexpected_retrieve(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("exact owner read must not use semantic retrieval")

    monkeypatch.setattr(store, "retrieve", unexpected_retrieve)

    service = VerifiedMemoryService(store)

    assert service.current_memory(record.memory_id) == record


def test_current_memory_preserves_superseded_owner_state(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    old = _record(statement="Use preference A.")
    store.save(old)

    replacement = _record(
        statement="Use preference B.",
        supersedes=old.memory_id,
    )
    store.save(replacement)

    current = VerifiedMemoryService(store).current_memory(old.memory_id)

    assert current.memory_id == old.memory_id
    assert current.status is MemoryRecordStatus.SUPERSEDED
    assert current.superseded_by == replacement.memory_id


def test_current_memory_preserves_expired_owner_state(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    record = _record(
        expires_at=now + timedelta(hours=1),
    )
    store.save(record)

    assert store.expire_due(
        now=now + timedelta(hours=2)
    ) == (record.memory_id,)

    current = VerifiedMemoryService(store).current_memory(record.memory_id)

    assert current.memory_id == record.memory_id
    assert current.status is MemoryRecordStatus.EXPIRED


def test_current_memory_propagates_missing_record(tmp_path: Path) -> None:
    service = VerifiedMemoryService(
        SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    )

    missing_id = uuid4()

    with pytest.raises(
        MemoryNotFoundError,
        match=str(missing_id),
    ):
        service.current_memory(missing_id)


def test_current_memory_propagates_integrity_failure(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    record = _record()
    store.save(record)

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            UPDATE memories
            SET payload_sha256 = ?
            WHERE memory_id = ?
            """,
            ("0" * 64, str(record.memory_id)),
        )

    service = VerifiedMemoryService(store)

    with pytest.raises(
        MemoryIntegrityError,
        match="memory payload digest mismatch",
    ):
        service.current_memory(record.memory_id)
