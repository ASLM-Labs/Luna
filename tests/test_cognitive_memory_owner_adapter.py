from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from luna.continuity import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolutionReason,
    CognitiveOwnerResolutionStatus,
    build_memory_owner_binding,
    resolve_memory_owner_binding,
)
from luna.continuity.models import model_digest
from luna.memory.models import (
    MemoryRecord,
    MemoryRecordStatus,
    MemoryScope,
    MemorySensitivity,
    MemorySourceKind,
    MemoryType,
)
from luna.memory.store import MemoryNotFoundError, SQLiteMemoryStore


def _record(
    *,
    statement: str = "Verified project fact.",
    expires_at: datetime | None = None,
    supersedes: UUID | None = None,
) -> MemoryRecord:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    memory_type = next(
        item for item in MemoryType if item is not MemoryType.SECRET_REFERENCE
    )
    return MemoryRecord(
        candidate_id=uuid4(),
        task_id=uuid4(),
        memory_type=memory_type,
        statement=statement,
        source_kind=next(iter(MemorySourceKind)),
        source_ref="fixture://verified-memory",
        observed_at=now,
        created_at=now,
        last_verified_at=now,
        confidence=1.0,
        scope=next(iter(MemoryScope)),
        sensitivity=MemorySensitivity.PRIVATE,
        expires_at=expires_at,
        supersedes=supersedes,
    )


def test_memory_binding_uses_exact_record_identity_and_digest() -> None:
    record = _record()

    binding = build_memory_owner_binding(record)

    assert binding.owner_kind is CognitiveOwnerKind.VERIFIED_MEMORY
    assert binding.source_ref == f"memory://record/{record.memory_id}"
    assert binding.content_sha256 == model_digest(record)
    assert binding.runtime_authority is False
    assert binding.execution_authority is False
    assert binding.completion_authority is False


def test_same_memory_record_matches_exact_snapshot() -> None:
    record = _record()
    historical = build_memory_owner_binding(record)

    resolution = resolve_memory_owner_binding(
        historical_binding=historical,
        current_record=record,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.MATCHED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.SNAPSHOT_MATCH


def test_superseded_memory_is_content_change_on_same_owner(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    old = _record(statement="Use preference A.")
    store.save(old)
    historical = build_memory_owner_binding(old)
    replacement = _record(statement="Use preference B.", supersedes=old.memory_id)
    replacement = replacement.model_copy(
        update={
            "memory_type": old.memory_type,
            "scope": old.scope,
        }
    )

    store.save(replacement)
    current = store.load(old.memory_id)
    resolution = resolve_memory_owner_binding(
        historical_binding=historical,
        current_record=current,
    )

    assert current.status is MemoryRecordStatus.SUPERSEDED
    assert current.superseded_by == replacement.memory_id
    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.CONTENT_CHANGED


def test_expired_memory_is_content_change_on_same_owner(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    record = _record(expires_at=now + timedelta(hours=1))
    store.save(record)
    historical = build_memory_owner_binding(record)

    assert store.expire_due(now=now + timedelta(hours=2)) == (record.memory_id,)
    current = store.load(record.memory_id)
    resolution = resolve_memory_owner_binding(
        historical_binding=historical,
        current_record=current,
    )

    assert current.status is MemoryRecordStatus.EXPIRED
    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.CONTENT_CHANGED


def test_forgotten_memory_resolves_missing_and_cannot_resurrect(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    record = _record()
    store.save(record)
    historical = build_memory_owner_binding(record)

    store.forget(record.memory_id)

    with pytest.raises(MemoryNotFoundError):
        store.load(record.memory_id)

    resolution = resolve_memory_owner_binding(
        historical_binding=historical,
        current_record=None,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.MISSING
    assert resolution.reason_code is CognitiveOwnerResolutionReason.OWNER_MISSING
    assert resolution.current_binding is None


def test_unavailable_memory_owner_is_not_misclassified_missing() -> None:
    historical = build_memory_owner_binding(_record())

    resolution = resolve_memory_owner_binding(
        historical_binding=historical,
        current_record=None,
        current_unavailable=True,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.UNAVAILABLE
    assert resolution.reason_code is CognitiveOwnerResolutionReason.OWNER_UNAVAILABLE


def test_memory_adapter_rejects_replacement_record_as_same_owner() -> None:
    historical_record = _record(statement="Historical record.")
    replacement = _record(statement="Replacement record.")

    with pytest.raises(ValueError, match="does not match historical memory identity"):
        resolve_memory_owner_binding(
            historical_binding=build_memory_owner_binding(historical_record),
            current_record=replacement,
        )


def test_memory_adapter_rejects_non_memory_historical_binding() -> None:
    historical = CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.IDENTITY_PROFILE,
        source_ref="identity://luna/profile/fixture",
        content_sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="not a verified-memory binding"):
        resolve_memory_owner_binding(
            historical_binding=historical,
            current_record=_record(),
        )


def test_memory_adapter_rejects_record_and_unavailable_together() -> None:
    record = _record()

    with pytest.raises(ValueError, match="cannot also be marked unavailable"):
        resolve_memory_owner_binding(
            historical_binding=build_memory_owner_binding(record),
            current_record=record,
            current_unavailable=True,
        )
