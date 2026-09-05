"""Minimal durable S4 invocation journal with fail-closed no-replay recovery."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from luna.parallel_cognition.controls import (
    ControlFencePhase,
    FenceDecision,
    evaluate_control_fence,
)
from luna.parallel_cognition.live import (
    LiveBackendRequest,
    LiveBackendResult,
    LiveInvocationRecord,
    LiveInvocationState,
)
from luna.parallel_cognition.models import (
    AgentExecutionAttempt,
    AgentExecutionReceipt,
    DistilledHandoff,
    canonical_contract_json,
    contract_sha256,
    validate_c011_contract_chain,
)

S4_LIVE_JOURNAL_SCHEMA_VERSION = 1


class LiveInvocationJournalError(RuntimeError):
    """Base S4 journal failure."""


class LiveInvocationConflictError(LiveInvocationJournalError):
    """A durable invocation identity was reused with different content."""


class LiveInvocationIntegrityError(LiveInvocationJournalError):
    """Persisted S4 invocation content failed validation."""


@dataclass(frozen=True, slots=True)
class LiveInvocationProjection:
    record: LiveInvocationRecord
    receipt: AgentExecutionReceipt | None


_SCHEMA = """
CREATE TABLE live_invocations (
    invocation_key TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    root_coordination_epoch INTEGER NOT NULL CHECK (root_coordination_epoch >= 1),
    assignment_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (state IN ('RESERVED', 'COMPLETED')),
    request_json TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    result_json TEXT,
    result_sha256 TEXT,
    receipt_json TEXT,
    receipt_sha256 TEXT,
    handoff_json TEXT,
    handoff_sha256 TEXT,
    record_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    UNIQUE (task_id, root_coordination_epoch, assignment_id)
);

CREATE TABLE handoff_reuse_fences (
    decision_id TEXT PRIMARY KEY,
    invocation_key TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    decision_sha256 TEXT NOT NULL,
    FOREIGN KEY (invocation_key) REFERENCES live_invocations(invocation_key)
);
"""


class SQLiteLiveInvocationJournal:
    """Persist S4 reservations before spawn and never replay an in-doubt attempt."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).resolve()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LiveInvocationJournalError(
                "failed to create S4 invocation journal directory"
            ) from exc
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA busy_timeout = 5000")
            row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
            if row is None or str(row[0]).casefold() != "wal":
                raise LiveInvocationJournalError("S4 journal did not enable WAL")
            return connection
        except LiveInvocationJournalError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            raise LiveInvocationJournalError("failed to open S4 journal") from exc

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        except LiveInvocationJournalError:
            raise
        except sqlite3.DatabaseError as exc:
            raise LiveInvocationJournalError("S4 journal read failed") from exc
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._read_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._verify(connection)
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize(self) -> None:
        with self._read_connection() as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
            if row is None:
                raise LiveInvocationJournalError("S4 journal version is unavailable")
            version = int(row[0])
            tables = frozenset(
                str(item[0])
                for item in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            )
            if version == 0:
                if tables:
                    raise LiveInvocationJournalError(
                        "unversioned S4 journal contains durable tables"
                    )
                connection.executescript(_SCHEMA)
                connection.execute(
                    f"PRAGMA user_version = {S4_LIVE_JOURNAL_SCHEMA_VERSION}"
                )
            elif version != S4_LIVE_JOURNAL_SCHEMA_VERSION or tables != {
                "handoff_reuse_fences",
                "live_invocations",
            }:
                raise LiveInvocationJournalError(
                    f"unsupported S4 journal schema: version={version}, tables={tables}"
                )
            connection.commit()
            self._verify(connection)

    @staticmethod
    def _projection_from_row(row: sqlite3.Row) -> LiveInvocationProjection:
        try:
            request = LiveBackendRequest.model_validate_json(str(row["request_json"]))
            record = LiveInvocationRecord.model_validate_json(str(row["record_json"]))
            result = (
                None
                if row["result_json"] is None
                else LiveBackendResult.model_validate_json(str(row["result_json"]))
            )
            receipt = (
                None
                if row["receipt_json"] is None
                else AgentExecutionReceipt.model_validate_json(str(row["receipt_json"]))
            )
            handoff = (
                None
                if row["handoff_json"] is None
                else DistilledHandoff.model_validate_json(str(row["handoff_json"]))
            )
        except (ValidationError, ValueError) as exc:
            raise LiveInvocationIntegrityError(
                "stored S4 invocation is invalid"
            ) from exc
        expected_columns = (
            record.invocation_key,
            str(request.assignment.task_id),
            request.assignment.root_coordination_epoch,
            request.assignment.assignment_id,
            request.attempt.attempt_id,
            record.state.value,
            contract_sha256(request),
            None if result is None else contract_sha256(result),
            None if receipt is None else contract_sha256(receipt),
            None if handoff is None else contract_sha256(handoff),
            contract_sha256(record),
        )
        actual_columns = (
            str(row["invocation_key"]),
            str(row["task_id"]),
            int(row["root_coordination_epoch"]),
            str(row["assignment_id"]),
            str(row["attempt_id"]),
            str(row["state"]),
            str(row["request_sha256"]),
            None if row["result_sha256"] is None else str(row["result_sha256"]),
            None if row["receipt_sha256"] is None else str(row["receipt_sha256"]),
            None if row["handoff_sha256"] is None else str(row["handoff_sha256"]),
            str(row["record_sha256"]),
        )
        if actual_columns != expected_columns:
            raise LiveInvocationIntegrityError(
                "stored S4 invocation columns do not match content"
            )
        if record.request != request or record.result != result or record.handoff != handoff:
            raise LiveInvocationIntegrityError(
                "stored S4 record does not project its durable artifacts"
            )
        if (record.receipt_sha256 is None) != (receipt is None):
            raise LiveInvocationIntegrityError(
                "stored S4 receipt projection is incomplete"
            )
        if receipt is not None and record.receipt_sha256 != contract_sha256(receipt):
            raise LiveInvocationIntegrityError("stored S4 receipt digest mismatch")
        return LiveInvocationProjection(record=record, receipt=receipt)

    def _verify(self, connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()
        if version is None or int(version[0]) != S4_LIVE_JOURNAL_SCHEMA_VERSION:
            raise LiveInvocationIntegrityError("S4 journal schema version changed")
        quick = connection.execute("PRAGMA quick_check").fetchone()
        if quick is None or str(quick[0]).casefold() != "ok":
            raise LiveInvocationIntegrityError("S4 journal quick_check failed")
        for row in connection.execute("SELECT * FROM live_invocations"):
            self._projection_from_row(row)
        for row in connection.execute("SELECT * FROM handoff_reuse_fences"):
            self._reuse_fence_from_row(connection, row)

    @staticmethod
    def _reuse_fence_from_row(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> FenceDecision:
        try:
            decision = FenceDecision.model_validate_json(str(row["decision_json"]))
        except (ValidationError, ValueError) as exc:
            raise LiveInvocationIntegrityError(
                "stored S4 handoff-reuse fence is invalid"
            ) from exc
        if (
            decision.phase is not ControlFencePhase.PRE_ADOPTION
            or decision.decision_id != str(row["decision_id"])
            or contract_sha256(decision) != str(row["decision_sha256"])
        ):
            raise LiveInvocationIntegrityError(
                "stored S4 handoff-reuse fence columns do not match content"
            )
        expected = evaluate_control_fence(
            phase=decision.phase,
            expectation=decision.expectation,
            current=decision.current,
            checked_at=decision.checked_at,
            attempt_id=decision.attempt_id,
            attempt_binding=decision.attempt_binding,
            subject_artifact_sha256=decision.subject_artifact_sha256,
        )
        if expected != decision:
            raise LiveInvocationIntegrityError(
                "stored S4 handoff-reuse fence was not derived from its snapshot"
            )
        invocation = connection.execute(
            "SELECT * FROM live_invocations WHERE invocation_key = ?",
            (str(row["invocation_key"]),),
        ).fetchone()
        if invocation is None:
            raise LiveInvocationIntegrityError(
                "stored S4 handoff-reuse fence has no invocation"
            )
        projection = SQLiteLiveInvocationJournal._projection_from_row(invocation)
        record = projection.record
        handoff = record.handoff
        completed_at = record.completed_at
        if (
            record.state is not LiveInvocationState.COMPLETED
            or handoff is None
            or completed_at is None
            or decision.expectation.task_id != record.request.assignment.task_id
            or decision.expectation.assignment_id
            != record.request.assignment.assignment_id
            or decision.expectation.root_coordination_epoch
            != record.request.assignment.root_coordination_epoch
            or decision.attempt_id != record.request.attempt.attempt_id
            or decision.subject_artifact_sha256 != contract_sha256(handoff)
            or decision.checked_at < completed_at
        ):
            raise LiveInvocationIntegrityError(
                "stored S4 handoff-reuse fence does not bind its terminal invocation"
            )
        return decision

    def verify_integrity(self) -> None:
        with self._read_connection() as connection:
            self._verify(connection)

    def load(self, invocation_key: str) -> LiveInvocationProjection | None:
        with self._read_connection() as connection:
            self._verify(connection)
            row = connection.execute(
                "SELECT * FROM live_invocations WHERE invocation_key = ?",
                (invocation_key,),
            ).fetchone()
            return None if row is None else self._projection_from_row(row)

    def record_reuse_fence(
        self,
        *,
        invocation_key: str,
        decision: FenceDecision,
    ) -> FenceDecision:
        """Append one freshly evaluated reuse fence without changing S3 history."""

        current = FenceDecision.model_validate(decision.model_dump(mode="json"))
        if current.phase is not ControlFencePhase.PRE_ADOPTION:
            raise ValueError("S4 handoff reuse requires a pre-adoption fence")
        with self._transaction() as connection:
            invocation = connection.execute(
                "SELECT * FROM live_invocations WHERE invocation_key = ?",
                (invocation_key,),
            ).fetchone()
            if invocation is None:
                raise LiveInvocationConflictError(
                    "S4 handoff reuse requires a durable invocation"
                )
            projection = self._projection_from_row(invocation)
            handoff = projection.record.handoff
            if (
                projection.record.state is not LiveInvocationState.COMPLETED
                or handoff is None
                or current.expectation.task_id
                != projection.record.request.assignment.task_id
                or current.expectation.assignment_id
                != projection.record.request.assignment.assignment_id
                or current.expectation.root_coordination_epoch
                != projection.record.request.assignment.root_coordination_epoch
                or current.attempt_id
                != projection.record.request.attempt.attempt_id
                or current.subject_artifact_sha256 != contract_sha256(handoff)
            ):
                raise LiveInvocationConflictError(
                    "S4 handoff-reuse fence does not bind the durable invocation"
                )
            existing = connection.execute(
                "SELECT * FROM handoff_reuse_fences WHERE decision_id = ?",
                (current.decision_id,),
            ).fetchone()
            if existing is not None:
                recorded = self._reuse_fence_from_row(connection, existing)
                if recorded != current:
                    raise LiveInvocationConflictError(
                        "S4 handoff-reuse decision identity was reused"
                    )
                return recorded
            connection.execute(
                """
                INSERT INTO handoff_reuse_fences (
                    decision_id, invocation_key, decision_json, decision_sha256
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    current.decision_id,
                    invocation_key,
                    canonical_contract_json(current),
                    contract_sha256(current),
                ),
            )
            row = connection.execute(
                "SELECT * FROM handoff_reuse_fences WHERE decision_id = ?",
                (current.decision_id,),
            ).fetchone()
            if row is None:
                raise LiveInvocationIntegrityError(
                    "S4 handoff-reuse fence insert was not readable"
                )
            return self._reuse_fence_from_row(connection, row)

    def load_reuse_fences(self, invocation_key: str) -> tuple[FenceDecision, ...]:
        """Return the append-only current-state checks for one durable handoff."""

        with self._read_connection() as connection:
            self._verify(connection)
            return tuple(
                self._reuse_fence_from_row(connection, row)
                for row in connection.execute(
                    """
                    SELECT * FROM handoff_reuse_fences
                    WHERE invocation_key = ? ORDER BY rowid
                    """,
                    (invocation_key,),
                )
            )

    def reserve(
        self,
        *,
        invocation_key: str,
        request: LiveBackendRequest,
    ) -> LiveInvocationProjection:
        if not invocation_key.strip():
            raise ValueError("S4 invocation key cannot be blank")
        current_request = LiveBackendRequest.model_validate(
            request.model_dump(mode="json")
        )
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM live_invocations WHERE invocation_key = ?",
                (invocation_key,),
            ).fetchone()
            if row is not None:
                existing = self._projection_from_row(row)
                if existing.record.request != current_request:
                    raise LiveInvocationConflictError(
                        "S4 invocation key is bound to another request"
                    )
                return existing
            record = LiveInvocationRecord(
                invocation_key=invocation_key,
                request=current_request,
                state=LiveInvocationState.RESERVED,
                reserved_at=current_request.requested_at,
            )
            connection.execute(
                """
                INSERT INTO live_invocations (
                    invocation_key, task_id, root_coordination_epoch,
                    assignment_id, attempt_id, state,
                    request_json, request_sha256,
                    result_json, result_sha256,
                    receipt_json, receipt_sha256,
                    handoff_json, handoff_sha256,
                    record_json, record_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL,
                          NULL, NULL, ?, ?)
                """,
                (
                    invocation_key,
                    str(current_request.assignment.task_id),
                    current_request.assignment.root_coordination_epoch,
                    current_request.assignment.assignment_id,
                    current_request.attempt.attempt_id,
                    record.state.value,
                    canonical_contract_json(current_request),
                    contract_sha256(current_request),
                    canonical_contract_json(record),
                    contract_sha256(record),
                ),
            )
            return LiveInvocationProjection(record=record, receipt=None)

    def complete(
        self,
        *,
        invocation_key: str,
        result: LiveBackendResult,
        receipt: AgentExecutionReceipt,
        cleanup_attempt: AgentExecutionAttempt,
        handoff: DistilledHandoff | None,
    ) -> LiveInvocationProjection:
        current_result = LiveBackendResult.model_validate(result.model_dump(mode="json"))
        current_receipt = AgentExecutionReceipt.model_validate(
            receipt.model_dump(mode="json")
        )
        current_attempt = AgentExecutionAttempt.model_validate(
            cleanup_attempt.model_dump(mode="json")
        )
        current_handoff = (
            None
            if handoff is None
            else DistilledHandoff.model_validate(handoff.model_dump(mode="json"))
        )
        request = current_result.request
        expected_receipt = (
            request.assignment.task_id,
            request.assignment.source_task_revision,
            request.assignment.assignment_id,
            request.attempt.attempt_id,
            current_attempt.attempt_integrity_id,
            request.assignment.context_manifest_sha256,
            current_result.payload.payload_id,
            contract_sha256(current_result.payload),
            current_result.backend_id,
            current_result.profile_id,
            current_result.outcome_state,
            current_result.cleanup_state,
            current_result.outcome_at,
            current_result.cleanup_at,
        )
        actual_receipt = (
            current_receipt.task_id,
            current_receipt.source_task_revision,
            current_receipt.assignment_id,
            current_receipt.attempt_id,
            current_receipt.attempt_integrity_id,
            current_receipt.context_manifest_sha256,
            current_receipt.payload_id,
            current_receipt.payload_sha256,
            current_receipt.backend_id,
            current_receipt.profile_id,
            current_receipt.outcome_state,
            current_receipt.cleanup_state,
            current_receipt.outcome_at,
            current_receipt.cleanup_at,
        )
        if actual_receipt != expected_receipt:
            raise LiveInvocationConflictError(
                "S4 execution receipt does not bind the durable result"
            )
        if current_handoff is not None:
            validate_c011_contract_chain(
                context=request.context,
                assignment=request.assignment,
                attempt=current_attempt,
                payload=current_result.payload,
                receipt=current_receipt,
                claims=current_handoff.qualified_claims,
                handoff=current_handoff,
            )

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM live_invocations WHERE invocation_key = ?",
                (invocation_key,),
            ).fetchone()
            if row is None:
                raise LiveInvocationConflictError(
                    "S4 invocation must be reserved before completion"
                )
            existing = self._projection_from_row(row)
            if existing.record.request != request:
                raise LiveInvocationConflictError(
                    "S4 result belongs to another durable request"
                )
            if existing.record.state is LiveInvocationState.COMPLETED:
                if (
                    existing.record.result != current_result
                    or existing.receipt != current_receipt
                    or existing.record.handoff != current_handoff
                ):
                    raise LiveInvocationConflictError(
                        "S4 invocation already completed with another result"
                    )
                return existing
            record = LiveInvocationRecord(
                invocation_key=invocation_key,
                request=request,
                state=LiveInvocationState.COMPLETED,
                reserved_at=existing.record.reserved_at,
                result=current_result,
                receipt_sha256=contract_sha256(current_receipt),
                handoff=current_handoff,
                completed_at=current_result.cleanup_at,
            )
            connection.execute(
                """
                UPDATE live_invocations SET
                    state = ?, result_json = ?, result_sha256 = ?,
                    receipt_json = ?, receipt_sha256 = ?,
                    handoff_json = ?, handoff_sha256 = ?,
                    record_json = ?, record_sha256 = ?
                WHERE invocation_key = ?
                """,
                (
                    record.state.value,
                    canonical_contract_json(current_result),
                    contract_sha256(current_result),
                    canonical_contract_json(current_receipt),
                    contract_sha256(current_receipt),
                    None
                    if current_handoff is None
                    else canonical_contract_json(current_handoff),
                    None
                    if current_handoff is None
                    else contract_sha256(current_handoff),
                    canonical_contract_json(record),
                    contract_sha256(record),
                    invocation_key,
                ),
            )
            return LiveInvocationProjection(record=record, receipt=current_receipt)


__all__ = [
    "S4_LIVE_JOURNAL_SCHEMA_VERSION",
    "LiveInvocationConflictError",
    "LiveInvocationIntegrityError",
    "LiveInvocationJournalError",
    "LiveInvocationProjection",
    "SQLiteLiveInvocationJournal",
]
