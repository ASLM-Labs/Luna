from __future__ import annotations

import json
import sqlite3
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from luna.applied_changes.models import (
    AppliedChangeBindingError,
    AppliedChangeBindingState,
    AppliedChangeCandidate,
    AppliedChangeDegradationReason,
    AppliedChangeOperation,
    AppliedChangeRecord,
    AppliedChangeState,
    applied_change_manifest_sha256,
)
from luna.applied_changes.replay import (
    AppliedChangeReplayIntegrityError,
    AppliedChangeReplayState,
    resolve_applied_change_replay,
)
from luna.applied_changes.store import (
    SQLiteAppliedChangeStore,
)
from luna.contracts import (
    RiskLevel,
    TaskContract,
    TaskScope,
)
from luna.runtime.journal import (
    RuntimeJournalError,
    SQLiteRuntimeJournal,
)
from luna.tools import (
    AutonomyLevel,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    build_phase5_registry,
)


def _candidate(
    task_id: UUID,
    *,
    relative_path: str = "notes.txt",
) -> AppliedChangeCandidate:
    return AppliedChangeCandidate(
        task_id=task_id,
        operation=AppliedChangeOperation.WRITE_TEXT,
        relative_path=relative_path,
        state=AppliedChangeState.DEGRADED,
        before_existed=True,
        before_digest="1" * 64,
        after_digest="2" * 64,
        before_size_bytes=7,
        after_size_bytes=6,
        degradation_reason=(
            AppliedChangeDegradationReason
            .PROJECTION_UNAVAILABLE
        ),
    )


def _record(
    *,
    task_id: UUID,
    request_id: UUID,
    result_id: UUID,
    relative_path: str = "notes.txt",
) -> AppliedChangeRecord:
    return AppliedChangeRecord.build(
        request_id=request_id,
        result_id=result_id,
        candidate=_candidate(
            task_id,
            relative_path=relative_path,
        ),
    )


def _bound_metadata(
    records: tuple[
        AppliedChangeRecord,
        ...,
    ],
) -> dict[str, object]:
    return {
        "applied_change_binding_state": (
            AppliedChangeBindingState.BOUND.value
        ),
        "applied_change_count": len(records),
        "applied_change_manifest_sha256": (
            applied_change_manifest_sha256(
                records
            )
        ),
    }


class _NoReadStore:
    def __init__(self) -> None:
        self.calls = 0

    def list_for_result(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> tuple[AppliedChangeRecord, ...]:
        del task_id, request_id, result_id

        self.calls += 1

        raise AssertionError(
            "cold readback must not consult store"
        )


class _StaticStore:
    def __init__(
        self,
        records: tuple[
            AppliedChangeRecord,
            ...,
        ],
    ) -> None:
        self.records = records
        self.calls = 0

    def list_for_result(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> tuple[AppliedChangeRecord, ...]:
        del task_id, request_id, result_id

        self.calls += 1

        return self.records


class _FailingStore:
    def __init__(self) -> None:
        self.calls = 0

    def list_for_result(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> tuple[AppliedChangeRecord, ...]:
        del task_id, request_id, result_id

        self.calls += 1

        raise RuntimeError(
            "synthetic cold-store read failure"
        )


def test_legacy_outcome_is_absent_without_store_read() -> None:
    store = _NoReadStore()

    replay = resolve_applied_change_replay(
        task_id=uuid4(),
        request_id=uuid4(),
        result_id=uuid4(),
        metadata={
            "safe": "legacy",
        },
        store=store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.ABSENT
    )

    assert replay.records == ()
    assert replay.binding_error is None
    assert replay.integrity_error is None
    assert store.calls == 0


def test_dispatch_time_unavailable_binding_does_not_read_store() -> None:
    store = _NoReadStore()

    replay = resolve_applied_change_replay(
        task_id=uuid4(),
        request_id=uuid4(),
        result_id=uuid4(),
        metadata={
            "applied_change_binding_state": (
                AppliedChangeBindingState
                .UNAVAILABLE.value
            ),
            "applied_change_count": 1,
            "applied_change_binding_error": (
                AppliedChangeBindingError
                .STORE_NOT_CONFIGURED.value
            ),
        },
        store=store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.UNAVAILABLE
    )

    assert replay.expected_count == 1

    assert (
        replay.binding_error
        is AppliedChangeBindingError
        .STORE_NOT_CONFIGURED
    )

    assert replay.records == ()
    assert replay.integrity_error is None
    assert store.calls == 0


def test_partial_bound_receipt_fails_before_store_read() -> None:
    store = _NoReadStore()

    replay = resolve_applied_change_replay(
        task_id=uuid4(),
        request_id=uuid4(),
        result_id=uuid4(),
        metadata={
            "applied_change_binding_state": (
                AppliedChangeBindingState
                .BOUND.value
            ),
        },
        store=store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.INTEGRITY_FAILURE
    )

    assert (
        replay.integrity_error
        is AppliedChangeReplayIntegrityError
        .RECEIPT_INVALID
    )

    assert replay.records == ()
    assert store.calls == 0


def test_boolean_count_is_not_accepted_as_integer_receipt() -> None:
    store = _NoReadStore()

    replay = resolve_applied_change_replay(
        task_id=uuid4(),
        request_id=uuid4(),
        result_id=uuid4(),
        metadata={
            "applied_change_binding_state": (
                AppliedChangeBindingState
                .BOUND.value
            ),
            "applied_change_count": True,
            "applied_change_manifest_sha256": (
                "0" * 64
            ),
        },
        store=store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.INTEGRITY_FAILURE
    )

    assert (
        replay.integrity_error
        is AppliedChangeReplayIntegrityError
        .RECEIPT_INVALID
    )

    assert store.calls == 0


def test_malformed_unavailable_receipt_fails_before_store_read() -> None:
    store = _NoReadStore()

    replay = resolve_applied_change_replay(
        task_id=uuid4(),
        request_id=uuid4(),
        result_id=uuid4(),
        metadata={
            "applied_change_binding_state": (
                AppliedChangeBindingState
                .UNAVAILABLE.value
            ),
            "applied_change_count": 1,
            "applied_change_binding_error": (
                AppliedChangeBindingError
                .STORE_NOT_CONFIGURED.value
            ),
            "applied_change_manifest_sha256": (
                "0" * 64
            ),
        },
        store=store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.INTEGRITY_FAILURE
    )

    assert (
        replay.integrity_error
        is AppliedChangeReplayIntegrityError
        .RECEIPT_INVALID
    )

    assert store.calls == 0


def test_bound_receipt_reloads_exact_persisted_record_set(
    tmp_path: Path,
) -> None:
    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    records = (
        _record(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            relative_path="a.txt",
        ),
        _record(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
            relative_path="b.txt",
        ),
    )

    store = SQLiteAppliedChangeStore(
        tmp_path / "applied-changes.sqlite3"
    )

    persisted = store.persist_many(
        records
    )

    replay = resolve_applied_change_replay(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        metadata=_bound_metadata(
            persisted
        ),
        store=store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.AVAILABLE
    )

    assert replay.records == persisted
    assert replay.expected_count == 2

    assert (
        replay.expected_manifest_sha256
        == applied_change_manifest_sha256(
            persisted
        )
    )

    assert replay.binding_error is None
    assert replay.integrity_error is None


def test_bound_receipt_with_missing_record_set_fails_closed() -> None:
    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    expected = (
        _record(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
        ),
    )

    store = _StaticStore(())

    replay = resolve_applied_change_replay(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        metadata=_bound_metadata(
            expected
        ),
        store=store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.INTEGRITY_FAILURE
    )

    assert (
        replay.integrity_error
        is AppliedChangeReplayIntegrityError
        .RECORD_SET_MISSING
    )

    assert replay.records == ()
    assert store.calls == 1


def test_store_returning_other_exact_binding_fails_closed() -> None:
    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    expected = (
        _record(
            task_id=task_id,
            request_id=request_id,
            result_id=result_id,
        ),
    )

    wrong = (
        _record(
            task_id=task_id,
            request_id=uuid4(),
            result_id=result_id,
        ),
    )

    store = _StaticStore(
        wrong
    )

    replay = resolve_applied_change_replay(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        metadata=_bound_metadata(
            expected
        ),
        store=store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.INTEGRITY_FAILURE
    )

    assert (
        replay.integrity_error
        is AppliedChangeReplayIntegrityError
        .RECORD_BINDING_MISMATCH
    )

    assert replay.records == ()
    assert store.calls == 1


def test_bound_receipt_count_mismatch_fails_closed() -> None:
    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    record = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
    )

    metadata = _bound_metadata(
        (record,)
    )

    metadata[
        "applied_change_count"
    ] = 2

    store = _StaticStore(
        (record,)
    )

    replay = resolve_applied_change_replay(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        metadata=metadata,
        store=store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.INTEGRITY_FAILURE
    )

    assert (
        replay.integrity_error
        is AppliedChangeReplayIntegrityError
        .RECORD_COUNT_MISMATCH
    )

    assert replay.records == ()
    assert store.calls == 1


def test_bound_receipt_manifest_mismatch_fails_closed() -> None:
    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    record = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
    )

    metadata = _bound_metadata(
        (record,)
    )

    metadata[
        "applied_change_manifest_sha256"
    ] = "0" * 64

    store = _StaticStore(
        (record,)
    )

    replay = resolve_applied_change_replay(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        metadata=metadata,
        store=store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.INTEGRITY_FAILURE
    )

    assert (
        replay.integrity_error
        is AppliedChangeReplayIntegrityError
        .MANIFEST_MISMATCH
    )

    assert replay.records == ()
    assert store.calls == 1


def test_store_read_failure_never_falls_back_to_workspace_state() -> None:
    task_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    record = _record(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
    )

    store = _FailingStore()

    replay = resolve_applied_change_replay(
        task_id=task_id,
        request_id=request_id,
        result_id=result_id,
        metadata=_bound_metadata(
            (record,)
        ),
        store=store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.INTEGRITY_FAILURE
    )

    assert (
        replay.integrity_error
        is AppliedChangeReplayIntegrityError
        .STORE_READ_FAILED
    )

    assert replay.records == ()
    assert store.calls == 1


def _persist_real_bound_write_for_cold_replay(
    workspace: Path,
    *,
    store_path: Path,
    journal_path: Path,
) -> tuple[
    Path,
    UUID,
    tuple[AppliedChangeRecord, ...],
]:
    workspace.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = workspace / "notes.txt"

    before = b"before\n"
    target.write_bytes(before)

    contract = TaskContract(
        objective=(
            "Persist one real workspace mutation "
            "for cold historical readback."
        ),
        required_conditions=(
            "Historical evidence survives restart.",
        ),
        evidence_required=(
            "Exact durable applied-change records.",
        ),
        scope=TaskScope(
            workspace_root=str(workspace),
            allowed_paths=("notes.txt",),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
    )

    request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="filesystem.write_text",
        arguments={
            "path": "notes.txt",
            "content": "after\n",
            "expected_sha256": sha256(
                before
            ).hexdigest(),
            "create_if_missing": False,
        },
        expectation_id=uuid4(),
    )

    store = SQLiteAppliedChangeStore(
        store_path
    )

    journal = SQLiteRuntimeJournal(
        journal_path
    )

    outcome = ToolDispatcher(
        build_phase5_registry(),
        applied_change_store=store,
    ).dispatch(
        request=request,
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=(
                "filesystem.write_text",
            ),
            autonomy_level=(
                AutonomyLevel.BOUNDED
            ),
            max_risk=RiskLevel.MEDIUM,
        ),
    )

    assert (
        outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_state"
        ]
        == AppliedChangeBindingState.BOUND.value
    )

    records = store.list_for_result(
        task_id=contract.task_id,
        request_id=request.request_id,
        result_id=outcome.result.result_id,
    )

    assert records

    assert (
        outcome.result.metadata[
            "applied_change_count"
        ]
        == len(records)
    )

    assert (
        outcome.result.metadata[
            "applied_change_manifest_sha256"
        ]
        == applied_change_manifest_sha256(
            records
        )
    )

    journal.record_outcome(
        outcome
    )

    assert journal.verify_integrity()

    return (
        target,
        contract.task_id,
        records,
    )


def test_process_style_cold_restart_uses_durable_evidence_not_later_workspace(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    workspace = tmp_path / "workspace"

    state_root.mkdir()

    store_path = (
        state_root
        / "applied-changes.sqlite3"
    )

    journal_path = (
        state_root
        / "runtime-journal.sqlite3"
    )

    (
        target,
        task_id,
        original_records,
    ) = _persist_real_bound_write_for_cold_replay(
        workspace,
        store_path=store_path,
        journal_path=journal_path,
    )

    assert target.read_bytes() == b"after\n"

    original_manifest = (
        applied_change_manifest_sha256(
            original_records
        )
    )

    original_after_digest = (
        original_records[0]
        .candidate
        .after_digest
    )

    # Mutable reality now diverges from the historical mutation.
    later_content = b"later-mutated-workspace\n"
    target.write_bytes(
        later_content
    )

    assert (
        sha256(
            later_content
        ).hexdigest()
        != original_after_digest
    )

    # New instances model process-style durable reopen.
    reopened_journal = SQLiteRuntimeJournal(
        journal_path
    )

    reopened_store = SQLiteAppliedChangeStore(
        store_path
    )

    assert reopened_journal.verify_integrity()

    observations = (
        reopened_journal.list_observations(
            task_id
        )
    )

    assert len(observations) == 1

    historical = observations[0].outcome

    assert (
        historical.result.metadata[
            "applied_change_manifest_sha256"
        ]
        == original_manifest
    )

    replay = resolve_applied_change_replay(
        task_id=historical.request.task_id,
        request_id=(
            historical.request.request_id
        ),
        result_id=(
            historical.result.result_id
        ),
        metadata=historical.result.metadata,
        store=reopened_store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.AVAILABLE
    )

    assert replay.records == original_records

    assert (
        replay.expected_manifest_sha256
        == original_manifest
    )

    assert (
        replay.records[0]
        .candidate
        .after_digest
        == original_after_digest
    )

    # Proves the mutable workspace stayed divergent;
    # replay did not rewrite or reinterpret it.
    assert target.read_bytes() == later_content

    assert (
        replay.records[0]
        .candidate
        .after_digest
        != sha256(
            target.read_bytes()
        ).hexdigest()
    )


def test_process_style_cold_restart_survives_historical_target_deletion(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    workspace = tmp_path / "workspace"

    state_root.mkdir()

    store_path = (
        state_root
        / "applied-changes.sqlite3"
    )

    journal_path = (
        state_root
        / "runtime-journal.sqlite3"
    )

    (
        target,
        task_id,
        original_records,
    ) = _persist_real_bound_write_for_cold_replay(
        workspace,
        store_path=store_path,
        journal_path=journal_path,
    )

    original_manifest = (
        applied_change_manifest_sha256(
            original_records
        )
    )

    target.unlink()

    assert not target.exists()

    reopened_journal = SQLiteRuntimeJournal(
        journal_path
    )

    reopened_store = SQLiteAppliedChangeStore(
        store_path
    )

    assert reopened_journal.verify_integrity()

    observations = (
        reopened_journal.list_observations(
            task_id
        )
    )

    assert len(observations) == 1

    historical = observations[0].outcome

    replay = resolve_applied_change_replay(
        task_id=historical.request.task_id,
        request_id=(
            historical.request.request_id
        ),
        result_id=(
            historical.result.result_id
        ),
        metadata=historical.result.metadata,
        store=reopened_store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.AVAILABLE
    )

    assert replay.records == original_records

    assert (
        replay.expected_manifest_sha256
        == original_manifest
    )

    # Historical evidence remains available even though
    # the original mutable target no longer exists.
    assert not target.exists()


def test_process_style_cold_restart_fails_closed_on_applied_store_payload_tamper(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    workspace = tmp_path / "workspace"

    state_root.mkdir()

    store_path = (
        state_root
        / "applied-changes.sqlite3"
    )

    journal_path = (
        state_root
        / "runtime-journal.sqlite3"
    )

    (
        target,
        task_id,
        original_records,
    ) = _persist_real_bound_write_for_cold_replay(
        workspace,
        store_path=store_path,
        journal_path=journal_path,
    )

    original_manifest = (
        applied_change_manifest_sha256(
            original_records
        )
    )

    later_content = (
        b"workspace-after-historical-write\n"
    )

    target.write_bytes(
        later_content
    )

    # Keep the JSON syntactically valid while changing
    # its exact durable bytes. The persisted SHA must
    # therefore detect the tamper during cold readback.
    with sqlite3.connect(
        store_path
    ) as connection:
        cursor = connection.execute(
            """
            UPDATE applied_change_records
            SET payload_json = payload_json || ' '
            """
        )

        assert cursor.rowcount == len(
            original_records
        )

        connection.commit()

    reopened_journal = SQLiteRuntimeJournal(
        journal_path
    )

    observations = (
        reopened_journal.list_observations(
            task_id
        )
    )

    assert len(observations) == 1

    historical = observations[0].outcome

    assert (
        historical.result.metadata[
            "applied_change_manifest_sha256"
        ]
        == original_manifest
    )

    reopened_store = SQLiteAppliedChangeStore(
        store_path
    )

    replay = resolve_applied_change_replay(
        task_id=historical.request.task_id,
        request_id=(
            historical.request.request_id
        ),
        result_id=(
            historical.result.result_id
        ),
        metadata=historical.result.metadata,
        store=reopened_store,
    )

    assert (
        replay.state
        is AppliedChangeReplayState.INTEGRITY_FAILURE
    )

    assert (
        replay.integrity_error
        is AppliedChangeReplayIntegrityError
        .STORE_READ_FAILED
    )

    assert replay.records == ()

    # Fail-closed readback must not reinterpret,
    # repair, or overwrite current workspace state.
    assert target.read_bytes() == later_content


def test_process_style_cold_restart_rejects_tampered_journal_before_replay(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    workspace = tmp_path / "workspace"

    state_root.mkdir()

    store_path = (
        state_root
        / "applied-changes.sqlite3"
    )

    journal_path = (
        state_root
        / "runtime-journal.sqlite3"
    )

    (
        target,
        task_id,
        original_records,
    ) = _persist_real_bound_write_for_cold_replay(
        workspace,
        store_path=store_path,
        journal_path=journal_path,
    )

    assert original_records

    later_content = (
        b"later-current-workspace\n"
    )

    target.write_bytes(
        later_content
    )

    # RuntimeJournal integrity is canonical-model based,
    # not raw JSON-byte based. Change trusted model
    # semantics while deliberately leaving the persisted
    # digest untouched.
    with sqlite3.connect(
        journal_path
    ) as connection:
        row = connection.execute(
            """
            SELECT
                payload_json,
                payload_sha256
            FROM runtime_observations
            WHERE task_id = ?
            """,
            (
                str(task_id),
            ),
        ).fetchone()

        assert row is not None

        original_payload = str(
            row[0]
        )

        original_digest = str(
            row[1]
        )

        payload = json.loads(
            original_payload
        )

        metadata = (
            payload["outcome"]
            ["result"]
            ["metadata"]
        )

        assert isinstance(
            metadata,
            dict,
        )

        metadata[
            "w4a4c_semantic_tamper_probe"
        ] = "changed"

        tampered_payload = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

        assert (
            tampered_payload
            != original_payload
        )

        cursor = connection.execute(
            """
            UPDATE runtime_observations
            SET payload_json = ?
            WHERE task_id = ?
            """,
            (
                tampered_payload,
                str(task_id),
            ),
        )

        assert cursor.rowcount == 1

        persisted_digest = (
            connection.execute(
                """
                SELECT payload_sha256
                FROM runtime_observations
                WHERE task_id = ?
                """,
                (
                    str(task_id),
                ),
            )
            .fetchone()
        )

        assert persisted_digest is not None

        assert (
            str(persisted_digest[0])
            == original_digest
        )

        connection.commit()
    reopened_journal = SQLiteRuntimeJournal(
        journal_path
    )

    assert not reopened_journal.verify_integrity()

    with pytest.raises(
        RuntimeJournalError,
        match="digest mismatch",
    ):
        reopened_journal.list_observations(
            task_id
        )

    # The historical DispatchOutcome never becomes
    # trusted input to the resolver after journal
    # integrity failure.
    assert target.read_bytes() == later_content

    # Applied-change storage remains independently
    # readable; journal corruption does not silently
    # promote it into a substitute outcome owner.
    reopened_store = SQLiteAppliedChangeStore(
        store_path
    )

    stored = reopened_store.list_for_result(
        task_id=task_id,
        request_id=(
            original_records[0].request_id
        ),
        result_id=(
            original_records[0].result_id
        ),
    )

    assert stored == original_records


@pytest.mark.parametrize(
    "column",
    (
        "observation_id",
        "task_id",
        "trace_id",
    ),
)
def test_runtime_journal_rejects_observation_locator_row_binding_tamper(
    tmp_path: Path,
    column: str,
) -> None:
    state_root = tmp_path / "state"
    workspace = tmp_path / "workspace"

    state_root.mkdir()

    store_path = (
        state_root
        / "applied-changes.sqlite3"
    )

    journal_path = (
        state_root
        / "runtime-journal.sqlite3"
    )

    (
        _target,
        task_id,
        original_records,
    ) = _persist_real_bound_write_for_cold_replay(
        workspace,
        store_path=store_path,
        journal_path=journal_path,
    )

    assert original_records

    journal = SQLiteRuntimeJournal(
        journal_path
    )

    original_observations = (
        journal.list_observations(
            task_id
        )
    )

    assert len(original_observations) == 1

    observation = original_observations[0]

    original_values = {
        "observation_id": (
            observation.observation_id
        ),
        "task_id": observation.task_id,
        "trace_id": observation.trace_id,
    }

    fake_value = uuid4()

    statements = {
        "observation_id": """
            UPDATE runtime_observations
            SET observation_id = ?
            WHERE observation_id = ?
        """,
        "task_id": """
            UPDATE runtime_observations
            SET task_id = ?
            WHERE observation_id = ?
        """,
        "trace_id": """
            UPDATE runtime_observations
            SET trace_id = ?
            WHERE observation_id = ?
        """,
    }

    with sqlite3.connect(
        journal_path
    ) as connection:
        cursor = connection.execute(
            statements[column],
            (
                str(fake_value),
                str(
                    observation.observation_id
                ),
            ),
        )

        assert cursor.rowcount == 1

        connection.commit()

    reopened = SQLiteRuntimeJournal(
        journal_path
    )

    assert not reopened.verify_integrity()

    lookup_task_id = (
        fake_value
        if column == "task_id"
        else task_id
    )

    with pytest.raises(
        RuntimeJournalError,
        match="row binding mismatch",
    ):
        reopened.list_observations(
            lookup_task_id
        )

    # The validated payload identity itself was never
    # changed by the SQL locator-column corruption.
    assert (
        original_values[column]
        != fake_value
    )

    # Independent applied-change evidence remains intact;
    # it does not repair or override the corrupted journal.
    reopened_store = SQLiteAppliedChangeStore(
        store_path
    )

    assert (
        reopened_store.list_for_result(
            task_id=task_id,
            request_id=(
                original_records[0]
                .request_id
            ),
            result_id=(
                original_records[0]
                .result_id
            ),
        )
        == original_records
    )
