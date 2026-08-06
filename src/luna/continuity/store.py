"""SQLite WAL store for atomic task state and immutable checkpoints."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from luna.continuity.models import (
    CheckpointEnvelope,
    ContinuityIntegrity,
    StoredCheckpoint,
    canonical_model_json,
    model_digest,
)
from luna.contracts.base import utc_now
from luna.contracts.enums import TaskPhase
from luna.contracts.state import TaskState

SCHEMA_VERSION = 1


class ContinuityError(RuntimeError):
    """Base continuity-store failure."""


class ContinuityConflictError(ContinuityError):
    """Optimistic concurrency or immutable-terminal conflict."""


class CheckpointNotFoundError(ContinuityError):
    """Requested checkpoint or task checkpoint chain does not exist."""


class ContinuityIntegrityError(ContinuityError):
    """Persisted checkpoint or state digest is invalid."""


class SQLiteContinuityStore:
    """Open short-lived SQLite connections with WAL and FULL sync."""

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
        """Yield one read connection and always close its Windows file handle."""
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
                raise ContinuityError(
                    f"database schema {current} is newer than runtime "
                    f"{SCHEMA_VERSION}"
                )
            if current < 1:
                connection.execute(
                    """
                    CREATE TABLE checkpoints (
                        checkpoint_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        state_revision INTEGER NOT NULL,
                        terminal INTEGER NOT NULL CHECK (terminal IN (0, 1)),
                        runtime_revision TEXT NOT NULL,
                        workspace_fingerprint TEXT NOT NULL,
                        environment_fingerprint TEXT NOT NULL,
                        previous_checkpoint_id TEXT,
                        created_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        FOREIGN KEY(previous_checkpoint_id)
                            REFERENCES checkpoints(checkpoint_id)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX checkpoints_task_created
                    ON checkpoints(task_id, created_at, checkpoint_id)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE task_states (
                        task_id TEXT PRIMARY KEY,
                        revision INTEGER NOT NULL,
                        phase TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        terminal INTEGER NOT NULL CHECK (terminal IN (0, 1))
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    "VALUES (?, ?)",
                    (1, utc_now().isoformat()),
                )

    def schema_version(self) -> int:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version "
                "FROM schema_migrations"
            ).fetchone()
            return int(row["version"]) if row is not None else 0

    def journal_mode(self) -> str:
        with self._read_connection() as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
            if row is None:
                raise ContinuityError("SQLite did not report journal mode")
            return str(row[0]).casefold()

    def save_checkpoint(self, envelope: CheckpointEnvelope) -> StoredCheckpoint:
        payload_json = canonical_model_json(envelope)
        payload_sha256 = model_digest(envelope)
        state_json = canonical_model_json(envelope.state)
        state_sha256 = model_digest(envelope.state)
        task_id = str(envelope.state.task_id)

        with self._transaction() as connection:
            latest = connection.execute(
                """
                SELECT checkpoint_id, terminal
                FROM checkpoints
                WHERE task_id = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            current_state = connection.execute(
                "SELECT revision, terminal FROM task_states WHERE task_id = ?",
                (task_id,),
            ).fetchone()

            if latest is None:
                if envelope.previous_checkpoint_id is not None:
                    raise ContinuityConflictError(
                        "first checkpoint cannot reference a previous checkpoint"
                    )
            else:
                if bool(latest["terminal"]):
                    raise ContinuityConflictError(
                        "terminal checkpoint is immutable; open a new task"
                    )
                if str(envelope.previous_checkpoint_id) != str(
                    latest["checkpoint_id"]
                ):
                    raise ContinuityConflictError(
                        "previous_checkpoint_id is not the latest checkpoint"
                    )

            if (
                current_state is not None
                and envelope.state.revision <= int(current_state["revision"])
            ):
                raise ContinuityConflictError(
                    "checkpoint state revision must advance persisted state"
                )
            if current_state is not None and bool(current_state["terminal"]):
                raise ContinuityConflictError(
                    "terminal task state is immutable; open a new task"
                )

            connection.execute(
                """
                INSERT INTO checkpoints(
                    checkpoint_id,
                    task_id,
                    state_revision,
                    terminal,
                    runtime_revision,
                    workspace_fingerprint,
                    environment_fingerprint,
                    previous_checkpoint_id,
                    created_at,
                    payload_json,
                    payload_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(envelope.checkpoint.checkpoint_id),
                    task_id,
                    envelope.state.revision,
                    int(envelope.terminal),
                    envelope.runtime_revision,
                    envelope.checkpoint.workspace_fingerprint,
                    envelope.checkpoint.environment_fingerprint,
                    (
                        str(envelope.previous_checkpoint_id)
                        if envelope.previous_checkpoint_id is not None
                        else None
                    ),
                    envelope.checkpoint.created_at.isoformat(),
                    payload_json,
                    payload_sha256,
                ),
            )
            connection.execute(
                """
                INSERT INTO task_states(
                    task_id,
                    revision,
                    phase,
                    payload_json,
                    payload_sha256,
                    updated_at,
                    terminal
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    revision = excluded.revision,
                    phase = excluded.phase,
                    payload_json = excluded.payload_json,
                    payload_sha256 = excluded.payload_sha256,
                    updated_at = excluded.updated_at,
                    terminal = excluded.terminal
                """,
                (
                    task_id,
                    envelope.state.revision,
                    envelope.state.phase.value,
                    state_json,
                    state_sha256,
                    envelope.state.updated_at.isoformat(),
                    int(envelope.terminal),
                ),
            )

        return StoredCheckpoint(
            envelope=envelope,
            payload_sha256=payload_sha256,
        )

    @staticmethod
    def _stored_from_row(row: sqlite3.Row) -> StoredCheckpoint:
        payload_json = str(row["payload_json"])
        payload_sha256 = str(row["payload_sha256"])
        try:
            envelope = CheckpointEnvelope.model_validate_json(payload_json)
            return StoredCheckpoint(
                envelope=envelope,
                payload_sha256=payload_sha256,
            )
        except (ValidationError, ValueError) as exc:
            raise ContinuityIntegrityError(
                f"invalid checkpoint {row['checkpoint_id']}: {exc}"
            ) from exc

    def load_checkpoint(self, checkpoint_id: UUID) -> StoredCheckpoint:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM checkpoints WHERE checkpoint_id = ?",
                (str(checkpoint_id),),
            ).fetchone()
        if row is None:
            raise CheckpointNotFoundError(f"checkpoint not found: {checkpoint_id}")
        return self._stored_from_row(row)

    def load_latest(self, task_id: UUID) -> StoredCheckpoint:
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM checkpoints
                WHERE task_id = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (str(task_id),),
            ).fetchone()
        if row is None:
            raise CheckpointNotFoundError(f"no checkpoint for task: {task_id}")
        return self._stored_from_row(row)

    def list_checkpoints(self, task_id: UUID) -> tuple[StoredCheckpoint, ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM checkpoints
                WHERE task_id = ?
                ORDER BY rowid
                """,
                (str(task_id),),
            ).fetchall()
        return tuple(self._stored_from_row(row) for row in rows)

    def load_task_state(self, task_id: UUID) -> TaskState:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM task_states WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
        if row is None:
            raise ContinuityError(f"task state not found: {task_id}")
        payload_json = str(row["payload_json"])
        payload_sha256 = str(row["payload_sha256"])
        try:
            state = TaskState.model_validate_json(payload_json)
        except (ValidationError, ValueError) as exc:
            raise ContinuityIntegrityError(
                f"invalid task state {task_id}: {exc}"
            ) from exc
        if model_digest(state) != payload_sha256:
            raise ContinuityIntegrityError(
                f"task state digest mismatch: {task_id}"
            )
        return state

    def resume_checkpoint(
        self,
        *,
        stored: StoredCheckpoint,
        resumed_state: TaskState,
    ) -> None:
        envelope = stored.envelope
        if envelope.terminal:
            raise ContinuityConflictError("terminal checkpoint cannot resume")
        expected_state_digest = model_digest(envelope.state)
        resumed_json = canonical_model_json(resumed_state)
        resumed_digest = model_digest(resumed_state)

        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT revision, phase, payload_sha256, terminal
                FROM task_states
                WHERE task_id = ?
                """,
                (str(envelope.state.task_id),),
            ).fetchone()
            if row is None:
                raise ContinuityConflictError(
                    "persisted task state disappeared before resume"
                )
            if bool(row["terminal"]):
                raise ContinuityConflictError("terminal task cannot resume")
            if (
                int(row["revision"]) != envelope.state.revision
                or str(row["phase"]) != TaskPhase.CHECKPOINTED.value
                or str(row["payload_sha256"]) != expected_state_digest
            ):
                raise ContinuityConflictError(
                    "checkpoint is stale or has already resumed"
                )

            cursor = connection.execute(
                """
                UPDATE task_states
                SET revision = ?,
                    phase = ?,
                    payload_json = ?,
                    payload_sha256 = ?,
                    updated_at = ?,
                    terminal = 0
                WHERE task_id = ? AND revision = ?
                """,
                (
                    resumed_state.revision,
                    resumed_state.phase.value,
                    resumed_json,
                    resumed_digest,
                    resumed_state.updated_at.isoformat(),
                    str(resumed_state.task_id),
                    envelope.state.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ContinuityConflictError(
                    "concurrent resume changed the task state"
                )

    def verify_integrity(self) -> ContinuityIntegrity:
        checkpoint_count = 0
        state_count = 0
        try:
            with self._read_connection() as connection:
                checkpoint_rows = connection.execute(
                    "SELECT * FROM checkpoints ORDER BY task_id, rowid"
                ).fetchall()
                state_rows = connection.execute(
                    "SELECT * FROM task_states ORDER BY task_id"
                ).fetchall()

            previous_by_task: dict[str, str | None] = {}
            for row in checkpoint_rows:
                stored = self._stored_from_row(row)
                envelope = stored.envelope
                task_key = str(envelope.state.task_id)
                expected_previous = previous_by_task.get(task_key)
                actual_previous = (
                    str(envelope.previous_checkpoint_id)
                    if envelope.previous_checkpoint_id is not None
                    else None
                )
                if actual_previous != expected_previous:
                    raise ContinuityIntegrityError(
                        f"checkpoint chain mismatch for task {task_key}"
                    )
                previous_by_task[task_key] = str(
                    envelope.checkpoint.checkpoint_id
                )
                checkpoint_count += 1

            for row in state_rows:
                state = TaskState.model_validate_json(str(row["payload_json"]))
                if model_digest(state) != str(row["payload_sha256"]):
                    raise ContinuityIntegrityError(
                        f"task state digest mismatch: {row['task_id']}"
                    )
                if state.revision != int(row["revision"]):
                    raise ContinuityIntegrityError(
                        f"task state revision mismatch: {row['task_id']}"
                    )
                if state.phase.value != str(row["phase"]):
                    raise ContinuityIntegrityError(
                        f"task state phase mismatch: {row['task_id']}"
                    )
                state_count += 1
        except (
            ContinuityError,
            ValidationError,
            ValueError,
            sqlite3.DatabaseError,
        ) as exc:
            return ContinuityIntegrity(
                valid=False,
                database_schema_version=self.schema_version(),
                checkpoint_count=checkpoint_count,
                task_state_count=state_count,
                first_error=str(exc),
            )

        return ContinuityIntegrity(
            valid=True,
            database_schema_version=self.schema_version(),
            checkpoint_count=checkpoint_count,
            task_state_count=state_count,
        )
