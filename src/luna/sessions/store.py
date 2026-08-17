"""SQLite store for durable working-session continuity."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from luna.contracts.base import utc_now
from luna.sessions.models import (
    SessionEntry,
    SessionEntryRole,
    SessionStatus,
    WorkingSession,
    canonical_model_json,
    model_digest,
)

SCHEMA_VERSION = 1


class SessionStoreError(RuntimeError):
    """Base working-session storage failure."""


class SessionNotFoundError(SessionStoreError):
    """Requested working session does not exist."""


class SessionClosedError(SessionStoreError):
    """A closed working session rejected an append."""


class SessionOwnershipError(SessionStoreError):
    """Caller owner binding does not match the durable session owner."""


class SessionIntegrityError(SessionStoreError):
    """Persisted session content failed deterministic integrity validation."""


class SQLiteSessionStore:
    """Persist sessions and append-only visible entries with SQLite WAL + FULL sync."""

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
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            current = int(row["version"]) if row is not None else 0
            if current > SCHEMA_VERSION:
                raise SessionStoreError(
                    f"database schema {current} is newer than runtime {SCHEMA_VERSION}"
                )
            if current < 1:
                connection.execute(
                    """
                    CREATE TABLE working_sessions (
                        session_id TEXT PRIMARY KEY,
                        owner_ref TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        closed_at TEXT,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE session_entries (
                        entry_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL CHECK (sequence >= 1),
                        role TEXT NOT NULL,
                        source_task_id TEXT,
                        created_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        UNIQUE(session_id, sequence),
                        FOREIGN KEY(session_id) REFERENCES working_sessions(session_id)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX session_entries_sequence
                    ON session_entries(session_id, sequence)
                    """
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, utc_now().isoformat()),
                )

    def schema_version(self) -> int:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            return int(row["version"]) if row is not None else 0

    def journal_mode(self) -> str:
        with self._read_connection() as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
            if row is None:
                raise SessionStoreError("SQLite did not report journal mode")
            return str(row[0]).casefold()

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> WorkingSession:
        try:
            session = WorkingSession.model_validate_json(str(row["payload_json"]))
        except ValidationError as exc:
            raise SessionIntegrityError("stored working session is invalid") from exc
        if model_digest(session) != str(row["payload_sha256"]):
            raise SessionIntegrityError("working session digest mismatch")
        if str(session.session_id) != str(row["session_id"]):
            raise SessionIntegrityError("working session ID does not match row identity")
        if session.owner_ref != str(row["owner_ref"]):
            raise SessionIntegrityError("working session owner does not match row identity")
        if session.status.value != str(row["status"]):
            raise SessionIntegrityError("working session status does not match row identity")
        if session.created_at.isoformat() != str(row["created_at"]):
            raise SessionIntegrityError("working session created_at does not match row identity")
        row_closed = str(row["closed_at"]) if row["closed_at"] is not None else None
        session_closed = session.closed_at.isoformat() if session.closed_at is not None else None
        if session_closed != row_closed:
            raise SessionIntegrityError("working session closed_at does not match row identity")
        return session

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> SessionEntry:
        try:
            entry = SessionEntry.model_validate_json(str(row["payload_json"]))
        except ValidationError as exc:
            raise SessionIntegrityError("stored session entry is invalid") from exc
        if model_digest(entry) != str(row["payload_sha256"]):
            raise SessionIntegrityError("session entry digest mismatch")
        if str(entry.entry_id) != str(row["entry_id"]):
            raise SessionIntegrityError("session entry ID does not match row identity")
        if str(entry.session_id) != str(row["session_id"]):
            raise SessionIntegrityError("session entry session ID does not match row identity")
        if entry.sequence != int(row["sequence"]):
            raise SessionIntegrityError("session entry sequence does not match row identity")
        if entry.role.value != str(row["role"]):
            raise SessionIntegrityError("session entry role does not match row identity")
        row_task = str(row["source_task_id"]) if row["source_task_id"] is not None else None
        entry_task = str(entry.source_task_id) if entry.source_task_id is not None else None
        if entry_task != row_task:
            raise SessionIntegrityError("session entry source task does not match row identity")
        if entry.created_at.isoformat() != str(row["created_at"]):
            raise SessionIntegrityError("session entry created_at does not match row identity")
        return entry

    def create_session(self, session: WorkingSession) -> WorkingSession:
        payload_json = canonical_model_json(session)
        payload_sha256 = model_digest(session)
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO working_sessions(
                        session_id,
                        owner_ref,
                        status,
                        created_at,
                        closed_at,
                        payload_json,
                        payload_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(session.session_id),
                        session.owner_ref,
                        session.status.value,
                        session.created_at.isoformat(),
                        session.closed_at.isoformat() if session.closed_at is not None else None,
                        payload_json,
                        payload_sha256,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise SessionStoreError("working session already exists") from exc
        return session

    def load_session(self, session_id: UUID) -> WorkingSession:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM working_sessions WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
        if row is None:
            raise SessionNotFoundError(f"working session not found: {session_id}")
        return self._session_from_row(row)

    def load_session_state(
        self,
        session_id: UUID,
    ) -> tuple[WorkingSession, tuple[SessionEntry, ...]]:
        """Read one complete session owner state from one SQLite snapshot."""
        with self._read_connection() as connection:
            connection.execute("BEGIN")
            try:
                session_row = connection.execute(
                    "SELECT * FROM working_sessions WHERE session_id = ?",
                    (str(session_id),),
                ).fetchone()
                if session_row is None:
                    raise SessionNotFoundError(
                        f"working session not found: {session_id}"
                    )
                session = self._session_from_row(session_row)
                entry_rows = connection.execute(
                    "SELECT * FROM session_entries "
                    "WHERE session_id = ? ORDER BY sequence ASC",
                    (str(session_id),),
                ).fetchall()
                entries = tuple(self._entry_from_row(row) for row in entry_rows)
                sequences = tuple(entry.sequence for entry in entries)
                if sequences != tuple(range(1, len(entries) + 1)):
                    raise SessionIntegrityError(
                        "session entry sequence contains a gap"
                    )
                return session, entries
            finally:
                connection.rollback()

    def append_entry(
        self,
        *,
        session_id: UUID,
        owner_ref: str,
        role: SessionEntryRole,
        content: str,
        source_task_id: UUID | None,
        redactions_applied: tuple[str, ...],
    ) -> SessionEntry:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM working_sessions WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
            if row is None:
                raise SessionNotFoundError(f"working session not found: {session_id}")
            session = self._session_from_row(row)
            if session.owner_ref != owner_ref:
                raise SessionOwnershipError("working session owner binding mismatch")
            if session.status is not SessionStatus.OPEN:
                raise SessionClosedError("closed working session cannot accept new entries")
            sequence_row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence "
                "FROM session_entries WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
            sequence = int(sequence_row["sequence"]) + 1 if sequence_row is not None else 1
            entry = SessionEntry(
                session_id=session_id,
                sequence=sequence,
                role=role,
                content=content,
                source_task_id=source_task_id,
                redactions_applied=redactions_applied,
            )
            connection.execute(
                """
                INSERT INTO session_entries(
                    entry_id,
                    session_id,
                    sequence,
                    role,
                    source_task_id,
                    created_at,
                    payload_json,
                    payload_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(entry.entry_id),
                    str(entry.session_id),
                    entry.sequence,
                    entry.role.value,
                    str(entry.source_task_id) if entry.source_task_id is not None else None,
                    entry.created_at.isoformat(),
                    canonical_model_json(entry),
                    model_digest(entry),
                ),
            )
        return entry

    def list_entries(self, session_id: UUID) -> tuple[SessionEntry, ...]:
        return self.load_session_state(session_id)[1]

    def close_session(self, *, session_id: UUID, owner_ref: str) -> WorkingSession:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM working_sessions WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
            if row is None:
                raise SessionNotFoundError(f"working session not found: {session_id}")
            current = self._session_from_row(row)
            if current.owner_ref != owner_ref:
                raise SessionOwnershipError("working session owner binding mismatch")
            if current.status is SessionStatus.CLOSED:
                return current
            updated = current.model_copy(
                update={"status": SessionStatus.CLOSED, "closed_at": utc_now()}
            )
            updated = WorkingSession.model_validate(updated.model_dump(mode="python"))
            connection.execute(
                """
                UPDATE working_sessions
                SET status = ?, closed_at = ?, payload_json = ?, payload_sha256 = ?
                WHERE session_id = ?
                """,
                (
                    updated.status.value,
                    updated.closed_at.isoformat() if updated.closed_at is not None else None,
                    canonical_model_json(updated),
                    model_digest(updated),
                    str(session_id),
                ),
            )
        return updated
