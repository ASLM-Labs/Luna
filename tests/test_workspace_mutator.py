from __future__ import annotations

from hashlib import sha256
from pathlib import Path

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
