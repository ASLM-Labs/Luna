from __future__ import annotations

import stat
from pathlib import Path
from uuid import uuid4

import pytest

from luna.workspace.store import (
    SnapshotStoreError,
    WorkspaceSnapshotStore,
    digest_bytes,
)


def test_captured_existing_state_uses_captured_bytes_not_later_lexical_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    target.write_bytes(b"ACCEPTED")

    accepted_mode = stat.S_IMODE(
        target.stat().st_mode
    )

    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )

    target.write_bytes(b"FOREIGN")

    snapshot = (
        store._create_snapshot_from_captured_state(
            task_id=uuid4(),
            relative_path="src/module.py",
            existed=True,
            content=b"ACCEPTED",
            mode=accepted_mode,
        )
    )

    entry = snapshot.entries[0]

    assert entry.existed
    assert entry.content_digest == digest_bytes(
        b"ACCEPTED"
    )
    assert entry.size_bytes == len(
        b"ACCEPTED"
    )
    assert entry.mode == accepted_mode

    rollback = store.restore(
        snapshot_id=snapshot.snapshot_id,
        task_id=snapshot.task_id,
    )

    assert rollback.verified
    assert target.read_bytes() == b"ACCEPTED"


def test_captured_snapshot_creation_never_resolves_lexical_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )

    def forbidden_target_path(
        relative_path: str,
    ) -> Path:
        raise AssertionError(
            f"unexpected lexical target access: {relative_path}"
        )

    monkeypatch.setattr(
        store,
        "target_path",
        forbidden_target_path,
    )

    snapshot = (
        store._create_snapshot_from_captured_state(
            task_id=uuid4(),
            relative_path="src/module.py",
            existed=True,
            content=b"BOUND",
            mode=0o666,
        )
    )

    entry = snapshot.entries[0]

    assert entry.existed
    assert entry.content_digest == digest_bytes(
        b"BOUND"
    )


def test_captured_absence_does_not_reinterpret_later_competitor(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )

    competitor = source / "new.txt"
    competitor.write_bytes(
        b"FOREIGN-COMPETITOR"
    )

    snapshot = (
        store._create_snapshot_from_captured_state(
            task_id=uuid4(),
            relative_path="src/new.txt",
            existed=False,
            content=None,
            mode=None,
        )
    )

    entry = snapshot.entries[0]

    assert not entry.existed
    assert entry.content_digest is None
    assert entry.size_bytes == 0
    assert entry.mode is None

    assert (
        competitor.read_bytes()
        == b"FOREIGN-COMPETITOR"
    )


@pytest.mark.parametrize(
    ("existed", "content", "mode"),
    (
        (True, None, 0o666),
        (True, b"x", None),
        (False, b"x", None),
        (False, None, 0o666),
    ),
)
def test_captured_state_rejects_inconsistent_metadata(
    tmp_path: Path,
    existed: bool,
    content: bytes | None,
    mode: int | None,
) -> None:
    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )

    with pytest.raises(
        SnapshotStoreError,
    ):
        store._create_snapshot_from_captured_state(
            task_id=uuid4(),
            relative_path="src/module.py",
            existed=existed,
            content=content,
            mode=mode,
        )


def test_legacy_snapshot_capture_still_reads_workspace_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    target.write_bytes(b"LEGACY")

    store = WorkspaceSnapshotStore(
        str(tmp_path)
    )

    snapshot = store.create_snapshot(
        task_id=uuid4(),
        relative_paths=("src/module.py",),
    )

    entry = snapshot.entries[0]

    assert entry.existed
    assert entry.content_digest == digest_bytes(
        b"LEGACY"
    )
    assert entry.size_bytes == len(
        b"LEGACY"
    )
