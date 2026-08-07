"""Durable evidence registry used by the Phase 12F verification handoff."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from luna.audit.evidence import EvidenceLedger
from luna.contracts.evidence import Evidence

EVIDENCE_STORE_SCHEMA_VERSION = 1


class EvidenceStoreError(RuntimeError):
    """Base durable evidence-store error."""


class EvidenceStoreConflictError(EvidenceStoreError):
    """Raised when an evidence ID is reused with a different payload."""


def _canonical_json(evidence: Evidence) -> str:
    return json.dumps(
        evidence.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(evidence: Evidence) -> str:
    return sha256(_canonical_json(evidence).encode()).hexdigest()


class SQLiteEvidenceStore:
    """SQLite WAL storage for immutable evidence records."""

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
                CREATE TABLE IF NOT EXISTS evidence_schema (
                    version INTEGER PRIMARY KEY
                )
                """
            )
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM evidence_schema"
            ).fetchone()
            current = int(row["version"]) if row is not None else 0
            if current > EVIDENCE_STORE_SCHEMA_VERSION:
                raise EvidenceStoreError(
                    f"evidence schema {current} is newer than "
                    f"{EVIDENCE_STORE_SCHEMA_VERSION}"
                )
            if current < 1:
                connection.execute(
                    """
                    CREATE TABLE evidence_records (
                        evidence_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        requirement_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX evidence_task_requirement
                    ON evidence_records(task_id, requirement_id, evidence_id)
                    """
                )
                connection.execute(
                    "INSERT INTO evidence_schema(version) VALUES (1)"
                )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Evidence:
        payload = str(row["payload_json"])
        evidence = Evidence.model_validate_json(payload)
        if _digest(evidence) != str(row["payload_sha256"]):
            raise EvidenceStoreError(
                f"evidence payload digest mismatch: {row['evidence_id']}"
            )
        if str(evidence.evidence_id) != str(row["evidence_id"]):
            raise EvidenceStoreError("evidence row ID does not match payload")
        if str(evidence.task_id) != str(row["task_id"]):
            raise EvidenceStoreError("evidence row task_id does not match payload")
        if evidence.requirement_id != str(row["requirement_id"]):
            raise EvidenceStoreError("evidence row requirement_id does not match payload")
        return evidence

    def save(self, evidence: Evidence) -> Evidence:
        """Persist an immutable evidence record idempotently."""
        payload = _canonical_json(evidence)
        digest = _digest(evidence)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM evidence_records WHERE evidence_id = ?",
                (str(evidence.evidence_id),),
            ).fetchone()
            if existing is not None:
                current = self._from_row(existing)
                if current != evidence:
                    raise EvidenceStoreConflictError(
                        "evidence ID already exists with different payload"
                    )
                return current
            connection.execute(
                """
                INSERT INTO evidence_records(
                    evidence_id,
                    task_id,
                    requirement_id,
                    payload_json,
                    payload_sha256
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(evidence.evidence_id),
                    str(evidence.task_id),
                    evidence.requirement_id,
                    payload,
                    digest,
                ),
            )
        return evidence

    def list_for_task(self, task_id: UUID) -> tuple[Evidence, ...]:
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM evidence_records
                WHERE task_id = ?
                ORDER BY rowid
                """,
                (str(task_id),),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def verify_integrity(self) -> bool:
        try:
            with self._read_connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM evidence_records ORDER BY rowid"
                ).fetchall()
            for row in rows:
                self._from_row(row)
        except (EvidenceStoreError, ValueError, sqlite3.DatabaseError):
            return False
        return True


class VerifiedEvidenceRegistry:
    """Persist evidence and optionally mirror it into the append-only audit ledger."""

    def __init__(
        self,
        store: SQLiteEvidenceStore,
        ledger: EvidenceLedger | None = None,
    ) -> None:
        self.store = store
        self.ledger = ledger

    def record(
        self,
        *,
        evidence: Evidence,
        trace_id: UUID | None = None,
        observation_id: UUID | None = None,
    ) -> Evidence:
        if self.ledger is not None and trace_id is None:
            raise ValueError("audited evidence recording requires trace_id")
        stored = self.store.save(evidence)
        if self.ledger is not None:
            assert trace_id is not None
            self.ledger.record(
                evidence=stored,
                trace_id=trace_id,
                observation_id=observation_id,
            )
        return stored

    def list_for_task(self, task_id: UUID) -> tuple[Evidence, ...]:
        return self.store.list_for_task(task_id)

    def verify_integrity(self) -> bool:
        return self.store.verify_integrity()
