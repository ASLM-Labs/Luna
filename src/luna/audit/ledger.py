"""Append-only JSONL audit ledger with a replayable SHA-256 hash chain."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from luna.audit.models import (
    GENESIS_EVENT_HASH,
    AuditEvent,
    AuditEventKind,
    AuditVerification,
    JsonValue,
    canonical_json,
)
from luna.audit.redaction import SecretRedactor
from luna.contracts.base import utc_now


class AuditIntegrityError(RuntimeError):
    """Raised when append-only audit integrity cannot be established."""


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise AuditIntegrityError("audit append write made no progress")
        offset += written


class AppendOnlyAuditLedger:
    """One JSON object per line; corrections are new events, never edits."""

    def __init__(
        self,
        root: str | Path,
        redactor: SecretRedactor | None = None,
        *,
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "events.jsonl"
        self.lock_path = self.root / "events.lock"
        self._redactor = redactor or SecretRedactor()
        self._lock_timeout_seconds = lock_timeout_seconds

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        deadline = time.monotonic() + self._lock_timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise AuditIntegrityError(
                        "timed out acquiring audit append lock"
                    ) from None
                time.sleep(0.01)
        try:
            _write_all(descriptor, str(os.getpid()).encode("ascii"))
            os.fsync(descriptor)
            yield
        finally:
            os.close(descriptor)
            self.lock_path.unlink(missing_ok=True)

    def append(
        self,
        *,
        kind: AuditEventKind,
        task_id: UUID,
        trace_id: UUID,
        subject_id: str,
        payload: dict[str, JsonValue],
    ) -> AuditEvent:
        redacted_payload, labels = self._redactor.redact_payload(payload)
        with self._exclusive_lock():
            verification = self.verify_integrity()
            if not verification.valid:
                raise AuditIntegrityError(
                    f"cannot append to invalid audit ledger: {verification.first_error}"
                )
            sequence = verification.event_count + 1
            previous_hash = verification.last_event_hash
            occurred_at = utc_now()
            payload_sha256 = sha256(
                canonical_json(redacted_payload).encode("utf-8")
            ).hexdigest()
            provisional = AuditEvent.model_construct(
                schema_version="1.0",
                sequence=sequence,
                task_id=task_id,
                trace_id=trace_id,
                kind=kind,
                subject_id=subject_id,
                occurred_at=occurred_at,
                payload=redacted_payload,
                payload_sha256=payload_sha256,
                previous_event_hash=previous_hash,
                event_hash="0" * 64,
                redactions_applied=labels,
            )
            event_hash = sha256(
                canonical_json(provisional.hash_payload()).encode("utf-8")
            ).hexdigest()
            event = AuditEvent.model_validate(
                {
                    **provisional.model_dump(mode="json"),
                    "event_hash": event_hash,
                }
            )
            line = event.model_dump_json() + "\n"
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_APPEND | os.O_WRONLY,
                0o600,
            )
            try:
                _write_all(descriptor, line.encode("utf-8"))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return event

    def append_correction(
        self,
        *,
        task_id: UUID,
        trace_id: UUID,
        original_event_id: UUID,
        reason: str,
        replacement_payload: dict[str, JsonValue],
    ) -> AuditEvent:
        return self.append(
            kind=AuditEventKind.CORRECTION,
            task_id=task_id,
            trace_id=trace_id,
            subject_id=str(original_event_id),
            payload={
                "original_event_id": str(original_event_id),
                "reason": reason,
                "replacement_payload": replacement_payload,
            },
        )

    def read_events(self) -> tuple[AuditEvent, ...]:
        if not self.path.exists():
            return ()
        events: list[AuditEvent] = []
        previous_hash = GENESIS_EVENT_HASH
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.endswith("\n"):
                    raise AuditIntegrityError(
                        f"audit line {line_number} is not newline-terminated"
                    )
                try:
                    event = AuditEvent.model_validate_json(line)
                except (ValidationError, ValueError) as exc:
                    raise AuditIntegrityError(
                        f"invalid audit line {line_number}: {exc}"
                    ) from exc
                if event.sequence != line_number:
                    raise AuditIntegrityError(
                        f"audit sequence mismatch at line {line_number}"
                    )
                if event.previous_event_hash != previous_hash:
                    raise AuditIntegrityError(
                        f"audit chain mismatch at line {line_number}"
                    )
                events.append(event)
                previous_hash = event.event_hash
        return tuple(events)

    def events_for_task(self, task_id: UUID) -> tuple[AuditEvent, ...]:
        return tuple(event for event in self.read_events() if event.task_id == task_id)

    def verify_integrity(self) -> AuditVerification:
        if not self.path.exists():
            return AuditVerification(
                valid=True,
                event_count=0,
                last_event_hash=GENESIS_EVENT_HASH,
            )
        previous_hash = GENESIS_EVENT_HASH
        count = 0
        try:
            with self.path.open("r", encoding="utf-8", newline="") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.endswith("\n"):
                        raise AuditIntegrityError(
                            f"audit line {line_number} is not newline-terminated"
                        )
                    event = AuditEvent.model_validate_json(line)
                    if event.sequence != line_number:
                        raise AuditIntegrityError(
                            f"audit sequence mismatch at line {line_number}"
                        )
                    if event.previous_event_hash != previous_hash:
                        raise AuditIntegrityError(
                            f"audit chain mismatch at line {line_number}"
                        )
                    previous_hash = event.event_hash
                    count = line_number
        except (AuditIntegrityError, ValidationError, ValueError) as exc:
            return AuditVerification(
                valid=False,
                event_count=count,
                last_event_hash=previous_hash,
                first_error=str(exc),
            )
        return AuditVerification(
            valid=True,
            event_count=count,
            last_event_hash=previous_hash,
        )
