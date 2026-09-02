from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from luna.workspace import WorkspaceMutationError, WorkspaceMutator
from luna.workspace.models import SafeUndoReceiptState
from luna.workspace.store import SnapshotStoreError

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows safe-undo receipt integration suite",
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


def _target_case(
    tmp_path: Path,
    *,
    existed: bool,
) -> tuple[str, Path, str | None]:
    if existed:
        source = tmp_path / "src"
        source.mkdir()

        target = source / "module.py"
        target.write_text(
            BEFORE,
            encoding="utf-8",
        )

        return (
            "src/module.py",
            target,
            _digest(BEFORE),
        )

    return (
        "new.txt",
        tmp_path / "new.txt",
        None,
    )


@pytest.mark.parametrize(
    "existed",
    [False, True],
)
def test_windows_commit_persists_exact_committed_safe_undo_receipt(
    tmp_path: Path,
    existed: bool,
) -> None:
    relative_path, target, expected = (
        _target_case(
            tmp_path,
            existed=existed,
        )
    )

    mutator = _mutator(
        tmp_path
    )

    result = mutator.write_text(
        relative_path=relative_path,
        content=AFTER,
        expected_sha256=expected,
        create_if_missing=not existed,
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
    assert receipt.after_token is not None
    assert (
        receipt.snapshot_id
        == result.snapshot.snapshot_id
    )
    assert receipt.task_id == mutator.task_id
    assert (
        receipt.relative_path
        == relative_path
    )
    assert (
        receipt.expected_after_sha256
        == _digest(AFTER)
    )
    assert (
        receipt.expected_after_size_bytes
        == len(AFTER.encode("utf-8"))
    )
    assert (
        receipt.after_token.content_sha256
        == _digest(AFTER)
    )
    assert (
        receipt.after_token.size_bytes
        == len(AFTER.encode("utf-8"))
    )
    assert (
        receipt.after_token.mode
        == result.changes[0].after_mode
    )
    assert (
        target.read_text(
            encoding="utf-8"
        )
        == AFTER
    )


def test_windows_receipt_lifecycle_orders_prepare_verify_then_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative_path, target, expected = (
        _target_case(
            tmp_path,
            existed=True,
        )
    )

    mutator = _mutator(
        tmp_path
    )

    original_prepare = (
        mutator.store.prepare_undo_receipt
    )
    original_verify = (
        mutator._verify_bound_publication
    )
    original_commit = (
        mutator.store.commit_undo_receipt
    )

    events: list[str] = []

    def prepare(
        *,
        snapshot,
        relative_path,
        expected_after_sha256,
        expected_after_size_bytes,
    ):
        assert events == []
        assert (
            target.read_text(
                encoding="utf-8"
            )
            == BEFORE
        )

        receipt = original_prepare(
            snapshot=snapshot,
            relative_path=relative_path,
            expected_after_sha256=(
                expected_after_sha256
            ),
            expected_after_size_bytes=(
                expected_after_size_bytes
            ),
        )

        assert (
            receipt.state
            is SafeUndoReceiptState.PREPARED
        )
        assert receipt.after_token is None

        events.append(
            "PREPARED"
        )

        return receipt

    def verify(
        *,
        observation,
        expected_content,
        source,
    ):
        assert events == [
            "PREPARED"
        ]

        result = original_verify(
            observation=observation,
            expected_content=expected_content,
            source=source,
        )

        events.append(
            "VERIFIED"
        )

        return result

    def commit(
        *,
        snapshot_id,
        task_id,
        after_token,
    ):
        assert events == [
            "PREPARED",
            "VERIFIED",
        ]

        prepared = (
            mutator.store.load_undo_receipt(
                snapshot_id,
                task_id=task_id,
            )
        )

        assert (
            prepared.state
            is SafeUndoReceiptState.PREPARED
        )
        assert prepared.after_token is None
        assert (
            after_token.content_sha256
            == _digest(AFTER)
        )
        assert (
            after_token.size_bytes
            == len(AFTER.encode("utf-8"))
        )

        events.append(
            "COMMIT"
        )

        return original_commit(
            snapshot_id=snapshot_id,
            task_id=task_id,
            after_token=after_token,
        )

    monkeypatch.setattr(
        mutator.store,
        "prepare_undo_receipt",
        prepare,
    )
    monkeypatch.setattr(
        mutator,
        "_verify_bound_publication",
        verify,
    )
    monkeypatch.setattr(
        mutator.store,
        "commit_undo_receipt",
        commit,
    )

    result = mutator.write_text(
        relative_path=relative_path,
        content=AFTER,
        expected_sha256=expected,
        create_if_missing=False,
    )

    assert events == [
        "PREPARED",
        "VERIFIED",
        "COMMIT",
    ]

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
    assert receipt.after_token is not None
    assert (
        target.read_text(
            encoding="utf-8"
        )
        == AFTER
    )


@pytest.mark.parametrize(
    "existed",
    [False, True],
)
def test_windows_receipt_commit_failure_rolls_back_and_leaves_prepared_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existed: bool,
) -> None:
    relative_path, target, expected = (
        _target_case(
            tmp_path,
            existed=existed,
        )
    )

    mutator = _mutator(
        tmp_path
    )

    original_prepare = (
        mutator.store.prepare_undo_receipt
    )

    snapshot_ids = []

    def capture_prepare(
        *,
        snapshot,
        relative_path,
        expected_after_sha256,
        expected_after_size_bytes,
    ):
        receipt = original_prepare(
            snapshot=snapshot,
            relative_path=relative_path,
            expected_after_sha256=(
                expected_after_sha256
            ),
            expected_after_size_bytes=(
                expected_after_size_bytes
            ),
        )

        snapshot_ids.append(
            snapshot.snapshot_id
        )

        return receipt

    def fail_commit(
        *,
        snapshot_id,
        task_id,
        after_token,
    ):
        del (
            snapshot_id,
            task_id,
            after_token,
        )

        raise SnapshotStoreError(
            "forced receipt commit failure"
        )

    monkeypatch.setattr(
        mutator.store,
        "prepare_undo_receipt",
        capture_prepare,
    )
    monkeypatch.setattr(
        mutator.store,
        "commit_undo_receipt",
        fail_commit,
    )

    with pytest.raises(
        WorkspaceMutationError,
        match="rolled back",
    ) as exc_info:
        mutator.write_text(
            relative_path=relative_path,
            content=AFTER,
            expected_sha256=expected,
            create_if_missing=not existed,
        )

    assert (
        exc_info.value.rollback
        is not None
    )
    assert (
        exc_info.value.rollback.verified
    )

    assert len(snapshot_ids) == 1

    receipt = (
        mutator.store.load_undo_receipt(
            snapshot_ids[0],
            task_id=mutator.task_id,
        )
    )

    assert (
        receipt.state
        is SafeUndoReceiptState.PREPARED
    )
    assert receipt.after_token is None

    if existed:
        assert (
            target.read_text(
                encoding="utf-8"
            )
            == BEFORE
        )

    else:
        assert not target.exists()


def test_windows_receipt_prepare_failure_prevents_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative_path, target, expected = (
        _target_case(
            tmp_path,
            existed=True,
        )
    )

    mutator = _mutator(
        tmp_path
    )

    def fail_prepare(
        *,
        snapshot,
        relative_path,
        expected_after_sha256,
        expected_after_size_bytes,
    ):
        del (
            snapshot,
            relative_path,
            expected_after_sha256,
            expected_after_size_bytes,
        )

        raise SnapshotStoreError(
            "forced receipt prepare failure"
        )

    monkeypatch.setattr(
        mutator.store,
        "prepare_undo_receipt",
        fail_prepare,
    )

    with pytest.raises(
        WorkspaceMutationError,
        match=(
            "safe-undo receipt preparation failed"
        ),
    ):
        mutator.write_text(
            relative_path=relative_path,
            content=AFTER,
            expected_sha256=expected,
            create_if_missing=False,
        )

    assert (
        target.read_text(
            encoding="utf-8"
        )
        == BEFORE
    )

    assert not list(
        (tmp_path / "src").glob(
            ".luna-stage-*"
        )
    )
