from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from luna.audit import (
    AppendOnlyAuditLedger,
    AuditEventKind,
    AuditIntegrityError,
    SecretRedactor,
)


def test_append_only_chain_is_queryable_by_task(tmp_path: Path) -> None:
    ledger = AppendOnlyAuditLedger(tmp_path / "audit")
    task_id = uuid4()
    trace_id = uuid4()

    first = ledger.append(
        kind=AuditEventKind.TASK_CONTRACT,
        task_id=task_id,
        trace_id=trace_id,
        subject_id=str(task_id),
        payload={"objective": "test"},
    )
    second = ledger.append(
        kind=AuditEventKind.OBSERVATION,
        task_id=task_id,
        trace_id=trace_id,
        subject_id=str(uuid4()),
        payload={"status": "SUCCESS"},
    )

    verification = ledger.verify_integrity()
    events = ledger.events_for_task(task_id)

    assert verification.valid
    assert verification.event_count == 2
    assert first.sequence == 1
    assert second.previous_event_hash == first.event_hash
    assert tuple(event.trace_id for event in events) == (trace_id, trace_id)


def test_correction_is_new_event_and_original_line_remains(tmp_path: Path) -> None:
    ledger = AppendOnlyAuditLedger(tmp_path / "audit")
    task_id = uuid4()
    trace_id = uuid4()
    original = ledger.append(
        kind=AuditEventKind.OBSERVATION,
        task_id=task_id,
        trace_id=trace_id,
        subject_id=str(uuid4()),
        payload={"status": "PARTIAL"},
    )
    original_line = ledger.path.read_text(encoding="utf-8").splitlines()[0]

    correction = ledger.append_correction(
        task_id=task_id,
        trace_id=trace_id,
        original_event_id=original.event_id,
        reason="new direct observation",
        replacement_payload={"status": "SUCCESS"},
    )

    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == original_line
    assert correction.kind is AuditEventKind.CORRECTION
    assert len(lines) == 2


def test_tampering_blocks_future_append(tmp_path: Path) -> None:
    ledger = AppendOnlyAuditLedger(tmp_path / "audit")
    task_id = uuid4()
    trace_id = uuid4()
    ledger.append(
        kind=AuditEventKind.OBSERVATION,
        task_id=task_id,
        trace_id=trace_id,
        subject_id=str(uuid4()),
        payload={"status": "SUCCESS"},
    )
    payload = json.loads(ledger.path.read_text(encoding="utf-8"))
    payload["payload"]["status"] = "FAILURE"
    ledger.path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert not ledger.verify_integrity().valid
    with pytest.raises(AuditIntegrityError, match="invalid audit ledger"):
        ledger.append(
            kind=AuditEventKind.EVIDENCE,
            task_id=task_id,
            trace_id=trace_id,
            subject_id=str(uuid4()),
            payload={"result": "PASS"},
        )


def test_payload_values_are_redacted_before_jsonl_append(tmp_path: Path) -> None:
    ledger = AppendOnlyAuditLedger(
        tmp_path / "audit",
        SecretRedactor(("owner-secret",)),
    )
    ledger.append(
        kind=AuditEventKind.TOOL_REQUEST,
        task_id=uuid4(),
        trace_id=uuid4(),
        subject_id=str(uuid4()),
        payload={
            "arguments": {
                "password": "owner-secret",
                "message": "token=owner-secret",
            }
        },
    )

    persisted = ledger.path.read_text(encoding="utf-8")
    assert "owner-secret" not in persisted
    assert "redacted" in persisted
