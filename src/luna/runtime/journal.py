"""Durable Phase 12E control and side-effect journal.

The journal is intentionally separate from the Phase 8 checkpoint database.  It is a
write-ahead fence around side effects: a process crash may lose in-memory state, but it
must not make Luna repeat an action whose handler may already have run.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.state import TaskState
from luna.planning.models import AttemptBasis
from luna.tools.models import DispatchOutcome, ToolRequest, ToolResultStatus

JOURNAL_SCHEMA_VERSION = 2


class RuntimeJournalError(RuntimeError):
    """Base error for durable Phase 12E runtime journaling."""


class RuntimeJournalConflictError(RuntimeJournalError):
    """Raised when an execution fence is advanced from an unexpected state."""


class RuntimeControlCommand(StrEnum):
    """Owner/runtime commands acknowledged only at safe loop boundaries."""

    SUSPEND = "SUSPEND"
    CANCEL = "CANCEL"


class RuntimeControlRecord(LunaContractModel):
    """Durable request to suspend or cancel one task."""

    control_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    command: RuntimeControlCommand
    reason: str = Field(default="owner requested control change", min_length=1, max_length=2000)
    requested_at: datetime = Field(default_factory=utc_now)
    acknowledged_at: datetime | None = None

    @field_validator("requested_at", "acknowledged_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_acknowledgement(self) -> RuntimeControlRecord:
        if self.acknowledged_at is not None and self.acknowledged_at < self.requested_at:
            raise ValueError("control acknowledgement cannot precede request")
        return self


class RuntimeObservationRecord(LunaContractModel):
    """Durable bounded dispatch evidence fed back into later model turns."""

    observation_id: UUID
    task_id: UUID
    trace_id: UUID
    outcome: DispatchOutcome
    recorded_at: datetime = Field(default_factory=utc_now)

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_links(self) -> RuntimeObservationRecord:
        if self.observation_id != self.outcome.observation.observation_id:
            raise ValueError("observation_id must match dispatch outcome")
        if self.task_id != self.outcome.request.task_id:
            raise ValueError("task_id must match dispatch request")
        if self.trace_id != self.outcome.request.trace_id:
            raise ValueError("trace_id must match dispatch request")
        return self

    @classmethod
    def from_outcome(cls, outcome: DispatchOutcome) -> RuntimeObservationRecord:
        return cls(
            observation_id=outcome.observation.observation_id,
            task_id=outcome.request.task_id,
            trace_id=outcome.request.trace_id,
            outcome=outcome,
        )


class SideEffectStage(StrEnum):
    """Write-ahead lifecycle for one potentially non-idempotent action."""

    PREPARED = "PREPARED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    OBSERVED = "OBSERVED"
    CHECKPOINTED = "CHECKPOINTED"
    ABORTED = "ABORTED"


_TERMINAL_SIDE_EFFECT_STAGES = {
    SideEffectStage.CHECKPOINTED,
    SideEffectStage.ABORTED,
}


class SideEffectReceipt(LunaContractModel):
    """Durable fence proving how far one side-effect action progressed."""

    receipt_id: UUID = Field(default_factory=uuid4)
    idempotency_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: UUID
    trace_id: UUID
    step_id: UUID
    proposal_id: UUID
    request: ToolRequest
    attempt_basis: AttemptBasis
    pre_action_state: TaskState
    execution_workspace_root: str = Field(min_length=1, max_length=4000)
    isolation_mode: str = Field(default="NONE", min_length=1, max_length=40)
    stage: SideEffectStage = SideEffectStage.PREPARED
    outcome: DispatchOutcome | None = None
    post_action_state: TaskState | None = None
    checkpoint_id: UUID | None = None
    abort_reason: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    observed_at: datetime | None = None
    checkpointed_at: datetime | None = None
    aborted_at: datetime | None = None

    @field_validator(
        "created_at",
        "started_at",
        "completed_at",
        "observed_at",
        "checkpointed_at",
        "aborted_at",
    )
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_links_and_stage(self) -> SideEffectReceipt:
        if self.request.task_id != self.task_id or self.request.trace_id != self.trace_id:
            raise ValueError("side-effect request IDs must match receipt")
        if self.pre_action_state.task_id != self.task_id:
            raise ValueError("pre_action_state task_id must match receipt")
        if self.stage in {
            SideEffectStage.STARTED,
            SideEffectStage.COMPLETED,
            SideEffectStage.OBSERVED,
            SideEffectStage.CHECKPOINTED,
        } and self.started_at is None:
            raise ValueError("started side effect requires started_at")
        if self.stage in {
            SideEffectStage.COMPLETED,
            SideEffectStage.OBSERVED,
            SideEffectStage.CHECKPOINTED,
        }:
            if self.completed_at is None or self.outcome is None:
                raise ValueError("completed side effect requires outcome and completed_at")
            if self.outcome.request.request_id != self.request.request_id:
                raise ValueError("dispatch outcome must reference journaled request")
        elif self.outcome is not None or self.completed_at is not None:
            raise ValueError("non-completed side effect cannot carry dispatch outcome")
        if self.stage in {SideEffectStage.OBSERVED, SideEffectStage.CHECKPOINTED}:
            if self.observed_at is None or self.post_action_state is None:
                raise ValueError("observed side effect requires post_action_state")
            if self.post_action_state.task_id != self.task_id:
                raise ValueError("post_action_state task_id must match receipt")
            assert self.outcome is not None
            if (
                self.outcome.observation.observation_id
                not in self.post_action_state.observation_ids
            ):
                raise ValueError("post_action_state must include dispatch observation")
        elif self.post_action_state is not None or self.observed_at is not None:
            raise ValueError("unobserved side effect cannot carry post_action_state")
        if self.stage is SideEffectStage.CHECKPOINTED:
            if self.checkpoint_id is None or self.checkpointed_at is None:
                raise ValueError("checkpointed side effect requires checkpoint metadata")
        elif self.checkpoint_id is not None or self.checkpointed_at is not None:
            raise ValueError("non-checkpointed side effect cannot carry checkpoint metadata")
        if self.stage is SideEffectStage.ABORTED:
            if self.abort_reason is None or self.aborted_at is None:
                raise ValueError("aborted side effect requires abort reason and timestamp")
            if self.started_at is not None:
                raise ValueError("a started side effect cannot be marked ABORTED")
        elif self.abort_reason is not None or self.aborted_at is not None:
            raise ValueError("non-aborted side effect cannot carry abort metadata")
        return self

    @property
    def terminal(self) -> bool:
        return self.stage in _TERMINAL_SIDE_EFFECT_STAGES

    @property
    def succeeded(self) -> bool | None:
        if self.outcome is None:
            return None
        return self.outcome.result.status is ToolResultStatus.SUCCESS


def _canonical_json(model: LunaContractModel) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(model: LunaContractModel) -> str:
    return sha256(_canonical_json(model).encode("utf-8")).hexdigest()


class SQLiteRuntimeJournal:
    """Small SQLite WAL journal for execution fences and safe control commands."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
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
                CREATE TABLE IF NOT EXISTS journal_schema (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM journal_schema"
            ).fetchone()
            current = int(row["version"]) if row is not None else 0
            if current > JOURNAL_SCHEMA_VERSION:
                raise RuntimeJournalError(
                    f"runtime journal schema {current} is newer than "
                    f"{JOURNAL_SCHEMA_VERSION}"
                )
            if current < 1:
                connection.execute(
                    """
                    CREATE TABLE side_effect_receipts (
                        idempotency_key TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        semantic_fingerprint TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX side_effect_task_semantic
                    ON side_effect_receipts(task_id, semantic_fingerprint)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE runtime_controls (
                        control_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        command TEXT NOT NULL,
                        acknowledged INTEGER NOT NULL CHECK (acknowledged IN (0, 1)),
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        requested_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX runtime_controls_task_requested
                    ON runtime_controls(task_id, requested_at, control_id)
                    """
                )
                connection.execute(
                    "INSERT INTO journal_schema(version, applied_at) VALUES (?, ?)",
                    (1, utc_now().isoformat()),
                )
            if current < 2:
                connection.execute(
                    """
                    CREATE TABLE runtime_observations (
                        observation_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        trace_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        recorded_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX runtime_observations_task_recorded
                    ON runtime_observations(task_id, recorded_at, observation_id)
                    """
                )
                connection.execute(
                    "INSERT INTO journal_schema(version, applied_at) VALUES (?, ?)",
                    (2, utc_now().isoformat()),
                )

    def schema_version(self) -> int:
        """Return the applied runtime-journal schema version."""
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM journal_schema"
            ).fetchone()
        return int(row["version"]) if row is not None else 0

    @staticmethod
    def _receipt_from_row(row: sqlite3.Row) -> SideEffectReceipt:
        payload = str(row["payload_json"])
        receipt = SideEffectReceipt.model_validate_json(payload)
        if _digest(receipt) != str(row["payload_sha256"]):
            raise RuntimeJournalError(
                f"side-effect receipt digest mismatch: {row['idempotency_key']}"
            )
        return receipt

    @staticmethod
    def _control_from_row(row: sqlite3.Row) -> RuntimeControlRecord:
        payload = str(row["payload_json"])
        record = RuntimeControlRecord.model_validate_json(payload)
        if _digest(record) != str(row["payload_sha256"]):
            raise RuntimeJournalError(
                f"runtime control digest mismatch: {row['control_id']}"
            )
        return record

    @staticmethod
    def _observation_from_row(row: sqlite3.Row) -> RuntimeObservationRecord:
        payload = str(row["payload_json"])
        record = RuntimeObservationRecord.model_validate_json(payload)
        if _digest(record) != str(row["payload_sha256"]):
            raise RuntimeJournalError(
                f"runtime observation digest mismatch: {row['observation_id']}"
            )
        return record

    def record_outcome(self, outcome: DispatchOutcome) -> RuntimeObservationRecord:
        """Persist bounded dispatch evidence idempotently for later reevaluation."""
        record = RuntimeObservationRecord.from_outcome(outcome)
        payload = _canonical_json(record)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM runtime_observations WHERE observation_id = ?",
                (str(record.observation_id),),
            ).fetchone()
            if existing is not None:
                current = self._observation_from_row(existing)
                if current.outcome != record.outcome:
                    raise RuntimeJournalConflictError(
                        "observation ID already exists with different dispatch evidence"
                    )
                return current
            connection.execute(
                """
                INSERT INTO runtime_observations(
                    observation_id,
                    task_id,
                    trace_id,
                    payload_json,
                    payload_sha256,
                    recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.observation_id),
                    str(record.task_id),
                    str(record.trace_id),
                    payload,
                    _digest(record),
                    record.recorded_at.isoformat(),
                ),
            )
        return record

    def list_observations(
        self,
        task_id: UUID,
        *,
        limit: int = 8,
    ) -> tuple[RuntimeObservationRecord, ...]:
        """Return the most recent bounded observations in chronological order."""
        if limit < 1:
            raise ValueError("observation limit must be positive")
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM runtime_observations
                WHERE task_id = ?
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (str(task_id), limit),
            ).fetchall()
        records = tuple(self._observation_from_row(row) for row in rows)
        return tuple(reversed(records))

    def reserve(self, receipt: SideEffectReceipt) -> SideEffectReceipt:
        if receipt.stage is not SideEffectStage.PREPARED:
            raise ValueError("new side-effect receipt must begin PREPARED")
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM side_effect_receipts WHERE idempotency_key = ?",
                (receipt.idempotency_key,),
            ).fetchone()
            if existing is not None:
                return self._receipt_from_row(existing)
            payload = _canonical_json(receipt)
            connection.execute(
                """
                INSERT INTO side_effect_receipts(
                    idempotency_key,
                    task_id,
                    semantic_fingerprint,
                    stage,
                    payload_json,
                    payload_sha256,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.idempotency_key,
                    str(receipt.task_id),
                    receipt.semantic_fingerprint,
                    receipt.stage.value,
                    payload,
                    _digest(receipt),
                    receipt.created_at.isoformat(),
                ),
            )
        return receipt

    def load(self, idempotency_key: str) -> SideEffectReceipt:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM side_effect_receipts WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            raise RuntimeJournalError(f"side-effect receipt not found: {idempotency_key}")
        return self._receipt_from_row(row)

    def list_for_task(self, task_id: UUID) -> tuple[SideEffectReceipt, ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM side_effect_receipts
                WHERE task_id = ?
                ORDER BY rowid
                """,
                (str(task_id),),
            ).fetchall()
        return tuple(self._receipt_from_row(row) for row in rows)

    def latest_recoverable(self, task_id: UUID) -> SideEffectReceipt | None:
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM side_effect_receipts
                WHERE task_id = ? AND stage NOT IN (?, ?)
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (
                    str(task_id),
                    SideEffectStage.CHECKPOINTED.value,
                    SideEffectStage.ABORTED.value,
                ),
            ).fetchone()
        return self._receipt_from_row(row) if row is not None else None

    def semantic_history(
        self,
        *,
        task_id: UUID,
        semantic_fingerprint: str,
    ) -> tuple[SideEffectReceipt, ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM side_effect_receipts
                WHERE task_id = ? AND semantic_fingerprint = ?
                ORDER BY rowid
                """,
                (str(task_id), semantic_fingerprint),
            ).fetchall()
        return tuple(self._receipt_from_row(row) for row in rows)

    def _replace_receipt(
        self,
        *,
        current: SideEffectReceipt,
        updated: SideEffectReceipt,
    ) -> SideEffectReceipt:
        payload = _canonical_json(updated)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT payload_sha256 FROM side_effect_receipts WHERE idempotency_key = ?",
                (current.idempotency_key,),
            ).fetchone()
            if row is None:
                raise RuntimeJournalConflictError("side-effect receipt disappeared")
            if str(row["payload_sha256"]) != _digest(current):
                raise RuntimeJournalConflictError("side-effect receipt changed concurrently")
            cursor = connection.execute(
                """
                UPDATE side_effect_receipts
                SET stage = ?, payload_json = ?, payload_sha256 = ?, updated_at = ?
                WHERE idempotency_key = ? AND payload_sha256 = ?
                """,
                (
                    updated.stage.value,
                    payload,
                    _digest(updated),
                    utc_now().isoformat(),
                    current.idempotency_key,
                    _digest(current),
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeJournalConflictError("side-effect receipt update lost race")
        return updated

    def mark_started(self, idempotency_key: str) -> SideEffectReceipt:
        current = self.load(idempotency_key)
        if current.stage is SideEffectStage.STARTED:
            return current
        if current.stage is not SideEffectStage.PREPARED:
            raise RuntimeJournalConflictError(
                f"cannot start side effect from {current.stage.value}"
            )
        updated = SideEffectReceipt.model_validate(
            {
                **current.model_dump(mode="python"),
                "stage": SideEffectStage.STARTED,
                "started_at": utc_now(),
            }
        )
        return self._replace_receipt(current=current, updated=updated)

    def mark_completed(
        self,
        *,
        idempotency_key: str,
        outcome: DispatchOutcome,
    ) -> SideEffectReceipt:
        current = self.load(idempotency_key)
        if current.stage is SideEffectStage.COMPLETED and current.outcome == outcome:
            return current
        if current.stage is not SideEffectStage.STARTED:
            raise RuntimeJournalConflictError(
                f"cannot complete side effect from {current.stage.value}"
            )
        updated = SideEffectReceipt.model_validate(
            {
                **current.model_dump(mode="python"),
                "stage": SideEffectStage.COMPLETED,
                "outcome": outcome,
                "completed_at": utc_now(),
            }
        )
        return self._replace_receipt(current=current, updated=updated)

    def mark_observed(
        self,
        *,
        idempotency_key: str,
        post_action_state: TaskState,
    ) -> SideEffectReceipt:
        current = self.load(idempotency_key)
        if (
            current.stage is SideEffectStage.OBSERVED
            and current.post_action_state == post_action_state
        ):
            return current
        if current.stage is not SideEffectStage.COMPLETED:
            raise RuntimeJournalConflictError(
                f"cannot observe side effect from {current.stage.value}"
            )
        updated = SideEffectReceipt.model_validate(
            {
                **current.model_dump(mode="python"),
                "stage": SideEffectStage.OBSERVED,
                "post_action_state": post_action_state,
                "observed_at": utc_now(),
            }
        )
        return self._replace_receipt(current=current, updated=updated)

    def mark_checkpointed(
        self,
        *,
        idempotency_key: str,
        checkpoint_id: UUID,
    ) -> SideEffectReceipt:
        current = self.load(idempotency_key)
        if current.stage is SideEffectStage.CHECKPOINTED and current.checkpoint_id == checkpoint_id:
            return current
        if current.stage is not SideEffectStage.OBSERVED:
            raise RuntimeJournalConflictError(
                f"cannot checkpoint side effect from {current.stage.value}"
            )
        updated = SideEffectReceipt.model_validate(
            {
                **current.model_dump(mode="python"),
                "stage": SideEffectStage.CHECKPOINTED,
                "checkpoint_id": checkpoint_id,
                "checkpointed_at": utc_now(),
            }
        )
        return self._replace_receipt(current=current, updated=updated)

    def abort_prepared(self, *, idempotency_key: str, reason: str) -> SideEffectReceipt:
        current = self.load(idempotency_key)
        if current.stage is SideEffectStage.ABORTED:
            return current
        if current.stage is not SideEffectStage.PREPARED:
            raise RuntimeJournalConflictError(
                f"cannot abort side effect from {current.stage.value}"
            )
        updated = SideEffectReceipt.model_validate(
            {
                **current.model_dump(mode="python"),
                "stage": SideEffectStage.ABORTED,
                "abort_reason": reason,
                "aborted_at": utc_now(),
            }
        )
        return self._replace_receipt(current=current, updated=updated)

    def request_control(
        self,
        *,
        task_id: UUID,
        command: RuntimeControlCommand,
        reason: str,
    ) -> RuntimeControlRecord:
        record = RuntimeControlRecord(task_id=task_id, command=command, reason=reason)
        payload = _canonical_json(record)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO runtime_controls(
                    control_id,
                    task_id,
                    command,
                    acknowledged,
                    payload_json,
                    payload_sha256,
                    requested_at
                ) VALUES (?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    str(record.control_id),
                    str(record.task_id),
                    record.command.value,
                    payload,
                    _digest(record),
                    record.requested_at.isoformat(),
                ),
            )
        return record

    def latest_control(self, task_id: UUID) -> RuntimeControlRecord | None:
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM runtime_controls
                WHERE task_id = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (str(task_id),),
            ).fetchone()
        return self._control_from_row(row) if row is not None else None

    def pending_control(self, task_id: UUID) -> RuntimeControlRecord | None:
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM runtime_controls
                WHERE task_id = ? AND acknowledged = 0
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (str(task_id),),
            ).fetchone()
        return self._control_from_row(row) if row is not None else None

    def acknowledge_control(self, control_id: UUID) -> RuntimeControlRecord:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_controls WHERE control_id = ?",
                (str(control_id),),
            ).fetchone()
            if row is None:
                raise RuntimeJournalError(f"runtime control not found: {control_id}")
            current = self._control_from_row(row)
            if current.acknowledged_at is not None:
                return current
            updated = current.model_copy(update={"acknowledged_at": utc_now()})
            updated = RuntimeControlRecord.model_validate(updated.model_dump(mode="python"))
            payload = _canonical_json(updated)
            connection.execute(
                """
                UPDATE runtime_controls
                SET acknowledged = 1, payload_json = ?, payload_sha256 = ?
                WHERE control_id = ?
                """,
                (payload, _digest(updated), str(control_id)),
            )
        return updated

    def verify_integrity(self) -> bool:
        try:
            with self._read_connection() as connection:
                receipt_rows = connection.execute(
                    "SELECT * FROM side_effect_receipts ORDER BY rowid"
                ).fetchall()
                control_rows = connection.execute(
                    "SELECT * FROM runtime_controls ORDER BY rowid"
                ).fetchall()
                observation_rows = connection.execute(
                    "SELECT * FROM runtime_observations ORDER BY rowid"
                ).fetchall()
            for row in receipt_rows:
                self._receipt_from_row(row)
            for row in control_rows:
                self._control_from_row(row)
            for row in observation_rows:
                self._observation_from_row(row)
        except (RuntimeJournalError, ValueError, sqlite3.DatabaseError):
            return False
        return True
