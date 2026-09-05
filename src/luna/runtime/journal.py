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
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import ObservationStatus
from luna.contracts.state import TaskState
from luna.modeling.retry import ProviderRetryEvidence
from luna.planning.models import AttemptBasis, AttemptRecord
from luna.tools.models import DispatchOutcome, ToolRequest, ToolResultStatus
from luna.workspace.models import WorkspaceExecutionReconciliation

JOURNAL_SCHEMA_VERSION = 4


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


class RuntimeReconciliationObservationRecord(
    LunaContractModel
):
    """Durable cold-reconciliation evidence separate from dispatch outcomes."""

    observation_id: UUID = Field(
        default_factory=uuid4
    )
    task_id: UUID
    trace_id: UUID

    runtime_receipt_id: UUID
    request_id: UUID

    side_effect_idempotency_key: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )

    workspace: WorkspaceExecutionReconciliation

    recorded_at: datetime = Field(
        default_factory=utc_now
    )

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(
        cls,
        value: datetime,
    ) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_links(
        self,
    ) -> RuntimeReconciliationObservationRecord:
        if (
            self.workspace.task_id
            != self.task_id
        ):
            raise ValueError(
                "reconciliation task_id must match "
                "runtime record"
            )

        if (
            self.workspace.request_id
            != self.request_id
        ):
            raise ValueError(
                "reconciliation request_id must match "
                "runtime record"
            )

        if (
            self.workspace.runtime_receipt_id
            != self.runtime_receipt_id
        ):
            raise ValueError(
                "reconciliation runtime receipt must "
                "match runtime record"
            )

        return self


class ProviderRetryScheduleStage(StrEnum):
    """Durable lifecycle of one authorized provider retry."""

    SCHEDULED = "SCHEDULED"
    STARTED = "STARTED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class ProviderRetryScheduleRecord(LunaContractModel):
    """Changed-basis provider retry authority persisted before any wait."""

    schedule_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    trace_id: UUID
    step_id: UUID

    failed_attempt: AttemptRecord
    candidate_basis: AttemptBasis
    evidence: ProviderRetryEvidence

    # Cold-recovery context only. This snapshot does not grant retry,
    # provider-call, side-effect, or completion authority.
    pre_retry_state: TaskState | None = None

    stage: ProviderRetryScheduleStage = ProviderRetryScheduleStage.SCHEDULED

    started_model_request_id: UUID | None = None
    started_model_request_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    scheduled_at: datetime = Field(default_factory=utc_now)
    eligible_at: datetime
    started_at: datetime | None = None
    resolved_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "scheduled_at",
        "eligible_at",
        "started_at",
        "resolved_at",
        "cancelled_at",
    )
    @classmethod
    def validate_retry_timestamp(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return require_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_retry_schedule(self) -> ProviderRetryScheduleRecord:
        if self.pre_retry_state is not None:
            if self.pre_retry_state.task_id != self.task_id:
                raise ValueError(
                    "provider retry pre-retry state task_id mismatch"
                )
            if not any(
                item.step_id == self.step_id
                for item in self.pre_retry_state.plan
            ):
                raise ValueError(
                    "provider retry step_id must exist in pre-retry state"
                )

        if self.failed_attempt.task_id != self.task_id:
            raise ValueError("provider retry failed attempt task_id mismatch")
        if self.failed_attempt.step_id != self.step_id:
            raise ValueError("provider retry failed attempt step_id mismatch")
        if self.failed_attempt.observation_id != self.evidence.failure_ref:
            raise ValueError("provider retry failure_ref mismatch")
        if self.failed_attempt.outcome is not ObservationStatus.FAILURE:
            raise ValueError("provider retry requires a failed prior attempt")
        if self.candidate_basis.fingerprint() != self.evidence.basis_fingerprint:
            raise ValueError("provider retry candidate basis fingerprint mismatch")
        if (
            self.candidate_basis.context_fingerprint
            != self.evidence.request_fingerprint
        ):
            raise ValueError("provider retry request fingerprint mismatch")
        if self.eligible_at < self.scheduled_at:
            raise ValueError("provider retry eligibility cannot precede scheduling")

        if self.stage is ProviderRetryScheduleStage.SCHEDULED:
            if any(
                value is not None
                for value in (
                    self.started_model_request_id,
                    self.started_model_request_fingerprint,
                    self.started_at,
                    self.resolved_at,
                    self.cancelled_at,
                    self.cancel_reason,
                )
            ):
                raise ValueError("scheduled provider retry cannot carry later state")

        elif self.stage is ProviderRetryScheduleStage.STARTED:
            if (
                self.started_model_request_id is None
                or self.started_model_request_fingerprint is None
                or self.started_at is None
            ):
                raise ValueError(
                    "started provider retry requires exact model request identity"
                )
            if self.started_at < self.eligible_at:
                raise ValueError("provider retry cannot start before eligible_at")
            if any(
                value is not None
                for value in (
                    self.resolved_at,
                    self.cancelled_at,
                    self.cancel_reason,
                )
            ):
                raise ValueError("started provider retry cannot carry terminal state")

        elif self.stage is ProviderRetryScheduleStage.RESOLVED:
            if (
                self.started_model_request_id is None
                or self.started_model_request_fingerprint is None
                or self.started_at is None
                or self.resolved_at is None
            ):
                raise ValueError(
                    "resolved provider retry requires exact started request "
                    "identity and resolution timestamps"
                )
            if self.started_at < self.eligible_at:
                raise ValueError("provider retry cannot start before eligible_at")
            if self.resolved_at < self.started_at:
                raise ValueError("provider retry resolution cannot precede start")
            if self.cancelled_at is not None or self.cancel_reason is not None:
                raise ValueError("resolved provider retry cannot be cancelled")

        elif self.stage is ProviderRetryScheduleStage.CANCELLED:
            if self.cancelled_at is None or not self.cancel_reason:
                raise ValueError(
                    "cancelled provider retry requires timestamp and reason"
                )
            if self.cancelled_at < self.scheduled_at:
                raise ValueError(
                    "provider retry cancellation cannot precede scheduling"
                )
            if (
                self.started_model_request_id is not None
                or self.started_model_request_fingerprint is not None
                or self.started_at is not None
                or self.resolved_at is not None
            ):
                raise ValueError(
                    "provider retry may be cancelled only before it starts"
                )

        return self


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


@dataclass(frozen=True)
class SideEffectExecutionProvenance:
    """Exact durable execution workspace provenance for one tool result."""

    receipt_id: UUID
    idempotency_key: str
    task_id: UUID
    request_id: UUID
    result_id: UUID
    execution_workspace_root: str
    isolation_mode: str


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
    approval_basis_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    approval_workspace_root: str | None = Field(default=None, min_length=1, max_length=4000)
    pre_action_state: TaskState
    execution_workspace_root: str = Field(min_length=1, max_length=4000)
    isolation_mode: str = Field(default="NONE", min_length=1, max_length=40)
    execution_revision: str | None = Field(
        default=None,
        pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$",
    )
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
        if (self.approval_basis_fingerprint is None) != (
            self.approval_workspace_root is None
        ):
            raise ValueError("approval basis and workspace root must be recorded together")
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
    payload = model.model_dump(mode="json")

    # Receipts written before execution_revision existed
    # retain their original canonical digest until a normal
    # journal transition rewrites them in the current shape.
    if (
        isinstance(model, SideEffectReceipt)
        and "execution_revision"
        not in model.model_fields_set
    ):
        payload.pop(
            "execution_revision",
            None,
        )

    return json.dumps(
        payload,
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
            if current < 3:
                connection.execute(
                    """
                    CREATE TABLE runtime_reconciliation_observations (
                        observation_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        trace_id TEXT NOT NULL,
                        runtime_receipt_id TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        side_effect_idempotency_key TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        recorded_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX runtime_reconciliation_task_recorded
                    ON runtime_reconciliation_observations(
                        task_id,
                        recorded_at,
                        observation_id
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX runtime_reconciliation_receipt
                    ON runtime_reconciliation_observations(
                        runtime_receipt_id,
                        observation_id
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO journal_schema(version, applied_at) VALUES (?, ?)",
                    (3, utc_now().isoformat()),
                )
            if current < 4:
                connection.execute(
                    """
                    CREATE TABLE provider_retry_schedules (
                        schedule_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        trace_id TEXT NOT NULL,
                        step_id TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX provider_retry_task_updated
                    ON provider_retry_schedules(
                        task_id,
                        updated_at,
                        schedule_id
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE UNIQUE INDEX provider_retry_single_pending_task
                    ON provider_retry_schedules(task_id)
                    WHERE stage IN ('SCHEDULED', 'STARTED')
                    """
                )
                connection.execute(
                    "INSERT INTO journal_schema(version, applied_at) VALUES (?, ?)",
                    (4, utc_now().isoformat()),
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

        row_binding = {
            "idempotency_key": str(row["idempotency_key"]),
            "task_id": str(row["task_id"]),
            "semantic_fingerprint": str(row["semantic_fingerprint"]),
            "stage": str(row["stage"]),
        }

        receipt_binding = {
            "idempotency_key": receipt.idempotency_key,
            "task_id": str(receipt.task_id),
            "semantic_fingerprint": receipt.semantic_fingerprint,
            "stage": receipt.stage.value,
        }

        if row_binding != receipt_binding:
            raise RuntimeJournalError(
                "side-effect receipt row binding mismatch: "
                f"{row['idempotency_key']}"
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

        row_binding = {
            "observation_id": str(row["observation_id"]),
            "task_id": str(row["task_id"]),
            "trace_id": str(row["trace_id"]),
        }

        record_binding = {
            "observation_id": str(record.observation_id),
            "task_id": str(record.task_id),
            "trace_id": str(record.trace_id),
        }

        if row_binding != record_binding:
            raise RuntimeJournalError(
                "runtime observation row binding mismatch: "
                f"{row['observation_id']}"
            )

        return record

    @staticmethod
    def _reconciliation_observation_from_row(
        row: sqlite3.Row,
    ) -> RuntimeReconciliationObservationRecord:
        payload = str(
            row["payload_json"]
        )

        record = (
            RuntimeReconciliationObservationRecord
            .model_validate_json(
                payload
            )
        )

        if (
            _digest(record)
            != str(row["payload_sha256"])
        ):
            raise RuntimeJournalError(
                "runtime reconciliation observation "
                "digest mismatch: "
                f"{row['observation_id']}"
            )

        row_binding = {
            "observation_id": str(
                row["observation_id"]
            ),
            "task_id": str(
                row["task_id"]
            ),
            "trace_id": str(
                row["trace_id"]
            ),
            "runtime_receipt_id": str(
                row["runtime_receipt_id"]
            ),
            "request_id": str(
                row["request_id"]
            ),
            "side_effect_idempotency_key": str(
                row["side_effect_idempotency_key"]
            ),
        }

        record_binding = {
            "observation_id": str(
                record.observation_id
            ),
            "task_id": str(
                record.task_id
            ),
            "trace_id": str(
                record.trace_id
            ),
            "runtime_receipt_id": str(
                record.runtime_receipt_id
            ),
            "request_id": str(
                record.request_id
            ),
            "side_effect_idempotency_key": (
                record.side_effect_idempotency_key
            ),
        }

        if row_binding != record_binding:
            raise RuntimeJournalError(
                "runtime reconciliation observation "
                "row binding mismatch: "
                f"{row['observation_id']}"
            )

        return record


    @staticmethod
    def _provider_retry_schedule_from_row(
        row: sqlite3.Row,
    ) -> ProviderRetryScheduleRecord:
        payload = str(row["payload_json"])
        record = ProviderRetryScheduleRecord.model_validate_json(payload)

        if _digest(record) != str(row["payload_sha256"]):
            raise RuntimeJournalError(
                "provider retry schedule digest mismatch: "
                f"{row['schedule_id']}"
            )

        row_binding = {
            "schedule_id": str(row["schedule_id"]),
            "task_id": str(row["task_id"]),
            "trace_id": str(row["trace_id"]),
            "step_id": str(row["step_id"]),
            "stage": str(row["stage"]),
        }
        record_binding = {
            "schedule_id": str(record.schedule_id),
            "task_id": str(record.task_id),
            "trace_id": str(record.trace_id),
            "step_id": str(record.step_id),
            "stage": record.stage.value,
        }

        if row_binding != record_binding:
            raise RuntimeJournalError(
                "provider retry schedule row binding mismatch: "
                f"{row['schedule_id']}"
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


    def schedule_provider_retry(
        self,
        *,
        task_id: UUID,
        trace_id: UUID,
        step_id: UUID,
        failed_attempt: AttemptRecord,
        candidate_basis: AttemptBasis,
        evidence: ProviderRetryEvidence,
        pre_retry_state: TaskState | None = None,
    ) -> ProviderRetryScheduleRecord:
        """Persist exact changed-basis retry authority before any wait."""

        scheduled_at = utc_now()
        record = ProviderRetryScheduleRecord(
            task_id=task_id,
            trace_id=trace_id,
            step_id=step_id,
            failed_attempt=failed_attempt,
            candidate_basis=candidate_basis,
            evidence=evidence,
            pre_retry_state=pre_retry_state,
            eligible_at=scheduled_at
            + timedelta(seconds=evidence.delay_seconds),
            scheduled_at=scheduled_at,
        )
        payload = _canonical_json(record)

        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM provider_retry_schedules
                WHERE task_id = ?
                  AND stage IN ('SCHEDULED', 'STARTED')
                ORDER BY rowid
                """,
                (str(task_id),),
            ).fetchall()

            if len(rows) > 1:
                raise RuntimeJournalConflictError(
                    "task has multiple pending provider retry schedules"
                )

            if rows:
                current = self._provider_retry_schedule_from_row(rows[0])
                if (
                    current.stage is ProviderRetryScheduleStage.SCHEDULED
                    and current.task_id == task_id
                    and current.trace_id == trace_id
                    and current.step_id == step_id
                    and current.failed_attempt == failed_attempt
                    and current.candidate_basis == candidate_basis
                    and current.evidence == evidence
                    and current.pre_retry_state == pre_retry_state
                ):
                    return current
                raise RuntimeJournalConflictError(
                    "task already has a different pending provider retry"
                )

            connection.execute(
                """
                INSERT INTO provider_retry_schedules(
                    schedule_id,
                    task_id,
                    trace_id,
                    step_id,
                    stage,
                    payload_json,
                    payload_sha256,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.schedule_id),
                    str(record.task_id),
                    str(record.trace_id),
                    str(record.step_id),
                    record.stage.value,
                    payload,
                    _digest(record),
                    record.scheduled_at.isoformat(),
                ),
            )

        return record

    def load_provider_retry_schedule(
        self,
        schedule_id: UUID,
    ) -> ProviderRetryScheduleRecord:
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM provider_retry_schedules
                WHERE schedule_id = ?
                """,
                (str(schedule_id),),
            ).fetchone()

        if row is None:
            raise RuntimeJournalError(
                f"provider retry schedule not found: {schedule_id}"
            )
        return self._provider_retry_schedule_from_row(row)

    def list_provider_retry_schedules(
        self,
        task_id: UUID,
        *,
        limit: int = 32,
    ) -> tuple[ProviderRetryScheduleRecord, ...]:
        if limit < 1:
            raise ValueError("provider retry schedule limit must be positive")

        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM provider_retry_schedules
                WHERE task_id = ?
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (str(task_id), limit),
            ).fetchall()

        records = tuple(
            self._provider_retry_schedule_from_row(row)
            for row in rows
        )
        return tuple(reversed(records))

    def latest_recoverable_provider_retry(
        self,
        task_id: UUID,
    ) -> ProviderRetryScheduleRecord | None:
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM provider_retry_schedules
                WHERE task_id = ?
                  AND stage IN ('SCHEDULED', 'STARTED')
                ORDER BY rowid DESC
                LIMIT 2
                """,
                (str(task_id),),
            ).fetchall()

        if len(rows) > 1:
            raise RuntimeJournalError(
                "task has multiple recoverable provider retry schedules"
            )
        if not rows:
            return None
        return self._provider_retry_schedule_from_row(rows[0])

    def _replace_provider_retry_schedule(
        self,
        *,
        current: ProviderRetryScheduleRecord,
        updated: ProviderRetryScheduleRecord,
    ) -> ProviderRetryScheduleRecord:
        payload = _canonical_json(updated)

        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT payload_sha256
                FROM provider_retry_schedules
                WHERE schedule_id = ?
                """,
                (str(current.schedule_id),),
            ).fetchone()

            if row is None:
                raise RuntimeJournalConflictError(
                    "provider retry schedule disappeared"
                )
            if str(row["payload_sha256"]) != _digest(current):
                raise RuntimeJournalConflictError(
                    "provider retry schedule changed concurrently"
                )

            cursor = connection.execute(
                """
                UPDATE provider_retry_schedules
                SET stage = ?,
                    payload_json = ?,
                    payload_sha256 = ?,
                    updated_at = ?
                WHERE schedule_id = ?
                  AND payload_sha256 = ?
                """,
                (
                    updated.stage.value,
                    payload,
                    _digest(updated),
                    utc_now().isoformat(),
                    str(current.schedule_id),
                    _digest(current),
                ),
            )

            if cursor.rowcount != 1:
                raise RuntimeJournalConflictError(
                    "provider retry schedule update lost race"
                )

        return updated

    def mark_provider_retry_started(
        self,
        *,
        schedule_id: UUID,
        model_request_id: UUID,
        model_request_fingerprint: str,
    ) -> ProviderRetryScheduleRecord:
        current = self.load_provider_retry_schedule(schedule_id)

        if current.stage is ProviderRetryScheduleStage.STARTED:
            if (
                current.started_model_request_id == model_request_id
                and current.started_model_request_fingerprint
                == model_request_fingerprint
            ):
                return current
            raise RuntimeJournalConflictError(
                "provider retry already started with a different model request"
            )

        if current.stage is not ProviderRetryScheduleStage.SCHEDULED:
            raise RuntimeJournalConflictError(
                "provider retry can start only from SCHEDULED"
            )

        # The schedule durably identifies the failed provider request
        # through evidence.request_fingerprint. The next safe request
        # boundary may intentionally change the complete model-visible
        # projection, such as activating a pending deferred tool schema.
        #
        # STARTED therefore binds the exact request actually crossing the
        # provider boundary rather than requiring it to equal the failed
        # request fingerprint.
        started_at = utc_now()
        if started_at < current.eligible_at:
            raise RuntimeJournalConflictError(
                "provider retry is not yet eligible to start"
            )

        updated = ProviderRetryScheduleRecord.model_validate(
            {
                **current.model_dump(mode="python"),
                "stage": ProviderRetryScheduleStage.STARTED,
                "started_model_request_id": model_request_id,
                "started_model_request_fingerprint": (
                    model_request_fingerprint
                ),
                "started_at": started_at,
            }
        )
        return self._replace_provider_retry_schedule(
            current=current,
            updated=updated,
        )

    def resolve_provider_retry(
        self,
        schedule_id: UUID,
    ) -> ProviderRetryScheduleRecord:
        current = self.load_provider_retry_schedule(schedule_id)

        if current.stage is ProviderRetryScheduleStage.RESOLVED:
            return current
        if current.stage is not ProviderRetryScheduleStage.STARTED:
            raise RuntimeJournalConflictError(
                "provider retry can resolve only from STARTED"
            )

        updated = ProviderRetryScheduleRecord.model_validate(
            {
                **current.model_dump(mode="python"),
                "stage": ProviderRetryScheduleStage.RESOLVED,
                "resolved_at": utc_now(),
            }
        )
        return self._replace_provider_retry_schedule(
            current=current,
            updated=updated,
        )

    def cancel_provider_retry(
        self,
        *,
        schedule_id: UUID,
        reason: str,
    ) -> ProviderRetryScheduleRecord:
        reason = reason.strip()
        if not reason:
            raise ValueError("provider retry cancellation reason must not be blank")

        current = self.load_provider_retry_schedule(schedule_id)

        if current.stage is ProviderRetryScheduleStage.CANCELLED:
            if current.cancel_reason == reason:
                return current
            raise RuntimeJournalConflictError(
                "provider retry already cancelled for a different reason"
            )
        if current.stage is not ProviderRetryScheduleStage.SCHEDULED:
            raise RuntimeJournalConflictError(
                "provider retry may be cancelled only before it starts"
            )

        updated = ProviderRetryScheduleRecord.model_validate(
            {
                **current.model_dump(mode="python"),
                "stage": ProviderRetryScheduleStage.CANCELLED,
                "cancelled_at": utc_now(),
                "cancel_reason": reason,
            }
        )
        return self._replace_provider_retry_schedule(
            current=current,
            updated=updated,
        )

    def record_reconciliation_observation(
        self,
        *,
        receipt: SideEffectReceipt,
        reconciliation: WorkspaceExecutionReconciliation,
    ) -> RuntimeReconciliationObservationRecord:
        """Persist cold-reconciliation evidence idempotently without changing side-effect state."""

        current = self.load(
            receipt.idempotency_key
        )

        if current != receipt:
            raise RuntimeJournalConflictError(
                "side-effect receipt changed before "
                "reconciliation observation persistence"
            )

        if (
            receipt.receipt_id
            != reconciliation.runtime_receipt_id
            or receipt.task_id
            != reconciliation.task_id
            or receipt.request.request_id
            != reconciliation.request_id
        ):
            raise RuntimeJournalConflictError(
                "workspace reconciliation does not "
                "match the exact runtime side-effect "
                "receipt"
            )

        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM runtime_reconciliation_observations
                WHERE runtime_receipt_id = ?
                ORDER BY rowid
                """,
                (
                    str(receipt.receipt_id),
                ),
            ).fetchall()

            for row in rows:
                existing = (
                    self
                    ._reconciliation_observation_from_row(
                        row
                    )
                )

                if (
                    existing.task_id
                    != receipt.task_id
                    or existing.trace_id
                    != receipt.trace_id
                    or existing.request_id
                    != receipt.request.request_id
                    or (
                        existing
                        .side_effect_idempotency_key
                        != receipt.idempotency_key
                    )
                ):
                    raise RuntimeJournalConflictError(
                        "runtime receipt ID already has "
                        "reconciliation evidence for a "
                        "different execution binding"
                    )

                if (
                    existing.workspace
                    == reconciliation
                ):
                    return existing

            record = (
                RuntimeReconciliationObservationRecord(
                    task_id=receipt.task_id,
                    trace_id=receipt.trace_id,
                    runtime_receipt_id=(
                        receipt.receipt_id
                    ),
                    request_id=(
                        receipt.request.request_id
                    ),
                    side_effect_idempotency_key=(
                        receipt.idempotency_key
                    ),
                    workspace=reconciliation,
                )
            )

            payload = _canonical_json(
                record
            )

            connection.execute(
                """
                INSERT INTO runtime_reconciliation_observations(
                    observation_id,
                    task_id,
                    trace_id,
                    runtime_receipt_id,
                    request_id,
                    side_effect_idempotency_key,
                    payload_json,
                    payload_sha256,
                    recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.observation_id),
                    str(record.task_id),
                    str(record.trace_id),
                    str(record.runtime_receipt_id),
                    str(record.request_id),
                    record.side_effect_idempotency_key,
                    payload,
                    _digest(record),
                    record.recorded_at.isoformat(),
                ),
            )

        return record

    def list_reconciliation_observations(
        self,
        task_id: UUID,
        *,
        limit: int = 8,
    ) -> tuple[
        RuntimeReconciliationObservationRecord,
        ...,
    ]:
        """Return durable cold-reconciliation observations chronologically."""

        if limit < 1:
            raise ValueError(
                "reconciliation observation limit "
                "must be positive"
            )

        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM runtime_reconciliation_observations
                WHERE task_id = ?
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (
                    str(task_id),
                    limit,
                ),
            ).fetchall()

        records = tuple(
            self._reconciliation_observation_from_row(
                row
            )
            for row in rows
        )

        return tuple(
            reversed(records)
        )

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


    def resolve_execution_provenance(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> SideEffectExecutionProvenance:
        """Resolve one exact completed side-effect result to its durable workspace."""

        matches: list[SideEffectReceipt] = []

        for receipt in self.list_for_task(task_id):
            outcome = receipt.outcome

            if outcome is None:
                continue
            if receipt.request.request_id != request_id:
                continue
            if outcome.request.request_id != request_id:
                continue
            if outcome.result.request_id != request_id:
                continue
            if outcome.result.result_id != result_id:
                continue

            matches.append(receipt)

        if len(matches) != 1:
            raise RuntimeJournalError(
                "side-effect execution provenance requires exactly one "
                f"matching receipt; found {len(matches)}"
            )

        receipt = matches[0]
        outcome = receipt.outcome

        if outcome is None:  # pragma: no cover - guarded above
            raise RuntimeJournalError(
                "matched side-effect receipt has no dispatch outcome"
            )

        return SideEffectExecutionProvenance(
            receipt_id=receipt.receipt_id,
            idempotency_key=receipt.idempotency_key,
            task_id=receipt.task_id,
            request_id=receipt.request.request_id,
            result_id=outcome.result.result_id,
            execution_workspace_root=receipt.execution_workspace_root,
            isolation_mode=receipt.isolation_mode,
        )

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
                reconciliation_rows = connection.execute(
                    """
                    SELECT *
                    FROM runtime_reconciliation_observations
                    ORDER BY rowid
                    """
                ).fetchall()
                provider_retry_rows = connection.execute(
                    """
                    SELECT *
                    FROM provider_retry_schedules
                    ORDER BY rowid
                    """
                ).fetchall()
            for row in receipt_rows:
                self._receipt_from_row(row)
            for row in control_rows:
                self._control_from_row(row)
            for row in observation_rows:
                self._observation_from_row(row)
            for row in reconciliation_rows:
                self._reconciliation_observation_from_row(
                    row
                )
            for row in provider_retry_rows:
                self._provider_retry_schedule_from_row(row)
        except (RuntimeJournalError, ValueError, sqlite3.DatabaseError):
            return False
        return True
