from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from luna.workspace import SnapshotStoreError, WorkspaceSnapshotStore


def test_snapshot_restores_existing_file_and_verifies_digest(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("original", encoding="utf-8")
    task_id = uuid4()
    store = WorkspaceSnapshotStore(str(tmp_path))
    snapshot = store.create_snapshot(task_id=task_id, relative_paths=("notes.txt",))

    target.write_text("changed", encoding="utf-8")
    result = store.restore(snapshot_id=snapshot.snapshot_id, task_id=task_id)

    assert target.read_text(encoding="utf-8") == "original"
    assert result.restored_files == ("notes.txt",)
    assert result.verified
    manifest = (
        tmp_path / ".luna" / "snapshots" / str(snapshot.snapshot_id) / "manifest.json"
    )
    assert manifest.is_file()


def test_snapshot_of_absent_file_removes_later_creation(tmp_path: Path) -> None:
    task_id = uuid4()
    store = WorkspaceSnapshotStore(str(tmp_path))
    snapshot = store.create_snapshot(task_id=task_id, relative_paths=("created.txt",))
    target = tmp_path / "created.txt"
    target.write_text("temporary", encoding="utf-8")

    result = store.restore(snapshot_id=snapshot.snapshot_id, task_id=task_id)

    assert not target.exists()
    assert result.removed_files == ("created.txt",)


def test_tampered_snapshot_blob_is_rejected_before_restore(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("trusted", encoding="utf-8")
    task_id = uuid4()
    store = WorkspaceSnapshotStore(str(tmp_path))
    snapshot = store.create_snapshot(task_id=task_id, relative_paths=("data.txt",))
    entry = snapshot.entries[0]
    assert entry.content_digest is not None
    blob = (
        tmp_path
        / ".luna"
        / "snapshots"
        / str(snapshot.snapshot_id)
        / "blobs"
        / entry.content_digest
    )
    blob.write_bytes(b"tampered")
    target.write_text("current", encoding="utf-8")

    with pytest.raises(SnapshotStoreError, match="SHA-256"):
        store.restore(snapshot_id=snapshot.snapshot_id, task_id=task_id)

    assert target.read_text(encoding="utf-8") == "current"


def test_snapshot_cannot_be_restored_by_another_task(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("value", encoding="utf-8")
    store = WorkspaceSnapshotStore(str(tmp_path))
    snapshot = store.create_snapshot(task_id=uuid4(), relative_paths=("file.txt",))

    with pytest.raises(SnapshotStoreError, match="task_id"):
        store.restore(snapshot_id=snapshot.snapshot_id, task_id=uuid4())


def test_runtime_owned_snapshot_path_cannot_be_task_target(tmp_path: Path) -> None:
    store = WorkspaceSnapshotStore(str(tmp_path))

    with pytest.raises(SnapshotStoreError, match="runtime-owned"):
        store.create_snapshot(
            task_id=uuid4(),
            relative_paths=(".luna/snapshots/escape.txt",),
        )
