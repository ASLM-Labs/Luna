"""SQLite-backed deterministic C-011 S2 fake backend.

This module persists frozen scripts and observations only.  It never calls a model,
tool, network endpoint, subprocess, worker, or Luna runtime.  A durable reservation
without a result is deliberately treated as in-doubt and is never replayed blindly.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from luna.parallel_cognition.events import (
    FakeBackendRequest,
    FakeBackendResult,
    FakeBackendScript,
    FakeInvocationRecord,
    FakeInvocationState,
)
from luna.parallel_cognition.models import canonical_contract_json, contract_sha256

FAKE_BACKEND_SCHEMA_VERSION = 1


class FakeBackendError(RuntimeError):
    """Base failure for the isolated deterministic backend."""


class FakeBackendConflict(FakeBackendError):
    """An idempotency key or immutable identity was reused with new content."""


class FakeBackendInDoubt(FakeBackendError):
    """A prior reservation exists without a durable result; replay is forbidden."""


class FakeBackendIntegrity(FakeBackendError):
    """Persisted fake-backend content failed validation or digest checks."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS fake_backend_schema (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS fake_backend_invocations (
    idempotency_key TEXT PRIMARY KEY,
    invocation_id TEXT NOT NULL UNIQUE,
    request_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    script_sha256 TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('RESERVED', 'COMPLETED')),
    reserved_at TEXT NOT NULL,
    completed_at TEXT,
    result_id TEXT,
    result_sha256 TEXT,
    execution_count INTEGER NOT NULL CHECK (execution_count IN (0, 1)),
    record_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    CHECK (
        (state = 'RESERVED' AND completed_at IS NULL AND result_id IS NULL
            AND result_sha256 IS NULL AND execution_count = 0)
        OR
        (state = 'COMPLETED' AND completed_at IS NOT NULL AND result_id IS NOT NULL
            AND result_sha256 IS NOT NULL AND execution_count = 1)
    )
);
"""


class SQLiteIdempotentFakeBackend:
    """Persist one idempotent fake completion and fail closed after uncertainty."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        backend_id: str = "fake:c011-s2",
        profile_id: str = "profile:deterministic",
    ) -> None:
        if not backend_id.strip() or not profile_id.strip():
            raise ValueError("fake backend and profile IDs must not be blank")
        self.path = Path(database_path).resolve()
        self.backend_id = backend_id.strip()
        self.profile_id = profile_id.strip()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FakeBackendError("failed to create fake backend directory") from exc
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA busy_timeout=5000")
            row = connection.execute("PRAGMA journal_mode=WAL").fetchone()
            if row is None or str(row[0]).casefold() != "wal":
                raise FakeBackendError("SQLite did not enable WAL journal mode")
            return connection
        except FakeBackendError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            raise FakeBackendError("failed to open fake backend database") from exc

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        except FakeBackendError:
            raise
        except sqlite3.DatabaseError as exc:
            raise FakeBackendError("fake backend read failed") from exc
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except FakeBackendError:
            connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            connection.rollback()
            raise FakeBackendError("fake backend transaction failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._transaction() as connection:
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(statement)
            rows = connection.execute(
                "SELECT version FROM fake_backend_schema ORDER BY version"
            ).fetchall()
            versions = tuple(int(row["version"]) for row in rows)
            if not versions:
                connection.execute(
                    "INSERT INTO fake_backend_schema(version) VALUES (?)",
                    (FAKE_BACKEND_SCHEMA_VERSION,),
                )
            elif versions != (FAKE_BACKEND_SCHEMA_VERSION,):
                raise FakeBackendError(
                    f"unsupported fake backend schema versions: {versions!r}"
                )

    @staticmethod
    def _validated_request(request: FakeBackendRequest) -> FakeBackendRequest:
        return FakeBackendRequest.model_validate(request.model_dump(mode="json"))

    @staticmethod
    def _validated_script(script: FakeBackendScript) -> FakeBackendScript:
        return FakeBackendScript.model_validate(script.model_dump(mode="json"))

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> FakeInvocationRecord:
        try:
            record = FakeInvocationRecord.model_validate_json(str(row["record_json"]))
            request_sha256 = contract_sha256(record.request)
            result = record.result
            result_id = None if result is None else result.result_id
            result_sha256 = None if result is None else contract_sha256(result)
            columns = (
                str(row["idempotency_key"]),
                str(row["invocation_id"]),
                str(row["request_id"]),
                str(row["request_sha256"]),
                str(row["script_sha256"]),
                str(row["state"]),
                str(row["reserved_at"]),
                None if row["completed_at"] is None else str(row["completed_at"]),
                None if row["result_id"] is None else str(row["result_id"]),
                None if row["result_sha256"] is None else str(row["result_sha256"]),
                int(row["execution_count"]),
                str(row["record_sha256"]),
            )
            expected = (
                record.idempotency_key,
                str(record.invocation_id),
                record.request.request_id,
                request_sha256,
                record.request.script_sha256,
                record.state.value,
                record.reserved_at.isoformat(),
                None if record.completed_at is None else record.completed_at.isoformat(),
                result_id,
                result_sha256,
                record.durable_completion_count,
                record.record_sha256,
            )
            if columns != expected:
                raise ValueError("fake invocation columns do not match record content")
            return record
        except (ValidationError, ValueError, TypeError) as exc:
            raise FakeBackendIntegrity(
                "persisted fake invocation failed integrity validation"
            ) from exc

    @staticmethod
    def _write_record(
        connection: sqlite3.Connection,
        record: FakeInvocationRecord,
        *,
        insert: bool,
    ) -> None:
        result = record.result
        result_id = None if result is None else result.result_id
        result_sha256 = None if result is None else contract_sha256(result)
        values = (
            str(record.invocation_id),
            record.request.request_id,
            contract_sha256(record.request),
            record.request.script_sha256,
            record.state.value,
            record.reserved_at.isoformat(),
            None if record.completed_at is None else record.completed_at.isoformat(),
            result_id,
            result_sha256,
            record.durable_completion_count,
            canonical_contract_json(record),
            record.record_sha256,
            record.idempotency_key,
        )
        if insert:
            connection.execute(
                """
                INSERT INTO fake_backend_invocations(
                    invocation_id, request_id, request_sha256, script_sha256,
                    state, reserved_at, completed_at, result_id, result_sha256,
                    execution_count, record_json, record_sha256, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        else:
            cursor = connection.execute(
                """
                UPDATE fake_backend_invocations SET
                    invocation_id = ?, request_id = ?, request_sha256 = ?,
                    script_sha256 = ?, state = ?, reserved_at = ?, completed_at = ?,
                    result_id = ?, result_sha256 = ?, execution_count = ?,
                    record_json = ?, record_sha256 = ?
                WHERE idempotency_key = ?
                """,
                values,
            )
            if cursor.rowcount != 1:
                raise FakeBackendIntegrity("fake invocation update lost its row")

    @classmethod
    def _lookup_in_transaction(
        cls,
        connection: sqlite3.Connection,
        idempotency_key: str,
    ) -> FakeInvocationRecord | None:
        row = connection.execute(
            "SELECT * FROM fake_backend_invocations WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return None if row is None else cls._record_from_row(row)

    @staticmethod
    def _require_same_request(
        existing: FakeInvocationRecord,
        request: FakeBackendRequest,
    ) -> None:
        if existing.request != request:
            raise FakeBackendConflict(
                "idempotency key is already bound to another fake request"
            )

    def reserve(
        self,
        request: FakeBackendRequest,
        *,
        idempotency_key: str,
        reserved_at: datetime | None = None,
    ) -> FakeInvocationRecord:
        """Durably reserve a request without performing or simulating execution."""

        request = self._validated_request(request)
        if not idempotency_key.strip():
            raise ValueError("fake backend idempotency key must not be blank")
        observed_at = request.requested_at if reserved_at is None else reserved_at
        with self._transaction() as connection:
            existing = self._lookup_in_transaction(connection, idempotency_key)
            if existing is not None:
                self._require_same_request(existing, request)
                return existing
            record = FakeInvocationRecord(
                invocation_id=uuid4(),
                idempotency_key=idempotency_key,
                request=request,
                state=FakeInvocationState.RESERVED,
                reserved_at=observed_at,
                durable_completion_count=0,
            )
            self._write_record(connection, record, insert=True)
            return record

    def execute(
        self,
        request: FakeBackendRequest,
        script: FakeBackendScript,
        *,
        idempotency_key: str,
        reserved_at: datetime | None = None,
    ) -> FakeBackendResult:
        """Materialize one frozen script, or return the exact cached result."""

        request = self._validated_request(request)
        script = self._validated_script(script)
        if not idempotency_key.strip():
            raise ValueError("fake backend idempotency key must not be blank")
        if request.script_sha256 != contract_sha256(script):
            raise FakeBackendConflict("fake script does not match request digest")
        if request.attempt.backend_id != self.backend_id:
            raise FakeBackendConflict("request attempt uses another backend")
        if request.attempt.profile_id != self.profile_id:
            raise FakeBackendConflict("request attempt uses another profile")
        observed_at = request.requested_at if reserved_at is None else reserved_at

        with self._transaction() as connection:
            existing = self._lookup_in_transaction(connection, idempotency_key)
            if existing is not None:
                self._require_same_request(existing, request)
                if existing.state is FakeInvocationState.RESERVED:
                    raise FakeBackendInDoubt(
                        "fake invocation is reserved without a result; replay denied"
                    )
                if existing.result is None:
                    raise FakeBackendIntegrity(
                        "completed fake invocation has no result"
                    )
                if existing.result.script != script:
                    raise FakeBackendConflict(
                        "cached fake invocation is bound to another script"
                    )
                return existing.result

            result = FakeBackendResult.from_request_script(
                request,
                script,
                backend_id=self.backend_id,
                profile_id=self.profile_id,
            )
            record = FakeInvocationRecord(
                invocation_id=uuid4(),
                idempotency_key=idempotency_key,
                request=request,
                state=FakeInvocationState.COMPLETED,
                reserved_at=observed_at,
                completed_at=script.cleanup_at,
                result=result,
                durable_completion_count=1,
            )
            self._write_record(connection, record, insert=True)
            return result

    def complete_reserved_for_test(
        self,
        idempotency_key: str,
        script: FakeBackendScript,
    ) -> FakeBackendResult:
        """Explicitly complete an in-doubt fixture; production recovery must not call it."""

        script = self._validated_script(script)
        with self._transaction() as connection:
            existing = self._lookup_in_transaction(connection, idempotency_key)
            if existing is None:
                raise FakeBackendConflict("fake invocation reservation does not exist")
            if existing.request.script_sha256 != contract_sha256(script):
                raise FakeBackendConflict("fake script does not match reservation")
            if existing.state is FakeInvocationState.COMPLETED:
                if existing.result is None:
                    raise FakeBackendIntegrity(
                        "completed fake invocation has no result"
                    )
                if existing.result.script != script:
                    raise FakeBackendConflict(
                        "completed fake invocation uses another script"
                    )
                return existing.result
            result = FakeBackendResult.from_request_script(
                existing.request,
                script,
                backend_id=self.backend_id,
                profile_id=self.profile_id,
            )
            completed = FakeInvocationRecord(
                invocation_id=existing.invocation_id,
                idempotency_key=existing.idempotency_key,
                request=existing.request,
                state=FakeInvocationState.COMPLETED,
                reserved_at=existing.reserved_at,
                completed_at=script.cleanup_at,
                result=result,
                durable_completion_count=1,
            )
            self._write_record(connection, completed, insert=False)
            return result

    def lookup(self, idempotency_key: str) -> FakeInvocationRecord | None:
        with self._read_connection() as connection:
            return self._lookup_in_transaction(connection, idempotency_key)

    def durable_completion_count(self) -> int:
        """Return the number of committed fake completion records."""

        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(execution_count), 0) FROM fake_backend_invocations"
            ).fetchone()
            if row is None:
                raise FakeBackendIntegrity("completion counter query returned no row")
            return int(row[0])

    def verify_integrity(self) -> bool:
        """Revalidate SQLite structure and every persisted immutable record."""

        with self._read_connection() as connection:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).casefold() != "ok":
                raise FakeBackendIntegrity("SQLite quick_check failed")
            rows = connection.execute(
                "SELECT * FROM fake_backend_invocations ORDER BY idempotency_key"
            ).fetchall()
            for row in rows:
                self._record_from_row(row)
        return True

    def journal_mode(self) -> str:
        with self._read_connection() as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
            if row is None:
                raise FakeBackendError("SQLite did not report journal mode")
            return str(row[0]).casefold()


__all__ = [
    "FAKE_BACKEND_SCHEMA_VERSION",
    "FakeBackendConflict",
    "FakeBackendError",
    "FakeBackendInDoubt",
    "FakeBackendIntegrity",
    "SQLiteIdempotentFakeBackend",
]
