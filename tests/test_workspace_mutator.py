from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import Event, Thread

import pytest

from luna.workspace import WorkspaceMutationError, WorkspaceMutator


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _mutator(tmp_path: Path, *, protected: tuple[str, ...] = ()) -> WorkspaceMutator:
    from uuid import uuid4

    return WorkspaceMutator(
        workspace_root=str(tmp_path),
        task_id=uuid4(),
        allowed_paths=("src", "new.txt"),
        protected_paths=protected,
    )


def test_create_is_snapshot_first_and_explicitly_reversible(tmp_path: Path) -> None:
    mutator = _mutator(tmp_path)
    result = mutator.write_text(
        relative_path="new.txt",
        content="hello",
        expected_sha256=None,
        create_if_missing=True,
    )

    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello"
    assert result.changes[0].created
    assert result.changes[0].after_digest == _digest("hello")

    rollback = mutator.rollback(result.snapshot.snapshot_id)
    assert rollback.verified
    assert not (tmp_path / "new.txt").exists()


def test_existing_write_requires_matching_sha256_precondition(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    target = source / "module.py"
    target.write_text("before", encoding="utf-8")
    mutator = _mutator(tmp_path)

    with pytest.raises(WorkspaceMutationError, match="requires expected_sha256"):
        mutator.write_text(
            relative_path="src/module.py",
            content="after",
            expected_sha256=None,
            create_if_missing=False,
        )

    with pytest.raises(WorkspaceMutationError, match="precondition"):
        mutator.write_text(
            relative_path="src/module.py",
            content="after",
            expected_sha256="0" * 64,
            create_if_missing=False,
        )

    assert target.read_text(encoding="utf-8") == "before"


def test_replace_requires_exact_occurrence_count(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    target = source / "module.py"
    original = "name = 'Luna'\nname = 'Luna'\n"
    target.write_bytes(original.encode("utf-8"))
    mutator = _mutator(tmp_path)

    with pytest.raises(WorkspaceMutationError, match="occurrence"):
        mutator.replace_text(
            relative_path="src/module.py",
            old_text="Luna",
            new_text="Sol",
            expected_sha256=_digest(original),
            expected_occurrences=1,
        )

    assert target.read_text(encoding="utf-8") == original

    result = mutator.replace_text(
        relative_path="src/module.py",
        old_text="Luna",
        new_text="Sol",
        expected_sha256=_digest(original),
        expected_occurrences=2,
    )
    assert target.read_text(encoding="utf-8").count("Sol") == 2
    assert result.changes[0].before_digest == _digest(original)


def test_protected_descendant_is_denied_before_snapshot(tmp_path: Path) -> None:
    protected_dir = tmp_path / "src" / "protected"
    protected_dir.mkdir(parents=True)
    target = protected_dir / "secret.txt"
    target.write_text("keep", encoding="utf-8")
    mutator = _mutator(tmp_path, protected=("src/protected",))

    with pytest.raises(WorkspaceMutationError, match="protected"):
        mutator.write_text(
            relative_path="src/protected/secret.txt",
            content="changed",
            expected_sha256=_digest("keep"),
            create_if_missing=False,
        )

    assert target.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / ".luna").exists()


def test_failed_post_write_verification_automatically_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    target = source / "module.py"
    target.write_text("stable", encoding="utf-8")
    mutator = _mutator(tmp_path)

    def fail_verification(path: Path, expected_digest: str) -> None:
        del path, expected_digest
        raise WorkspaceMutationError("injected verification failure")

    monkeypatch.setattr(mutator, "_verify_after_write", fail_verification)

    with pytest.raises(WorkspaceMutationError, match="rolled back") as exc_info:
        mutator.write_text(
            relative_path="src/module.py",
            content="unstable",
            expected_sha256=_digest("stable"),
            create_if_missing=False,
        )

    assert exc_info.value.rollback is not None
    assert exc_info.value.rollback.verified
    assert target.read_text(encoding="utf-8") == "stable"


def test_symlink_component_is_rejected_when_supported(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    source = tmp_path / "src"
    try:
        source.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    mutator = _mutator(tmp_path)

    with pytest.raises(WorkspaceMutationError):
        mutator.write_text(
            relative_path="src/escape.txt",
            content="blocked",
            expected_sha256=None,
            create_if_missing=True,
        )

    assert not (outside / "escape.txt").exists()


def test_same_process_luna_writers_cannot_both_publish_from_same_accepted_basis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    target = source / "module.py"
    target.write_text("A", encoding="utf-8")
    expected = _digest("A")

    first = _mutator(tmp_path)
    second = _mutator(tmp_path)

    first_paused = Event()
    release_first = Event()
    second_reached_snapshot = Event()

    first_create_snapshot = first.store.create_snapshot
    second_create_snapshot = second.store.create_snapshot

    def pause_first_snapshot(*, task_id, relative_paths):
        first_paused.set()
        assert release_first.wait(timeout=5)
        return first_create_snapshot(
            task_id=task_id,
            relative_paths=relative_paths,
        )

    def observe_second_snapshot(*, task_id, relative_paths):
        second_reached_snapshot.set()
        return second_create_snapshot(
            task_id=task_id,
            relative_paths=relative_paths,
        )

    monkeypatch.setattr(first.store, "create_snapshot", pause_first_snapshot)
    monkeypatch.setattr(second.store, "create_snapshot", observe_second_snapshot)

    successes: list[str] = []
    failures: list[Exception] = []

    def run(mutator: WorkspaceMutator, content: str) -> None:
        try:
            mutator.write_text(
                relative_path="src/module.py",
                content=content,
                expected_sha256=expected,
                create_if_missing=False,
            )
            successes.append(content)
        except Exception as exc:
            failures.append(exc)

    worker1 = Thread(target=run, args=(first, "first"))
    worker2 = Thread(target=run, args=(second, "second"))

    worker1.start()
    assert first_paused.wait(timeout=5)

    worker2.start()

    second_entered_unserialized_window = second_reached_snapshot.wait(timeout=2)

    if second_entered_unserialized_window:
        worker2.join(timeout=5)
        assert not worker2.is_alive()

    release_first.set()

    worker1.join(timeout=5)
    worker2.join(timeout=5)

    assert not worker1.is_alive()
    assert not worker2.is_alive()

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], WorkspaceMutationError)
    assert target.read_text(encoding="utf-8") == successes[0]


def test_snapshot_must_match_the_exact_basis_accepted_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    target = source / "module.py"
    target.write_text("A", encoding="utf-8")

    mutator = _mutator(tmp_path)
    original_create_snapshot = mutator.store.create_snapshot

    def mutate_before_snapshot(*, task_id, relative_paths):
        target.write_text("foreign-B", encoding="utf-8")
        return original_create_snapshot(
            task_id=task_id,
            relative_paths=relative_paths,
        )

    monkeypatch.setattr(
        mutator.store,
        "create_snapshot",
        mutate_before_snapshot,
    )

    with pytest.raises(WorkspaceMutationError):
        mutator.write_text(
            relative_path="src/module.py",
            content="Luna-C",
            expected_sha256=_digest("A"),
            create_if_missing=False,
        )

    assert target.read_text(encoding="utf-8") == "foreign-B"


def test_target_basis_is_revalidated_after_snapshot_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    target = source / "module.py"
    target.write_text("A", encoding="utf-8")

    mutator = _mutator(tmp_path)
    original_create_snapshot = mutator.store.create_snapshot

    def mutate_after_snapshot(*, task_id, relative_paths):
        snapshot = original_create_snapshot(
            task_id=task_id,
            relative_paths=relative_paths,
        )
        target.write_text("foreign-B", encoding="utf-8")
        return snapshot

    monkeypatch.setattr(
        mutator.store,
        "create_snapshot",
        mutate_after_snapshot,
    )

    with pytest.raises(WorkspaceMutationError):
        mutator.write_text(
            relative_path="src/module.py",
            content="Luna-C",
            expected_sha256=_digest("A"),
            create_if_missing=False,
        )

    assert target.read_text(encoding="utf-8") == "foreign-B"


def test_committed_change_records_after_mode_and_matches_snapshot_before_basis(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    target = source / "module.py"
    target.write_text("before", encoding="utf-8")

    mutator = _mutator(tmp_path)

    result = mutator.write_text(
        relative_path="src/module.py",
        content="after",
        expected_sha256=_digest("before"),
        create_if_missing=False,
    )

    snapshot_entry = result.snapshot.entries[0]
    change = result.changes[0]

    assert snapshot_entry.relative_path == change.relative_path
    assert snapshot_entry.existed is True
    assert snapshot_entry.content_digest == change.before_digest
    assert snapshot_entry.size_bytes == change.before_size_bytes

    assert change.after_mode is not None
    assert change.after_mode == (target.stat().st_mode & 0o7777)


def test_same_process_serializer_uses_platform_case_identity_for_target() -> None:
    import os
    from threading import Event, Thread

    import pytest

    from luna.workspace.coordination import WorkspaceTargetSerializer

    lower = "src/module.py"
    alias = "SRC/MODULE.PY"

    if os.path.normcase(lower) != os.path.normcase(alias):
        pytest.skip("platform treats these paths as distinct identities")

    root_digest = "w1-case-alias-regression"
    first = WorkspaceTargetSerializer(
        workspace_root_digest=root_digest,
    )
    second = WorkspaceTargetSerializer(
        workspace_root_digest=root_digest,
    )

    attempting = Event()
    entered = Event()

    def second_writer() -> None:
        attempting.set()
        with second.hold(alias):
            entered.set()

    worker = Thread(target=second_writer)

    with first.hold(lower):
        worker.start()

        assert attempting.wait(timeout=2)
        assert not entered.wait(timeout=2)

    assert entered.wait(timeout=2)

    worker.join(timeout=5)
    assert not worker.is_alive()


def test_same_process_serializer_releases_idle_registry_entry() -> None:
    import luna.workspace.coordination as coordination
    from luna.workspace.coordination import WorkspaceTargetSerializer

    before = len(coordination._TARGET_LOCKS)

    serializer = WorkspaceTargetSerializer(
        workspace_root_digest="w1-registry-cleanup-regression",
    )

    with serializer.hold("src/module.py"):
        assert len(coordination._TARGET_LOCKS) == before + 1

    assert len(coordination._TARGET_LOCKS) == before
