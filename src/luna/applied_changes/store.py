"""Immutable SQLite storage for integrity-bound applied changes."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from luna.applied_changes.models import (
    AppliedChangeRecord,
)
from luna.contracts.base import utc_now

APPLIED_CHANGE_SCHEMA_VERSION = 1


class AppliedChangeStoreError(
    RuntimeError
):
    """Base error for durable applied-change storage."""


class AppliedChangeConflictError(
    AppliedChangeStoreError
):
    """Raised when an immutable identity or binding conflicts."""


def _canonical_json(
    record: AppliedChangeRecord,
) -> str:
    return json.dumps(
        record.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _payload_sha256(
    payload: str,
) -> str:
    return sha256(
        payload.encode("utf-8")
    ).hexdigest()


class SQLiteAppliedChangeStore:
    """SQLite WAL store for immutable applied-change evidence."""

    def __init__(
        self,
        database_path: str | Path,
    ) -> None:
        self.path = (
            Path(database_path)
            .expanduser()
            .resolve()
        )

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._migrate()

    def _connect(
        self,
    ) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
        )

        connection.row_factory = (
            sqlite3.Row
        )

        connection.execute(
            "PRAGMA synchronous=FULL"
        )

        connection.execute(
            "PRAGMA busy_timeout=5000"
        )

        connection.execute(
            "PRAGMA journal_mode=WAL"
        )

        return connection

    @contextmanager
    def _read_connection(
        self,
    ) -> Iterator[sqlite3.Connection]:
        connection = self._connect()

        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(
        self,
    ) -> Iterator[sqlite3.Connection]:
        connection = self._connect()

        try:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            yield connection

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS
                applied_change_schema (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )

            row = connection.execute(
                """
                SELECT
                    COALESCE(MAX(version), 0)
                    AS version
                FROM applied_change_schema
                """
            ).fetchone()

            current = (
                int(row["version"])
                if row is not None
                else 0
            )

            if (
                current
                > APPLIED_CHANGE_SCHEMA_VERSION
            ):
                raise AppliedChangeStoreError(
                    "applied-change schema "
                    f"{current} is newer than "
                    f"{APPLIED_CHANGE_SCHEMA_VERSION}"
                )

            if current < 1:
                connection.execute(
                    """
                    CREATE TABLE
                    applied_change_records (
                        record_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        result_id TEXT NOT NULL,
                        relative_path TEXT NOT NULL,
                        state TEXT NOT NULL,
                        integrity_digest TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        recorded_at TEXT NOT NULL,
                        UNIQUE (
                            task_id,
                            request_id,
                            result_id,
                            relative_path
                        )
                    )
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX
                    applied_change_result_binding
                    ON applied_change_records(
                        task_id,
                        request_id,
                        result_id,
                        relative_path,
                        record_id
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO
                    applied_change_schema(
                        version,
                        applied_at
                    )
                    VALUES (?, ?)
                    """,
                    (
                        1,
                        utc_now().isoformat(),
                    ),
                )

    def schema_version(
        self,
    ) -> int:
        """Return the applied store schema version."""

        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    COALESCE(MAX(version), 0)
                    AS version
                FROM applied_change_schema
                """
            ).fetchone()

        return (
            int(row["version"])
            if row is not None
            else 0
        )

    @staticmethod
    def _record_from_row(
        row: sqlite3.Row,
    ) -> AppliedChangeRecord:
        payload = str(
            row["payload_json"]
        )

        if (
            _payload_sha256(payload)
            != str(row["payload_sha256"])
        ):
            raise AppliedChangeStoreError(
                "applied-change payload "
                "SHA-256 mismatch: "
                f"{row['record_id']}"
            )

        try:
            record = (
                AppliedChangeRecord
                .model_validate_json(payload)
            )
        except Exception as exc:
            raise AppliedChangeStoreError(
                "applied-change record is invalid: "
                f"{row['record_id']}: {exc}"
            ) from exc

        row_binding = {
            "record_id": str(
                row["record_id"]
            ),
            "task_id": str(
                row["task_id"]
            ),
            "request_id": str(
                row["request_id"]
            ),
            "result_id": str(
                row["result_id"]
            ),
            "relative_path": str(
                row["relative_path"]
            ),
            "state": str(
                row["state"]
            ),
            "integrity_digest": str(
                row["integrity_digest"]
            ),
        }

        record_binding = {
            "record_id": str(
                record.record_id
            ),
            "task_id": str(
                record.task_id
            ),
            "request_id": str(
                record.request_id
            ),
            "result_id": str(
                record.result_id
            ),
            "relative_path": (
                record.candidate.relative_path
            ),
            "state": (
                record.candidate.state.value
            ),
            "integrity_digest": (
                record.integrity_digest
            ),
        }

        if row_binding != record_binding:
            raise AppliedChangeStoreError(
                "applied-change row "
                "binding mismatch: "
                f"{row['record_id']}"
            )

        return record

    @staticmethod
    def _persist_record_in_transaction(
        connection: sqlite3.Connection,
        record: AppliedChangeRecord,
    ) -> AppliedChangeRecord:
        existing_row = (
            connection.execute(
                """
                SELECT *
                FROM applied_change_records
                WHERE record_id = ?
                """,
                (
                    str(record.record_id),
                ),
            )
            .fetchone()
        )

        if existing_row is not None:
            existing = (
                SQLiteAppliedChangeStore
                ._record_from_row(
                    existing_row
                )
            )

            if existing != record:
                raise (
                    AppliedChangeConflictError(
                        "applied-change "
                        "record_id already "
                        "exists with "
                        "different content"
                    )
                )

            return existing

        binding_row = (
            connection.execute(
                """
                SELECT *
                FROM applied_change_records
                WHERE task_id = ?
                  AND request_id = ?
                  AND result_id = ?
                  AND relative_path = ?
                """,
                (
                    str(record.task_id),
                    str(record.request_id),
                    str(record.result_id),
                    (
                        record.candidate
                        .relative_path
                    ),
                ),
            )
            .fetchone()
        )

        if binding_row is not None:
            existing = (
                SQLiteAppliedChangeStore
                ._record_from_row(
                    binding_row
                )
            )

            if existing != record:
                raise (
                    AppliedChangeConflictError(
                        "applied-change "
                        "result/path binding "
                        "already exists with "
                        "different content"
                    )
                )

            return existing

        try:
            connection.execute(
                """
                INSERT INTO
                applied_change_records(
                    record_id,
                    task_id,
                    request_id,
                    result_id,
                    relative_path,
                    state,
                    integrity_digest,
                    payload_json,
                    payload_sha256,
                    recorded_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    str(record.record_id),
                    str(record.task_id),
                    str(record.request_id),
                    str(record.result_id),
                    (
                        record.candidate
                        .relative_path
                    ),
                    (
                        record.candidate
                        .state.value
                    ),
                    record.integrity_digest,
                    _canonical_json(record),
                    _payload_sha256(
                        _canonical_json(
                            record
                        )
                    ),
                    (
                        record.recorded_at
                        .isoformat()
                    ),
                ),
            )

        except sqlite3.IntegrityError as exc:
            raise AppliedChangeConflictError(
                "applied-change immutable "
                "binding conflict"
            ) from exc

        return record

    def persist_many(
        self,
        records: tuple[
            AppliedChangeRecord,
            ...,
        ],
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        """Persist one exact record set atomically."""

        if not records:
            return ()

        record_ids = tuple(
            record.record_id
            for record in records
        )

        if len(record_ids) != len(
            set(record_ids)
        ):
            raise AppliedChangeConflictError(
                "applied-change batch contains "
                "duplicate record_id"
            )

        bindings = tuple(
            (
                record.task_id,
                record.request_id,
                record.result_id,
                (
                    record.candidate
                    .relative_path
                ),
            )
            for record in records
        )

        if len(bindings) != len(
            set(bindings)
        ):
            raise AppliedChangeConflictError(
                "applied-change batch contains "
                "duplicate result/path binding"
            )

        with self._transaction() as connection:
            persisted = tuple(
                self._persist_record_in_transaction(
                    connection,
                    record,
                )
                for record in records
            )

        return tuple(
            self.load(
                record.record_id
            )
            for record in persisted
        )

    def persist(
        self,
        record: AppliedChangeRecord,
    ) -> AppliedChangeRecord:
        """Persist exactly once or reject immutable conflicts."""

        persisted = self.persist_many(
            (record,)
        )

        return persisted[0]

    def load(
        self,
        record_id: UUID,
    ) -> AppliedChangeRecord:
        """Load and integrity-check one immutable record."""

        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM applied_change_records
                WHERE record_id = ?
                """,
                (
                    str(record_id),
                ),
            ).fetchone()

        if row is None:
            raise AppliedChangeStoreError(
                "applied-change record "
                "does not exist: "
                f"{record_id}"
            )

        return self._record_from_row(
            row
        )

    def list_for_result(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        """Return one exact result's records in deterministic order."""

        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM applied_change_records
                WHERE task_id = ?
                  AND request_id = ?
                  AND result_id = ?
                ORDER BY
                    relative_path,
                    record_id
                """,
                (
                    str(task_id),
                    str(request_id),
                    str(result_id),
                ),
            ).fetchall()

        return tuple(
            self._record_from_row(row)
            for row in rows
        )
