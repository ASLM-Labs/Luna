from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from luna.workspace.models import SafeUndoReceiptState, WindowsAfterStateToken
from luna.workspace.store import SnapshotStoreError, WorkspaceSnapshotStore

AFTER = b"after"
AFTER_SHA256 = sha256(AFTER).hexdigest()


def _snapshot(
    store: WorkspaceSnapshotStore,
    *,
    task_id: UUID,
    existed: bool = True,
):
    return store._create_snapshot_from_captured_state(
        task_id=task_id,
        relative_path="notes.txt",
        existed=existed,
        content=b"before" if existed else None,
        mode=0o666 if existed else None,
    )


def _after_token(
    *,
    content: bytes = AFTER,
) -> WindowsAfterStateToken:
    return WindowsAfterStateToken(
        volume_serial_number=17,
        file_id="ab" * 16,
        creation_time=101,
        last_write_time=202,
        change_time=303,
        content_sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        mode=0o666,
        dacl_sha256=sha256(b"dacl").hexdigest(),
        dacl_protected=False,
    )


@pytest.mark.parametrize(
    "existed",
    [True, False],
)
def test_prepared_safe_undo_receipt_is_durable_without_mutating_snapshot(
    tmp_path: Path,
    existed: bool,
) -> None:
    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )
    task_id = uuid4()

    snapshot = _snapshot(
        store,
        task_id=task_id,
        existed=existed,
    )

    manifest = (
        store._snapshot_directory(
            snapshot.snapshot_id
        )
        / "manifest.json"
    )

    manifest_before = manifest.read_bytes()

    receipt = store.prepare_undo_receipt(
        snapshot=snapshot,
        relative_path="notes.txt",
        expected_after_sha256=AFTER_SHA256,
        expected_after_size_bytes=len(AFTER),
    )

    assert (
        receipt.state
        is SafeUndoReceiptState.PREPARED
    )
    assert receipt.after_token is None
    assert manifest.read_bytes() == manifest_before

    reopened = WorkspaceSnapshotStore(
        str(tmp_path)
    )

    loaded = reopened.load_undo_receipt(
        snapshot.snapshot_id,
        task_id=task_id,
    )

    assert loaded == receipt
    assert (
        reopened.load_snapshot(
            snapshot.snapshot_id
        )
        == snapshot
    )


def test_safe_undo_receipt_transitions_prepared_committed_undone(
    tmp_path: Path,
) -> None:
    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )
    task_id = uuid4()

    snapshot = _snapshot(
        store,
        task_id=task_id,
    )

    prepared = store.prepare_undo_receipt(
        snapshot=snapshot,
        relative_path="notes.txt",
        expected_after_sha256=AFTER_SHA256,
        expected_after_size_bytes=len(AFTER),
    )

    committed = store.commit_undo_receipt(
        snapshot_id=snapshot.snapshot_id,
        task_id=task_id,
        after_token=_after_token(),
    )

    assert (
        prepared.state
        is SafeUndoReceiptState.PREPARED
    )
    assert (
        committed.state
        is SafeUndoReceiptState.COMMITTED
    )
    assert committed.after_token == _after_token()

    reopened = WorkspaceSnapshotStore(
        str(tmp_path)
    )

    assert (
        reopened.load_undo_receipt(
            snapshot.snapshot_id,
            task_id=task_id,
        )
        == committed
    )

    undone = reopened.mark_undo_receipt_undone(
        snapshot_id=snapshot.snapshot_id,
        task_id=task_id,
    )

    assert (
        undone.state
        is SafeUndoReceiptState.UNDONE
    )
    assert undone.after_token == committed.after_token

    assert (
        reopened.load_undo_receipt(
            snapshot.snapshot_id,
            task_id=task_id,
        )
        == undone
    )


def test_safe_undo_receipt_rejects_after_token_semantic_mismatch(
    tmp_path: Path,
) -> None:
    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )
    task_id = uuid4()

    snapshot = _snapshot(
        store,
        task_id=task_id,
    )

    store.prepare_undo_receipt(
        snapshot=snapshot,
        relative_path="notes.txt",
        expected_after_sha256=AFTER_SHA256,
        expected_after_size_bytes=len(AFTER),
    )

    with pytest.raises(
        SnapshotStoreError,
        match="after token",
    ):
        store.commit_undo_receipt(
            snapshot_id=snapshot.snapshot_id,
            task_id=task_id,
            after_token=_after_token(
                content=b"different"
            ),
        )


def test_safe_undo_receipt_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )
    task_id = uuid4()

    snapshot = _snapshot(
        store,
        task_id=task_id,
    )

    store.prepare_undo_receipt(
        snapshot=snapshot,
        relative_path="notes.txt",
        expected_after_sha256=AFTER_SHA256,
        expected_after_size_bytes=len(AFTER),
    )

    receipt_path = store._undo_receipt_path(
        snapshot.snapshot_id
    )

    payload = json.loads(
        receipt_path.read_text(
            encoding="utf-8"
        )
    )

    payload["expected_after_size_bytes"] += 1

    receipt_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(
        SnapshotStoreError,
        match="receipt is invalid",
    ):
        store.load_undo_receipt(
            snapshot.snapshot_id,
            task_id=task_id,
        )


def test_safe_undo_receipt_rejects_task_binding_mismatch(
    tmp_path: Path,
) -> None:
    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )
    task_id = uuid4()

    snapshot = _snapshot(
        store,
        task_id=task_id,
    )

    store.prepare_undo_receipt(
        snapshot=snapshot,
        relative_path="notes.txt",
        expected_after_sha256=AFTER_SHA256,
        expected_after_size_bytes=len(AFTER),
    )

    with pytest.raises(
        SnapshotStoreError,
        match="requesting task",
    ):
        store.load_undo_receipt(
            snapshot.snapshot_id,
            task_id=uuid4(),
        )


def test_safe_undo_receipt_rejects_snapshot_path_mismatch(
    tmp_path: Path,
) -> None:
    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )
    task_id = uuid4()

    snapshot = _snapshot(
        store,
        task_id=task_id,
    )

    with pytest.raises(
        SnapshotStoreError,
        match="snapshot target",
    ):
        store.prepare_undo_receipt(
            snapshot=snapshot,
            relative_path="other.txt",
            expected_after_sha256=AFTER_SHA256,
            expected_after_size_bytes=len(AFTER),
        )


def test_safe_undo_receipt_refuses_reprepare_and_invalid_transitions(
    tmp_path: Path,
) -> None:
    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )
    task_id = uuid4()

    snapshot = _snapshot(
        store,
        task_id=task_id,
    )

    store.prepare_undo_receipt(
        snapshot=snapshot,
        relative_path="notes.txt",
        expected_after_sha256=AFTER_SHA256,
        expected_after_size_bytes=len(AFTER),
    )

    with pytest.raises(
        SnapshotStoreError,
        match="already exists",
    ):
        store.prepare_undo_receipt(
            snapshot=snapshot,
            relative_path="notes.txt",
            expected_after_sha256=AFTER_SHA256,
            expected_after_size_bytes=len(AFTER),
        )

    with pytest.raises(
        SnapshotStoreError,
        match="COMMITTED",
    ):
        store.mark_undo_receipt_undone(
            snapshot_id=snapshot.snapshot_id,
            task_id=task_id,
        )

    store.commit_undo_receipt(
        snapshot_id=snapshot.snapshot_id,
        task_id=task_id,
        after_token=_after_token(),
    )

    with pytest.raises(
        SnapshotStoreError,
        match="PREPARED",
    ):
        store.commit_undo_receipt(
            snapshot_id=snapshot.snapshot_id,
            task_id=task_id,
            after_token=_after_token(),
        )
