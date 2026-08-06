"""SQLite WAL store for verified, scoped, expiring memory records."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from luna.contracts.base import require_utc, utc_now
from luna.memory.models import (
    MemoryIntegrity,
    MemoryQuery,
    MemoryRecord,
    MemoryRecordStatus,
    MemoryScope,
    canonical_model_json,
    model_digest,
)

SCHEMA_VERSION = 1


class MemoryStoreError(RuntimeError):
    """Base verified-memory persistence failure."""


class MemoryNotFoundError(MemoryStoreError):
    """Requested memory record does not exist."""


class MemoryConflictError(MemoryStoreError):
    """Duplicate candidate or invalid supersession conflict."""


class MemoryIntegrityError(MemoryStoreError):
    """Persisted record payload or digest is invalid."""


class SQLiteMemoryStore:
    """Short-lived SQLite connections with WAL, FULL sync, and secure delete."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
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
                CREATE TABLE IF NOT EXISTS memory_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version "
                "FROM memory_schema_migrations"
            ).fetchone()
            current = int(row["version"]) if row is not None else 0
            if current > SCHEMA_VERSION:
                raise MemoryStoreError(
                    f"memory schema {current} is newer than runtime {SCHEMA_VERSION}"
                )
            if current < 1:
                connection.execute(
                    """
                    CREATE TABLE memories (
                        memory_id TEXT PRIMARY KEY,
                        candidate_id TEXT NOT NULL UNIQUE,
                        task_id TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        status TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        observed_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        last_verified_at TEXT NOT NULL,
                        expires_at TEXT,
                        supersedes TEXT,
                        superseded_by TEXT,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        FOREIGN KEY(supersedes) REFERENCES memories(memory_id),
                        FOREIGN KEY(superseded_by) REFERENCES memories(memory_id)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX memories_scope_status_verified
                    ON memories(scope, status, last_verified_at, memory_id)
                    """
                )
                connection.execute(
                    "INSERT INTO memory_schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (1, utc_now().isoformat()),
                )

    def schema_version(self) -> int:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version "
                "FROM memory_schema_migrations"
            ).fetchone()
            return int(row["version"]) if row is not None else 0

    def journal_mode(self) -> str:
        with self._read_connection() as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
            if row is None:
                raise MemoryStoreError("SQLite did not report journal mode")
            return str(row[0]).casefold()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        payload_json = str(row["payload_json"])
        try:
            record = MemoryRecord.model_validate_json(payload_json)
        except (ValidationError, ValueError) as exc:
            raise MemoryIntegrityError("invalid memory payload") from exc
        if model_digest(record) != str(row["payload_sha256"]):
            raise MemoryIntegrityError("memory payload digest mismatch")
        if str(record.memory_id) != str(row["memory_id"]):
            raise MemoryIntegrityError("memory ID column mismatch")
        if record.status.value != str(row["status"]):
            raise MemoryIntegrityError("memory status column mismatch")
        if record.observed_at.isoformat() != str(row["observed_at"]):
            raise MemoryIntegrityError("memory observed_at column mismatch")
        return record

    @staticmethod
    def _update_record(
        connection: sqlite3.Connection,
        record: MemoryRecord,
    ) -> None:
        connection.execute(
            """
            UPDATE memories
            SET status = ?,
                expires_at = ?,
                supersedes = ?,
                superseded_by = ?,
                payload_json = ?,
                payload_sha256 = ?
            WHERE memory_id = ?
            """,
            (
                record.status.value,
                record.expires_at.isoformat() if record.expires_at is not None else None,
                str(record.supersedes) if record.supersedes is not None else None,
                str(record.superseded_by) if record.superseded_by is not None else None,
                canonical_model_json(record),
                model_digest(record),
                str(record.memory_id),
            ),
        )

    def save(self, record: MemoryRecord) -> MemoryRecord:
        with self._transaction() as connection:
            duplicate = connection.execute(
                "SELECT 1 FROM memories WHERE candidate_id = ?",
                (str(record.candidate_id),),
            ).fetchone()
            if duplicate is not None:
                raise MemoryConflictError("candidate is already committed")

            target: MemoryRecord | None = None
            if record.supersedes is not None:
                row = connection.execute(
                    "SELECT * FROM memories WHERE memory_id = ?",
                    (str(record.supersedes),),
                ).fetchone()
                if row is None:
                    raise MemoryConflictError("supersede target does not exist")
                target = self._row_to_record(row)
                if target.status is not MemoryRecordStatus.ACTIVE:
                    raise MemoryConflictError("supersede target is not active")
                if target.scope is not record.scope:
                    raise MemoryConflictError("supersede target scope mismatch")
                if target.memory_type is not record.memory_type:
                    raise MemoryConflictError("supersede target type mismatch")

            connection.execute(
                """
                INSERT INTO memories(
                    memory_id,
                    candidate_id,
                    task_id,
                    memory_type,
                    scope,
                    status,
                    confidence,
                    observed_at,
                    created_at,
                    last_verified_at,
                    expires_at,
                    supersedes,
                    superseded_by,
                    payload_json,
                    payload_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.memory_id),
                    str(record.candidate_id),
                    str(record.task_id),
                    record.memory_type.value,
                    record.scope.value,
                    record.status.value,
                    record.confidence,
                    record.observed_at.isoformat(),
                    record.created_at.isoformat(),
                    record.last_verified_at.isoformat(),
                    record.expires_at.isoformat() if record.expires_at is not None else None,
                    str(record.supersedes) if record.supersedes is not None else None,
                    None,
                    canonical_model_json(record),
                    model_digest(record),
                ),
            )
            if target is not None:
                target = target.model_copy(
                    update={
                        "status": MemoryRecordStatus.SUPERSEDED,
                        "superseded_by": record.memory_id,
                    }
                )
                self._update_record(connection, target)
        return record

    def load(self, memory_id: UUID) -> MemoryRecord:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE memory_id = ?",
                (str(memory_id),),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError(str(memory_id))
        return self._row_to_record(row)

    def list_records(self, scope: MemoryScope | None = None) -> tuple[MemoryRecord, ...]:
        with self._read_connection() as connection:
            if scope is None:
                rows = connection.execute(
                    "SELECT * FROM memories ORDER BY created_at, memory_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM memories WHERE scope = ? "
                    "ORDER BY created_at, memory_id",
                    (scope.value,),
                ).fetchall()
        return tuple(self._row_to_record(row) for row in rows)

    def expire_due(self, *, now: datetime | None = None) -> tuple[UUID, ...]:
        current = require_utc(now) if now is not None else utc_now()
        expired: list[UUID] = []
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE status = ? AND expires_at IS NOT NULL",
                (MemoryRecordStatus.ACTIVE.value,),
            ).fetchall()
            for row in rows:
                record = self._row_to_record(row)
                if record.expires_at is not None and record.expires_at <= current:
                    record = record.model_copy(update={"status": MemoryRecordStatus.EXPIRED})
                    self._update_record(connection, record)
                    expired.append(record.memory_id)
        return tuple(expired)

    def retrieve(
        self,
        query: MemoryQuery,
        *,
        now: datetime | None = None,
    ) -> tuple[tuple[MemoryRecord, ...], int]:
        self.expire_due(now=now)
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE scope = ? "
                "ORDER BY confidence DESC, last_verified_at DESC, memory_id",
                (query.scope.value,),
            ).fetchall()
        records = tuple(self._row_to_record(row) for row in rows)
        selected: list[MemoryRecord] = []
        for record in records:
            if record.status is not MemoryRecordStatus.ACTIVE:
                continue
            if record.confidence < query.minimum_confidence:
                continue
            if query.memory_types and record.memory_type not in query.memory_types:
                continue
            normalized_statement = record.statement.casefold()
            if query.terms and not all(
                term.casefold() in normalized_statement for term in query.terms
            ):
                continue
            selected.append(record)
        limited = tuple(selected[: query.limit])
        return limited, len(records) - len(limited)

    def forget(self, memory_id: UUID) -> None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE memory_id = ?",
                (str(memory_id),),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError(str(memory_id))
            record = self._row_to_record(row)
            older: MemoryRecord | None = None
            newer: MemoryRecord | None = None
            if record.supersedes is not None:
                older_row = connection.execute(
                    "SELECT * FROM memories WHERE memory_id = ?",
                    (str(record.supersedes),),
                ).fetchone()
                if older_row is not None:
                    older = self._row_to_record(older_row)
            if record.superseded_by is not None:
                newer_row = connection.execute(
                    "SELECT * FROM memories WHERE memory_id = ?",
                    (str(record.superseded_by),),
                ).fetchone()
                if newer_row is not None:
                    newer = self._row_to_record(newer_row)

            if older is not None and newer is not None:
                self._update_record(
                    connection,
                    older.model_copy(update={"superseded_by": newer.memory_id}),
                )
                self._update_record(
                    connection,
                    newer.model_copy(update={"supersedes": older.memory_id}),
                )
            elif older is not None:
                restored_status = (
                    MemoryRecordStatus.EXPIRED
                    if older.expires_at is not None and older.expires_at <= utc_now()
                    else MemoryRecordStatus.ACTIVE
                )
                self._update_record(
                    connection,
                    older.model_copy(
                        update={
                            "status": restored_status,
                            "superseded_by": None,
                        }
                    ),
                )
            elif newer is not None:
                self._update_record(
                    connection,
                    newer.model_copy(update={"supersedes": None}),
                )

            connection.execute(
                "DELETE FROM memories WHERE memory_id = ?",
                (str(memory_id),),
            )

    def verify_integrity(self) -> MemoryIntegrity:
        try:
            records = self.list_records()
            by_id = {record.memory_id: record for record in records}
            for record in records:
                if record.supersedes is not None:
                    older = by_id.get(record.supersedes)
                    if older is None:
                        raise MemoryIntegrityError("missing supersedes target")
                    if (
                        older.status is not MemoryRecordStatus.SUPERSEDED
                        or older.superseded_by != record.memory_id
                    ):
                        raise MemoryIntegrityError("broken reverse supersession link")
                if record.superseded_by is not None:
                    newer = by_id.get(record.superseded_by)
                    if newer is None or newer.supersedes != record.memory_id:
                        raise MemoryIntegrityError("broken supersession link")
            active_count = sum(
                record.status is MemoryRecordStatus.ACTIVE for record in records
            )
        except (MemoryIntegrityError, ValidationError, ValueError) as exc:
            return MemoryIntegrity(
                valid=False,
                record_count=0,
                active_count=0,
                first_error=str(exc),
            )
        return MemoryIntegrity(
            valid=True,
            record_count=len(records),
            active_count=active_count,
        )
