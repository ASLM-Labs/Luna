"""SQLite WAL persistence shared by the Phase 15 operations components."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from luna.contracts.base import utc_now
from luna.operations.models import (
    NotificationEvent,
    NotificationStatus,
    QueueItem,
    QueueStatus,
    ResourceCapacity,
    ResourceLease,
    ResourceLeaseStatus,
    ScheduledJob,
    canonical_payload_json,
    payload_digest,
)

OPERATIONS_SCHEMA_VERSION = 1


class OperationsStoreError(RuntimeError):
    """Base durable-operations store error."""


class OperationsConflictError(OperationsStoreError):
    """Raised when idempotency or an expected-state transition conflicts."""


class OperationsIntegrityError(OperationsStoreError):
    """Raised when a persisted record fails its SHA-256 integrity check."""


class OperationsNotFoundError(OperationsStoreError):
    """Raised when a requested durable operations record does not exist."""


_PRIORITY_RANK = {
    "LOW": 0,
    "NORMAL": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}


class SQLiteOperationsStore:
    """Shared transaction boundary for queue, schedules, resources, and outbox."""

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
                CREATE TABLE IF NOT EXISTS operations_schema (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM operations_schema"
            ).fetchone()
            current = int(row["version"]) if row is not None else 0
            if current > OPERATIONS_SCHEMA_VERSION:
                raise OperationsStoreError(
                    f"operations schema {current} is newer than runtime "
                    f"{OPERATIONS_SCHEMA_VERSION}"
                )
            if current < 1:
                connection.execute(
                    """
                    CREATE TABLE work_queue (
                        item_id TEXT PRIMARY KEY,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        task_id TEXT NOT NULL,
                        request_id TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL,
                        priority_rank INTEGER NOT NULL,
                        eligible_at TEXT NOT NULL,
                        lease_expires_at TEXT,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX work_queue_ready
                    ON work_queue(status, eligible_at, priority_rank)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX work_queue_task
                    ON work_queue(task_id, updated_at)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE scheduled_jobs (
                        schedule_id TEXT PRIMARY KEY,
                        enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                        next_run_at TEXT NOT NULL,
                        occurrence_count INTEGER NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX scheduled_jobs_due
                    ON scheduled_jobs(enabled, next_run_at)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE resource_leases (
                        lease_id TEXT PRIMARY KEY,
                        item_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(item_id) REFERENCES work_queue(item_id)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX resource_leases_active
                    ON resource_leases(status, expires_at)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE notification_outbox (
                        notification_id TEXT PRIMARY KEY,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        item_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        FOREIGN KEY(item_id) REFERENCES work_queue(item_id)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX notification_outbox_pending
                    ON notification_outbox(status, created_at)
                    """
                )
                connection.execute(
                    "INSERT INTO operations_schema(version, applied_at) VALUES (?, ?)",
                    (1, utc_now().isoformat()),
                )

    def schema_version(self) -> int:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM operations_schema"
            ).fetchone()
        return int(row["version"]) if row is not None else 0

    def journal_mode(self) -> str:
        with self._read_connection() as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
        if row is None:
            raise OperationsStoreError("SQLite did not report journal mode")
        return str(row[0]).casefold()

    @staticmethod
    def _validate_payload(
        model: QueueItem | ScheduledJob | ResourceLease | NotificationEvent,
        digest: str,
    ) -> None:
        if payload_digest(model) != digest:
            raise OperationsIntegrityError("persisted operations payload digest mismatch")

    @classmethod
    def _queue_from_row(cls, row: sqlite3.Row) -> QueueItem:
        item = QueueItem.model_validate_json(str(row["payload_json"]))
        cls._validate_payload(item, str(row["payload_sha256"]))
        return item

    @classmethod
    def _schedule_from_row(cls, row: sqlite3.Row) -> ScheduledJob:
        job = ScheduledJob.model_validate_json(str(row["payload_json"]))
        cls._validate_payload(job, str(row["payload_sha256"]))
        return job

    @classmethod
    def _resource_from_row(cls, row: sqlite3.Row) -> ResourceLease:
        lease = ResourceLease.model_validate_json(str(row["payload_json"]))
        cls._validate_payload(lease, str(row["payload_sha256"]))
        return lease

    @classmethod
    def _notification_from_row(cls, row: sqlite3.Row) -> NotificationEvent:
        event = NotificationEvent.model_validate_json(str(row["payload_json"]))
        cls._validate_payload(event, str(row["payload_sha256"]))
        return event

    @staticmethod
    def _queue_values(item: QueueItem) -> tuple[object, ...]:
        request = item.payload.envelope.request
        return (
            str(item.item_id),
            item.idempotency_key,
            str(request.task_id),
            str(request.request_id),
            item.status.value,
            _PRIORITY_RANK[item.priority.value],
            item.eligible_at.isoformat(),
            item.lease_expires_at.isoformat() if item.lease_expires_at is not None else None,
            canonical_payload_json(item),
            payload_digest(item),
            item.updated_at.isoformat(),
        )

    @staticmethod
    def _write_queue(connection: sqlite3.Connection, item: QueueItem) -> None:
        connection.execute(
            """
            UPDATE work_queue
            SET status = ?,
                priority_rank = ?,
                eligible_at = ?,
                lease_expires_at = ?,
                payload_json = ?,
                payload_sha256 = ?,
                updated_at = ?
            WHERE item_id = ?
            """,
            (
                item.status.value,
                _PRIORITY_RANK[item.priority.value],
                item.eligible_at.isoformat(),
                item.lease_expires_at.isoformat() if item.lease_expires_at is not None else None,
                canonical_payload_json(item),
                payload_digest(item),
                item.updated_at.isoformat(),
                str(item.item_id),
            ),
        )

    def insert_queue_item(self, item: QueueItem) -> QueueItem:
        """Insert idempotently; key reuse with different immutable work is a conflict."""
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM work_queue WHERE idempotency_key = ?",
                (item.idempotency_key,),
            ).fetchone()
            if existing is not None:
                current = self._queue_from_row(existing)
                if (
                    current.payload != item.payload
                    or current.priority != item.priority
                    or current.eligible_at != item.eligible_at
                ):
                    raise OperationsConflictError(
                        "queue idempotency key already exists with different work"
                    )
                return current
            request_id = str(item.payload.envelope.request.request_id)
            request_row = connection.execute(
                "SELECT * FROM work_queue WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if request_row is not None:
                current = self._queue_from_row(request_row)
                if current.idempotency_key != item.idempotency_key:
                    raise OperationsConflictError(
                        "RuntimeRequest request_id is already queued under another key"
                    )
                return current
            connection.execute(
                """
                INSERT INTO work_queue(
                    item_id,
                    idempotency_key,
                    task_id,
                    request_id,
                    status,
                    priority_rank,
                    eligible_at,
                    lease_expires_at,
                    payload_json,
                    payload_sha256,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._queue_values(item),
            )
        return item

    def load_queue_item(self, item_id: UUID) -> QueueItem:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM work_queue WHERE item_id = ?",
                (str(item_id),),
            ).fetchone()
        if row is None:
            raise OperationsNotFoundError(f"queue item not found: {item_id}")
        return self._queue_from_row(row)

    def list_queue_items(
        self,
        *,
        statuses: Sequence[QueueStatus] | None = None,
    ) -> tuple[QueueItem, ...]:
        with self._read_connection() as connection:
            if statuses:
                placeholders = ",".join("?" for _ in statuses)
                rows = connection.execute(
                    f"SELECT * FROM work_queue "
                    f"WHERE status IN ({placeholders}) ORDER BY rowid",
                    tuple(status.value for status in statuses),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM work_queue ORDER BY rowid"
                ).fetchall()
        return tuple(self._queue_from_row(row) for row in rows)

    def ready_queue_items(self, now_iso: str, *, limit: int = 100) -> tuple[QueueItem, ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM work_queue
                WHERE status = ? AND eligible_at <= ?
                ORDER BY priority_rank DESC, eligible_at ASC, rowid ASC
                LIMIT ?
                """,
                (QueueStatus.QUEUED.value, now_iso, limit),
            ).fetchall()
        return tuple(self._queue_from_row(row) for row in rows)

    def transition_queue_item(
        self,
        *,
        item_id: UUID,
        expected: QueueStatus,
        updated: QueueItem,
    ) -> QueueItem:
        if updated.item_id != item_id:
            raise ValueError("updated queue item ID mismatch")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM work_queue WHERE item_id = ?",
                (str(item_id),),
            ).fetchone()
            if row is None:
                raise OperationsNotFoundError(f"queue item not found: {item_id}")
            current = self._queue_from_row(row)
            if current.status is not expected:
                raise OperationsConflictError(
                    f"queue transition expected {expected.value}, found {current.status.value}"
                )
            if (
                current.payload != updated.payload
                or current.idempotency_key != updated.idempotency_key
            ):
                raise OperationsConflictError("queue transition cannot mutate immutable payload")
            self._write_queue(connection, updated)
        return updated

    def insert_schedule(self, job: ScheduledJob) -> ScheduledJob:
        payload = canonical_payload_json(job)
        digest = payload_digest(job)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM scheduled_jobs WHERE schedule_id = ?",
                (str(job.schedule_id),),
            ).fetchone()
            if existing is not None:
                current = self._schedule_from_row(existing)
                if current != job:
                    raise OperationsConflictError(
                        "schedule_id already exists with different payload"
                    )
                return current
            connection.execute(
                """
                INSERT INTO scheduled_jobs(
                    schedule_id, enabled, next_run_at, occurrence_count,
                    payload_json, payload_sha256, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(job.schedule_id),
                    int(job.enabled),
                    job.next_run_at.isoformat(),
                    job.occurrence_count,
                    payload,
                    digest,
                    job.updated_at.isoformat(),
                ),
            )
        return job

    def load_schedule(self, schedule_id: UUID) -> ScheduledJob:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_jobs WHERE schedule_id = ?",
                (str(schedule_id),),
            ).fetchone()
        if row is None:
            raise OperationsNotFoundError(f"schedule not found: {schedule_id}")
        return self._schedule_from_row(row)

    def due_schedules(self, now_iso: str, *, limit: int) -> tuple[ScheduledJob, ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM scheduled_jobs
                WHERE enabled = 1 AND next_run_at <= ?
                ORDER BY next_run_at ASC, rowid ASC
                LIMIT ?
                """,
                (now_iso, limit),
            ).fetchall()
        return tuple(self._schedule_from_row(row) for row in rows)

    def materialize_schedule_occurrence(
        self,
        *,
        current: ScheduledJob,
        item: QueueItem,
        updated: ScheduledJob,
    ) -> QueueItem:
        """Atomically materialize one due occurrence and advance its schedule."""
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_jobs WHERE schedule_id = ?",
                (str(current.schedule_id),),
            ).fetchone()
            if row is None:
                raise OperationsNotFoundError(f"schedule not found: {current.schedule_id}")
            stored = self._schedule_from_row(row)
            if (
                stored.occurrence_count != current.occurrence_count
                or stored.next_run_at != current.next_run_at
                or stored.enabled != current.enabled
            ):
                raise OperationsConflictError("schedule changed before materialization")

            existing = connection.execute(
                "SELECT * FROM work_queue WHERE idempotency_key = ?",
                (item.idempotency_key,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO work_queue(
                        item_id,
                        idempotency_key,
                        task_id,
                        request_id,
                        status,
                        priority_rank,
                        eligible_at,
                        lease_expires_at,
                        payload_json,
                        payload_sha256,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._queue_values(item),
                )
            else:
                persisted = self._queue_from_row(existing)
                if persisted.payload != item.payload:
                    raise OperationsConflictError(
                        "schedule occurrence idempotency key conflicts with different work"
                    )
                item = persisted

            connection.execute(
                """
                UPDATE scheduled_jobs
                SET enabled = ?, next_run_at = ?, occurrence_count = ?,
                    payload_json = ?, payload_sha256 = ?, updated_at = ?
                WHERE schedule_id = ?
                """,
                (
                    int(updated.enabled),
                    updated.next_run_at.isoformat(),
                    updated.occurrence_count,
                    canonical_payload_json(updated),
                    payload_digest(updated),
                    updated.updated_at.isoformat(),
                    str(updated.schedule_id),
                ),
            )
        return item

    def allocate_resource_lease(
        self,
        *,
        lease: ResourceLease,
        capacity: ResourceCapacity,
    ) -> ResourceLease | None:
        """Atomically enforce durable capacity including stale/ambiguous reservations."""
        with self._transaction() as connection:
            existing_item = connection.execute(
                "SELECT * FROM resource_leases WHERE item_id = ? AND status IN (?, ?)",
                (
                    str(lease.item_id),
                    ResourceLeaseStatus.ACTIVE.value,
                    ResourceLeaseStatus.STALE.value,
                ),
            ).fetchone()
            if existing_item is not None:
                return None
            rows = connection.execute(
                "SELECT * FROM resource_leases WHERE status IN (?, ?)",
                (ResourceLeaseStatus.ACTIVE.value, ResourceLeaseStatus.STALE.value),
            ).fetchall()
            active = tuple(self._resource_from_row(row) for row in rows)
            used_worker = sum(item.requirement.worker_slots for item in active)
            used_model = sum(item.requirement.model_slots for item in active)
            used_network = sum(item.requirement.network_slots for item in active)
            requirement = lease.requirement
            if (
                used_worker + requirement.worker_slots > capacity.worker_slots
                or used_model + requirement.model_slots > capacity.model_slots
                or used_network + requirement.network_slots > capacity.network_slots
            ):
                return None
            connection.execute(
                """
                INSERT INTO resource_leases(
                    lease_id, item_id, status, expires_at,
                    payload_json, payload_sha256, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(lease.lease_id),
                    str(lease.item_id),
                    lease.status.value,
                    lease.expires_at.isoformat(),
                    canonical_payload_json(lease),
                    payload_digest(lease),
                    lease.created_at.isoformat(),
                ),
            )
        return lease

    def load_resource_lease(self, lease_id: UUID) -> ResourceLease:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM resource_leases WHERE lease_id = ?",
                (str(lease_id),),
            ).fetchone()
        if row is None:
            raise OperationsNotFoundError(f"resource lease not found: {lease_id}")
        return self._resource_from_row(row)

    def list_resource_leases(
        self,
        *,
        statuses: Sequence[ResourceLeaseStatus] | None = None,
    ) -> tuple[ResourceLease, ...]:
        with self._read_connection() as connection:
            if statuses:
                placeholders = ",".join("?" for _ in statuses)
                rows = connection.execute(
                    f"SELECT * FROM resource_leases "
                    f"WHERE status IN ({placeholders}) ORDER BY rowid",
                    tuple(status.value for status in statuses),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM resource_leases ORDER BY rowid"
                ).fetchall()
        return tuple(self._resource_from_row(row) for row in rows)

    def update_resource_lease(
        self,
        *,
        lease_id: UUID,
        expected: ResourceLeaseStatus,
        updated: ResourceLease,
    ) -> ResourceLease:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM resource_leases WHERE lease_id = ?",
                (str(lease_id),),
            ).fetchone()
            if row is None:
                raise OperationsNotFoundError(f"resource lease not found: {lease_id}")
            current = self._resource_from_row(row)
            if current.status is not expected:
                if current == updated:
                    return current
                raise OperationsConflictError(
                    f"resource lease expected {expected.value}, found {current.status.value}"
                )
            connection.execute(
                """
                UPDATE resource_leases
                SET status = ?, expires_at = ?, payload_json = ?, payload_sha256 = ?, updated_at = ?
                WHERE lease_id = ?
                """,
                (
                    updated.status.value,
                    updated.expires_at.isoformat(),
                    canonical_payload_json(updated),
                    payload_digest(updated),
                    (updated.released_at or updated.created_at).isoformat(),
                    str(lease_id),
                ),
            )
        return updated

    def insert_notification(self, event: NotificationEvent) -> NotificationEvent:
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM notification_outbox WHERE dedupe_key = ?",
                (event.dedupe_key,),
            ).fetchone()
            if existing is not None:
                current = self._notification_from_row(existing)
                if (
                    current.item_id != event.item_id
                    or current.outcome_id != event.outcome_id
                    or current.kind != event.kind
                ):
                    raise OperationsConflictError(
                        "notification dedupe key already exists with different event"
                    )
                return current
            connection.execute(
                """
                INSERT INTO notification_outbox(
                    notification_id, dedupe_key, item_id, task_id, status,
                    created_at, payload_json, payload_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event.notification_id),
                    event.dedupe_key,
                    str(event.item_id),
                    str(event.task_id),
                    event.status.value,
                    event.created_at.isoformat(),
                    canonical_payload_json(event),
                    payload_digest(event),
                ),
            )
        return event

    def pending_notifications(self, *, limit: int = 100) -> tuple[NotificationEvent, ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM notification_outbox
                WHERE status = ?
                ORDER BY created_at ASC, rowid ASC
                LIMIT ?
                """,
                (NotificationStatus.PENDING.value, limit),
            ).fetchall()
        return tuple(self._notification_from_row(row) for row in rows)

    def load_notification(self, notification_id: UUID) -> NotificationEvent:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM notification_outbox WHERE notification_id = ?",
                (str(notification_id),),
            ).fetchone()
        if row is None:
            raise OperationsNotFoundError(f"notification not found: {notification_id}")
        return self._notification_from_row(row)

    def acknowledge_notification(
        self,
        *,
        current: NotificationEvent,
        updated: NotificationEvent,
    ) -> NotificationEvent:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM notification_outbox WHERE notification_id = ?",
                (str(current.notification_id),),
            ).fetchone()
            if row is None:
                raise OperationsNotFoundError(
                    f"notification not found: {current.notification_id}"
                )
            stored = self._notification_from_row(row)
            if stored.status is NotificationStatus.ACKNOWLEDGED:
                return stored
            if stored.status is not NotificationStatus.PENDING:
                raise OperationsConflictError("notification is not pending")
            connection.execute(
                """
                UPDATE notification_outbox
                SET status = ?, payload_json = ?, payload_sha256 = ?
                WHERE notification_id = ?
                """,
                (
                    updated.status.value,
                    canonical_payload_json(updated),
                    payload_digest(updated),
                    str(updated.notification_id),
                ),
            )
        return updated


    def finalize_dispatch_atomically(
        self,
        *,
        current_item: QueueItem,
        updated_item: QueueItem,
        current_lease: ResourceLease,
        released_lease: ResourceLease,
        event: NotificationEvent,
    ) -> NotificationEvent:
        """Commit runtime outcome, release capacity, and create outbox event together."""
        if current_item.status is not QueueStatus.DISPATCHED:
            raise ValueError("atomic finalization requires DISPATCHED queue item")
        if current_lease.status not in {
            ResourceLeaseStatus.ACTIVE,
            ResourceLeaseStatus.STALE,
        }:
            raise ValueError("atomic finalization requires held resource capacity")
        if released_lease.status is not ResourceLeaseStatus.RELEASED:
            raise ValueError("atomic finalization requires RELEASED resource lease")
        if current_item.resource_lease_id != current_lease.lease_id:
            raise ValueError("queue item and resource lease mismatch")
        if updated_item.outcome is None or updated_item.outcome.outcome_id != event.outcome_id:
            raise ValueError("notification must reference the finalized RuntimeOutcome")

        with self._transaction() as connection:
            queue_row = connection.execute(
                "SELECT * FROM work_queue WHERE item_id = ?",
                (str(current_item.item_id),),
            ).fetchone()
            if queue_row is None:
                raise OperationsNotFoundError(f"queue item not found: {current_item.item_id}")
            stored_item = self._queue_from_row(queue_row)
            if stored_item.status is not QueueStatus.DISPATCHED:
                raise OperationsConflictError(
                    f"atomic finalization expected DISPATCHED, found {stored_item.status.value}"
                )
            if stored_item.dispatch_id != current_item.dispatch_id:
                raise OperationsConflictError("dispatch fence changed before finalization")

            lease_row = connection.execute(
                "SELECT * FROM resource_leases WHERE lease_id = ?",
                (str(current_lease.lease_id),),
            ).fetchone()
            if lease_row is None:
                raise OperationsNotFoundError(
                    f"resource lease not found: {current_lease.lease_id}"
                )
            stored_lease = self._resource_from_row(lease_row)
            if stored_lease.status not in {
                ResourceLeaseStatus.ACTIVE,
                ResourceLeaseStatus.STALE,
            }:
                raise OperationsConflictError(
                    "resource lease is no longer held during dispatch finalization"
                )

            self._write_queue(connection, updated_item)
            connection.execute(
                """
                UPDATE resource_leases
                SET status = ?, expires_at = ?, payload_json = ?, payload_sha256 = ?, updated_at = ?
                WHERE lease_id = ?
                """,
                (
                    released_lease.status.value,
                    released_lease.expires_at.isoformat(),
                    canonical_payload_json(released_lease),
                    payload_digest(released_lease),
                    released_lease.released_at.isoformat()
                    if released_lease.released_at is not None
                    else released_lease.created_at.isoformat(),
                    str(released_lease.lease_id),
                ),
            )

            existing_event = connection.execute(
                "SELECT * FROM notification_outbox WHERE dedupe_key = ?",
                (event.dedupe_key,),
            ).fetchone()
            if existing_event is None:
                connection.execute(
                    """
                    INSERT INTO notification_outbox(
                        notification_id, dedupe_key, item_id, task_id, status,
                        created_at, payload_json, payload_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(event.notification_id),
                        event.dedupe_key,
                        str(event.item_id),
                        str(event.task_id),
                        event.status.value,
                        event.created_at.isoformat(),
                        canonical_payload_json(event),
                        payload_digest(event),
                    ),
                )
            else:
                persisted = self._notification_from_row(existing_event)
                if (
                    persisted.item_id != event.item_id
                    or persisted.outcome_id != event.outcome_id
                    or persisted.kind != event.kind
                ):
                    raise OperationsConflictError(
                        "notification dedupe conflict during dispatch finalization"
                    )
                event = persisted
        return event
