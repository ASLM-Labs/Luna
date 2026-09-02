from __future__ import annotations

import ast
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import luna.applied_changes.presentation as presentation_module
from luna.applied_changes.models import (
    AppliedChangeBindingError,
    AppliedChangeDegradationReason,
    AppliedChangeOperation,
    AppliedChangeProjectionPolicy,
    AppliedChangeRecord,
    applied_change_manifest_sha256,
)
from luna.applied_changes.presentation import (
    project_applied_change_presentation,
)
from luna.applied_changes.projector import project_text_change
from luna.applied_changes.replay import (
    AppliedChangeReplayIntegrityError,
    AppliedChangeReplayResult,
    AppliedChangeReplayState,
)

TASK_ID = UUID("00000000-0000-0000-0000-000000000001")
REQUEST_ID = UUID("00000000-0000-0000-0000-000000000002")
RESULT_ID = UUID("00000000-0000-0000-0000-000000000003")
FIRST_RECORD_ID = UUID("00000000-0000-0000-0000-000000000004")
SECOND_RECORD_ID = UUID("00000000-0000-0000-0000-000000000005")
RECORDED_AT = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _record(
    *,
    relative_path: str,
    record_id: UUID,
    before: str,
    after: str,
) -> AppliedChangeRecord:
    candidate = project_text_change(
        task_id=TASK_ID,
        operation=AppliedChangeOperation.WRITE_TEXT,
        relative_path=relative_path,
        before_text=before,
        after_text=after,
        before_digest=_digest(before),
        after_digest=_digest(after),
        before_size_bytes=len(before.encode("utf-8")),
        after_size_bytes=len(after.encode("utf-8")),
        policy=AppliedChangeProjectionPolicy(),
    )

    return AppliedChangeRecord.build(
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
        candidate=candidate,
        record_id=record_id,
        recorded_at=RECORDED_AT,
    )


def test_available_replay_projects_exact_historical_records_deterministically() -> None:
    first = _record(
        relative_path="a.txt",
        record_id=FIRST_RECORD_ID,
        before="alpha\n",
        after="alpha changed\n",
    )
    second = _record(
        relative_path="z.txt",
        record_id=SECOND_RECORD_ID,
        before="zeta\n",
        after="zeta changed\n",
    )

    replay = AppliedChangeReplayResult(
        state=AppliedChangeReplayState.AVAILABLE,
        task_id=TASK_ID,
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
        expected_count=2,
        expected_manifest_sha256=applied_change_manifest_sha256(
            (second, first)
        ),
        records=(second, first),
    )

    presented = project_applied_change_presentation(replay)

    assert presented.state is AppliedChangeReplayState.AVAILABLE
    assert presented.task_id == TASK_ID
    assert presented.request_id == REQUEST_ID
    assert presented.result_id == RESULT_ID
    assert tuple(
        entry.relative_path
        for entry in presented.entries
    ) == ("a.txt", "z.txt")

    first_entry = presented.entries[0]

    assert first_entry.record_id == first.record_id
    assert first_entry.integrity_digest == first.integrity_digest
    assert first_entry.recorded_at == first.recorded_at
    assert first_entry.operation is first.candidate.operation
    assert first_entry.state is first.candidate.state
    assert first_entry.before_existed is first.candidate.before_existed
    assert first_entry.before_digest == first.candidate.before_digest
    assert first_entry.after_digest == first.candidate.after_digest
    assert first_entry.before_size_bytes == first.candidate.before_size_bytes
    assert first_entry.after_size_bytes == first.candidate.after_size_bytes
    assert first_entry.hunks == first.candidate.hunks
    assert (
        first_entry.degradation_reason
        is first.candidate.degradation_reason
    )

    # Presentation ordering must not mutate durable replay ordering.
    assert replay.records == (second, first)


def test_absent_replay_presents_no_historical_change_claim() -> None:
    replay = AppliedChangeReplayResult(
        state=AppliedChangeReplayState.ABSENT,
        task_id=TASK_ID,
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
    )

    presented = project_applied_change_presentation(replay)

    assert presented.state is AppliedChangeReplayState.ABSENT
    assert presented.entries == ()
    assert presented.expected_count is None
    assert presented.expected_manifest_sha256 is None
    assert presented.binding_error is None
    assert presented.integrity_error is None


def test_unavailable_replay_preserves_binding_failure_without_fake_diff() -> None:
    replay = AppliedChangeReplayResult(
        state=AppliedChangeReplayState.UNAVAILABLE,
        task_id=TASK_ID,
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
        expected_count=1,
        binding_error=AppliedChangeBindingError.STORE_NOT_CONFIGURED,
    )

    presented = project_applied_change_presentation(replay)

    assert presented.state is AppliedChangeReplayState.UNAVAILABLE
    assert presented.expected_count == 1
    assert (
        presented.binding_error
        is AppliedChangeBindingError.STORE_NOT_CONFIGURED
    )
    assert presented.entries == ()
    assert presented.expected_manifest_sha256 is None
    assert presented.integrity_error is None


def test_integrity_failure_never_exposes_untrusted_records() -> None:
    replay = AppliedChangeReplayResult(
        state=AppliedChangeReplayState.INTEGRITY_FAILURE,
        task_id=TASK_ID,
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
        expected_count=1,
        expected_manifest_sha256="a" * 64,
        integrity_error=(
            AppliedChangeReplayIntegrityError.MANIFEST_MISMATCH
        ),
    )

    presented = project_applied_change_presentation(replay)

    assert (
        presented.state
        is AppliedChangeReplayState.INTEGRITY_FAILURE
    )
    assert presented.entries == ()
    assert presented.expected_count == 1
    assert presented.expected_manifest_sha256 == "a" * 64
    assert (
        presented.integrity_error
        is AppliedChangeReplayIntegrityError.MANIFEST_MISMATCH
    )
    assert presented.binding_error is None


def test_degraded_record_is_presented_as_degraded_not_reconstructed() -> None:
    before = "before\n"
    after = "after\n"

    candidate = project_text_change(
        task_id=TASK_ID,
        operation=AppliedChangeOperation.WRITE_TEXT,
        relative_path="degraded.txt",
        before_text=before,
        after_text=after,
        before_digest=_digest(before),
        after_digest=_digest(after),
        before_size_bytes=len(before.encode("utf-8")),
        after_size_bytes=len(after.encode("utf-8")),
        policy=AppliedChangeProjectionPolicy(
            max_representation_bytes=1,
        ),
    )

    assert candidate.degradation_reason is (
        AppliedChangeDegradationReason.REPRESENTATION_BUDGET_EXCEEDED
    )

    record = AppliedChangeRecord.build(
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
        candidate=candidate,
        record_id=FIRST_RECORD_ID,
        recorded_at=RECORDED_AT,
    )

    replay = AppliedChangeReplayResult(
        state=AppliedChangeReplayState.AVAILABLE,
        task_id=TASK_ID,
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
        expected_count=1,
        expected_manifest_sha256=applied_change_manifest_sha256(
            (record,)
        ),
        records=(record,),
    )

    presented = project_applied_change_presentation(replay)
    entry = presented.entries[0]

    assert entry.state is candidate.state
    assert entry.hunks == ()
    assert entry.degradation_reason is (
        AppliedChangeDegradationReason.REPRESENTATION_BUDGET_EXCEEDED
    )


def test_presentation_module_has_no_runtime_or_side_effect_authority() -> None:
    path = Path(presentation_module.__file__)
    tree = ast.parse(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )

    forbidden_imports = (
        "luna.desktop",
        "luna.runtime",
        "luna.tools",
        "luna.verification",
        "luna.workspace",
        "luna.recovery",
    )

    forbidden_calls = {
        "open",
        "write_text",
        "write_bytes",
        "unlink",
        "dispatch",
        "record_outcome",
        "mark_completed",
        "mark_observed",
        "latest_recoverable",
    }

    imported_forbidden: list[str] = []
    called_forbidden: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""

            if module.startswith(forbidden_imports):
                imported_forbidden.append(module)

        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(forbidden_imports):
                    imported_forbidden.append(alias.name)

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                continue

            if name in forbidden_calls:
                called_forbidden.append(name)

    assert imported_forbidden == []
    assert called_forbidden == []
