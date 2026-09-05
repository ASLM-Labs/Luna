from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from luna.workspace import WorkspaceMutationError, WorkspaceMutator
from luna.workspace.models import (
    SafeUndoReceiptState,
    WorkspaceExecutionBinding,
    WorkspaceReconciliationTargetState,
)
from luna.workspace.store import SnapshotStoreError
from luna.workspace.windows_publication import (
    BoundPublicationParent,
    PublicationState,
)

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


def _runtime_bound_mutator(
    tmp_path: Path,
) -> tuple[WorkspaceMutator, UUID, UUID]:
    request_id = uuid4()
    runtime_receipt_id = uuid4()

    return (
        WorkspaceMutator(
            workspace_root=str(tmp_path),
            task_id=uuid4(),
            allowed_paths=(
                "src",
                "new.txt",
            ),
            protected_paths=(),
            request_id=request_id,
            runtime_receipt_id=(
                runtime_receipt_id
            ),
        ),
        request_id,
        runtime_receipt_id,
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
def test_runtime_bound_receipt_is_publication_prepared_before_native_publish(
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

    (
        mutator,
        request_id,
        runtime_receipt_id,
    ) = _runtime_bound_mutator(
        tmp_path
    )

    original_prepare = (
        mutator.store.prepare_undo_receipt
    )
    original_publication_prepared = (
        mutator.store
        .mark_undo_receipt_publication_prepared
    )
    original_verify = (
        mutator._verify_bound_publication
    )
    original_commit = (
        mutator.store.commit_undo_receipt
    )

    events: list[str] = []

    def assert_target_before() -> None:
        if existed:
            assert (
                target.read_text(
                    encoding="utf-8"
                )
                == BEFORE
            )
        else:
            assert not target.exists()

    def prepare(
        *,
        snapshot,
        relative_path,
        expected_after_sha256,
        expected_after_size_bytes,
        execution_binding,
    ):
        assert events == []
        assert_target_before()

        assert (
            execution_binding
            == WorkspaceExecutionBinding(
                request_id=request_id,
                runtime_receipt_id=(
                    runtime_receipt_id
                ),
            )
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
            execution_binding=execution_binding,
        )

        assert receipt.receipt_version == 2
        assert (
            receipt.state
            is SafeUndoReceiptState.PREPARED
        )

        events.append(
            "PREPARED"
        )

        return receipt

    def publication_prepared(
        *,
        snapshot_id,
        task_id,
        prepared_publication_identity,
    ):
        assert events == [
            "PREPARED"
        ]

        # This is the critical ordering assertion:
        # durable publication identity is persisted while
        # the target namespace still shows BEFORE / ABSENT.
        assert_target_before()

        receipt = (
            original_publication_prepared(
                snapshot_id=snapshot_id,
                task_id=task_id,
                prepared_publication_identity=(
                    prepared_publication_identity
                ),
            )
        )

        assert (
            receipt.state
            is SafeUndoReceiptState.PUBLICATION_PREPARED
        )
        assert (
            receipt.prepared_publication_identity
            == prepared_publication_identity
        )

        events.append(
            "PUBLICATION_PREPARED"
        )

        return receipt

    def verify(
        *,
        observation,
        expected_content,
        source,
    ):
        assert events == [
            "PREPARED",
            "PUBLICATION_PREPARED",
        ]

        # The published object is still held by Luna's bound
        # stage handle here. On Windows, a pathname reopen may
        # legitimately be denied by the active sharing contract.
        # Use the already-bound post-publication observation.
        assert observation.existed
        assert (
            observation.content
            == AFTER.encode("utf-8")
        )

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
            "PUBLICATION_PREPARED",
            "VERIFIED",
        ]

        durable = (
            mutator.store.load_undo_receipt(
                snapshot_id,
                task_id=task_id,
            )
        )

        assert (
            durable.state
            is SafeUndoReceiptState.PUBLICATION_PREPARED
        )
        assert (
            durable.execution_binding
            == WorkspaceExecutionBinding(
                request_id=request_id,
                runtime_receipt_id=(
                    runtime_receipt_id
                ),
            )
        )
        assert (
            durable.prepared_publication_identity
            is not None
        )
        assert (
            durable.prepared_publication_identity
            .matches_after_state_token(
                after_token
            )
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
        mutator.store,
        "mark_undo_receipt_publication_prepared",
        publication_prepared,
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
        create_if_missing=not existed,
    )

    assert events == [
        "PREPARED",
        "PUBLICATION_PREPARED",
        "VERIFIED",
        "COMMIT",
    ]

    receipt = (
        mutator.store.load_undo_receipt(
            result.snapshot.snapshot_id,
            task_id=mutator.task_id,
        )
    )

    assert receipt.receipt_version == 2
    assert (
        receipt.state
        is SafeUndoReceiptState.COMMITTED
    )
    assert (
        receipt.execution_binding
        == WorkspaceExecutionBinding(
            request_id=request_id,
            runtime_receipt_id=(
                runtime_receipt_id
            ),
        )
    )
    assert (
        receipt.prepared_publication_identity
        is not None
    )
    assert receipt.after_token is not None
    assert (
        receipt.prepared_publication_identity
        .matches_after_state_token(
            receipt.after_token
        )
    )


@pytest.mark.parametrize(
    "existed",
    [False, True],
)
def test_runtime_bound_commit_failure_preserves_publication_prepared_receipt(
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

    (
        mutator,
        request_id,
        runtime_receipt_id,
    ) = _runtime_bound_mutator(
        tmp_path
    )

    original_publication_prepared = (
        mutator.store
        .mark_undo_receipt_publication_prepared
    )

    snapshot_ids: list[UUID] = []

    def capture_publication_prepared(
        *,
        snapshot_id,
        task_id,
        prepared_publication_identity,
    ):
        receipt = (
            original_publication_prepared(
                snapshot_id=snapshot_id,
                task_id=task_id,
                prepared_publication_identity=(
                    prepared_publication_identity
                ),
            )
        )

        snapshot_ids.append(
            snapshot_id
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
            "forced v2 receipt commit failure"
        )

    monkeypatch.setattr(
        mutator.store,
        "mark_undo_receipt_publication_prepared",
        capture_publication_prepared,
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
    assert exc_info.value.rollback.verified
    assert len(snapshot_ids) == 1

    receipt = (
        mutator.store.load_undo_receipt(
            snapshot_ids[0],
            task_id=mutator.task_id,
        )
    )

    assert receipt.receipt_version == 2
    assert (
        receipt.state
        is SafeUndoReceiptState.PUBLICATION_PREPARED
    )
    assert (
        receipt.execution_binding
        == WorkspaceExecutionBinding(
            request_id=request_id,
            runtime_receipt_id=(
                runtime_receipt_id
            ),
        )
    )
    assert (
        receipt.prepared_publication_identity
        is not None
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


def test_cold_reconciliation_reports_no_bound_receipt_without_creating_state(
    tmp_path: Path,
) -> None:
    (
        mutator,
        request_id,
        runtime_receipt_id,
    ) = _runtime_bound_mutator(
        tmp_path
    )

    assert not mutator.store.snapshot_root.exists()

    result = (
        mutator.store
        .reconcile_execution_undo_receipt(
            task_id=mutator.task_id,
            request_id=request_id,
            runtime_receipt_id=(
                runtime_receipt_id
            ),
        )
    )

    assert (
        result.target_state
        is WorkspaceReconciliationTargetState.NO_BOUND_RECEIPT
    )
    assert result.receipt_state is None
    assert result.snapshot_id is None
    assert result.observed_after_token is None
    assert not mutator.store.snapshot_root.exists()


@pytest.mark.parametrize(
    "existed",
    [False, True],
)
def test_cold_reconciliation_prepared_receipt_matches_before_without_mutation(
    tmp_path: Path,
    existed: bool,
) -> None:
    relative_path, target, _ = _target_case(
        tmp_path,
        existed=existed,
    )

    (
        mutator,
        request_id,
        runtime_receipt_id,
    ) = _runtime_bound_mutator(
        tmp_path
    )

    snapshot = mutator.store.create_snapshot(
        task_id=mutator.task_id,
        relative_paths=(relative_path,),
    )

    binding = WorkspaceExecutionBinding(
        request_id=request_id,
        runtime_receipt_id=(
            runtime_receipt_id
        ),
    )

    receipt = mutator.store.prepare_undo_receipt(
        snapshot=snapshot,
        relative_path=relative_path,
        expected_after_sha256=_digest(AFTER),
        expected_after_size_bytes=(
            len(AFTER.encode("utf-8"))
        ),
        execution_binding=binding,
    )

    receipt_path = (
        mutator.store._undo_receipt_path(
            snapshot.snapshot_id
        )
    )

    durable_before = receipt_path.read_bytes()

    target_before = (
        target.read_bytes()
        if target.exists()
        else None
    )

    result = (
        mutator.store
        .reconcile_execution_undo_receipt(
            task_id=mutator.task_id,
            request_id=request_id,
            runtime_receipt_id=(
                runtime_receipt_id
            ),
        )
    )

    assert receipt.receipt_version == 2
    assert (
        result.receipt_state
        is SafeUndoReceiptState.PREPARED
    )
    assert (
        result.target_state
        is WorkspaceReconciliationTargetState.BEFORE_MATCH
    )

    assert receipt_path.read_bytes() == durable_before

    assert (
        target.read_bytes()
        if target.exists()
        else None
    ) == target_before


@pytest.mark.parametrize(
    "existed",
    [False, True],
)
def test_cold_reconciliation_publication_prepared_after_native_publish_matches_after(
    tmp_path: Path,
    existed: bool,
) -> None:
    relative_path, target, _ = _target_case(
        tmp_path,
        existed=existed,
    )

    (
        mutator,
        request_id,
        runtime_receipt_id,
    ) = _runtime_bound_mutator(
        tmp_path
    )

    snapshot = mutator.store.create_snapshot(
        task_id=mutator.task_id,
        relative_paths=(relative_path,),
    )

    binding = WorkspaceExecutionBinding(
        request_id=request_id,
        runtime_receipt_id=(
            runtime_receipt_id
        ),
    )

    mutator.store.prepare_undo_receipt(
        snapshot=snapshot,
        relative_path=relative_path,
        expected_after_sha256=_digest(AFTER),
        expected_after_size_bytes=(
            len(AFTER.encode("utf-8"))
        ),
        execution_binding=binding,
    )

    with BoundPublicationParent.bind(
        str(tmp_path),
        relative_path,
    ) as authority:
        before = authority.observe_target()

        stage = authority.create_stage(
            source=(
                before
                if before.existed
                else None
            )
        )

        try:
            stage.write_bytes(
                AFTER.encode("utf-8")
            )

            prepared_identity = (
                stage.prepare_for_publication()
            )

            prepared_receipt = (
                mutator.store
                .mark_undo_receipt_publication_prepared(
                    snapshot_id=(
                        snapshot.snapshot_id
                    ),
                    task_id=mutator.task_id,
                    prepared_publication_identity=(
                        prepared_identity
                    ),
                )
            )

            publication = stage.publish(
                authority.leaf_name,
                replace=existed,
            )

            assert (
                publication.state
                is PublicationState.PUBLISHED
            )

        finally:
            stage.close()

    assert (
        prepared_receipt.state
        is SafeUndoReceiptState.PUBLICATION_PREPARED
    )

    receipt_path = (
        mutator.store._undo_receipt_path(
            snapshot.snapshot_id
        )
    )

    durable_before = receipt_path.read_bytes()

    result = (
        mutator.store
        .reconcile_execution_undo_receipt(
            task_id=mutator.task_id,
            request_id=request_id,
            runtime_receipt_id=(
                runtime_receipt_id
            ),
        )
    )

    assert (
        result.receipt_state
        is SafeUndoReceiptState.PUBLICATION_PREPARED
    )
    assert (
        result.target_state
        is WorkspaceReconciliationTargetState.AFTER_MATCH
    )
    assert result.observed_after_token is not None
    assert (
        prepared_identity
        .matches_after_state_token(
            result.observed_after_token
        )
    )

    assert receipt_path.read_bytes() == durable_before
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
def test_cold_reconciliation_committed_after_then_foreign_change_is_diverged(
    tmp_path: Path,
    existed: bool,
) -> None:
    relative_path, target, expected = (
        _target_case(
            tmp_path,
            existed=existed,
        )
    )

    (
        mutator,
        request_id,
        runtime_receipt_id,
    ) = _runtime_bound_mutator(
        tmp_path
    )

    mutation = mutator.write_text(
        relative_path=relative_path,
        content=AFTER,
        expected_sha256=expected,
        create_if_missing=not existed,
    )

    committed = (
        mutator.store
        .reconcile_execution_undo_receipt(
            task_id=mutator.task_id,
            request_id=request_id,
            runtime_receipt_id=(
                runtime_receipt_id
            ),
        )
    )

    assert (
        committed.receipt_state
        is SafeUndoReceiptState.COMMITTED
    )
    assert (
        committed.target_state
        is WorkspaceReconciliationTargetState.AFTER_MATCH
    )
    assert committed.observed_after_token is not None

    receipt_path = (
        mutator.store._undo_receipt_path(
            mutation.snapshot.snapshot_id
        )
    )

    durable_before = receipt_path.read_bytes()

    target.write_text(
        "foreign",
        encoding="utf-8",
    )

    diverged = (
        mutator.store
        .reconcile_execution_undo_receipt(
            task_id=mutator.task_id,
            request_id=request_id,
            runtime_receipt_id=(
                runtime_receipt_id
            ),
        )
    )

    assert (
        diverged.receipt_state
        is SafeUndoReceiptState.COMMITTED
    )
    assert (
        diverged.target_state
        is WorkspaceReconciliationTargetState.DIVERGED
    )

    assert receipt_path.read_bytes() == durable_before
    assert (
        target.read_text(
            encoding="utf-8"
        )
        == "foreign"
    )


def test_cold_reconciliation_duplicate_exact_execution_binding_fails_closed(
    tmp_path: Path,
) -> None:
    (
        mutator,
        request_id,
        runtime_receipt_id,
    ) = _runtime_bound_mutator(
        tmp_path
    )

    binding = WorkspaceExecutionBinding(
        request_id=request_id,
        runtime_receipt_id=(
            runtime_receipt_id
        ),
    )

    for relative_path in (
        "duplicate-a.txt",
        "duplicate-b.txt",
    ):
        snapshot = (
            mutator.store.create_snapshot(
                task_id=mutator.task_id,
                relative_paths=(
                    relative_path,
                ),
            )
        )

        mutator.store.prepare_undo_receipt(
            snapshot=snapshot,
            relative_path=relative_path,
            expected_after_sha256=(
                _digest(AFTER)
            ),
            expected_after_size_bytes=(
                len(AFTER.encode("utf-8"))
            ),
            execution_binding=binding,
        )

    with pytest.raises(
        SnapshotStoreError,
        match="exact execution binding",
    ):
        mutator.store.reconcile_execution_undo_receipt(
            task_id=mutator.task_id,
            request_id=request_id,
            runtime_receipt_id=(
                runtime_receipt_id
            ),
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
