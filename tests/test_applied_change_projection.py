from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

from luna.applied_changes.models import (
    AppliedChangeDegradationReason,
    AppliedChangeOperation,
    AppliedChangeProjectionPolicy,
    AppliedChangeSegmentKind,
    AppliedChangeState,
)
from luna.applied_changes.projector import (
    project_text_change,
)


def _digest(text: str) -> str:
    return sha256(
        text.encode("utf-8")
    ).hexdigest()


def _project(
    *,
    before: str | None,
    after: str,
    policy: (
        AppliedChangeProjectionPolicy
        | None
    ) = None,
):
    return project_text_change(
        task_id=uuid4(),
        operation=(
            AppliedChangeOperation.WRITE_TEXT
        ),
        relative_path="notes.txt",
        before_text=before,
        after_text=after,
        before_digest=(
            None
            if before is None
            else _digest(before)
        ),
        after_digest=_digest(after),
        before_size_bytes=(
            0
            if before is None
            else len(
                before.encode("utf-8")
            )
        ),
        after_size_bytes=len(
            after.encode("utf-8")
        ),
        policy=(
            policy
            or AppliedChangeProjectionPolicy()
        ),
    )


def test_projection_captures_actual_replacement_with_context() -> None:
    before = "alpha\nold\nomega\n"
    after = "alpha\nnew\nomega\n"
    task_id = uuid4()

    candidate = project_text_change(
        task_id=task_id,
        operation=(
            AppliedChangeOperation
            .REPLACE_TEXT
        ),
        relative_path="notes.txt",
        before_text=before,
        after_text=after,
        before_digest=_digest(before),
        after_digest=_digest(after),
        before_size_bytes=len(
            before.encode("utf-8")
        ),
        after_size_bytes=len(
            after.encode("utf-8")
        ),
        policy=(
            AppliedChangeProjectionPolicy(
                context_lines=1
            )
        ),
    )

    assert candidate.task_id == task_id
    assert (
        candidate.state
        is AppliedChangeState.COMPLETE
    )
    assert candidate.degradation_reason is None
    assert len(candidate.hunks) == 1

    hunk = candidate.hunks[0]

    assert hunk.before_start == 0
    assert hunk.before_count == 3
    assert hunk.after_start == 0
    assert hunk.after_count == 3

    assert tuple(
        segment.kind
        for segment in hunk.segments
    ) == (
        AppliedChangeSegmentKind.CONTEXT,
        AppliedChangeSegmentKind.DELETE,
        AppliedChangeSegmentKind.INSERT,
        AppliedChangeSegmentKind.CONTEXT,
    )

    assert (
        hunk.segments[1].lines
        == ("old\n",)
    )

    assert (
        hunk.segments[2].lines
        == ("new\n",)
    )


def test_projection_is_deterministic_for_same_inputs() -> None:
    before = "one\ntwo\n"
    after = "one\nthree\n"
    task_id = uuid4()
    policy = AppliedChangeProjectionPolicy(
        context_lines=1
    )

    arguments = {
        "task_id": task_id,
        "operation": (
            AppliedChangeOperation
            .REPLACE_TEXT
        ),
        "relative_path": "notes.txt",
        "before_text": before,
        "after_text": after,
        "before_digest": _digest(before),
        "after_digest": _digest(after),
        "before_size_bytes": len(
            before.encode("utf-8")
        ),
        "after_size_bytes": len(
            after.encode("utf-8")
        ),
        "policy": policy,
    }

    first = project_text_change(
        **arguments
    )

    second = project_text_change(
        **arguments
    )

    assert first == second


def test_projection_reports_no_change_without_hunks() -> None:
    text = "same\n"

    candidate = _project(
        before=text,
        after=text,
    )

    assert (
        candidate.state
        is AppliedChangeState.NO_CHANGE
    )
    assert candidate.hunks == ()
    assert candidate.degradation_reason is None
    assert (
        candidate.before_digest
        == candidate.after_digest
    )


def test_projection_represents_empty_creation_without_fake_hunk() -> None:
    candidate = _project(
        before=None,
        after="",
    )

    assert (
        candidate.state
        is AppliedChangeState.COMPLETE
    )
    assert candidate.before_existed is False
    assert candidate.before_digest is None
    assert candidate.before_size_bytes == 0
    assert candidate.after_size_bytes == 0
    assert candidate.hunks == ()


def test_projection_degrades_when_input_budget_is_exceeded() -> None:
    before = "a" * 20
    after = "b" * 20

    candidate = _project(
        before=before,
        after=after,
        policy=(
            AppliedChangeProjectionPolicy(
                max_input_bytes=10
            )
        ),
    )

    assert (
        candidate.state
        is AppliedChangeState.DEGRADED
    )

    assert (
        candidate.degradation_reason
        is AppliedChangeDegradationReason
        .INPUT_BUDGET_EXCEEDED
    )

    assert candidate.hunks == ()


def test_projection_degrades_on_after_basis_mismatch() -> None:
    before = "before\n"
    after = "after\n"

    candidate = project_text_change(
        task_id=uuid4(),
        operation=(
            AppliedChangeOperation.WRITE_TEXT
        ),
        relative_path="notes.txt",
        before_text=before,
        after_text=after,
        before_digest=_digest(before),
        after_digest=_digest(
            "different\n"
        ),
        before_size_bytes=len(
            before.encode("utf-8")
        ),
        after_size_bytes=len(
            after.encode("utf-8")
        ),
        policy=(
            AppliedChangeProjectionPolicy()
        ),
    )

    assert (
        candidate.state
        is AppliedChangeState.DEGRADED
    )

    assert (
        candidate.degradation_reason
        is AppliedChangeDegradationReason
        .AFTER_CONTENT_BASIS_MISMATCH
    )

    assert candidate.hunks == ()


def test_projection_degrades_on_before_basis_mismatch() -> None:
    accepted = "before\n"
    observed = "stale\n"
    after = "after\n"

    candidate = project_text_change(
        task_id=uuid4(),
        operation=(
            AppliedChangeOperation.WRITE_TEXT
        ),
        relative_path="notes.txt",
        before_text=observed,
        after_text=after,
        before_digest=_digest(accepted),
        after_digest=_digest(after),
        before_size_bytes=len(
            accepted.encode("utf-8")
        ),
        after_size_bytes=len(
            after.encode("utf-8")
        ),
        policy=(
            AppliedChangeProjectionPolicy()
        ),
    )

    assert (
        candidate.state
        is AppliedChangeState.DEGRADED
    )

    assert (
        candidate.degradation_reason
        is AppliedChangeDegradationReason
        .BEFORE_CONTENT_BASIS_MISMATCH
    )

    assert candidate.hunks == ()


def test_projection_degrades_when_hunk_budget_is_exceeded() -> None:
    before_lines = [
        f"line-{index}\n"
        for index in range(20)
    ]

    after_lines = list(before_lines)

    after_lines[2] = "changed-2\n"
    after_lines[17] = "changed-17\n"

    candidate = _project(
        before="".join(before_lines),
        after="".join(after_lines),
        policy=(
            AppliedChangeProjectionPolicy(
                max_hunks=1,
                context_lines=0,
            )
        ),
    )

    assert (
        candidate.state
        is AppliedChangeState.DEGRADED
    )

    assert (
        candidate.degradation_reason
        is AppliedChangeDegradationReason
        .HUNK_BUDGET_EXCEEDED
    )

    assert candidate.hunks == ()


def test_projection_degrades_when_representation_budget_is_exceeded() -> None:
    candidate = _project(
        before="alpha\n",
        after="beta\n",
        policy=(
            AppliedChangeProjectionPolicy(
                max_representation_bytes=1,
                context_lines=0,
            )
        ),
    )

    assert (
        candidate.state
        is AppliedChangeState.DEGRADED
    )

    assert (
        candidate.degradation_reason
        is AppliedChangeDegradationReason
        .REPRESENTATION_BUDGET_EXCEEDED
    )

    assert candidate.hunks == ()


def test_projection_preserves_final_newline_difference() -> None:
    candidate = _project(
        before="alpha",
        after="alpha\n",
        policy=(
            AppliedChangeProjectionPolicy(
                context_lines=0
            )
        ),
    )

    assert (
        candidate.state
        is AppliedChangeState.COMPLETE
    )

    assert len(candidate.hunks) == 1

    assert tuple(
        segment.kind
        for segment
        in candidate.hunks[0].segments
    ) == (
        AppliedChangeSegmentKind.DELETE,
        AppliedChangeSegmentKind.INSERT,
    )

    assert (
        candidate.hunks[0]
        .segments[0].lines
        == ("alpha",)
    )

    assert (
        candidate.hunks[0]
        .segments[1].lines
        == ("alpha\n",)
    )


def test_projection_degrades_for_unencodable_text() -> None:
    before = "before\n"
    after = "\ud800"

    candidate = project_text_change(
        task_id=uuid4(),
        operation=(
            AppliedChangeOperation.WRITE_TEXT
        ),
        relative_path="notes.txt",
        before_text=before,
        after_text=after,
        before_digest=_digest(before),
        after_digest="0" * 64,
        before_size_bytes=len(
            before.encode("utf-8")
        ),
        after_size_bytes=1,
        policy=(
            AppliedChangeProjectionPolicy()
        ),
    )

    assert (
        candidate.state
        is AppliedChangeState.DEGRADED
    )

    assert (
        candidate.degradation_reason
        is AppliedChangeDegradationReason
        .TEXT_ENCODING_UNSUPPORTED
    )

    assert candidate.hunks == ()
