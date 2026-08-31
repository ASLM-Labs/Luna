from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from luna.applied_changes.models import (
    AppliedChangeOperation,
    AppliedChangeProjectionPolicy,
    AppliedChangeRecord,
    AppliedChangeState,
    applied_change_manifest_sha256,
)
from luna.applied_changes.projector import (
    project_text_change,
)
from luna.applied_changes.store import (
    APPLIED_CHANGE_SCHEMA_VERSION,
    AppliedChangeConflictError,
    AppliedChangeStoreError,
    SQLiteAppliedChangeStore,
)


def _digest(
    text: str,
) -> str:
    return sha256(
        text.encode("utf-8")
    ).hexdigest()


def _candidate(
    *,
    task_id: UUID,
    relative_path: str = "notes.txt",
    before: str = "before\n",
    after: str = "after\n",
):
    return project_text_change(
        task_id=task_id,
        operation=(
            AppliedChangeOperation.WRITE_TEXT
        ),
        relative_path=relative_path,
        before_text=before,
        after_text=after,
        before_digest=_digest(before),
        after_digest=_digest(after),
        before_size_bytes=len(
            before.encode("utf-8")
        ),
        after_size_bytes=len(
            after.encode("utf-8")
        ),
        policy=(
            AppliedChangeProjectionPolicy()
        ),
    )


def _record(
    *,
    task_id: UUID | None = None,
    request_id: UUID | None = None,
    result_id: UUID | None = None,
    relative_path: str = "notes.txt",
    record_id: UUID | None = None,
    after: str = "after\n",
) -> AppliedChangeRecord:
    active_task_id = (
        task_id or uuid4()
    )

    return AppliedChangeRecord.build(
        request_id=(
            request_id or uuid4()
        ),
        result_id=(
            result_id or uuid4()
        ),
        candidate=_candidate(
            task_id=active_task_id,
            relative_path=relative_path,
            after=after,
        ),
        record_id=record_id,
        recorded_at=datetime(
            2026,
            8,
            31,
            0,
            0,
            tzinfo=UTC,
        ),
    )


def test_store_persists_reopens_and_returns_exact_record(
    tmp_path: Path,
) -> None:
    database = (
        tmp_path
        / "applied_changes.sqlite3"
    )

    record = _record()

    store = SQLiteAppliedChangeStore(
        database
    )

    persisted = store.persist(
        record
    )

    assert persisted == record
    assert (
        store.schema_version()
        == APPLIED_CHANGE_SCHEMA_VERSION
    )

    reopened = SQLiteAppliedChangeStore(
        database
    )

    assert (
        reopened.load(
            record.record_id
        )
        == record
    )

    reference = record.as_ref()

    assert (
        reference.record_id
        == record.record_id
    )

    assert (
        reference.integrity_digest
        == record.integrity_digest
    )

    assert (
        reference.state
        is AppliedChangeState.COMPLETE
    )

    assert (
        reference.relative_path
        == "notes.txt"
    )


def test_store_persist_is_idempotent_for_exact_record(
    tmp_path: Path,
) -> None:
    store = SQLiteAppliedChangeStore(
        tmp_path
        / "applied_changes.sqlite3"
    )

    record = _record()

    first = store.persist(record)
    second = store.persist(record)

    assert first == record
    assert second == record


def test_store_rejects_same_record_id_with_different_content(
    tmp_path: Path,
) -> None:
    store = SQLiteAppliedChangeStore(
        tmp_path
        / "applied_changes.sqlite3"
    )

    record = _record()

    store.persist(record)

    conflicting = _record(
        task_id=record.task_id,
        request_id=record.request_id,
        result_id=record.result_id,
        relative_path="other.txt",
        record_id=record.record_id,
    )

    with pytest.raises(
        AppliedChangeConflictError,
        match="record_id",
    ):
        store.persist(
            conflicting
        )


def test_store_rejects_duplicate_result_path_binding(
    tmp_path: Path,
) -> None:
    store = SQLiteAppliedChangeStore(
        tmp_path
        / "applied_changes.sqlite3"
    )

    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    first = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
    )

    second = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        after="different\n",
    )

    store.persist(first)

    with pytest.raises(
        AppliedChangeConflictError,
        match="result/path binding",
    ):
        store.persist(second)



def test_store_persist_many_preserves_atomic_set_and_input_order(
    tmp_path: Path,
) -> None:
    store = SQLiteAppliedChangeStore(
        tmp_path
        / "applied_changes.sqlite3"
    )

    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    zeta = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        relative_path="zeta.txt",
    )

    alpha = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        relative_path="alpha.txt",
    )

    persisted = store.persist_many(
        (
            zeta,
            alpha,
        )
    )

    assert persisted == (
        zeta,
        alpha,
    )

    assert store.list_for_result(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
    ) == (
        alpha,
        zeta,
    )


def test_store_persist_many_rolls_back_earlier_insert_on_late_conflict(
    tmp_path: Path,
) -> None:
    store = SQLiteAppliedChangeStore(
        tmp_path
        / "applied_changes.sqlite3"
    )

    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    existing = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        relative_path="b.txt",
        after="existing\n",
    )

    store.persist(existing)

    first = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        relative_path="a.txt",
    )

    conflicting = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        relative_path="b.txt",
        after="different\n",
    )

    with pytest.raises(
        AppliedChangeConflictError,
        match="result/path binding",
    ):
        store.persist_many(
            (
                first,
                conflicting,
            )
        )

    with pytest.raises(
        AppliedChangeStoreError,
        match="does not exist",
    ):
        store.load(
            first.record_id
        )

    assert (
        store.load(
            existing.record_id
        )
        == existing
    )


def test_store_persist_many_rejects_duplicate_batch_binding_without_write(
    tmp_path: Path,
) -> None:
    store = SQLiteAppliedChangeStore(
        tmp_path
        / "applied_changes.sqlite3"
    )

    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    first = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
    )

    second = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        after="different\n",
    )

    with pytest.raises(
        AppliedChangeConflictError,
        match="duplicate result/path binding",
    ):
        store.persist_many(
            (
                first,
                second,
            )
        )

    for record in (
        first,
        second,
    ):
        with pytest.raises(
            AppliedChangeStoreError,
            match="does not exist",
        ):
            store.load(
                record.record_id
            )


def test_applied_change_manifest_is_order_independent_for_exact_result(
    tmp_path: Path,
) -> None:
    del tmp_path

    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    alpha = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        relative_path="alpha.txt",
        record_id=UUID(
            "00000000-0000-0000-0000-000000000001"
        ),
    )

    zeta = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        relative_path="zeta.txt",
        record_id=UUID(
            "00000000-0000-0000-0000-000000000002"
        ),
    )

    forward = applied_change_manifest_sha256(
        (
            alpha,
            zeta,
        )
    )

    reverse = applied_change_manifest_sha256(
        (
            zeta,
            alpha,
        )
    )

    assert forward == reverse
    assert len(forward) == 64


def test_applied_change_manifest_rejects_mixed_result_binding(
    tmp_path: Path,
) -> None:
    del tmp_path

    task_id = uuid4()
    request_id = uuid4()

    first = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=uuid4(),
        relative_path="alpha.txt",
    )

    second = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=uuid4(),
        relative_path="zeta.txt",
    )

    with pytest.raises(
        ValueError,
        match="one exact result binding",
    ):
        applied_change_manifest_sha256(
            (
                first,
                second,
            )
        )


def test_store_detects_payload_tamper_after_restart(
    tmp_path: Path,
) -> None:
    database = (
        tmp_path
        / "applied_changes.sqlite3"
    )

    record = _record()

    SQLiteAppliedChangeStore(
        database
    ).persist(record)

    connection = sqlite3.connect(
        database
    )

    try:
        row = connection.execute(
            """
            SELECT payload_json
            FROM applied_change_records
            WHERE record_id = ?
            """,
            (
                str(record.record_id),
            ),
        ).fetchone()

        assert row is not None

        payload = json.loads(
            str(row[0])
        )

        payload[
            "candidate"
        ][
            "after_size_bytes"
        ] += 1

        connection.execute(
            """
            UPDATE applied_change_records
            SET payload_json = ?
            WHERE record_id = ?
            """,
            (
                json.dumps(payload),
                str(record.record_id),
            ),
        )

        connection.commit()

    finally:
        connection.close()

    reopened = SQLiteAppliedChangeStore(
        database
    )

    with pytest.raises(
        AppliedChangeStoreError,
        match="payload SHA-256 mismatch",
    ):
        reopened.load(
            record.record_id
        )


def test_store_detects_intrinsic_record_digest_tamper(
    tmp_path: Path,
) -> None:
    database = (
        tmp_path
        / "applied_changes.sqlite3"
    )

    record = _record()

    SQLiteAppliedChangeStore(
        database
    ).persist(record)

    connection = sqlite3.connect(
        database
    )

    try:
        row = connection.execute(
            """
            SELECT payload_json
            FROM applied_change_records
            WHERE record_id = ?
            """,
            (
                str(record.record_id),
            ),
        ).fetchone()

        assert row is not None

        payload = json.loads(
            str(row[0])
        )

        payload[
            "candidate"
        ][
            "after_size_bytes"
        ] += 1

        tampered = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        tampered_sha = sha256(
            tampered.encode("utf-8")
        ).hexdigest()

        connection.execute(
            """
            UPDATE applied_change_records
            SET payload_json = ?,
                payload_sha256 = ?
            WHERE record_id = ?
            """,
            (
                tampered,
                tampered_sha,
                str(record.record_id),
            ),
        )

        connection.commit()

    finally:
        connection.close()

    reopened = SQLiteAppliedChangeStore(
        database
    )

    with pytest.raises(
        AppliedChangeStoreError,
        match="record is invalid",
    ):
        reopened.load(
            record.record_id
        )


def test_store_detects_row_binding_tamper(
    tmp_path: Path,
) -> None:
    database = (
        tmp_path
        / "applied_changes.sqlite3"
    )

    record = _record()

    SQLiteAppliedChangeStore(
        database
    ).persist(record)

    connection = sqlite3.connect(
        database
    )

    try:
        connection.execute(
            """
            UPDATE applied_change_records
            SET state = ?
            WHERE record_id = ?
            """,
            (
                (
                    AppliedChangeState
                    .DEGRADED.value
                ),
                str(record.record_id),
            ),
        )

        connection.commit()

    finally:
        connection.close()

    reopened = SQLiteAppliedChangeStore(
        database
    )

    with pytest.raises(
        AppliedChangeStoreError,
        match="row binding mismatch",
    ):
        reopened.load(
            record.record_id
        )


def test_store_lists_only_exact_result_binding_in_path_order(
    tmp_path: Path,
) -> None:
    store = SQLiteAppliedChangeStore(
        tmp_path
        / "applied_changes.sqlite3"
    )

    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    zeta = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        relative_path="zeta.txt",
    )

    alpha = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        relative_path="alpha.txt",
    )

    unrelated = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=uuid4(),
        relative_path="middle.txt",
    )

    store.persist(zeta)
    store.persist(unrelated)
    store.persist(alpha)

    records = store.list_for_result(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
    )

    assert records == (
        alpha,
        zeta,
    )


def test_store_rejects_missing_record(
    tmp_path: Path,
) -> None:
    store = SQLiteAppliedChangeStore(
        tmp_path
        / "applied_changes.sqlite3"
    )

    with pytest.raises(
        AppliedChangeStoreError,
        match="does not exist",
    ):
        store.load(
            uuid4()
        )


def test_store_refuses_newer_schema(
    tmp_path: Path,
) -> None:
    database = (
        tmp_path
        / "applied_changes.sqlite3"
    )

    connection = sqlite3.connect(
        database
    )

    try:
        connection.execute(
            """
            CREATE TABLE applied_change_schema (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            INSERT INTO applied_change_schema(
                version,
                applied_at
            )
            VALUES (?, ?)
            """,
            (
                (
                    APPLIED_CHANGE_SCHEMA_VERSION
                    + 1
                ),
                datetime.now(
                    UTC
                ).isoformat(),
            ),
        )

        connection.commit()

    finally:
        connection.close()

    with pytest.raises(
        AppliedChangeStoreError,
        match="newer",
    ):
        SQLiteAppliedChangeStore(
            database
        )
