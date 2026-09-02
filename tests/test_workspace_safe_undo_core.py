from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

import luna.workspace.mutator as mutator_module
from luna.workspace import (
    WorkspaceMutationError,
    WorkspaceMutator,
)
from luna.workspace.models import (
    RollbackStatus,
    SafeUndoReceiptState,
)
from luna.workspace.store import SnapshotStoreError

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows conditional safe-undo core suite",
)

BEFORE = "before"
AFTER = "after"


def _digest(
    text: str,
) -> str:
    return sha256(
        text.encode("utf-8")
    ).hexdigest()


def _mutator(
    tmp_path: Path,
) -> WorkspaceMutator:
    return WorkspaceMutator(
        workspace_root=str(tmp_path),
        task_id=uuid4(),
        allowed_paths=(
            "src",
            "new.txt",
        ),
        protected_paths=(),
    )


def _commit_case(
    tmp_path: Path,
    *,
    existed: bool,
) -> tuple[
    WorkspaceMutator,
    object,
    Path,
]:
    mutator = _mutator(
        tmp_path
    )

    if existed:
        source = tmp_path / "src"
        source.mkdir()

        target = source / "module.py"
        target.write_text(
            BEFORE,
            encoding="utf-8",
        )

        result = mutator.write_text(
            relative_path="src/module.py",
            content=AFTER,
            expected_sha256=_digest(BEFORE),
            create_if_missing=False,
        )

    else:
        target = tmp_path / "new.txt"

        result = mutator.write_text(
            relative_path="new.txt",
            content=AFTER,
            expected_sha256=None,
            create_if_missing=True,
        )

    return (
        mutator,
        result,
        target,
    )


@pytest.mark.parametrize(
    "existed",
    [False, True],
)
def test_safe_undo_restores_exact_before_state_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existed: bool,
) -> None:
    mutator, result, target = (
        _commit_case(
            tmp_path,
            existed=existed,
        )
    )

    def legacy_restore_must_not_run(
        *args,
        **kwargs,
    ):
        del args, kwargs
        raise AssertionError(
            "legacy store.restore was invoked"
        )

    monkeypatch.setattr(
        mutator.store,
        "restore",
        legacy_restore_must_not_run,
    )

    undone = mutator.safe_undo(
        result.snapshot.snapshot_id
    )

    assert (
        undone.status
        is RollbackStatus.RESTORED
    )
    assert undone.verified

    receipt = (
        mutator.store.load_undo_receipt(
            result.snapshot.snapshot_id,
            task_id=mutator.task_id,
        )
    )

    assert (
        receipt.state
        is SafeUndoReceiptState.UNDONE
    )

    if existed:
        assert (
            target.read_text(
                encoding="utf-8"
            )
            == BEFORE
        )
        assert undone.restored_files == (
            "src/module.py",
        )
        assert undone.removed_files == ()

    else:
        assert not target.exists()
        assert undone.restored_files == ()
        assert undone.removed_files == (
            "new.txt",
        )

    second = mutator.safe_undo(
        result.snapshot.snapshot_id
    )

    assert (
        second.status
        is RollbackStatus.NO_CHANGES
    )
    assert second.verified
    assert second.restored_files == ()
    assert second.removed_files == ()


def test_prepared_receipt_never_authorizes_safe_undo(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    target.write_text(
        BEFORE,
        encoding="utf-8",
    )

    mutator = _mutator(
        tmp_path
    )

    snapshot = (
        mutator.store
        ._create_snapshot_from_captured_state(
            task_id=mutator.task_id,
            relative_path="src/module.py",
            existed=True,
            content=BEFORE.encode("utf-8"),
            mode=target.stat().st_mode & 0o777,
        )
    )

    mutator.store.prepare_undo_receipt(
        snapshot=snapshot,
        relative_path="src/module.py",
        expected_after_sha256=_digest(AFTER),
        expected_after_size_bytes=len(
            AFTER.encode("utf-8")
        ),
    )

    with pytest.raises(
        WorkspaceMutationError,
        match="does not authorize undo",
    ):
        mutator.safe_undo(
            snapshot.snapshot_id
        )

    assert (
        target.read_text(
            encoding="utf-8"
        )
        == BEFORE
    )

    receipt = (
        mutator.store.load_undo_receipt(
            snapshot.snapshot_id,
            task_id=mutator.task_id,
        )
    )

    assert (
        receipt.state
        is SafeUndoReceiptState.PREPARED
    )


def test_foreign_same_object_rewrite_blocks_safe_undo_without_clobber(
    tmp_path: Path,
) -> None:
    mutator, result, target = (
        _commit_case(
            tmp_path,
            existed=True,
        )
    )

    target.write_bytes(
        b"FOREIGN"
    )

    with pytest.raises(
        WorkspaceMutationError,
        match=(
            "does not match committed "
            "after-state token"
        ),
    ):
        mutator.safe_undo(
            result.snapshot.snapshot_id
        )

    assert target.read_bytes() == b"FOREIGN"


def test_same_bytes_foreign_replacement_blocks_safe_undo(
    tmp_path: Path,
) -> None:
    mutator, result, target = (
        _commit_case(
            tmp_path,
            existed=True,
        )
    )

    replacement = (
        target.parent
        / "replacement.py"
    )

    replacement.write_text(
        AFTER,
        encoding="utf-8",
    )

    os.replace(
        replacement,
        target,
    )

    with pytest.raises(
        WorkspaceMutationError,
        match=(
            "does not match committed "
            "after-state token"
        ),
    ):
        mutator.safe_undo(
            result.snapshot.snapshot_id
        )

    assert (
        target.read_text(
            encoding="utf-8"
        )
        == AFTER
    )


def test_undone_receipt_refuses_foreign_drift_instead_of_claiming_no_changes(
    tmp_path: Path,
) -> None:
    mutator, result, target = (
        _commit_case(
            tmp_path,
            existed=True,
        )
    )

    mutator.safe_undo(
        result.snapshot.snapshot_id
    )

    target.write_bytes(
        b"FOREIGN-AFTER-UNDO"
    )

    with pytest.raises(
        WorkspaceMutationError,
        match=(
            "UNDONE safe-undo receipt target "
            "does not match snapshot before-state"
        ),
    ):
        mutator.safe_undo(
            result.snapshot.snapshot_id
        )

    assert (
        target.read_bytes()
        == b"FOREIGN-AFTER-UNDO"
    )


def test_undone_persistence_failure_stops_after_verified_inverse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutator, result, target = (
        _commit_case(
            tmp_path,
            existed=True,
        )
    )

    def fail_before_persist(
        *,
        snapshot_id,
        task_id,
    ):
        del snapshot_id, task_id
        raise SnapshotStoreError(
            "forced UNDONE persistence failure"
        )

    monkeypatch.setattr(
        mutator.store,
        "mark_undo_receipt_undone",
        fail_before_persist,
    )

    with pytest.raises(
        WorkspaceMutationError,
        match="receipt remains incomplete",
    ):
        mutator.safe_undo(
            result.snapshot.snapshot_id
        )

    assert (
        target.read_text(
            encoding="utf-8"
        )
        == BEFORE
    )

    receipt = (
        mutator.store.load_undo_receipt(
            result.snapshot.snapshot_id,
            task_id=mutator.task_id,
        )
    )

    assert (
        receipt.state
        is SafeUndoReceiptState.COMMITTED
    )

    with pytest.raises(
        WorkspaceMutationError,
        match=(
            "does not match committed "
            "after-state token"
        ),
    ):
        mutator.safe_undo(
            result.snapshot.snapshot_id
        )

    assert (
        target.read_text(
            encoding="utf-8"
        )
        == BEFORE
    )


def test_durable_undone_write_is_reconciled_after_postpersist_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutator, result, target = (
        _commit_case(
            tmp_path,
            existed=True,
        )
    )

    original = (
        mutator.store
        .mark_undo_receipt_undone
    )

    def persist_then_raise(
        *,
        snapshot_id,
        task_id,
    ):
        original(
            snapshot_id=snapshot_id,
            task_id=task_id,
        )

        raise SnapshotStoreError(
            "forced exception after durable UNDONE"
        )

    monkeypatch.setattr(
        mutator.store,
        "mark_undo_receipt_undone",
        persist_then_raise,
    )

    undone = mutator.safe_undo(
        result.snapshot.snapshot_id
    )

    assert (
        undone.status
        is RollbackStatus.RESTORED
    )

    assert (
        target.read_text(
            encoding="utf-8"
        )
        == BEFORE
    )

    receipt = (
        mutator.store.load_undo_receipt(
            result.snapshot.snapshot_id,
            task_id=mutator.task_id,
        )
    )

    assert (
        receipt.state
        is SafeUndoReceiptState.UNDONE
    )


def test_snapshot_blob_tamper_blocks_safe_undo_before_target_mutation(
    tmp_path: Path,
) -> None:
    mutator, result, target = (
        _commit_case(
            tmp_path,
            existed=True,
        )
    )

    entry = result.snapshot.entries[0]

    assert entry.content_digest is not None

    blob = (
        mutator.store.snapshot_root
        / str(result.snapshot.snapshot_id)
        / "blobs"
        / entry.content_digest
    )

    blob.write_bytes(
        b"TAMPER"
    )

    with pytest.raises(
        WorkspaceMutationError,
        match="failed SHA-256 verification",
    ):
        mutator.safe_undo(
            result.snapshot.snapshot_id
        )

    assert (
        target.read_text(
            encoding="utf-8"
        )
        == AFTER
    )

    receipt = (
        mutator.store.load_undo_receipt(
            result.snapshot.snapshot_id,
            task_id=mutator.task_id,
        )
    )

    assert (
        receipt.state
        is SafeUndoReceiptState.COMMITTED
    )


def test_safe_undo_fails_closed_outside_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutator = _mutator(
        tmp_path
    )

    monkeypatch.setattr(
        mutator_module.os,
        "name",
        "posix",
    )

    with pytest.raises(
        WorkspaceMutationError,
        match="supported only on Windows",
    ):
        mutator.safe_undo(
            uuid4()
        )
