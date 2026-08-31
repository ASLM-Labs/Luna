from __future__ import annotations

from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from luna.applied_changes.models import (
    AppliedChangeOperation,
    AppliedChangeProjectionPolicy,
    AppliedChangeState,
)
from luna.applied_changes.projector import (
    project_text_change_bytes,
)
from luna.workspace.models import (
    FileChange,
    MutationStatus,
    RollbackResult,
    RollbackStatus,
    SnapshotEntry,
    WorkspaceMutationResult,
    WorkspaceSnapshot,
)


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _snapshot(
    *,
    task_id: UUID,
    paths: tuple[
        tuple[str, bytes | None],
        ...,
    ],
) -> WorkspaceSnapshot:
    entries = tuple(
        SnapshotEntry(
            relative_path=relative_path,
            existed=content is not None,
            content_digest=(
                None
                if content is None
                else _digest(content)
            ),
            size_bytes=(
                0
                if content is None
                else len(content)
            ),
            mode=(
                None
                if content is None
                else 0o644
            ),
        )
        for relative_path, content in paths
    )

    return WorkspaceSnapshot.build(
        task_id=task_id,
        workspace_root_digest="0" * 64,
        entries=entries,
    )


def _candidate(
    *,
    task_id: UUID,
    relative_path: str = "notes.txt",
    before: bytes | None = b"before\n",
    after: bytes = b"after\n",
):
    return project_text_change_bytes(
        task_id=task_id,
        operation=(
            AppliedChangeOperation.WRITE_TEXT
        ),
        relative_path=relative_path,
        before_content=before,
        after_content=after,
        before_digest=(
            None
            if before is None
            else _digest(before)
        ),
        after_digest=_digest(after),
        before_size_bytes=(
            0
            if before is None
            else len(before)
        ),
        after_size_bytes=len(after),
        policy=(
            AppliedChangeProjectionPolicy()
        ),
    )


def _change(
    *,
    relative_path: str = "notes.txt",
    before: bytes | None = b"before\n",
    after: bytes = b"after\n",
) -> FileChange:
    return FileChange(
        relative_path=relative_path,
        before_digest=(
            None
            if before is None
            else _digest(before)
        ),
        after_digest=_digest(after),
        before_size_bytes=(
            0
            if before is None
            else len(before)
        ),
        after_size_bytes=len(after),
        after_mode=0o644,
        created=before is None,
    )


def _result(
    *,
    task_id: UUID,
    before: bytes | None = b"before\n",
    after: bytes = b"after\n",
    candidate_task_id: UUID | None = None,
) -> WorkspaceMutationResult:
    candidate = _candidate(
        task_id=(
            candidate_task_id
            or task_id
        ),
        before=before,
        after=after,
    )

    return WorkspaceMutationResult(
        task_id=task_id,
        snapshot=_snapshot(
            task_id=task_id,
            paths=(
                ("notes.txt", before),
            ),
        ),
        status=MutationStatus.COMMITTED,
        changes=(
            _change(
                before=before,
                after=after,
            ),
        ),
        applied_changes=(candidate,),
    )


def test_workspace_mutation_result_defaults_to_no_applied_changes() -> None:
    task_id = uuid4()
    before = b"before\n"
    after = b"after\n"

    result = WorkspaceMutationResult(
        task_id=task_id,
        snapshot=_snapshot(
            task_id=task_id,
            paths=(
                ("notes.txt", before),
            ),
        ),
        status=MutationStatus.COMMITTED,
        changes=(
            _change(
                before=before,
                after=after,
            ),
        ),
    )

    assert result.applied_changes == ()


def test_workspace_mutation_result_accepts_bound_complete_candidate() -> None:
    result = _result(
        task_id=uuid4(),
    )

    assert len(result.applied_changes) == 1
    assert (
        result.applied_changes[0].state
        is AppliedChangeState.COMPLETE
    )


def test_workspace_mutation_result_accepts_bound_degraded_candidate() -> None:
    before = b"\xff\xfe"
    after = b"valid\n"

    result = _result(
        task_id=uuid4(),
        before=before,
        after=after,
    )

    assert (
        result.applied_changes[0].state
        is AppliedChangeState.DEGRADED
    )


def test_workspace_mutation_result_accepts_created_file_candidate() -> None:
    result = _result(
        task_id=uuid4(),
        before=None,
        after=b"created\n",
    )

    assert (
        result.changes[0].created
        is True
    )
    assert (
        result.applied_changes[0]
        .before_existed
        is False
    )


def test_workspace_mutation_result_rejects_candidate_task_mismatch() -> None:
    with pytest.raises(
        ValidationError,
        match=(
            "applied-change task_id must "
            "match mutation task_id"
        ),
    ):
        _result(
            task_id=uuid4(),
            candidate_task_id=uuid4(),
        )


def test_workspace_mutation_result_rejects_candidate_path_mismatch() -> None:
    task_id = uuid4()
    before = b"before\n"
    after = b"after\n"

    with pytest.raises(
        ValidationError,
        match=(
            "applied-change paths must "
            "exactly match file changes"
        ),
    ):
        WorkspaceMutationResult(
            task_id=task_id,
            snapshot=_snapshot(
                task_id=task_id,
                paths=(
                    ("notes.txt", before),
                ),
            ),
            status=MutationStatus.COMMITTED,
            changes=(
                _change(
                    before=before,
                    after=after,
                ),
            ),
            applied_changes=(
                _candidate(
                    task_id=task_id,
                    relative_path="other.txt",
                    before=before,
                    after=after,
                ),
            ),
        )


def test_workspace_mutation_result_rejects_digest_mismatch() -> None:
    task_id = uuid4()
    before = b"before\n"
    after = b"after\n"

    with pytest.raises(
        ValidationError,
        match=(
            "applied-change digests do not "
            "match file change"
        ),
    ):
        WorkspaceMutationResult(
            task_id=task_id,
            snapshot=_snapshot(
                task_id=task_id,
                paths=(
                    ("notes.txt", before),
                ),
            ),
            status=MutationStatus.COMMITTED,
            changes=(
                FileChange(
                    relative_path="notes.txt",
                    before_digest=_digest(
                        before
                    ),
                    after_digest="1" * 64,
                    before_size_bytes=len(
                        before
                    ),
                    after_size_bytes=len(
                        after
                    ),
                    after_mode=0o644,
                ),
            ),
            applied_changes=(
                _candidate(
                    task_id=task_id,
                    before=before,
                    after=after,
                ),
            ),
        )


def test_workspace_mutation_result_rejects_size_mismatch() -> None:
    task_id = uuid4()
    before = b"before\n"
    after = b"after\n"

    with pytest.raises(
        ValidationError,
        match=(
            "applied-change sizes do not "
            "match file change"
        ),
    ):
        WorkspaceMutationResult(
            task_id=task_id,
            snapshot=_snapshot(
                task_id=task_id,
                paths=(
                    ("notes.txt", before),
                ),
            ),
            status=MutationStatus.COMMITTED,
            changes=(
                FileChange(
                    relative_path="notes.txt",
                    before_digest=_digest(
                        before
                    ),
                    after_digest=_digest(
                        after
                    ),
                    before_size_bytes=len(
                        before
                    ),
                    after_size_bytes=999,
                    after_mode=0o644,
                ),
            ),
            applied_changes=(
                _candidate(
                    task_id=task_id,
                    before=before,
                    after=after,
                ),
            ),
        )


def test_workspace_mutation_result_rejects_snapshot_before_mismatch() -> None:
    task_id = uuid4()
    before = b"before\n"
    stale = b"stale\n"
    after = b"after\n"

    with pytest.raises(
        ValidationError,
        match=(
            "applied-change before-state does not "
            "match mutation snapshot"
        ),
    ):
        WorkspaceMutationResult(
            task_id=task_id,
            snapshot=_snapshot(
                task_id=task_id,
                paths=(
                    ("notes.txt", stale),
                ),
            ),
            status=MutationStatus.COMMITTED,
            changes=(
                _change(
                    before=before,
                    after=after,
                ),
            ),
            applied_changes=(
                _candidate(
                    task_id=task_id,
                    before=before,
                    after=after,
                ),
            ),
        )


def test_workspace_mutation_result_rejects_partial_candidate_coverage() -> None:
    task_id = uuid4()

    before_a = b"a\n"
    after_a = b"A\n"

    before_b = b"b\n"
    after_b = b"B\n"

    with pytest.raises(
        ValidationError,
        match=(
            "applied-change evidence must "
            "cover every file change"
        ),
    ):
        WorkspaceMutationResult(
            task_id=task_id,
            snapshot=_snapshot(
                task_id=task_id,
                paths=(
                    ("a.txt", before_a),
                    ("b.txt", before_b),
                ),
            ),
            status=MutationStatus.COMMITTED,
            changes=(
                _change(
                    relative_path="a.txt",
                    before=before_a,
                    after=after_a,
                ),
                _change(
                    relative_path="b.txt",
                    before=before_b,
                    after=after_b,
                ),
            ),
            applied_changes=(
                _candidate(
                    task_id=task_id,
                    relative_path="a.txt",
                    before=before_a,
                    after=after_a,
                ),
            ),
        )


def test_workspace_mutation_result_rejects_applied_change_on_rolled_back_result() -> None:
    task_id = uuid4()
    before = b"before\n"
    after = b"after\n"

    snapshot = _snapshot(
        task_id=task_id,
        paths=(
            ("notes.txt", before),
        ),
    )

    rollback = RollbackResult(
        snapshot_id=snapshot.snapshot_id,
        task_id=task_id,
        status=RollbackStatus.RESTORED,
        restored_files=("notes.txt",),
        verified=True,
    )

    with pytest.raises(
        ValidationError,
        match=(
            "applied-change evidence requires "
            "a committed mutation"
        ),
    ):
        WorkspaceMutationResult(
            task_id=task_id,
            snapshot=snapshot,
            status=MutationStatus.ROLLED_BACK,
            changes=(
                _change(
                    before=before,
                    after=after,
                ),
            ),
            applied_changes=(
                _candidate(
                    task_id=task_id,
                    before=before,
                    after=after,
                ),
            ),
            rollback=rollback,
        )
