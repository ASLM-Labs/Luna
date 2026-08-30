"""Bounded deterministic projection of actual text changes."""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from hashlib import sha256
from uuid import UUID

from luna.applied_changes.models import (
    AppliedChangeCandidate,
    AppliedChangeDegradationReason,
    AppliedChangeHunk,
    AppliedChangeOperation,
    AppliedChangeProjectionPolicy,
    AppliedChangeSegment,
    AppliedChangeSegmentKind,
    AppliedChangeState,
)


def _digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _degraded(
    *,
    task_id: UUID,
    operation: AppliedChangeOperation,
    relative_path: str,
    before_existed: bool,
    before_digest: str | None,
    after_digest: str,
    before_size_bytes: int,
    after_size_bytes: int,
    reason: AppliedChangeDegradationReason,
) -> AppliedChangeCandidate:
    return AppliedChangeCandidate(
        task_id=task_id,
        operation=operation,
        relative_path=relative_path,
        state=AppliedChangeState.DEGRADED,
        before_existed=before_existed,
        before_digest=before_digest,
        after_digest=after_digest,
        before_size_bytes=before_size_bytes,
        after_size_bytes=after_size_bytes,
        degradation_reason=reason,
    )


def _segment(
    *,
    kind: AppliedChangeSegmentKind,
    lines: tuple[str, ...],
) -> AppliedChangeSegment | None:
    if not lines:
        return None

    return AppliedChangeSegment(
        kind=kind,
        lines=lines,
    )


def _project_hunks(
    *,
    before_lines: tuple[str, ...],
    after_lines: tuple[str, ...],
    context_lines: int,
) -> tuple[AppliedChangeHunk, ...]:
    matcher = SequenceMatcher(
        None,
        before_lines,
        after_lines,
        autojunk=False,
    )

    hunks: list[AppliedChangeHunk] = []

    for group in matcher.get_grouped_opcodes(
        n=context_lines
    ):
        if not group:
            continue

        before_start = group[0][1]
        before_end = group[-1][2]
        after_start = group[0][3]
        after_end = group[-1][4]

        segments: list[
            AppliedChangeSegment
        ] = []

        for (
            tag,
            before_first,
            before_last,
            after_first,
            after_last,
        ) in group:
            if tag == "equal":
                segment = _segment(
                    kind=(
                        AppliedChangeSegmentKind
                        .CONTEXT
                    ),
                    lines=before_lines[
                        before_first:before_last
                    ],
                )

                if segment is not None:
                    segments.append(segment)

                continue

            if tag in {"delete", "replace"}:
                segment = _segment(
                    kind=(
                        AppliedChangeSegmentKind
                        .DELETE
                    ),
                    lines=before_lines[
                        before_first:before_last
                    ],
                )

                if segment is not None:
                    segments.append(segment)

            if tag in {"insert", "replace"}:
                segment = _segment(
                    kind=(
                        AppliedChangeSegmentKind
                        .INSERT
                    ),
                    lines=after_lines[
                        after_first:after_last
                    ],
                )

                if segment is not None:
                    segments.append(segment)

        if not segments:
            continue

        hunks.append(
            AppliedChangeHunk(
                before_start=before_start,
                before_count=(
                    before_end - before_start
                ),
                after_start=after_start,
                after_count=(
                    after_end - after_start
                ),
                segments=tuple(segments),
            )
        )

    return tuple(hunks)


def _representation_size_bytes(
    hunks: tuple[
        AppliedChangeHunk,
        ...,
    ],
) -> int:
    payload = {
        "hunks": [
            hunk.model_dump(mode="json")
            for hunk in hunks
        ]
    }

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    return len(
        serialized.encode("utf-8")
    )


def project_text_change(
    *,
    task_id: UUID,
    operation: AppliedChangeOperation,
    relative_path: str,
    before_text: str | None,
    after_text: str,
    before_digest: str | None,
    after_digest: str,
    before_size_bytes: int,
    after_size_bytes: int,
    policy: AppliedChangeProjectionPolicy,
) -> AppliedChangeCandidate:
    """Project bounded evidence from an accepted content basis.

    Projection has no mutation, recovery, presentation,
    verification, or authorization authority.
    """

    before_existed = (
        before_digest is not None
    )

    try:
        before_bytes = (
            None
            if before_text is None
            else before_text.encode("utf-8")
        )

        after_bytes = after_text.encode(
            "utf-8"
        )

    except UnicodeEncodeError:
        return _degraded(
            task_id=task_id,
            operation=operation,
            relative_path=relative_path,
            before_existed=before_existed,
            before_digest=before_digest,
            after_digest=after_digest,
            before_size_bytes=(
                before_size_bytes
            ),
            after_size_bytes=after_size_bytes,
            reason=(
                AppliedChangeDegradationReason
                .TEXT_ENCODING_UNSUPPORTED
            ),
        )

    if before_existed:
        if (
            before_bytes is None
            or len(before_bytes)
            != before_size_bytes
            or _digest_bytes(before_bytes)
            != before_digest
        ):
            return _degraded(
                task_id=task_id,
                operation=operation,
                relative_path=relative_path,
                before_existed=True,
                before_digest=before_digest,
                after_digest=after_digest,
                before_size_bytes=(
                    before_size_bytes
                ),
                after_size_bytes=(
                    after_size_bytes
                ),
                reason=(
                    AppliedChangeDegradationReason
                    .BEFORE_CONTENT_BASIS_MISMATCH
                ),
            )

    elif (
        before_bytes is not None
        or before_size_bytes != 0
    ):
        return _degraded(
            task_id=task_id,
            operation=operation,
            relative_path=relative_path,
            before_existed=False,
            before_digest=None,
            after_digest=after_digest,
            before_size_bytes=(
                before_size_bytes
            ),
            after_size_bytes=after_size_bytes,
            reason=(
                AppliedChangeDegradationReason
                .BEFORE_CONTENT_BASIS_MISMATCH
            ),
        )

    if (
        len(after_bytes)
        != after_size_bytes
        or _digest_bytes(after_bytes)
        != after_digest
    ):
        return _degraded(
            task_id=task_id,
            operation=operation,
            relative_path=relative_path,
            before_existed=before_existed,
            before_digest=before_digest,
            after_digest=after_digest,
            before_size_bytes=(
                before_size_bytes
            ),
            after_size_bytes=after_size_bytes,
            reason=(
                AppliedChangeDegradationReason
                .AFTER_CONTENT_BASIS_MISMATCH
            ),
        )

    total_input_bytes = len(
        after_bytes
    )

    if before_bytes is not None:
        total_input_bytes += len(
            before_bytes
        )

    if (
        total_input_bytes
        > policy.max_input_bytes
    ):
        return _degraded(
            task_id=task_id,
            operation=operation,
            relative_path=relative_path,
            before_existed=before_existed,
            before_digest=before_digest,
            after_digest=after_digest,
            before_size_bytes=(
                before_size_bytes
            ),
            after_size_bytes=after_size_bytes,
            reason=(
                AppliedChangeDegradationReason
                .INPUT_BUDGET_EXCEEDED
            ),
        )

    if (
        before_bytes is not None
        and before_bytes == after_bytes
    ):
        return AppliedChangeCandidate(
            task_id=task_id,
            operation=operation,
            relative_path=relative_path,
            state=AppliedChangeState.NO_CHANGE,
            before_existed=True,
            before_digest=before_digest,
            after_digest=after_digest,
            before_size_bytes=(
                before_size_bytes
            ),
            after_size_bytes=after_size_bytes,
        )

    before_lines = (
        ()
        if before_text is None
        else tuple(
            before_text.splitlines(
                keepends=True
            )
        )
    )

    after_lines = tuple(
        after_text.splitlines(
            keepends=True
        )
    )

    hunks = _project_hunks(
        before_lines=before_lines,
        after_lines=after_lines,
        context_lines=(
            policy.context_lines
        ),
    )

    if len(hunks) > policy.max_hunks:
        return _degraded(
            task_id=task_id,
            operation=operation,
            relative_path=relative_path,
            before_existed=before_existed,
            before_digest=before_digest,
            after_digest=after_digest,
            before_size_bytes=(
                before_size_bytes
            ),
            after_size_bytes=after_size_bytes,
            reason=(
                AppliedChangeDegradationReason
                .HUNK_BUDGET_EXCEEDED
            ),
        )

    if (
        _representation_size_bytes(hunks)
        > policy.max_representation_bytes
    ):
        return _degraded(
            task_id=task_id,
            operation=operation,
            relative_path=relative_path,
            before_existed=before_existed,
            before_digest=before_digest,
            after_digest=after_digest,
            before_size_bytes=(
                before_size_bytes
            ),
            after_size_bytes=after_size_bytes,
            reason=(
                AppliedChangeDegradationReason
                .REPRESENTATION_BUDGET_EXCEEDED
            ),
        )

    if not hunks:
        # Creation of an empty file is a real
        # mutation with no line-oriented hunk.
        if (
            before_text is None
            and len(after_bytes) == 0
        ):
            return AppliedChangeCandidate(
                task_id=task_id,
                operation=operation,
                relative_path=relative_path,
                state=(
                    AppliedChangeState.COMPLETE
                ),
                before_existed=False,
                before_digest=None,
                after_digest=after_digest,
                before_size_bytes=0,
                after_size_bytes=0,
            )

        return _degraded(
            task_id=task_id,
            operation=operation,
            relative_path=relative_path,
            before_existed=before_existed,
            before_digest=before_digest,
            after_digest=after_digest,
            before_size_bytes=(
                before_size_bytes
            ),
            after_size_bytes=after_size_bytes,
            reason=(
                AppliedChangeDegradationReason
                .PROJECTION_UNAVAILABLE
            ),
        )

    return AppliedChangeCandidate(
        task_id=task_id,
        operation=operation,
        relative_path=relative_path,
        state=AppliedChangeState.COMPLETE,
        before_existed=before_existed,
        before_digest=before_digest,
        after_digest=after_digest,
        before_size_bytes=(
            before_size_bytes
        ),
        after_size_bytes=after_size_bytes,
        hunks=hunks,
    )
