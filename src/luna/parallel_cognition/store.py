"""Durable, fail-closed C-011 S2/S3 coordination state without live execution."""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from threading import RLock
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import ValidationError

from luna.contracts.base import utc_now
from luna.parallel_cognition.controls import (
    ControlDisposition,
    ControlFencePhase,
    FenceDecision,
    ResultQuarantineRecord,
)
from luna.parallel_cognition.events import (
    AttemptRecoveryRecord,
    CoordinationEvent,
    CoordinationEventKind,
    FakeBackendRequest,
    FakeBackendResult,
    FakeInvocationRecord,
    FakeInvocationState,
    RecoveryDisposition,
    RootLeaseHandle,
    RootLeaseRecord,
    RootLeaseStatus,
    validate_attempt_transition,
)
from luna.parallel_cognition.models import (
    AgentExecutionAttempt,
    AgentExecutionReceipt,
    AgentLifecycleState,
    AgentPayload,
    canonical_contract_json,
    contract_sha256,
)

COORDINATION_STORE_SCHEMA_VERSION = 2


class CoordinationStoreError(RuntimeError):
    """Base error for the isolated durable coordination store."""


class CoordinationStoreConflictError(CoordinationStoreError):
    """Raised when a durable identity or idempotency intent conflicts."""


class CoordinationStoreIntegrityError(CoordinationStoreError):
    """Raised when persisted coordination state fails validation."""


class CoordinationStoreLeaseError(CoordinationStoreError):
    """Raised when a caller does not hold the current in-memory lease token."""


class CoordinationStoreNotFoundError(CoordinationStoreError):
    """Raised when requested durable coordination state does not exist."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _model_json(value: Any) -> str:
    return _canonical_json(value.model_dump(mode="json"))


def _require_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _intent_sha256(operation: str, payload: Mapping[str, object]) -> str:
    return _json_sha256(_canonical_json({"operation": operation, "payload": payload}))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS root_lease_versions (
    lease_id TEXT NOT NULL,
    lease_version INTEGER NOT NULL CHECK (lease_version >= 1),
    task_id TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK (epoch >= 1),
    token_sha256 TEXT NOT NULL,
    record_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    PRIMARY KEY (lease_id, lease_version),
    UNIQUE (task_id, epoch, lease_version),
    FOREIGN KEY (event_id) REFERENCES coordination_events(event_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS root_lease_heads (
    task_id TEXT PRIMARY KEY,
    lease_id TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK (epoch >= 1),
    lease_version INTEGER NOT NULL CHECK (lease_version >= 1),
    record_sha256 TEXT NOT NULL,
    FOREIGN KEY (lease_id, lease_version)
        REFERENCES root_lease_versions(lease_id, lease_version)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS coordination_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    task_sequence INTEGER NOT NULL CHECK (task_sequence >= 1),
    kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    intent_sha256 TEXT NOT NULL,
    root_coordination_epoch INTEGER NOT NULL CHECK (root_coordination_epoch >= 1),
    previous_event_sha256 TEXT,
    event_json TEXT NOT NULL,
    event_sha256 TEXT NOT NULL,
    UNIQUE (task_id, task_sequence),
    UNIQUE (task_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS coordination_event_heads (
    task_id TEXT PRIMARY KEY,
    task_sequence INTEGER NOT NULL CHECK (task_sequence >= 1),
    event_id TEXT NOT NULL UNIQUE,
    event_sha256 TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES coordination_events(event_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS attempt_snapshots (
    attempt_id TEXT NOT NULL,
    snapshot_version INTEGER NOT NULL CHECK (snapshot_version >= 1),
    task_id TEXT NOT NULL,
    root_coordination_epoch INTEGER NOT NULL CHECK (root_coordination_epoch >= 1),
    lifecycle_state TEXT NOT NULL,
    attempt_integrity_id TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    PRIMARY KEY (attempt_id, snapshot_version),
    FOREIGN KEY (event_id) REFERENCES coordination_events(event_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS attempt_heads (
    attempt_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    snapshot_version INTEGER NOT NULL CHECK (snapshot_version >= 1),
    root_coordination_epoch INTEGER NOT NULL CHECK (root_coordination_epoch >= 1),
    lifecycle_state TEXT NOT NULL,
    attempt_integrity_id TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    FOREIGN KEY (attempt_id, snapshot_version)
        REFERENCES attempt_snapshots(attempt_id, snapshot_version)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS fake_invocations (
    invocation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL UNIQUE,
    root_coordination_epoch INTEGER NOT NULL CHECK (root_coordination_epoch >= 1),
    state TEXT NOT NULL,
    request_json TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    result_json TEXT,
    result_sha256 TEXT,
    payload_json TEXT,
    payload_sha256 TEXT,
    receipt_json TEXT,
    receipt_sha256 TEXT,
    record_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    start_event_id TEXT NOT NULL UNIQUE,
    result_event_id TEXT UNIQUE,
    receipt_event_id TEXT UNIQUE,
    FOREIGN KEY (attempt_id) REFERENCES attempt_heads(attempt_id) ON DELETE RESTRICT,
    FOREIGN KEY (start_event_id)
        REFERENCES coordination_events(event_id) ON DELETE RESTRICT,
    FOREIGN KEY (result_event_id)
        REFERENCES coordination_events(event_id) ON DELETE RESTRICT,
    FOREIGN KEY (receipt_event_id)
        REFERENCES coordination_events(event_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS attempt_recoveries (
    recovery_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    root_coordination_epoch INTEGER NOT NULL CHECK (root_coordination_epoch >= 1),
    disposition TEXT NOT NULL,
    recovery_json TEXT NOT NULL,
    recovery_sha256 TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    FOREIGN KEY (attempt_id) REFERENCES attempt_heads(attempt_id) ON DELETE RESTRICT,
    FOREIGN KEY (event_id) REFERENCES coordination_events(event_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS s3_control_artifacts (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_id TEXT,
    root_coordination_epoch INTEGER NOT NULL CHECK (root_coordination_epoch >= 1),
    artifact_type TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    FOREIGN KEY (event_id) REFERENCES coordination_events(event_id) ON DELETE RESTRICT
);
"""

_S3_SCHEMA = """
CREATE TABLE s3_control_artifacts (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_id TEXT,
    root_coordination_epoch INTEGER NOT NULL CHECK (root_coordination_epoch >= 1),
    artifact_type TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    FOREIGN KEY (event_id) REFERENCES coordination_events(event_id) ON DELETE RESTRICT
);
"""

_LEGACY_COORDINATION_TABLES = frozenset(
    {
        "root_lease_versions",
        "root_lease_heads",
        "coordination_events",
        "coordination_event_heads",
        "attempt_snapshots",
        "attempt_heads",
        "fake_invocations",
        "attempt_recoveries",
    }
)
_CURRENT_COORDINATION_TABLES = _LEGACY_COORDINATION_TABLES | {
    "s3_control_artifacts"
}


class SQLiteCoordinationStore:
    """Persist S2/S3 events, leases, attempts, controls, and fake executions."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).resolve()
        self._token_lock = RLock()
        self._lease_tokens: dict[tuple[str, str, int], str] = {}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CoordinationStoreError(
                "failed to create coordination store directory"
            ) from exc
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA busy_timeout = 5000")
            row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
            if row is None or str(row[0]).casefold() != "wal":
                raise CoordinationStoreError("SQLite did not enable WAL journal mode")
            return connection
        except CoordinationStoreError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            raise CoordinationStoreError("failed to open coordination store") from exc

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        except CoordinationStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise CoordinationStoreError("coordination store read failed") from exc
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._read_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._verify_integrity_connection(connection)
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize_schema(self) -> None:
        with self._read_connection() as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
            if row is None:
                raise CoordinationStoreError(
                    "SQLite did not report coordination schema version"
                )
            version = int(row[0])
            if version not in (0, 1, COORDINATION_STORE_SCHEMA_VERSION):
                raise CoordinationStoreError(
                    f"unsupported coordination store schema version: {version}"
                )
            tables = frozenset(
                str(item[0])
                for item in connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    """
                )
            )
            if version == 0:
                if tables:
                    raise CoordinationStoreError(
                        "unversioned coordination store contains durable tables"
                    )
                connection.executescript(_SCHEMA)
                connection.execute(
                    f"PRAGMA user_version = {COORDINATION_STORE_SCHEMA_VERSION}"
                )
            elif version == 1:
                if tables != _LEGACY_COORDINATION_TABLES:
                    raise CoordinationStoreError(
                        "legacy coordination store table set is not exact"
                    )
                connection.executescript(_S3_SCHEMA)
                connection.execute(
                    f"PRAGMA user_version = {COORDINATION_STORE_SCHEMA_VERSION}"
                )
            elif tables != _CURRENT_COORDINATION_TABLES:
                raise CoordinationStoreError(
                    "current coordination store table set is not exact"
                )
            connection.commit()
            self._verify_integrity_connection(connection)

    def journal_mode(self) -> str:
        with self._read_connection() as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
            if row is None:
                raise CoordinationStoreError("SQLite did not report journal mode")
            return str(row[0]).casefold()

    def verify_integrity(self) -> None:
        """Validate every durable object, digest, chain, and current pointer."""

        with self._read_connection() as connection:
            self._verify_integrity_connection(connection)

    def _verify_integrity_connection(self, connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()
        if version is None or int(version[0]) != COORDINATION_STORE_SCHEMA_VERSION:
            raise CoordinationStoreIntegrityError(
                "coordination store schema version changed after initialization"
            )
        quick = connection.execute("PRAGMA quick_check").fetchone()
        if quick is None or str(quick[0]).casefold() != "ok":
            raise CoordinationStoreIntegrityError("SQLite quick_check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise CoordinationStoreIntegrityError("SQLite foreign-key check failed")
        self._verify_event_chains(connection)
        self._verify_lease_rows(connection)
        self._verify_attempt_rows(connection)
        self._verify_invocation_rows(connection)
        self._verify_control_rows(connection)

    def _verify_event_chains(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT * FROM coordination_events ORDER BY task_id, task_sequence"
        ).fetchall()
        observed: dict[str, tuple[int, str, str, datetime]] = {}
        for row in rows:
            task_id = str(row["task_id"])
            previous = observed.get(task_id)
            expected_sequence = 1 if previous is None else previous[0] + 1
            expected_previous = None if previous is None else previous[1]
            try:
                event = CoordinationEvent.model_validate_json(str(row["event_json"]))
            except (ValidationError, ValueError) as exc:
                raise CoordinationStoreIntegrityError(
                    "stored coordination event is invalid"
                ) from exc
            if event.task_sequence != expected_sequence:
                raise CoordinationStoreIntegrityError(
                    "coordination event sequence is not contiguous"
                )
            if event.previous_event_sha256 != expected_previous:
                raise CoordinationStoreIntegrityError(
                    "coordination event hash chain is broken"
                )
            if previous is not None and event.occurred_at < previous[3]:
                raise CoordinationStoreIntegrityError(
                    "coordination event timestamps are not monotonic"
                )
            if (
                str(event.event_id) != str(row["event_id"])
                or str(event.task_id) != task_id
                or event.task_sequence != int(row["task_sequence"])
                or event.kind.value != str(row["kind"])
                or event.subject_id != str(row["subject_id"])
                or event.idempotency_key != str(row["idempotency_key"])
                or event.intent_sha256 != str(row["intent_sha256"])
                or event.root_coordination_epoch
                != int(row["root_coordination_epoch"])
                or event.previous_event_sha256
                != (
                    None
                    if row["previous_event_sha256"] is None
                    else str(row["previous_event_sha256"])
                )
                or event.event_sha256 != str(row["event_sha256"])
            ):
                raise CoordinationStoreIntegrityError(
                    "coordination event columns do not match canonical payload"
                )
            lease_rows = connection.execute(
                """
                SELECT record_json FROM root_lease_versions
                WHERE lease_id = ? AND task_id = ? AND epoch = ?
                """,
                (
                    str(event.root_lease_id),
                    str(event.task_id),
                    event.root_coordination_epoch,
                ),
            ).fetchall()
            if not lease_rows:
                raise CoordinationStoreIntegrityError(
                    "coordination event is not bound to a durable root lease"
                )
            bound = False
            for lease_row in lease_rows:
                try:
                    lease = RootLeaseRecord.model_validate_json(
                        str(lease_row["record_json"])
                    )
                except (ValidationError, ValueError) as exc:
                    raise CoordinationStoreIntegrityError(
                        "coordination event references an invalid root lease"
                    ) from exc
                if (
                    lease.root_owner_ref == event.root_owner_ref
                    and lease.root_instance_id == event.root_instance_id
                ):
                    bound = True
                    break
            if not bound:
                raise CoordinationStoreIntegrityError(
                    "coordination event root identity does not match its lease"
                )
            observed[task_id] = (
                expected_sequence,
                event.event_sha256,
                str(event.event_id),
                event.occurred_at,
            )
        heads = connection.execute("SELECT * FROM coordination_event_heads").fetchall()
        if len(heads) != len(observed):
            raise CoordinationStoreIntegrityError("coordination event head set mismatch")
        for row in heads:
            expected = observed.get(str(row["task_id"]))
            actual = (
                int(row["task_sequence"]),
                str(row["event_sha256"]),
                str(row["event_id"]),
            )
            if expected is None or expected[:3] != actual:
                raise CoordinationStoreIntegrityError(
                    "coordination event head does not match the hash-chain tail"
                )

    @classmethod
    def _integrity_event(
        cls,
        connection: sqlite3.Connection,
        event_id: object,
        *,
        label: str,
    ) -> CoordinationEvent:
        row = connection.execute(
            "SELECT * FROM coordination_events WHERE event_id = ?",
            (str(event_id),),
        ).fetchone()
        if row is None:
            raise CoordinationStoreIntegrityError(f"{label} event is missing")
        return cls._event_from_row(row)

    def _verify_lease_rows(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT * FROM root_lease_versions ORDER BY task_id, epoch, lease_version"
        ).fetchall()
        observed: dict[str, dict[int, list[tuple[RootLeaseRecord, sqlite3.Row]]]] = {}
        for row in rows:
            try:
                record = RootLeaseRecord.model_validate_json(str(row["record_json"]))
            except (ValidationError, ValueError) as exc:
                raise CoordinationStoreIntegrityError("stored root lease is invalid") from exc
            rendered = _model_json(record)
            if (
                _json_sha256(rendered) != str(row["record_sha256"])
                or str(record.lease_id) != str(row["lease_id"])
                or str(record.task_id) != str(row["task_id"])
                or record.epoch != int(row["epoch"])
                or record.lease_version != int(row["lease_version"])
                or record.token_sha256 != str(row["token_sha256"])
            ):
                raise CoordinationStoreIntegrityError(
                    "stored root lease does not match durable columns"
                )
            event = self._integrity_event(
                connection, row["event_id"], label="root lease"
            )
            if record.status is RootLeaseStatus.ACTIVE:
                expected_kind = (
                    CoordinationEventKind.ROOT_LEASE_ACQUIRED
                    if record.lease_version == 1
                    else CoordinationEventKind.ROOT_LEASE_RENEWED
                )
            elif record.status is RootLeaseStatus.EXPIRED:
                expected_kind = CoordinationEventKind.ROOT_LEASE_EXPIRED
            else:
                expected_kind = CoordinationEventKind.ROOT_LEASE_RELEASED
            if (
                event.kind is not expected_kind
                or event.subject_id != str(record.lease_id)
                or event.task_id != record.task_id
                or event.root_lease_id != record.lease_id
                or event.root_owner_ref != record.root_owner_ref
                or event.root_instance_id != record.root_instance_id
                or event.root_coordination_epoch != record.epoch
            ):
                raise CoordinationStoreIntegrityError(
                    "root lease event does not bind its durable record"
                )
            if record.status is RootLeaseStatus.ACTIVE:
                if event.lease_expires_at != record.expires_at:
                    raise CoordinationStoreIntegrityError(
                        "active root lease event has the wrong expiry"
                    )
                if (
                    record.lease_version == 1
                    and event.occurred_at != record.acquired_at
                ):
                    raise CoordinationStoreIntegrityError(
                        "root lease acquisition time does not match its event"
                    )
            elif event.occurred_at != record.ended_at:
                raise CoordinationStoreIntegrityError(
                    "ended root lease time does not match its event"
                )
            observed.setdefault(str(record.task_id), {}).setdefault(
                record.epoch, []
            ).append((record, row))

        expected_heads: dict[str, tuple[RootLeaseRecord, sqlite3.Row]] = {}
        for task_id, epochs in observed.items():
            ordered_epochs = sorted(epochs)
            if ordered_epochs != list(range(1, ordered_epochs[-1] + 1)):
                raise CoordinationStoreIntegrityError(
                    "root lease fencing epochs are not contiguous"
                )
            for epoch in ordered_epochs:
                versions = sorted(epochs[epoch], key=lambda item: item[0].lease_version)
                records = [item[0] for item in versions]
                if [item.lease_version for item in records] != list(
                    range(1, len(records) + 1)
                ):
                    raise CoordinationStoreIntegrityError(
                        "root lease versions are not contiguous"
                    )
                if len({item.lease_id for item in records}) != 1:
                    raise CoordinationStoreIntegrityError(
                        "one fencing epoch contains multiple root lease identities"
                    )
                if records[0].status is not RootLeaseStatus.ACTIVE:
                    raise CoordinationStoreIntegrityError(
                        "root lease epoch does not begin with an active acquisition"
                    )
                for previous, current in pairwise(records):
                    immutable_previous = (
                        previous.lease_id,
                        previous.task_id,
                        previous.root_owner_ref,
                        previous.root_instance_id,
                        previous.epoch,
                        previous.acquired_at,
                    )
                    immutable_current = (
                        current.lease_id,
                        current.task_id,
                        current.root_owner_ref,
                        current.root_instance_id,
                        current.epoch,
                        current.acquired_at,
                    )
                    if (
                        immutable_current != immutable_previous
                        or previous.status is not RootLeaseStatus.ACTIVE
                    ):
                        raise CoordinationStoreIntegrityError(
                            "root lease version lineage is invalid"
                        )
                    if current.status is RootLeaseStatus.ACTIVE:
                        if (
                            current.expires_at <= previous.expires_at
                            or current.token_sha256 == previous.token_sha256
                        ):
                            raise CoordinationStoreIntegrityError(
                                "root lease renewal did not extend and rotate authority"
                            )
                    elif (
                        current.expires_at != previous.expires_at
                        or current.token_sha256 != previous.token_sha256
                    ):
                        raise CoordinationStoreIntegrityError(
                            "ended root lease changed its prior authority projection"
                        )
                if epoch != ordered_epochs[-1] and records[-1].status is RootLeaseStatus.ACTIVE:
                    raise CoordinationStoreIntegrityError(
                        "superseded root lease epoch has no durable terminal version"
                    )
                if epoch == ordered_epochs[-1]:
                    expected_heads[task_id] = versions[-1]

        heads = connection.execute("SELECT * FROM root_lease_heads").fetchall()
        if len(heads) != len(expected_heads):
            raise CoordinationStoreIntegrityError("root lease head set mismatch")
        for head in heads:
            expected = expected_heads.get(str(head["task_id"]))
            if expected is None:
                raise CoordinationStoreIntegrityError("root lease head is orphaned")
            record, row = expected
            if (
                str(head["lease_id"]) != str(record.lease_id)
                or int(head["epoch"]) != record.epoch
                or int(head["lease_version"]) != record.lease_version
                or str(head["record_sha256"]) != str(row["record_sha256"])
            ):
                raise CoordinationStoreIntegrityError("root lease head is invalid")

    def _verify_attempt_rows(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT * FROM attempt_snapshots ORDER BY attempt_id, snapshot_version"
        ).fetchall()
        observed: dict[
            str, list[tuple[int, AgentExecutionAttempt, CoordinationEvent, sqlite3.Row]]
        ] = {}
        for row in rows:
            try:
                attempt = AgentExecutionAttempt.model_validate_json(
                    str(row["snapshot_json"])
                )
            except (ValidationError, ValueError) as exc:
                raise CoordinationStoreIntegrityError(
                    "stored attempt snapshot is invalid"
                ) from exc
            rendered = canonical_contract_json(attempt)
            if (
                _json_sha256(rendered) != str(row["snapshot_sha256"])
                or attempt.attempt_id != str(row["attempt_id"])
                or str(attempt.task_id) != str(row["task_id"])
                or attempt.root_coordination_epoch
                != int(row["root_coordination_epoch"])
                or attempt.lifecycle_state.value != str(row["lifecycle_state"])
                or attempt.attempt_integrity_id
                != str(row["attempt_integrity_id"])
            ):
                raise CoordinationStoreIntegrityError(
                    "attempt snapshot does not match durable columns"
                )
            event = self._integrity_event(
                connection, row["event_id"], label="attempt transition"
            )
            if (
                event.kind is not CoordinationEventKind.ATTEMPT_TRANSITION
                or event.subject_id != attempt.attempt_id
                or event.task_id != attempt.task_id
                or event.attempt_id != attempt.attempt_id
                or event.root_coordination_epoch != attempt.root_coordination_epoch
                or event.to_state is not attempt.lifecycle_state
                or event.artifact_ref != attempt.attempt_integrity_id
                or event.artifact_sha256 != contract_sha256(attempt)
            ):
                raise CoordinationStoreIntegrityError(
                    "attempt transition event does not bind its snapshot"
                )
            observed.setdefault(attempt.attempt_id, []).append(
                (int(row["snapshot_version"]), attempt, event, row)
            )

        expected_heads: dict[
            str, tuple[int, AgentExecutionAttempt, CoordinationEvent, sqlite3.Row]
        ] = {}
        for attempt_id, snapshots in observed.items():
            snapshots.sort(key=lambda item: item[0])
            if [item[0] for item in snapshots] != list(range(1, len(snapshots) + 1)):
                raise CoordinationStoreIntegrityError(
                    "attempt snapshot versions are not contiguous"
                )
            previous: AgentExecutionAttempt | None = None
            previous_sequence = 0
            for _, attempt, event, _ in snapshots:
                from_state = None if previous is None else previous.lifecycle_state
                if event.from_state is not from_state:
                    raise CoordinationStoreIntegrityError(
                        "attempt event transition source does not match prior snapshot"
                    )
                try:
                    validate_attempt_transition(from_state, attempt.lifecycle_state)
                    if previous is None:
                        if attempt.cancellation_epoch != 0:
                            raise CoordinationStoreIntegrityError(
                                "initial attempt cancellation epoch is not zero"
                            )
                    else:
                        self._validate_attempt_lineage(previous, attempt)
                except (ValueError, CoordinationStoreConflictError) as exc:
                    raise CoordinationStoreIntegrityError(
                        "attempt snapshot lineage is invalid"
                    ) from exc
                if event.task_sequence <= previous_sequence:
                    raise CoordinationStoreIntegrityError(
                        "attempt transition events are not journal ordered"
                    )
                previous = attempt
                previous_sequence = event.task_sequence
            expected_heads[attempt_id] = snapshots[-1]

        heads = connection.execute("SELECT * FROM attempt_heads").fetchall()
        if len(heads) != len(expected_heads):
            raise CoordinationStoreIntegrityError("attempt head set mismatch")
        for head in heads:
            expected = expected_heads.get(str(head["attempt_id"]))
            if expected is None:
                raise CoordinationStoreIntegrityError("attempt head is orphaned")
            _, _, _, row = expected
            if any(
                str(row[key]) != str(head[key])
                for key in (
                    "task_id",
                    "snapshot_version",
                    "root_coordination_epoch",
                    "lifecycle_state",
                    "attempt_integrity_id",
                    "snapshot_sha256",
                    "event_id",
                )
            ):
                raise CoordinationStoreIntegrityError("attempt head is invalid")

    def _verify_invocation_rows(self, connection: sqlite3.Connection) -> None:
        for row in connection.execute("SELECT * FROM fake_invocations"):
            try:
                request = FakeBackendRequest.model_validate_json(str(row["request_json"]))
                record = FakeInvocationRecord.model_validate_json(str(row["record_json"]))
            except (ValidationError, ValueError) as exc:
                raise CoordinationStoreIntegrityError(
                    "stored fake invocation is invalid"
                ) from exc
            if (
                contract_sha256(request) != str(row["request_sha256"])
                or contract_sha256(record) != str(row["record_sha256"])
            ):
                raise CoordinationStoreIntegrityError(
                    "stored fake invocation digest mismatch"
                )
            if (
                str(record.invocation_id) != str(row["invocation_id"])
                or record.request != request
                or record.state.value != str(row["state"])
                or str(request.assignment.task_id) != str(row["task_id"])
                or request.attempt.attempt_id != str(row["attempt_id"])
                or request.assignment.root_coordination_epoch
                != int(row["root_coordination_epoch"])
            ):
                raise CoordinationStoreIntegrityError(
                    "stored fake invocation does not match durable columns"
                )
            started_snapshot = connection.execute(
                """
                SELECT snapshot_json FROM attempt_snapshots
                WHERE attempt_id = ? AND attempt_integrity_id = ?
                """,
                (request.attempt.attempt_id, request.attempt.attempt_integrity_id),
            ).fetchone()
            if started_snapshot is None:
                raise CoordinationStoreIntegrityError(
                    "fake invocation request has no durable STARTED snapshot"
                )
            try:
                durable_started = AgentExecutionAttempt.model_validate_json(
                    str(started_snapshot["snapshot_json"])
                )
            except (ValidationError, ValueError) as exc:
                raise CoordinationStoreIntegrityError(
                    "fake invocation STARTED snapshot is invalid"
                ) from exc
            if durable_started != request.attempt:
                raise CoordinationStoreIntegrityError(
                    "fake invocation request changed its durable STARTED snapshot"
                )

            start_event = self._integrity_event(
                connection, row["start_event_id"], label="fake reservation"
            )
            if (
                start_event.kind is not CoordinationEventKind.FAKE_INVOCATION_RESERVED
                or start_event.subject_id != str(record.invocation_id)
                or start_event.idempotency_key != record.idempotency_key
                or start_event.task_id != request.assignment.task_id
                or start_event.attempt_id != request.attempt.attempt_id
                or start_event.root_coordination_epoch
                != request.assignment.root_coordination_epoch
                or start_event.occurred_at != record.reserved_at
                or start_event.artifact_ref != request.request_id
                or start_event.artifact_sha256 != contract_sha256(request)
            ):
                raise CoordinationStoreIntegrityError(
                    "fake reservation event does not bind its invocation"
                )

            result_fields = (
                row["result_json"],
                row["result_sha256"],
                row["result_event_id"],
            )
            payload_fields = (row["payload_json"], row["payload_sha256"])
            receipt_fields = (
                row["receipt_json"],
                row["receipt_sha256"],
                row["receipt_event_id"],
            )
            result_present = all(value is not None for value in result_fields)
            payload_present = all(value is not None for value in payload_fields)
            receipt_present = all(value is not None for value in receipt_fields)
            if any(value is not None for value in result_fields) != result_present:
                raise CoordinationStoreIntegrityError(
                    "fake result columns have inconsistent nullability"
                )
            if any(value is not None for value in payload_fields) != payload_present:
                raise CoordinationStoreIntegrityError(
                    "fake payload columns have inconsistent nullability"
                )
            if any(value is not None for value in receipt_fields) != receipt_present:
                raise CoordinationStoreIntegrityError(
                    "execution receipt columns have inconsistent nullability"
                )
            if payload_present is not receipt_present:
                raise CoordinationStoreIntegrityError(
                    "fake payload and execution receipt are not atomically projected"
                )
            if receipt_present and not result_present:
                raise CoordinationStoreIntegrityError(
                    "execution receipt exists without a durable fake result"
                )

            result: FakeBackendResult | None = None
            result_event: CoordinationEvent | None = None
            if result_present:
                try:
                    result = FakeBackendResult.model_validate_json(
                        str(row["result_json"])
                    )
                except (ValidationError, ValueError) as exc:
                    raise CoordinationStoreIntegrityError(
                        "stored fake result is invalid"
                    ) from exc
                if contract_sha256(result) != str(row["result_sha256"]):
                    raise CoordinationStoreIntegrityError(
                        "stored fake result digest mismatch"
                    )
                if record.result != result:
                    raise CoordinationStoreIntegrityError(
                        "fake invocation record does not project its durable result"
                    )
                result_event = self._integrity_event(
                    connection, row["result_event_id"], label="fake result"
                )
                if (
                    result_event.kind is not CoordinationEventKind.FAKE_RESULT_RECORDED
                    or result_event.subject_id != str(record.invocation_id)
                    or result_event.task_id != request.assignment.task_id
                    or result_event.attempt_id != request.attempt.attempt_id
                    or result_event.root_coordination_epoch
                    != request.assignment.root_coordination_epoch
                    or result_event.occurred_at != record.completed_at
                    or result_event.artifact_ref != result.result_id
                    or result_event.artifact_sha256 != contract_sha256(result)
                    or result_event.task_sequence <= start_event.task_sequence
                ):
                    raise CoordinationStoreIntegrityError(
                        "fake result event does not bind its invocation"
                    )
            elif (
                record.state is not FakeInvocationState.RESERVED
                or record.result is not None
                or record.completed_at is not None
                or record.durable_completion_count != 0
            ):
                raise CoordinationStoreIntegrityError(
                    "reserved fake invocation has a completed projection"
                )

            payload: AgentPayload | None = None
            if payload_present:
                try:
                    payload = AgentPayload.model_validate_json(str(row["payload_json"]))
                except ValidationError as exc:
                    raise CoordinationStoreIntegrityError(
                        "stored fake payload is invalid"
                    ) from exc
                if contract_sha256(payload) != str(row["payload_sha256"]):
                    raise CoordinationStoreIntegrityError(
                        "stored fake payload digest mismatch"
                    )
                if result is None or payload != result.payload:
                    raise CoordinationStoreIntegrityError(
                        "stored fake payload does not bind its durable result"
                    )

            if receipt_present:
                try:
                    receipt = AgentExecutionReceipt.model_validate_json(
                        str(row["receipt_json"])
                    )
                except ValidationError as exc:
                    raise CoordinationStoreIntegrityError(
                        "stored execution receipt is invalid"
                    ) from exc
                if contract_sha256(receipt) != str(row["receipt_sha256"]):
                    raise CoordinationStoreIntegrityError(
                        "stored execution receipt digest mismatch"
                    )
                if result is None or payload is None or result_event is None:
                    raise CoordinationStoreIntegrityError(
                        "execution receipt dependency projection is incomplete"
                    )
                receipt_event = self._integrity_event(
                    connection, row["receipt_event_id"], label="execution receipt"
                )
                if (
                    receipt_event.kind
                    is not CoordinationEventKind.EXECUTION_RECEIPT_RECORDED
                    or receipt_event.subject_id != str(record.invocation_id)
                    or receipt_event.task_id != request.assignment.task_id
                    or receipt_event.attempt_id != request.attempt.attempt_id
                    or receipt_event.root_coordination_epoch
                    != request.assignment.root_coordination_epoch
                    or receipt_event.artifact_ref != receipt.receipt_id
                    or receipt_event.artifact_sha256 != contract_sha256(receipt)
                    or receipt_event.task_sequence <= result_event.task_sequence
                    or receipt_event.occurred_at < result.script.cleanup_at
                ):
                    raise CoordinationStoreIntegrityError(
                        "execution receipt event does not bind its invocation"
                    )
                head_row = self._head_attempt_row(
                    connection, request.attempt.attempt_id
                )
                if head_row is None:
                    raise CoordinationStoreIntegrityError(
                        "execution receipt attempt head is missing"
                    )
                cleanup_attempt = self._attempt_from_row(head_row)
                if (
                    receipt.task_id != request.assignment.task_id
                    or receipt.source_task_revision
                    != request.assignment.source_task_revision
                    or receipt.assignment_id != request.assignment.assignment_id
                    or receipt.attempt_id != request.attempt.attempt_id
                    or receipt.attempt_integrity_id
                    != cleanup_attempt.attempt_integrity_id
                    or receipt.context_manifest_sha256
                    != request.assignment.context_manifest_sha256
                    or receipt.payload_id != payload.payload_id
                    or receipt.payload_sha256 != contract_sha256(payload)
                    or receipt.root_coordination_epoch
                    != request.assignment.root_coordination_epoch
                    or receipt.cancellation_epoch
                    != cleanup_attempt.cancellation_epoch
                    or receipt.outcome_state is not result.outcome_state
                    or receipt.cleanup_state.value != result.cleanup_state.value
                    or receipt.outcome_at != result.script.outcome_at
                    or receipt.cleanup_at != result.script.cleanup_at
                    or cleanup_attempt.lifecycle_state.value
                    != result.cleanup_state.value
                ):
                    raise CoordinationStoreIntegrityError(
                        "execution receipt does not project its durable dependencies"
                    )
                prior_attempt_events = tuple(
                    event
                    for event in (
                        self._event_from_row(event_row)
                        for event_row in connection.execute(
                            """
                            SELECT * FROM coordination_events
                            WHERE task_id = ? AND task_sequence < ?
                            ORDER BY task_sequence
                            """,
                            (
                                str(request.assignment.task_id),
                                receipt_event.task_sequence,
                            ),
                        )
                    )
                    if event.attempt_id == request.attempt.attempt_id
                )
                expected_refs = tuple(
                    sorted(event.event_ref for event in prior_attempt_events)
                )
                if receipt.event_refs != expected_refs:
                    raise CoordinationStoreIntegrityError(
                        "execution receipt event references do not match its journal prefix"
                    )
                transition_events = tuple(
                    event
                    for event in prior_attempt_events
                    if event.kind is CoordinationEventKind.ATTEMPT_TRANSITION
                )
                if len(transition_events) < 2 or (
                    transition_events[-2].to_state is not result.outcome_state
                    or transition_events[-2].occurred_at != receipt_event.occurred_at
                    or transition_events[-1].to_state is not cleanup_attempt.lifecycle_state
                    or transition_events[-1].occurred_at != receipt_event.occurred_at
                ):
                    raise CoordinationStoreIntegrityError(
                        "execution receipt outcome and cleanup events are invalid"
                    )
        for row in connection.execute("SELECT * FROM attempt_recoveries"):
            try:
                recovery = AttemptRecoveryRecord.model_validate_json(
                    str(row["recovery_json"])
                )
            except (ValidationError, ValueError) as exc:
                raise CoordinationStoreIntegrityError(
                    "stored attempt recovery decision is invalid"
                ) from exc
            if (
                contract_sha256(recovery) != str(row["recovery_sha256"])
                or recovery.recovery_id != str(row["recovery_id"])
                or str(recovery.task_id) != str(row["task_id"])
                or recovery.attempt_id != str(row["attempt_id"])
                or recovery.root_coordination_epoch
                != int(row["root_coordination_epoch"])
                or recovery.disposition.value != str(row["disposition"])
            ):
                raise CoordinationStoreIntegrityError(
                    "attempt recovery decision does not match durable columns"
                )
            event = self._integrity_event(
                connection, row["event_id"], label="attempt recovery"
            )
            if (
                event.kind is not CoordinationEventKind.RECOVERY_DECISION_RECORDED
                or event.subject_id != recovery.recovery_id
                or event.task_id != recovery.task_id
                or event.attempt_id != recovery.attempt_id
                or event.root_coordination_epoch
                != recovery.root_coordination_epoch
                or event.occurred_at != recovery.decided_at
                or event.previous_event_sha256 != recovery.event_head_sha256
                or event.artifact_ref != recovery.recovery_id
                or event.artifact_sha256 != contract_sha256(recovery)
                or event.reason != recovery.reason
            ):
                raise CoordinationStoreIntegrityError(
                    "attempt recovery event does not bind its durable decision"
                )
            if recovery.receipt_ref is not None:
                receipt_row = connection.execute(
                    """
                    SELECT receipt_json, receipt_sha256 FROM fake_invocations
                    WHERE attempt_id = ? AND receipt_json IS NOT NULL
                    """,
                    (recovery.attempt_id,),
                ).fetchone()
                if receipt_row is None:
                    raise CoordinationStoreIntegrityError(
                        "attempt recovery references a missing execution receipt"
                    )
                try:
                    receipt = AgentExecutionReceipt.model_validate_json(
                        str(receipt_row["receipt_json"])
                    )
                except ValidationError as exc:
                    raise CoordinationStoreIntegrityError(
                        "attempt recovery references an invalid execution receipt"
                    ) from exc
                if (
                    receipt.receipt_id != recovery.receipt_ref
                    or str(receipt_row["receipt_sha256"])
                    != recovery.receipt_sha256
                ):
                    raise CoordinationStoreIntegrityError(
                        "attempt recovery receipt projection is invalid"
                    )

    def _verify_control_rows(self, connection: sqlite3.Connection) -> None:
        decisions_by_attempt: dict[str, list[FenceDecision]] = {}
        rows = connection.execute(
            """
            SELECT artifact.* FROM s3_control_artifacts AS artifact
            JOIN coordination_events AS event ON event.event_id = artifact.event_id
            ORDER BY event.task_id, event.task_sequence
            """
        )
        for row in rows:
            artifact_type = str(row["artifact_type"])
            try:
                if artifact_type == "FENCE_DECISION":
                    decision = FenceDecision.model_validate_json(
                        str(row["artifact_json"])
                    )
                    artifact: FenceDecision | ResultQuarantineRecord = decision
                    artifact_id = decision.decision_id
                    task_id = decision.expectation.task_id
                    attempt_id = decision.attempt_id
                    epoch = decision.expectation.root_coordination_epoch
                    occurred_at = decision.checked_at
                    decisions_by_attempt.setdefault(decision.attempt_id, []).append(
                        decision
                    )
                elif artifact_type == "RESULT_QUARANTINE":
                    quarantine = ResultQuarantineRecord.model_validate_json(
                        str(row["artifact_json"])
                    )
                    artifact = quarantine
                    artifact_id = quarantine.quarantine_id
                    task_id = quarantine.decision.expectation.task_id
                    attempt_id = quarantine.decision.attempt_id
                    epoch = quarantine.decision.expectation.root_coordination_epoch
                    occurred_at = quarantine.received_at
                else:
                    raise CoordinationStoreIntegrityError(
                        "stored S3 control artifact has an unknown type"
                    )
            except (ValidationError, ValueError) as exc:
                raise CoordinationStoreIntegrityError(
                    "stored S3 control artifact is invalid"
                ) from exc
            artifact_sha256 = contract_sha256(artifact)
            if (
                artifact_id != str(row["artifact_id"])
                or str(task_id) != str(row["task_id"])
                or attempt_id != row["attempt_id"]
                or epoch != int(row["root_coordination_epoch"])
                or artifact_sha256 != str(row["artifact_sha256"])
            ):
                raise CoordinationStoreIntegrityError(
                    "S3 control artifact does not match durable columns"
                )
            event = self._integrity_event(
                connection, row["event_id"], label="S3 control artifact"
            )
            if (
                event.kind is not CoordinationEventKind.S3_CONTROL_RECORDED
                or event.subject_id != artifact_id
                or event.task_id != task_id
                or event.attempt_id != attempt_id
                or event.root_coordination_epoch != epoch
                or event.occurred_at != occurred_at
                or event.artifact_ref != artifact_id
                or event.artifact_sha256 != artifact_sha256
                or event.reason != artifact_type
            ):
                raise CoordinationStoreIntegrityError(
                    "S3 control event does not bind its durable artifact"
                )
            if isinstance(artifact, ResultQuarantineRecord):
                decision_row = connection.execute(
                    """
                    SELECT artifact_sha256, event_id FROM s3_control_artifacts
                    WHERE artifact_id = ? AND artifact_type = 'FENCE_DECISION'
                    """,
                    (artifact.decision.decision_id,),
                ).fetchone()
                if decision_row is None or str(decision_row["artifact_sha256"]) != (
                    contract_sha256(artifact.decision)
                ):
                    raise CoordinationStoreIntegrityError(
                        "result quarantine has no durable fence decision"
                    )
                decision_event = self._integrity_event(
                    connection,
                    decision_row["event_id"],
                    label="result-quarantine fence decision",
                )
                if decision_event.task_sequence >= event.task_sequence:
                    raise CoordinationStoreIntegrityError(
                        "result quarantine must follow its fence decision"
                    )
        phase_rank = {
            ControlFencePhase.BEFORE_CREATION: 0,
            ControlFencePhase.BEFORE_EXECUTION: 1,
            ControlFencePhase.RESULT_ADMISSION: 2,
            ControlFencePhase.PRE_ADOPTION: 3,
        }
        for decisions in decisions_by_attempt.values():
            phases = tuple(item.phase for item in decisions)
            ranks = tuple(phase_rank[item] for item in phases)
            if len(phases) != len(set(phases)) or ranks != tuple(sorted(ranks)):
                raise CoordinationStoreIntegrityError(
                    "S3 control phases are duplicated or out of order"
                )
            denied = tuple(
                index
                for index, item in enumerate(decisions)
                if item.disposition is ControlDisposition.DENY
            )
            if denied and denied != (len(decisions) - 1,):
                raise CoordinationStoreIntegrityError(
                    "S3 denied fence cannot be followed by another phase"
                )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> CoordinationEvent:
        try:
            return CoordinationEvent.model_validate_json(str(row["event_json"]))
        except (ValidationError, ValueError) as exc:
            raise CoordinationStoreIntegrityError(
                "stored coordination event is invalid"
            ) from exc

    @classmethod
    def _event_for_idempotency(
        cls,
        connection: sqlite3.Connection,
        *,
        task_id: UUID,
        idempotency_key: str,
        intent_sha256: str,
        kind: CoordinationEventKind,
    ) -> CoordinationEvent | None:
        row = connection.execute(
            """
            SELECT * FROM coordination_events
            WHERE task_id = ? AND idempotency_key = ?
            """,
            (str(task_id), idempotency_key),
        ).fetchone()
        if row is None:
            return None
        event = cls._event_from_row(row)
        if event.intent_sha256 != intent_sha256 or event.kind is not kind:
            raise CoordinationStoreConflictError(
                "idempotency key is already bound to another coordination intent"
            )
        return event

    @classmethod
    def _append_event(
        cls,
        connection: sqlite3.Connection,
        *,
        lease: RootLeaseRecord,
        kind: CoordinationEventKind,
        subject_id: str,
        idempotency_key: str,
        intent_sha256: str,
        occurred_at: datetime,
        attempt_id: str | None = None,
        from_state: AgentLifecycleState | None = None,
        to_state: AgentLifecycleState | None = None,
        artifact_ref: str | None = None,
        artifact_sha256: str | None = None,
        lease_expires_at: datetime | None = None,
        reason: str | None = None,
    ) -> tuple[CoordinationEvent, bool]:
        if not idempotency_key.strip() or len(idempotency_key) > 500:
            raise ValueError("coordination idempotency key must contain 1-500 characters")
        existing = cls._event_for_idempotency(
            connection,
            task_id=lease.task_id,
            idempotency_key=idempotency_key,
            intent_sha256=intent_sha256,
            kind=kind,
        )
        if existing is not None:
            return existing, False
        head = connection.execute(
            "SELECT * FROM coordination_event_heads WHERE task_id = ?",
            (str(lease.task_id),),
        ).fetchone()
        if head is not None:
            previous_row = connection.execute(
                "SELECT * FROM coordination_events WHERE event_id = ?",
                (str(head["event_id"]),),
            ).fetchone()
            if previous_row is None:
                raise CoordinationStoreIntegrityError(
                    "coordination event head references a missing event"
                )
            previous_event = cls._event_from_row(previous_row)
            if occurred_at < previous_event.occurred_at:
                raise CoordinationStoreConflictError(
                    "coordination event time cannot move backwards"
                )
        sequence = 1 if head is None else int(head["task_sequence"]) + 1
        previous_sha256 = None if head is None else str(head["event_sha256"])
        event = CoordinationEvent(
            event_id=uuid4(),
            task_id=lease.task_id,
            task_sequence=sequence,
            kind=kind,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            intent_sha256=intent_sha256,
            root_lease_id=lease.lease_id,
            root_owner_ref=lease.root_owner_ref,
            root_instance_id=lease.root_instance_id,
            root_coordination_epoch=lease.epoch,
            occurred_at=occurred_at,
            previous_event_sha256=previous_sha256,
            attempt_id=attempt_id,
            from_state=from_state,
            to_state=to_state,
            artifact_ref=artifact_ref,
            artifact_sha256=artifact_sha256,
            lease_expires_at=lease_expires_at,
            reason=reason,
        )
        connection.execute(
            """
            INSERT INTO coordination_events (
                event_id, task_id, task_sequence, kind, subject_id,
                idempotency_key, intent_sha256, root_coordination_epoch,
                previous_event_sha256, event_json, event_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event.event_id),
                str(event.task_id),
                event.task_sequence,
                event.kind.value,
                event.subject_id,
                event.idempotency_key,
                event.intent_sha256,
                event.root_coordination_epoch,
                event.previous_event_sha256,
                _model_json(event),
                event.event_sha256,
            ),
        )
        connection.execute(
            """
            INSERT INTO coordination_event_heads (
                task_id, task_sequence, event_id, event_sha256
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                task_sequence = excluded.task_sequence,
                event_id = excluded.event_id,
                event_sha256 = excluded.event_sha256
            """,
            (
                str(event.task_id),
                event.task_sequence,
                str(event.event_id),
                event.event_sha256,
            ),
        )
        return event, True

    @staticmethod
    def _lease_from_row(row: sqlite3.Row) -> RootLeaseRecord:
        try:
            return RootLeaseRecord.model_validate_json(str(row["record_json"]))
        except (ValidationError, ValueError) as exc:
            raise CoordinationStoreIntegrityError("stored root lease is invalid") from exc

    @classmethod
    def _lease_for_event(
        cls,
        connection: sqlite3.Connection,
        event: CoordinationEvent,
    ) -> RootLeaseRecord:
        rows = connection.execute(
            "SELECT * FROM root_lease_versions WHERE event_id = ?",
            (str(event.event_id),),
        ).fetchall()
        if len(rows) != 1:
            raise CoordinationStoreIntegrityError(
                "root lease event does not identify exactly one durable version"
            )
        record = cls._lease_from_row(rows[0])
        if (
            record.task_id != event.task_id
            or record.lease_id != event.root_lease_id
            or record.epoch != event.root_coordination_epoch
        ):
            raise CoordinationStoreIntegrityError(
                "root lease event does not bind its exact durable version"
            )
        return record

    @classmethod
    def _head_lease_row(
        cls,
        connection: sqlite3.Connection,
        task_id: UUID,
    ) -> sqlite3.Row | None:
        row = connection.execute(
            """
            SELECT versions.*
            FROM root_lease_heads AS heads
            JOIN root_lease_versions AS versions
              ON versions.lease_id = heads.lease_id
             AND versions.lease_version = heads.lease_version
            WHERE heads.task_id = ?
            """,
            (str(task_id),),
        ).fetchone()
        return cast(sqlite3.Row | None, row)

    @staticmethod
    def _insert_lease_version(
        connection: sqlite3.Connection,
        record: RootLeaseRecord,
        event: CoordinationEvent,
    ) -> None:
        rendered = _model_json(record)
        digest = _json_sha256(rendered)
        connection.execute(
            """
            INSERT INTO root_lease_versions (
                lease_id, lease_version, task_id, epoch, token_sha256,
                record_json, record_sha256, event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(record.lease_id),
                record.lease_version,
                str(record.task_id),
                record.epoch,
                record.token_sha256,
                rendered,
                digest,
                str(event.event_id),
            ),
        )
        connection.execute(
            """
            INSERT INTO root_lease_heads (
                task_id, lease_id, epoch, lease_version, record_sha256
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                lease_id = excluded.lease_id,
                epoch = excluded.epoch,
                lease_version = excluded.lease_version,
                record_sha256 = excluded.record_sha256
            """,
            (
                str(record.task_id),
                str(record.lease_id),
                record.epoch,
                record.lease_version,
                digest,
            ),
        )

    def _raw_token_for(self, record: RootLeaseRecord) -> str:
        key = (str(record.task_id), str(record.lease_id), record.lease_version)
        with self._token_lock:
            token = self._lease_tokens.get(key)
        if token is None or sha256(token.encode("utf-8")).hexdigest() != record.token_sha256:
            raise CoordinationStoreLeaseError(
                "root lease bearer token is unavailable in this store instance"
            )
        return token

    def _validate_lease_handle(
        self,
        connection: sqlite3.Connection,
        handle: RootLeaseHandle,
        *,
        now: datetime,
    ) -> RootLeaseRecord:
        record = handle.record
        row = self._head_lease_row(connection, record.task_id)
        if row is None:
            raise CoordinationStoreLeaseError("root lease does not exist")
        current = self._lease_from_row(row)
        if current != record:
            raise CoordinationStoreLeaseError(
                "root lease handle is stale or belongs to another fencing epoch"
            )
        token = self._raw_token_for(current)
        if not secrets.compare_digest(token, handle.token):
            raise CoordinationStoreLeaseError("root lease bearer token mismatch")
        if current.status is not RootLeaseStatus.ACTIVE:
            raise CoordinationStoreLeaseError("root lease is not active")
        if now < current.acquired_at:
            raise CoordinationStoreLeaseError("root lease cannot be used before acquisition")
        if now >= current.expires_at:
            raise CoordinationStoreLeaseError("root lease has expired")
        return current

    def acquire_root_lease(
        self,
        task_id: UUID,
        root_owner_ref: str | None = None,
        *,
        owner_id: str | None = None,
        root_instance_id: UUID | None = None,
        ttl_seconds: float = 30.0,
        now: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> RootLeaseHandle:
        """Acquire a task-scoped lease and issue a non-persisted bearer token."""

        observed_at = _require_utc(now or utc_now(), label="lease acquisition time")
        owner = root_owner_ref if root_owner_ref is not None else owner_id
        if owner is None or not owner.strip():
            raise ValueError("root owner reference must not be blank")
        if root_owner_ref is not None and owner_id is not None and root_owner_ref != owner_id:
            raise ValueError("root owner aliases disagree")
        if ttl_seconds <= 0:
            raise ValueError("root lease ttl_seconds must be positive")
        instance_id = root_instance_id or uuid4()
        key = idempotency_key or f"root-lease-acquire:{instance_id}"
        intent = _intent_sha256(
            "acquire_root_lease",
            {
                "task_id": str(task_id),
                "root_owner_ref": owner,
                "root_instance_id": str(instance_id),
                "ttl_seconds": ttl_seconds,
            },
        )
        issued_record: RootLeaseRecord | None = None
        issued_token: str | None = None
        expired_token_key: tuple[str, str, int] | None = None
        with self._transaction() as connection:
            existing = self._event_for_idempotency(
                connection,
                task_id=task_id,
                idempotency_key=key,
                intent_sha256=intent,
                kind=CoordinationEventKind.ROOT_LEASE_ACQUIRED,
            )
            if existing is not None:
                issued_record = self._lease_for_event(connection, existing)
                head_row = self._head_lease_row(connection, task_id)
                if head_row is None:
                    raise CoordinationStoreIntegrityError(
                        "idempotent lease event has no durable lease head"
                    )
                if self._lease_from_row(head_row) != issued_record:
                    raise CoordinationStoreLeaseError(
                        "idempotent lease acquisition was superseded"
                    )
                raise CoordinationStoreLeaseError(
                    "idempotent lease acquisition cannot reissue bearer authority"
                )
            else:
                head_row = self._head_lease_row(connection, task_id)
                prior_epoch = 0
                if head_row is not None:
                    previous = self._lease_from_row(head_row)
                    prior_epoch = previous.epoch
                    if (
                        previous.status is RootLeaseStatus.ACTIVE
                        and observed_at < previous.expires_at
                    ):
                        raise CoordinationStoreConflictError(
                            "another root coordinator holds the active task lease"
                        )
                    if previous.status is RootLeaseStatus.ACTIVE:
                        expired = RootLeaseRecord(
                            lease_id=previous.lease_id,
                            task_id=previous.task_id,
                            root_owner_ref=previous.root_owner_ref,
                            root_instance_id=previous.root_instance_id,
                            epoch=previous.epoch,
                            lease_version=previous.lease_version + 1,
                            token_sha256=previous.token_sha256,
                            acquired_at=previous.acquired_at,
                            expires_at=previous.expires_at,
                            status=RootLeaseStatus.EXPIRED,
                            ended_at=observed_at,
                        )
                        expire_intent = _intent_sha256(
                            "expire_root_lease",
                            {
                                "lease_id": str(previous.lease_id),
                                "lease_version": expired.lease_version,
                            },
                        )
                        expire_event, created = self._append_event(
                            connection,
                            lease=expired,
                            kind=CoordinationEventKind.ROOT_LEASE_EXPIRED,
                            subject_id=str(expired.lease_id),
                            idempotency_key=(
                                f"root-lease-expire:{expired.lease_id}:"
                                f"{expired.lease_version}"
                            ),
                            intent_sha256=expire_intent,
                            occurred_at=observed_at,
                            reason="root lease expired before replacement",
                        )
                        if not created:
                            raise CoordinationStoreIntegrityError(
                                "new lease replacement found an unexpected expiry event"
                            )
                        self._insert_lease_version(connection, expired, expire_event)
                        expired_token_key = (
                            str(previous.task_id),
                            str(previous.lease_id),
                            previous.lease_version,
                        )
                raw_token = secrets.token_urlsafe(32)
                token_sha256 = sha256(raw_token.encode("utf-8")).hexdigest()
                issued_record = RootLeaseRecord(
                    lease_id=uuid4(),
                    task_id=task_id,
                    root_owner_ref=owner,
                    root_instance_id=instance_id,
                    epoch=prior_epoch + 1,
                    lease_version=1,
                    token_sha256=token_sha256,
                    acquired_at=observed_at,
                    expires_at=observed_at + timedelta(seconds=ttl_seconds),
                    status=RootLeaseStatus.ACTIVE,
                )
                acquired_event, created = self._append_event(
                    connection,
                    lease=issued_record,
                    kind=CoordinationEventKind.ROOT_LEASE_ACQUIRED,
                    subject_id=str(issued_record.lease_id),
                    idempotency_key=key,
                    intent_sha256=intent,
                    occurred_at=observed_at,
                    lease_expires_at=issued_record.expires_at,
                )
                if not created:
                    raise CoordinationStoreIntegrityError(
                        "new lease acquisition unexpectedly reused an event"
                    )
                self._insert_lease_version(connection, issued_record, acquired_event)
                issued_token = raw_token
        if issued_record is None or issued_token is None:
            raise CoordinationStoreIntegrityError("root lease acquisition produced no handle")
        with self._token_lock:
            if expired_token_key is not None:
                self._lease_tokens.pop(expired_token_key, None)
            self._lease_tokens[
                (
                    str(issued_record.task_id),
                    str(issued_record.lease_id),
                    issued_record.lease_version,
                )
            ] = issued_token
        return RootLeaseHandle(record=issued_record, token=issued_token)

    def renew_root_lease(
        self,
        handle: RootLeaseHandle,
        *,
        ttl_seconds: float = 30.0,
        now: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> RootLeaseHandle:
        """CAS-renew a current lease, rotating both version and bearer token."""

        observed_at = _require_utc(now or utc_now(), label="lease renewal time")
        if ttl_seconds <= 0:
            raise ValueError("root lease ttl_seconds must be positive")
        prior = handle.record
        key = idempotency_key or (
            f"root-lease-renew:{prior.lease_id}:{prior.lease_version + 1}"
        )
        intent = _intent_sha256(
            "renew_root_lease",
            {
                "lease_id": str(prior.lease_id),
                "lease_version": prior.lease_version,
                "ttl_seconds": ttl_seconds,
            },
        )
        renewed: RootLeaseRecord | None = None
        raw_token: str | None = None
        with self._transaction() as connection:
            existing = self._event_for_idempotency(
                connection,
                task_id=prior.task_id,
                idempotency_key=key,
                intent_sha256=intent,
                kind=CoordinationEventKind.ROOT_LEASE_RENEWED,
            )
            if existing is not None:
                renewed = self._lease_for_event(connection, existing)
                row = self._head_lease_row(connection, prior.task_id)
                if row is None:
                    raise CoordinationStoreIntegrityError(
                        "idempotent renewal has no durable lease head"
                    )
                if self._lease_from_row(row) != renewed:
                    raise CoordinationStoreLeaseError("renewed lease was superseded")
                predecessor_row = connection.execute(
                    """
                    SELECT * FROM root_lease_versions
                    WHERE lease_id = ? AND lease_version = ?
                    """,
                    (str(renewed.lease_id), renewed.lease_version - 1),
                ).fetchone()
                if predecessor_row is None:
                    raise CoordinationStoreIntegrityError(
                        "idempotent renewal has no durable predecessor"
                    )
                predecessor = self._lease_from_row(predecessor_row)
                supplied_digest = sha256(handle.token.encode("utf-8")).hexdigest()
                if prior != predecessor or not secrets.compare_digest(
                    supplied_digest,
                    predecessor.token_sha256,
                ):
                    raise CoordinationStoreLeaseError(
                        "idempotent renewal predecessor authority mismatch"
                    )
                raw_token = self._raw_token_for(renewed)
            else:
                current = self._validate_lease_handle(
                    connection, handle, now=observed_at
                )
                expires_at = observed_at + timedelta(seconds=ttl_seconds)
                if expires_at <= current.expires_at:
                    raise CoordinationStoreConflictError(
                        "root lease renewal must extend the current expiry"
                    )
                raw_token = secrets.token_urlsafe(32)
                renewed = RootLeaseRecord(
                    lease_id=current.lease_id,
                    task_id=current.task_id,
                    root_owner_ref=current.root_owner_ref,
                    root_instance_id=current.root_instance_id,
                    epoch=current.epoch,
                    lease_version=current.lease_version + 1,
                    token_sha256=sha256(raw_token.encode("utf-8")).hexdigest(),
                    acquired_at=current.acquired_at,
                    expires_at=expires_at,
                    status=RootLeaseStatus.ACTIVE,
                )
                event, created = self._append_event(
                    connection,
                    lease=renewed,
                    kind=CoordinationEventKind.ROOT_LEASE_RENEWED,
                    subject_id=str(renewed.lease_id),
                    idempotency_key=key,
                    intent_sha256=intent,
                    occurred_at=observed_at,
                    lease_expires_at=renewed.expires_at,
                )
                if not created:
                    raise CoordinationStoreIntegrityError(
                        "new lease renewal unexpectedly reused an event"
                    )
                self._insert_lease_version(connection, renewed, event)
        if renewed is None or raw_token is None:
            raise CoordinationStoreIntegrityError("root lease renewal produced no handle")
        with self._token_lock:
            self._lease_tokens.pop(
                (str(prior.task_id), str(prior.lease_id), prior.lease_version), None
            )
            self._lease_tokens[
                (str(renewed.task_id), str(renewed.lease_id), renewed.lease_version)
            ] = raw_token
        return RootLeaseHandle(record=renewed, token=raw_token)

    def release_root_lease(
        self,
        handle: RootLeaseHandle,
        *,
        reason: str = "root coordinator released the lease",
        now: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> RootLeaseRecord:
        """Release a current lease and permanently fence its bearer token."""

        observed_at = _require_utc(now or utc_now(), label="lease release time")
        if not reason.strip():
            raise ValueError("root lease release reason must not be blank")
        prior = handle.record
        key = idempotency_key or (
            f"root-lease-release:{prior.lease_id}:{prior.lease_version + 1}"
        )
        intent = _intent_sha256(
            "release_root_lease",
            {
                "lease_id": str(prior.lease_id),
                "lease_version": prior.lease_version,
                "reason": reason,
            },
        )
        released: RootLeaseRecord | None = None
        with self._transaction() as connection:
            existing = self._event_for_idempotency(
                connection,
                task_id=prior.task_id,
                idempotency_key=key,
                intent_sha256=intent,
                kind=CoordinationEventKind.ROOT_LEASE_RELEASED,
            )
            if existing is not None:
                row = self._head_lease_row(connection, prior.task_id)
                if row is None:
                    raise CoordinationStoreIntegrityError(
                        "idempotent release has no durable lease head"
                    )
                released = self._lease_from_row(row)
                if (
                    released.lease_id != existing.root_lease_id
                    or released.status is not RootLeaseStatus.RELEASED
                ):
                    raise CoordinationStoreLeaseError("released lease was superseded")
            else:
                current = self._validate_lease_handle(
                    connection, handle, now=observed_at
                )
                released = RootLeaseRecord(
                    lease_id=current.lease_id,
                    task_id=current.task_id,
                    root_owner_ref=current.root_owner_ref,
                    root_instance_id=current.root_instance_id,
                    epoch=current.epoch,
                    lease_version=current.lease_version + 1,
                    token_sha256=current.token_sha256,
                    acquired_at=current.acquired_at,
                    expires_at=current.expires_at,
                    status=RootLeaseStatus.RELEASED,
                    ended_at=observed_at,
                )
                event, created = self._append_event(
                    connection,
                    lease=released,
                    kind=CoordinationEventKind.ROOT_LEASE_RELEASED,
                    subject_id=str(released.lease_id),
                    idempotency_key=key,
                    intent_sha256=intent,
                    occurred_at=observed_at,
                    reason=reason,
                )
                if not created:
                    raise CoordinationStoreIntegrityError(
                        "new lease release unexpectedly reused an event"
                    )
                self._insert_lease_version(connection, released, event)
        if released is None:
            raise CoordinationStoreIntegrityError("root lease release produced no record")
        with self._token_lock:
            self._lease_tokens.pop(
                (str(prior.task_id), str(prior.lease_id), prior.lease_version), None
            )
        return released

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> AgentExecutionAttempt:
        try:
            return AgentExecutionAttempt.model_validate_json(str(row["snapshot_json"]))
        except (ValidationError, ValueError) as exc:
            raise CoordinationStoreIntegrityError(
                "stored attempt snapshot is invalid"
            ) from exc

    @classmethod
    def _head_attempt_row(
        cls,
        connection: sqlite3.Connection,
        attempt_id: str,
    ) -> sqlite3.Row | None:
        row = connection.execute(
            """
            SELECT snapshots.*
            FROM attempt_heads AS heads
            JOIN attempt_snapshots AS snapshots
              ON snapshots.attempt_id = heads.attempt_id
             AND snapshots.snapshot_version = heads.snapshot_version
            WHERE heads.attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()
        return cast(sqlite3.Row | None, row)

    @staticmethod
    def _validate_attempt_lineage(
        previous: AgentExecutionAttempt,
        current: AgentExecutionAttempt,
    ) -> None:
        immutable_previous = (
            previous.attempt_id,
            previous.task_id,
            previous.source_task_revision,
            previous.assignment_id,
            previous.context_manifest_sha256,
            previous.root_coordination_epoch,
            previous.created_at,
            previous.deadline_at,
        )
        immutable_current = (
            current.attempt_id,
            current.task_id,
            current.source_task_revision,
            current.assignment_id,
            current.context_manifest_sha256,
            current.root_coordination_epoch,
            current.created_at,
            current.deadline_at,
        )
        if immutable_current != immutable_previous:
            raise CoordinationStoreConflictError(
                "attempt transition changed immutable execution identity"
            )
        if current.lifecycle_state is AgentLifecycleState.CANCEL_REQUESTED:
            expected_cancellation_epoch = previous.cancellation_epoch + 1
        else:
            expected_cancellation_epoch = previous.cancellation_epoch
        if current.cancellation_epoch != expected_cancellation_epoch:
            raise CoordinationStoreConflictError(
                "attempt transition has an invalid cancellation epoch"
            )
        provisioning_previous = (
            previous.runtime_session_id,
            previous.backend_id,
            previous.profile_id,
            previous.isolation,
        )
        provisioning_current = (
            current.runtime_session_id,
            current.backend_id,
            current.profile_id,
            current.isolation,
        )
        if (
            any(value is not None for value in provisioning_previous)
            and provisioning_current != provisioning_previous
        ):
            raise CoordinationStoreConflictError(
                "attempt transition changed its provisioned runtime binding"
            )
        if (
            not any(value is not None for value in provisioning_previous)
            and any(value is not None for value in provisioning_current)
            and current.lifecycle_state is not AgentLifecycleState.CREATED
        ):
            raise CoordinationStoreConflictError(
                "only CREATED may establish runtime provisioning"
            )
        if previous.started_at is not None and current.started_at != previous.started_at:
            raise CoordinationStoreConflictError(
                "attempt transition changed its established start time"
            )
        if (
            previous.started_at is None
            and current.started_at is not None
            and current.lifecycle_state is not AgentLifecycleState.STARTED
        ):
            raise CoordinationStoreConflictError(
                "only STARTED may establish the attempt start time"
            )

    def record_attempt_transition(
        self,
        lease: RootLeaseHandle,
        attempt: AgentExecutionAttempt,
        *,
        idempotency_key: str,
        occurred_at: datetime | None = None,
        reason: str | None = None,
    ) -> CoordinationEvent:
        """Persist one explicitly allowed attempt snapshot and store-authored event."""

        observed_at = _require_utc(
            occurred_at or utc_now(), label="attempt transition time"
        )
        if attempt.task_id != lease.record.task_id:
            raise CoordinationStoreLeaseError("attempt belongs to another root task")
        if attempt.root_coordination_epoch != lease.record.epoch:
            raise CoordinationStoreLeaseError(
                "attempt belongs to another root fencing epoch"
            )
        live_integration_states = {
            AgentLifecycleState.ADOPTED,
        }
        snapshot_json = canonical_contract_json(attempt)
        snapshot_sha256 = _json_sha256(snapshot_json)
        intent = _intent_sha256(
            "record_attempt_transition",
            {
                "attempt_id": attempt.attempt_id,
                "attempt_integrity_id": attempt.attempt_integrity_id,
                "snapshot_sha256": snapshot_sha256,
                "reason": reason,
            },
        )
        with self._transaction() as connection:
            current_lease = self._validate_lease_handle(
                connection, lease, now=observed_at
            )
            existing = self._event_for_idempotency(
                connection,
                task_id=attempt.task_id,
                idempotency_key=idempotency_key,
                intent_sha256=intent,
                kind=CoordinationEventKind.ATTEMPT_TRANSITION,
            )
            if existing is not None:
                row = connection.execute(
                    "SELECT 1 FROM attempt_snapshots WHERE event_id = ?",
                    (str(existing.event_id),),
                ).fetchone()
                if row is None:
                    raise CoordinationStoreIntegrityError(
                        "idempotent attempt event has no snapshot"
                    )
                return existing

            head_row = self._head_attempt_row(connection, attempt.attempt_id)
            previous = None if head_row is None else self._attempt_from_row(head_row)
            from_state = None if previous is None else previous.lifecycle_state
            if previous is None and attempt.cancellation_epoch != 0:
                raise CoordinationStoreConflictError(
                    "initial attempt snapshot requires cancellation_epoch=0"
                )
            if attempt.lifecycle_state in live_integration_states:
                raise CoordinationStoreConflictError(
                    "attempt adoption belongs to the later live-integration stage"
                )
            try:
                validate_attempt_transition(from_state, attempt.lifecycle_state)
            except ValueError as exc:
                raise CoordinationStoreConflictError(str(exc)) from exc
            if previous is not None and head_row is not None:
                self._validate_attempt_lineage(previous, attempt)
                snapshot_version = int(head_row["snapshot_version"]) + 1
            else:
                snapshot_version = 1
            event, created = self._append_event(
                connection,
                lease=current_lease,
                kind=CoordinationEventKind.ATTEMPT_TRANSITION,
                subject_id=attempt.attempt_id,
                idempotency_key=idempotency_key,
                intent_sha256=intent,
                occurred_at=observed_at,
                attempt_id=attempt.attempt_id,
                from_state=from_state,
                to_state=attempt.lifecycle_state,
                artifact_ref=attempt.attempt_integrity_id,
                artifact_sha256=contract_sha256(attempt),
                reason=reason,
            )
            if not created:
                raise CoordinationStoreIntegrityError(
                    "new attempt transition unexpectedly reused an event"
                )
            connection.execute(
                """
                INSERT INTO attempt_snapshots (
                    attempt_id, snapshot_version, task_id,
                    root_coordination_epoch, lifecycle_state,
                    attempt_integrity_id, snapshot_json, snapshot_sha256, event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.attempt_id,
                    snapshot_version,
                    str(attempt.task_id),
                    attempt.root_coordination_epoch,
                    attempt.lifecycle_state.value,
                    attempt.attempt_integrity_id,
                    snapshot_json,
                    snapshot_sha256,
                    str(event.event_id),
                ),
            )
            connection.execute(
                """
                INSERT INTO attempt_heads (
                    attempt_id, task_id, snapshot_version,
                    root_coordination_epoch, lifecycle_state,
                    attempt_integrity_id, snapshot_sha256, event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attempt_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    snapshot_version = excluded.snapshot_version,
                    root_coordination_epoch = excluded.root_coordination_epoch,
                    lifecycle_state = excluded.lifecycle_state,
                    attempt_integrity_id = excluded.attempt_integrity_id,
                    snapshot_sha256 = excluded.snapshot_sha256,
                    event_id = excluded.event_id
                """,
                (
                    attempt.attempt_id,
                    str(attempt.task_id),
                    snapshot_version,
                    attempt.root_coordination_epoch,
                    attempt.lifecycle_state.value,
                    attempt.attempt_integrity_id,
                    snapshot_sha256,
                    str(event.event_id),
                ),
            )
            return event

    def _record_generated_attempt_transition(
        self,
        connection: sqlite3.Connection,
        *,
        lease: RootLeaseRecord,
        previous: AgentExecutionAttempt,
        to_state: AgentLifecycleState,
        operation_key: str,
        occurred_at: datetime,
        reason: str,
    ) -> AgentExecutionAttempt:
        """Append a store-derived fake outcome snapshot inside an existing transaction."""

        try:
            validate_attempt_transition(previous.lifecycle_state, to_state)
        except ValueError as exc:
            raise CoordinationStoreConflictError(str(exc)) from exc
        raw = previous.model_dump(mode="json")
        raw.pop("attempt_integrity_id", None)
        raw["lifecycle_state"] = to_state.value
        if to_state is AgentLifecycleState.CANCEL_REQUESTED:
            raw["cancellation_epoch"] = previous.cancellation_epoch + 1
        try:
            current = AgentExecutionAttempt.model_validate(raw)
        except ValidationError as exc:
            raise CoordinationStoreIntegrityError(
                "store-derived fake execution snapshot is invalid"
            ) from exc
        self._validate_attempt_lineage(previous, current)
        head_row = self._head_attempt_row(connection, previous.attempt_id)
        if head_row is None or self._attempt_from_row(head_row) != previous:
            raise CoordinationStoreIntegrityError(
                "store-derived transition lost the current attempt head"
            )
        snapshot_version = int(head_row["snapshot_version"]) + 1
        snapshot_json = canonical_contract_json(current)
        snapshot_sha256 = _json_sha256(snapshot_json)
        intent = _intent_sha256(
            "store_generated_fake_transition",
            {
                "attempt_id": current.attempt_id,
                "from_integrity_id": previous.attempt_integrity_id,
                "to_integrity_id": current.attempt_integrity_id,
                "to_state": to_state.value,
            },
        )
        event, created = self._append_event(
            connection,
            lease=lease,
            kind=CoordinationEventKind.ATTEMPT_TRANSITION,
            subject_id=current.attempt_id,
            idempotency_key=operation_key,
            intent_sha256=intent,
            occurred_at=occurred_at,
            attempt_id=current.attempt_id,
            from_state=previous.lifecycle_state,
            to_state=current.lifecycle_state,
            artifact_ref=current.attempt_integrity_id,
            artifact_sha256=contract_sha256(current),
            reason=reason,
        )
        if not created:
            raise CoordinationStoreIntegrityError(
                "partial store-generated transition exists without its receipt"
            )
        connection.execute(
            """
            INSERT INTO attempt_snapshots (
                attempt_id, snapshot_version, task_id,
                root_coordination_epoch, lifecycle_state,
                attempt_integrity_id, snapshot_json, snapshot_sha256, event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                current.attempt_id,
                snapshot_version,
                str(current.task_id),
                current.root_coordination_epoch,
                current.lifecycle_state.value,
                current.attempt_integrity_id,
                snapshot_json,
                snapshot_sha256,
                str(event.event_id),
            ),
        )
        connection.execute(
            """
            UPDATE attempt_heads SET
                snapshot_version = ?, lifecycle_state = ?,
                attempt_integrity_id = ?, snapshot_sha256 = ?, event_id = ?
            WHERE attempt_id = ?
            """,
            (
                snapshot_version,
                current.lifecycle_state.value,
                current.attempt_integrity_id,
                snapshot_sha256,
                str(event.event_id),
                current.attempt_id,
            ),
        )
        return current

    def events_for_task(self, task_id: UUID) -> tuple[CoordinationEvent, ...]:
        """Return one task journal after validating the complete durable store."""

        with self._read_connection() as connection:
            self._verify_integrity_connection(connection)
            rows = connection.execute(
                """
                SELECT * FROM coordination_events
                WHERE task_id = ? ORDER BY task_sequence
                """,
                (str(task_id),),
            ).fetchall()
            return tuple(self._event_from_row(row) for row in rows)

    def events_for_attempt(self, attempt_id: str) -> tuple[CoordinationEvent, ...]:
        """Return all store-authored events explicitly bound to an attempt."""

        with self._read_connection() as connection:
            self._verify_integrity_connection(connection)
            rows = connection.execute(
                "SELECT * FROM coordination_events ORDER BY task_id, task_sequence"
            ).fetchall()
            return tuple(
                event
                for event in (self._event_from_row(row) for row in rows)
                if event.attempt_id == attempt_id
            )

    def load_attempt(self, attempt_id: str) -> AgentExecutionAttempt:
        """Load the current immutable attempt snapshot."""

        with self._read_connection() as connection:
            self._verify_integrity_connection(connection)
            row = self._head_attempt_row(connection, attempt_id)
            if row is None:
                raise CoordinationStoreNotFoundError("coordination attempt was not found")
            return self._attempt_from_row(row)

    def current_root_lease(self, task_id: UUID) -> RootLeaseRecord:
        """Inspect the durable lease head without recovering bearer authority."""

        with self._read_connection() as connection:
            self._verify_integrity_connection(connection)
            row = self._head_lease_row(connection, task_id)
            if row is None:
                raise CoordinationStoreNotFoundError("root coordination lease was not found")
            return self._lease_from_row(row)

    @staticmethod
    def _control_artifact_metadata(
        artifact: FenceDecision | ResultQuarantineRecord,
    ) -> tuple[str, str, UUID, str | None, int, datetime]:
        if isinstance(artifact, FenceDecision):
            return (
                "FENCE_DECISION",
                artifact.decision_id,
                artifact.expectation.task_id,
                artifact.attempt_id,
                artifact.expectation.root_coordination_epoch,
                artifact.checked_at,
            )
        return (
            "RESULT_QUARANTINE",
            artifact.quarantine_id,
            artifact.decision.expectation.task_id,
            artifact.decision.attempt_id,
            artifact.decision.expectation.root_coordination_epoch,
            artifact.received_at,
        )

    @staticmethod
    def _control_artifact_from_row(
        row: sqlite3.Row,
    ) -> FenceDecision | ResultQuarantineRecord:
        try:
            if str(row["artifact_type"]) == "FENCE_DECISION":
                return FenceDecision.model_validate_json(str(row["artifact_json"]))
            if str(row["artifact_type"]) == "RESULT_QUARANTINE":
                return ResultQuarantineRecord.model_validate_json(
                    str(row["artifact_json"])
                )
        except (ValidationError, ValueError) as exc:
            raise CoordinationStoreIntegrityError(
                "stored S3 control artifact is invalid"
            ) from exc
        raise CoordinationStoreIntegrityError(
            "stored S3 control artifact has an unknown type"
        )

    def _insert_control_artifact(
        self,
        connection: sqlite3.Connection,
        *,
        lease: RootLeaseRecord,
        artifact: FenceDecision | ResultQuarantineRecord,
        idempotency_key: str,
    ) -> FenceDecision | ResultQuarantineRecord:
        artifact_type, artifact_id, task_id, attempt_id, epoch, occurred_at = (
            self._control_artifact_metadata(artifact)
        )
        artifact_sha256 = contract_sha256(artifact)
        existing_row = connection.execute(
            "SELECT * FROM s3_control_artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if existing_row is not None:
            existing = self._control_artifact_from_row(existing_row)
            if existing != artifact:
                raise CoordinationStoreConflictError(
                    "S3 control artifact identity is already bound to other content"
                )
            return existing
        intent = _intent_sha256(
            "record_s3_control_artifact",
            {
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
                "artifact_sha256": artifact_sha256,
            },
        )
        existing_event = self._event_for_idempotency(
            connection,
            task_id=task_id,
            idempotency_key=idempotency_key,
            intent_sha256=intent,
            kind=CoordinationEventKind.S3_CONTROL_RECORDED,
        )
        if existing_event is not None:
            raise CoordinationStoreIntegrityError(
                "idempotent S3 control event has no projected artifact"
            )
        event, created = self._append_event(
            connection,
            lease=lease,
            kind=CoordinationEventKind.S3_CONTROL_RECORDED,
            subject_id=artifact_id,
            idempotency_key=idempotency_key,
            intent_sha256=intent,
            occurred_at=occurred_at,
            attempt_id=attempt_id,
            artifact_ref=artifact_id,
            artifact_sha256=artifact_sha256,
            reason=artifact_type,
        )
        if not created:
            raise CoordinationStoreIntegrityError(
                "new S3 control artifact unexpectedly reused an event"
            )
        connection.execute(
            """
            INSERT INTO s3_control_artifacts (
                artifact_id, task_id, attempt_id, root_coordination_epoch,
                artifact_type, artifact_json, artifact_sha256, event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                str(task_id),
                attempt_id,
                epoch,
                artifact_type,
                canonical_contract_json(artifact),
                artifact_sha256,
                str(event.event_id),
            ),
        )
        return artifact

    def record_control_decision(
        self,
        lease: RootLeaseHandle,
        decision: FenceDecision,
        *,
        idempotency_key: str,
    ) -> FenceDecision:
        """Durably bind one runtime-owned S3 fence decision to the task journal."""

        if decision.expectation.task_id != lease.record.task_id:
            raise CoordinationStoreLeaseError("control decision belongs to another task")
        if decision.expectation.root_coordination_epoch != lease.record.epoch:
            raise CoordinationStoreLeaseError(
                "control decision belongs to another root fencing epoch"
            )
        with self._transaction() as connection:
            current_lease = self._validate_lease_handle(
                connection, lease, now=decision.checked_at
            )
            recorded = self._insert_control_artifact(
                connection,
                lease=current_lease,
                artifact=decision,
                idempotency_key=idempotency_key,
            )
            if not isinstance(recorded, FenceDecision):
                raise CoordinationStoreIntegrityError(
                    "control decision projected as another artifact type"
                )
            return recorded

    def record_result_quarantine(
        self,
        lease: RootLeaseHandle,
        quarantine: ResultQuarantineRecord,
        *,
        idempotency_key: str,
    ) -> ResultQuarantineRecord:
        """Atomically persist an ineligible result and its exact fence decision."""

        decision = quarantine.decision
        if decision.expectation.task_id != lease.record.task_id:
            raise CoordinationStoreLeaseError("quarantined result belongs to another task")
        if decision.expectation.root_coordination_epoch != lease.record.epoch:
            raise CoordinationStoreLeaseError(
                "quarantined result belongs to another root fencing epoch"
            )
        with self._transaction() as connection:
            current_lease = self._validate_lease_handle(
                connection, lease, now=quarantine.received_at
            )
            self._insert_control_artifact(
                connection,
                lease=current_lease,
                artifact=decision,
                idempotency_key=f"{idempotency_key}:decision",
            )
            recorded = self._insert_control_artifact(
                connection,
                lease=current_lease,
                artifact=quarantine,
                idempotency_key=f"{idempotency_key}:quarantine",
            )
            if not isinstance(recorded, ResultQuarantineRecord):
                raise CoordinationStoreIntegrityError(
                    "result quarantine projected as another artifact type"
                )
            return recorded

    def record_control_denial_and_close(
        self,
        lease: RootLeaseHandle,
        decision: FenceDecision,
        *,
        idempotency_key: str,
    ) -> FenceDecision:
        """Atomically deny a pre-start fence and close its attempt without execution."""

        if decision.disposition is not ControlDisposition.DENY:
            raise ValueError("control denial closure requires a DENY decision")
        if decision.phase not in {
            ControlFencePhase.BEFORE_CREATION,
            ControlFencePhase.BEFORE_EXECUTION,
        }:
            raise ValueError("only a pre-start fence may close without execution")
        if decision.expectation.task_id != lease.record.task_id:
            raise CoordinationStoreLeaseError("control denial belongs to another task")
        if decision.expectation.root_coordination_epoch != lease.record.epoch:
            raise CoordinationStoreLeaseError(
                "control denial belongs to another root fencing epoch"
            )
        with self._transaction() as connection:
            current_lease = self._validate_lease_handle(
                connection, lease, now=decision.checked_at
            )
            self._insert_control_artifact(
                connection,
                lease=current_lease,
                artifact=decision,
                idempotency_key=f"{idempotency_key}:decision",
            )
            head = self._head_attempt_row(connection, decision.attempt_id)
            if head is None:
                raise CoordinationStoreIntegrityError(
                    "control denial has no durable attempt head"
                )
            previous = self._attempt_from_row(head)
            if previous.lifecycle_state is AgentLifecycleState.CLOSED:
                return decision
            expected_state = (
                AgentLifecycleState.ADMITTED
                if decision.phase is ControlFencePhase.BEFORE_CREATION
                else AgentLifecycleState.CREATED
            )
            if previous.lifecycle_state is not expected_state:
                raise CoordinationStoreConflictError(
                    "control denial does not match the expected pre-start attempt state"
                )
            operation_digest = _json_sha256(idempotency_key)
            if "DEADLINE_REACHED" in decision.reasons:
                outcome = self._record_generated_attempt_transition(
                    connection,
                    lease=current_lease,
                    previous=previous,
                    to_state=AgentLifecycleState.TIMED_OUT,
                    operation_key=f"s3-timeout:{operation_digest}",
                    occurred_at=decision.checked_at,
                    reason="S3 current-state fence reached the attempt deadline",
                )
            else:
                cancel_requested = self._record_generated_attempt_transition(
                    connection,
                    lease=current_lease,
                    previous=previous,
                    to_state=AgentLifecycleState.CANCEL_REQUESTED,
                    operation_key=f"s3-cancel-request:{operation_digest}",
                    occurred_at=decision.checked_at,
                    reason="S3 current-state fence denied pre-start execution",
                )
                outcome = self._record_generated_attempt_transition(
                    connection,
                    lease=current_lease,
                    previous=cancel_requested,
                    to_state=AgentLifecycleState.CANCELLED,
                    operation_key=f"s3-cancelled:{operation_digest}",
                    occurred_at=decision.checked_at,
                    reason="S3 denied attempt was cancelled before execution",
                )
            cleaned = self._record_generated_attempt_transition(
                connection,
                lease=current_lease,
                previous=outcome,
                to_state=AgentLifecycleState.CLEANUP_COMPLETE,
                operation_key=f"s3-cleanup:{operation_digest}",
                occurred_at=decision.checked_at,
                reason="S3 pre-start denial cleanup completed",
            )
            self._record_generated_attempt_transition(
                connection,
                lease=current_lease,
                previous=cleaned,
                to_state=AgentLifecycleState.CLOSED,
                operation_key=f"s3-close:{operation_digest}",
                occurred_at=decision.checked_at,
                reason="S3 denied attempt closed without execution",
            )
            return decision

    def load_control_artifact(
        self, artifact_id: str
    ) -> FenceDecision | ResultQuarantineRecord:
        """Load one verified S3 control artifact by its content identity."""

        with self._read_connection() as connection:
            self._verify_integrity_connection(connection)
            row = connection.execute(
                "SELECT * FROM s3_control_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            if row is None:
                raise CoordinationStoreNotFoundError("S3 control artifact was not found")
            return self._control_artifact_from_row(row)

    def quarantines_for_attempt(
        self, attempt_id: str
    ) -> tuple[ResultQuarantineRecord, ...]:
        """Return verified quarantined results for one attempt in event order."""

        with self._read_connection() as connection:
            self._verify_integrity_connection(connection)
            rows = connection.execute(
                """
                SELECT artifact.* FROM s3_control_artifacts AS artifact
                JOIN coordination_events AS event ON event.event_id = artifact.event_id
                WHERE artifact.attempt_id = ?
                  AND artifact.artifact_type = 'RESULT_QUARANTINE'
                ORDER BY event.task_sequence
                """,
                (attempt_id,),
            ).fetchall()
            artifacts = tuple(self._control_artifact_from_row(row) for row in rows)
            if not all(isinstance(item, ResultQuarantineRecord) for item in artifacts):
                raise CoordinationStoreIntegrityError(
                    "result-quarantine query returned another artifact type"
                )
            return cast(tuple[ResultQuarantineRecord, ...], artifacts)

    @staticmethod
    def _invocation_from_row(row: sqlite3.Row) -> FakeInvocationRecord:
        try:
            return FakeInvocationRecord.model_validate_json(str(row["record_json"]))
        except (ValidationError, ValueError) as exc:
            raise CoordinationStoreIntegrityError(
                "stored fake invocation is invalid"
            ) from exc

    def start_fake_invocation(
        self,
        lease: RootLeaseHandle,
        request: FakeBackendRequest,
        *,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> FakeInvocationRecord:
        """Reserve exactly one durable invocation for a validated fake request."""

        observed_at = _require_utc(
            occurred_at or request.requested_at,
            label="fake invocation reservation time",
        )
        if observed_at < request.requested_at:
            raise ValueError("fake invocation cannot be reserved before its request")
        if request.assignment.task_id != lease.record.task_id:
            raise CoordinationStoreLeaseError("fake request belongs to another root task")
        if request.assignment.root_coordination_epoch != lease.record.epoch:
            raise CoordinationStoreLeaseError(
                "fake request belongs to another root fencing epoch"
            )
        request_sha256 = contract_sha256(request)
        intent = _intent_sha256(
            "start_fake_invocation",
            {
                "request_id": request.request_id,
                "request_sha256": request_sha256,
            },
        )
        with self._transaction() as connection:
            current_lease = self._validate_lease_handle(
                connection, lease, now=observed_at
            )
            existing_event = self._event_for_idempotency(
                connection,
                task_id=request.assignment.task_id,
                idempotency_key=idempotency_key,
                intent_sha256=intent,
                kind=CoordinationEventKind.FAKE_INVOCATION_RESERVED,
            )
            if existing_event is not None:
                row = connection.execute(
                    "SELECT * FROM fake_invocations WHERE start_event_id = ?",
                    (str(existing_event.event_id),),
                ).fetchone()
                if row is None:
                    raise CoordinationStoreIntegrityError(
                        "idempotent fake reservation has no invocation"
                    )
                return self._invocation_from_row(row)

            attempt_row = connection.execute(
                """
                SELECT * FROM attempt_snapshots
                WHERE attempt_id = ? AND attempt_integrity_id = ?
                """,
                (
                    request.attempt.attempt_id,
                    request.attempt.attempt_integrity_id,
                ),
            ).fetchone()
            if attempt_row is None or self._attempt_from_row(attempt_row) != request.attempt:
                raise CoordinationStoreConflictError(
                    "fake request STARTED snapshot is not durably recorded"
                )
            head_row = self._head_attempt_row(connection, request.attempt.attempt_id)
            if (
                head_row is None
                or self._attempt_from_row(head_row) != request.attempt
                or request.attempt.lifecycle_state is not AgentLifecycleState.STARTED
            ):
                raise CoordinationStoreConflictError(
                    "fake request is not bound to the current STARTED attempt head"
                )
            if observed_at >= request.attempt.deadline_at:
                raise CoordinationStoreConflictError(
                    "fake invocation cannot start at or after its deadline"
                )
            existing_invocation = connection.execute(
                "SELECT * FROM fake_invocations WHERE attempt_id = ?",
                (request.attempt.attempt_id,),
            ).fetchone()
            if existing_invocation is not None:
                raise CoordinationStoreConflictError(
                    "attempt already has a fake invocation under another intent"
                )
            record = FakeInvocationRecord(
                invocation_id=uuid4(),
                idempotency_key=idempotency_key,
                request=request,
                state=FakeInvocationState.RESERVED,
                reserved_at=observed_at,
                durable_completion_count=0,
            )
            event, created = self._append_event(
                connection,
                lease=current_lease,
                kind=CoordinationEventKind.FAKE_INVOCATION_RESERVED,
                subject_id=str(record.invocation_id),
                idempotency_key=idempotency_key,
                intent_sha256=intent,
                occurred_at=observed_at,
                attempt_id=request.attempt.attempt_id,
                artifact_ref=request.request_id,
                artifact_sha256=request_sha256,
            )
            if not created:
                raise CoordinationStoreIntegrityError(
                    "new fake reservation unexpectedly reused an event"
                )
            connection.execute(
                """
                INSERT INTO fake_invocations (
                    invocation_id, task_id, attempt_id,
                    root_coordination_epoch, state,
                    request_json, request_sha256,
                    result_json, result_sha256,
                    payload_json, payload_sha256,
                    receipt_json, receipt_sha256,
                    record_json, record_sha256,
                    start_event_id, result_event_id, receipt_event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL,
                          NULL, NULL, ?, ?, ?, NULL, NULL)
                """,
                (
                    str(record.invocation_id),
                    str(request.assignment.task_id),
                    request.attempt.attempt_id,
                    request.assignment.root_coordination_epoch,
                    record.state.value,
                    canonical_contract_json(request),
                    request_sha256,
                    canonical_contract_json(record),
                    contract_sha256(record),
                    str(event.event_id),
                ),
            )
            return record

    def record_fake_result(
        self,
        lease: RootLeaseHandle,
        result: FakeBackendResult,
        *,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> FakeInvocationRecord:
        """Bind one deterministic fake result; caller cannot author a receipt."""

        request = result.request
        observed_at = _require_utc(
            occurred_at or result.script.cleanup_at,
            label="fake result recording time",
        )
        if request.assignment.task_id != lease.record.task_id:
            raise CoordinationStoreLeaseError("fake result belongs to another root task")
        if request.assignment.root_coordination_epoch != lease.record.epoch:
            raise CoordinationStoreLeaseError(
                "fake result belongs to another root fencing epoch"
            )
        result_sha256 = contract_sha256(result)
        intent = _intent_sha256(
            "record_fake_result",
            {
                "result_id": result.result_id,
                "result_sha256": result_sha256,
            },
        )
        with self._transaction() as connection:
            current_lease = self._validate_lease_handle(
                connection, lease, now=observed_at
            )
            existing_event = self._event_for_idempotency(
                connection,
                task_id=request.assignment.task_id,
                idempotency_key=idempotency_key,
                intent_sha256=intent,
                kind=CoordinationEventKind.FAKE_RESULT_RECORDED,
            )
            if existing_event is not None:
                row = connection.execute(
                    "SELECT * FROM fake_invocations WHERE result_event_id = ?",
                    (str(existing_event.event_id),),
                ).fetchone()
                if row is None:
                    raise CoordinationStoreIntegrityError(
                        "idempotent fake result event has no invocation"
                    )
                return self._invocation_from_row(row)

            row = connection.execute(
                "SELECT * FROM fake_invocations WHERE attempt_id = ?",
                (request.attempt.attempt_id,),
            ).fetchone()
            if row is None:
                raise CoordinationStoreNotFoundError(
                    "fake invocation must be reserved before recording a result"
                )
            prior = self._invocation_from_row(row)
            if prior.request != request:
                raise CoordinationStoreConflictError(
                    "fake result is bound to another durable request"
                )
            if prior.state is not FakeInvocationState.RESERVED:
                raise CoordinationStoreConflictError(
                    "fake invocation already completed under another intent"
                )
            if observed_at < prior.reserved_at:
                raise CoordinationStoreConflictError(
                    "fake result cannot be recorded before reservation"
                )
            attempt_head = self._head_attempt_row(
                connection, request.attempt.attempt_id
            )
            if (
                attempt_head is None
                or self._attempt_from_row(attempt_head) != request.attempt
                or request.attempt.lifecycle_state is not AgentLifecycleState.STARTED
            ):
                raise CoordinationStoreConflictError(
                    "fake result is ineligible for the current STARTED attempt head"
                )
            if observed_at >= request.attempt.deadline_at:
                raise CoordinationStoreConflictError(
                    "late fake result requires S3 quarantine"
                )
            completed = FakeInvocationRecord(
                invocation_id=prior.invocation_id,
                idempotency_key=prior.idempotency_key,
                request=prior.request,
                state=FakeInvocationState.COMPLETED,
                reserved_at=prior.reserved_at,
                completed_at=observed_at,
                result=result,
                durable_completion_count=1,
            )
            event, created = self._append_event(
                connection,
                lease=current_lease,
                kind=CoordinationEventKind.FAKE_RESULT_RECORDED,
                subject_id=str(completed.invocation_id),
                idempotency_key=idempotency_key,
                intent_sha256=intent,
                occurred_at=observed_at,
                attempt_id=request.attempt.attempt_id,
                artifact_ref=result.result_id,
                artifact_sha256=result_sha256,
            )
            if not created:
                raise CoordinationStoreIntegrityError(
                    "new fake result unexpectedly reused an event"
                )
            connection.execute(
                """
                UPDATE fake_invocations SET
                    state = ?, result_json = ?, result_sha256 = ?,
                    record_json = ?, record_sha256 = ?, result_event_id = ?
                WHERE invocation_id = ?
                """,
                (
                    completed.state.value,
                    canonical_contract_json(result),
                    result_sha256,
                    canonical_contract_json(completed),
                    contract_sha256(completed),
                    str(event.event_id),
                    str(completed.invocation_id),
                ),
            )
            return completed

    def finalize_fake_execution(
        self,
        lease: RootLeaseHandle,
        attempt_id: str,
        *,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> AgentExecutionReceipt:
        """Author and persist an S1 receipt solely from durable S2 observations."""

        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM fake_invocations WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise CoordinationStoreNotFoundError("fake invocation was not found")
            invocation = self._invocation_from_row(row)
            if invocation.result is None:
                raise CoordinationStoreConflictError(
                    "fake execution cannot finalize before its result is durable"
                )
            default_time = invocation.result.script.cleanup_at
        observed_at = _require_utc(
            occurred_at or default_time,
            label="execution receipt recording time",
        )
        if observed_at < default_time:
            raise ValueError("execution receipt cannot be recorded before fake cleanup")
        result = invocation.result
        payload = result.payload
        intent = _intent_sha256(
            "finalize_fake_execution",
            {
                "attempt_id": attempt_id,
                "result_id": result.result_id,
                "result_sha256": contract_sha256(result),
            },
        )
        with self._transaction() as connection:
            current_lease = self._validate_lease_handle(
                connection, lease, now=observed_at
            )
            if current_lease.task_id != result.request.assignment.task_id:
                raise CoordinationStoreLeaseError(
                    "fake execution belongs to another root task"
                )
            existing_event = self._event_for_idempotency(
                connection,
                task_id=current_lease.task_id,
                idempotency_key=idempotency_key,
                intent_sha256=intent,
                kind=CoordinationEventKind.EXECUTION_RECEIPT_RECORDED,
            )
            if existing_event is not None:
                row = connection.execute(
                    "SELECT receipt_json FROM fake_invocations WHERE receipt_event_id = ?",
                    (str(existing_event.event_id),),
                ).fetchone()
                if row is None or row["receipt_json"] is None:
                    raise CoordinationStoreIntegrityError(
                        "idempotent receipt event has no durable receipt"
                    )
                try:
                    return AgentExecutionReceipt.model_validate_json(
                        str(row["receipt_json"])
                    )
                except ValidationError as exc:
                    raise CoordinationStoreIntegrityError(
                        "stored execution receipt is invalid"
                    ) from exc

            row = connection.execute(
                "SELECT * FROM fake_invocations WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise CoordinationStoreNotFoundError("fake invocation was not found")
            invocation = self._invocation_from_row(row)
            if invocation.state is not FakeInvocationState.COMPLETED or invocation.result is None:
                raise CoordinationStoreConflictError(
                    "fake invocation does not have one completed result"
                )
            if row["receipt_json"] is not None:
                raise CoordinationStoreConflictError(
                    "fake execution already has a receipt under another intent"
                )
            if invocation.result != result:
                raise CoordinationStoreConflictError(
                    "durable fake result changed during receipt finalization"
                )
            result = invocation.result
            payload = result.payload
            head_row = self._head_attempt_row(connection, attempt_id)
            if head_row is None:
                raise CoordinationStoreIntegrityError(
                    "fake invocation attempt head is missing"
                )
            started_attempt = self._attempt_from_row(head_row)
            if (
                started_attempt.lifecycle_state is not AgentLifecycleState.STARTED
                or started_attempt != result.request.attempt
            ):
                raise CoordinationStoreConflictError(
                    "fake receipt requires the exact durable STARTED request snapshot"
                )
            if result.outcome_state not in {
                AgentLifecycleState.RESULT_RECEIVED,
                AgentLifecycleState.FAILED,
                AgentLifecycleState.TIMED_OUT,
            }:
                raise CoordinationStoreConflictError(
                    "fake result has an unsupported S2 execution outcome"
                )
            if started_attempt.root_coordination_epoch != current_lease.epoch:
                raise CoordinationStoreLeaseError(
                    "fake receipt attempt belongs to a stale fencing epoch"
                )
            operation_digest = _json_sha256(idempotency_key)
            outcome_attempt = self._record_generated_attempt_transition(
                connection,
                lease=current_lease,
                previous=started_attempt,
                to_state=result.outcome_state,
                operation_key=f"store-fake-outcome:{operation_digest}",
                occurred_at=observed_at,
                reason="store observed the durable deterministic fake outcome",
            )
            cleanup_attempt = self._record_generated_attempt_transition(
                connection,
                lease=current_lease,
                previous=outcome_attempt,
                to_state=AgentLifecycleState(result.cleanup_state.value),
                operation_key=f"store-fake-cleanup:{operation_digest}",
                occurred_at=observed_at,
                reason="store observed the durable deterministic fake cleanup",
            )
            started_at = result.request.attempt.started_at
            if started_at is None:
                raise CoordinationStoreIntegrityError(
                    "fake result request has no attempt start time"
                )
            runtime_session_id = result.request.attempt.runtime_session_id
            if runtime_session_id is None:
                raise CoordinationStoreIntegrityError(
                    "fake result request has no runtime session identity"
                )
            attempt_events = tuple(
                event
                for event in (
                    self._event_from_row(event_row)
                    for event_row in connection.execute(
                        """
                        SELECT * FROM coordination_events
                        WHERE task_id = ? ORDER BY task_sequence
                        """,
                        (str(current_lease.task_id),),
                    )
                )
                if event.attempt_id == attempt_id
            )
            if not attempt_events:
                raise CoordinationStoreIntegrityError(
                    "fake execution has no durable attempt events"
                )
            cancel_events = tuple(
                event
                for event in attempt_events
                if event.kind is CoordinationEventKind.ATTEMPT_TRANSITION
                and event.to_state is AgentLifecycleState.CANCEL_REQUESTED
            )
            receipt = AgentExecutionReceipt(
                task_id=result.request.assignment.task_id,
                source_task_revision=result.request.assignment.source_task_revision,
                assignment_id=result.request.assignment.assignment_id,
                attempt_id=attempt_id,
                attempt_integrity_id=cleanup_attempt.attempt_integrity_id,
                context_manifest_sha256=(
                    result.request.assignment.context_manifest_sha256
                ),
                payload_id=payload.payload_id,
                payload_sha256=contract_sha256(payload),
                runtime_session_id=runtime_session_id,
                backend_id=result.backend_id,
                profile_id=result.profile_id,
                root_coordination_epoch=current_lease.epoch,
                cancellation_epoch=cleanup_attempt.cancellation_epoch,
                budget=result.request.assignment.budget,
                usage=result.usage,
                started_at=started_at,
                outcome_at=result.script.outcome_at,
                deadline_at=result.request.attempt.deadline_at,
                cancel_requested_at=(
                    None if not cancel_events else cancel_events[0].occurred_at
                ),
                cleanup_at=result.script.cleanup_at,
                outcome_state=result.outcome_state,
                cleanup_state=result.cleanup_state,
                late_result=(
                    result.outcome_state is AgentLifecycleState.RESULT_RECEIVED
                    and result.script.outcome_at > result.request.attempt.deadline_at
                ),
                event_refs=tuple(event.event_ref for event in attempt_events),
            )
            receipt_sha256 = contract_sha256(receipt)
            event, created = self._append_event(
                connection,
                lease=current_lease,
                kind=CoordinationEventKind.EXECUTION_RECEIPT_RECORDED,
                subject_id=str(invocation.invocation_id),
                idempotency_key=idempotency_key,
                intent_sha256=intent,
                occurred_at=observed_at,
                attempt_id=attempt_id,
                artifact_ref=receipt.receipt_id,
                artifact_sha256=receipt_sha256,
            )
            if not created:
                raise CoordinationStoreIntegrityError(
                    "new execution receipt unexpectedly reused an event"
                )
            connection.execute(
                """
                UPDATE fake_invocations SET
                    payload_json = ?, payload_sha256 = ?,
                    receipt_json = ?, receipt_sha256 = ?, receipt_event_id = ?
                WHERE invocation_id = ?
                """,
                (
                    canonical_contract_json(payload),
                    contract_sha256(payload),
                    canonical_contract_json(receipt),
                    receipt_sha256,
                    str(event.event_id),
                    str(invocation.invocation_id),
                ),
            )
            return receipt

    def load_payload(self, identifier: str) -> AgentPayload:
        """Load a fake payload by attempt ID or payload ID."""

        with self._read_connection() as connection:
            self._verify_integrity_connection(connection)
            rows = connection.execute(
                "SELECT attempt_id, payload_json FROM fake_invocations "
                "WHERE payload_json IS NOT NULL"
            ).fetchall()
            for row in rows:
                try:
                    payload = AgentPayload.model_validate_json(str(row["payload_json"]))
                except ValidationError as exc:
                    raise CoordinationStoreIntegrityError(
                        "stored fake payload is invalid"
                    ) from exc
                if str(row["attempt_id"]) == identifier or payload.payload_id == identifier:
                    return payload
        raise CoordinationStoreNotFoundError("fake payload was not found")

    def load_execution_receipt(self, identifier: str) -> AgentExecutionReceipt:
        """Load a store-authored receipt by attempt ID or receipt ID."""

        with self._read_connection() as connection:
            self._verify_integrity_connection(connection)
            rows = connection.execute(
                "SELECT attempt_id, receipt_json FROM fake_invocations "
                "WHERE receipt_json IS NOT NULL"
            ).fetchall()
            for row in rows:
                try:
                    receipt = AgentExecutionReceipt.model_validate_json(
                        str(row["receipt_json"])
                    )
                except ValidationError as exc:
                    raise CoordinationStoreIntegrityError(
                        "stored execution receipt is invalid"
                    ) from exc
                if str(row["attempt_id"]) == identifier or receipt.receipt_id == identifier:
                    return receipt
        raise CoordinationStoreNotFoundError("execution receipt was not found")

    def inspect_attempt(
        self,
        lease: RootLeaseHandle,
        attempt_id: str,
        *,
        idempotency_key: str,
        decided_at: datetime | None = None,
    ) -> AttemptRecoveryRecord:
        """Record a deterministic restart decision that never authorizes replay."""

        observed_at = _require_utc(
            decided_at or utc_now(), label="attempt recovery decision time"
        )
        with self._transaction() as connection:
            current_lease = self._validate_lease_handle(
                connection, lease, now=observed_at
            )
            intent = _intent_sha256(
                "inspect_attempt",
                {"attempt_id": attempt_id},
            )
            existing_event = self._event_for_idempotency(
                connection,
                task_id=current_lease.task_id,
                idempotency_key=idempotency_key,
                intent_sha256=intent,
                kind=CoordinationEventKind.RECOVERY_DECISION_RECORDED,
            )
            if existing_event is not None:
                row = connection.execute(
                    "SELECT * FROM attempt_recoveries WHERE event_id = ?",
                    (str(existing_event.event_id),),
                ).fetchone()
                if row is None:
                    raise CoordinationStoreIntegrityError(
                        "idempotent recovery event has no decision record"
                    )
                try:
                    return AttemptRecoveryRecord.model_validate_json(
                        str(row["recovery_json"])
                    )
                except (ValidationError, ValueError) as exc:
                    raise CoordinationStoreIntegrityError(
                        "stored attempt recovery decision is invalid"
                    ) from exc
            attempt_row = self._head_attempt_row(connection, attempt_id)
            if attempt_row is None:
                raise CoordinationStoreNotFoundError("coordination attempt was not found")
            attempt = self._attempt_from_row(attempt_row)
            if attempt.task_id != current_lease.task_id:
                raise CoordinationStoreLeaseError(
                    "recovery attempt belongs to another root task"
                )
            invocation_row = connection.execute(
                "SELECT * FROM fake_invocations WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            receipt: AgentExecutionReceipt | None = None
            invocation: FakeInvocationRecord | None = None
            if invocation_row is not None:
                invocation = self._invocation_from_row(invocation_row)
                if invocation_row["receipt_json"] is not None:
                    try:
                        receipt = AgentExecutionReceipt.model_validate_json(
                            str(invocation_row["receipt_json"])
                        )
                    except ValidationError as exc:
                        raise CoordinationStoreIntegrityError(
                            "stored execution receipt is invalid"
                        ) from exc
            if receipt is not None:
                disposition = RecoveryDisposition.RECEIPT_REUSED
                reason = "durable store-authored execution receipt is reusable"
                receipt_ref = receipt.receipt_id
                receipt_sha256 = contract_sha256(receipt)
            elif invocation is not None and invocation.state is FakeInvocationState.COMPLETED:
                disposition = RecoveryDisposition.MANUAL_RECONCILIATION
                reason = "durable fake result exists without a store-authored receipt"
                receipt_ref = None
                receipt_sha256 = None
            elif invocation is not None:
                disposition = RecoveryDisposition.NO_REPLAY
                reason = "durable fake reservation has ambiguous execution outcome"
                receipt_ref = None
                receipt_sha256 = None
            elif attempt.lifecycle_state in {
                AgentLifecycleState.PROPOSED,
                AgentLifecycleState.ADMITTED,
                AgentLifecycleState.DENIED,
                AgentLifecycleState.CREATED,
            }:
                disposition = RecoveryDisposition.NO_ACTION
                reason = "attempt has no durable fake invocation to replay"
                receipt_ref = None
                receipt_sha256 = None
            else:
                disposition = RecoveryDisposition.NO_REPLAY
                reason = "attempt lifecycle is execution-ambiguous without a durable receipt"
                receipt_ref = None
                receipt_sha256 = None
            head = connection.execute(
                "SELECT * FROM coordination_event_heads WHERE task_id = ?",
                (str(current_lease.task_id),),
            ).fetchone()
            if head is None:
                raise CoordinationStoreIntegrityError(
                    "recovery requires a durable coordination event head"
                )
            event_head_sha256 = str(head["event_sha256"])
            recovery = AttemptRecoveryRecord(
                task_id=current_lease.task_id,
                attempt_id=attempt_id,
                root_coordination_epoch=current_lease.epoch,
                disposition=disposition,
                reason=reason,
                event_head_sha256=event_head_sha256,
                receipt_ref=receipt_ref,
                receipt_sha256=receipt_sha256,
                decided_at=observed_at,
            )
            recovery_sha256 = contract_sha256(recovery)
            event, created = self._append_event(
                connection,
                lease=current_lease,
                kind=CoordinationEventKind.RECOVERY_DECISION_RECORDED,
                subject_id=recovery.recovery_id,
                idempotency_key=idempotency_key,
                intent_sha256=intent,
                occurred_at=observed_at,
                attempt_id=attempt_id,
                artifact_ref=recovery.recovery_id,
                artifact_sha256=recovery_sha256,
                reason=reason,
            )
            if not created:
                raise CoordinationStoreIntegrityError(
                    "new recovery decision unexpectedly reused an event"
                )
            connection.execute(
                """
                INSERT INTO attempt_recoveries (
                    recovery_id, task_id, attempt_id,
                    root_coordination_epoch, disposition,
                    recovery_json, recovery_sha256, event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recovery.recovery_id,
                    str(recovery.task_id),
                    recovery.attempt_id,
                    recovery.root_coordination_epoch,
                    recovery.disposition.value,
                    canonical_contract_json(recovery),
                    recovery_sha256,
                    str(event.event_id),
                ),
            )
            return recovery
