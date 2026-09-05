from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import luna.workspace.mutator as mutator_module
from luna.applied_changes.models import (
    AppliedChangeDegradationReason,
    AppliedChangeOperation,
    AppliedChangeState,
)
from luna.workspace import WorkspaceMutator


def _digest_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def _mutator(
    tmp_path: Path,
    *,
    task_id: UUID,
) -> WorkspaceMutator:
    return WorkspaceMutator(
        workspace_root=str(tmp_path),
        task_id=task_id,
        allowed_paths=("src", "new.txt"),
        protected_paths=(),
    )


def test_write_text_captures_bound_applied_change(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"

    before = b"before\n"
    after = b"after\n"

    target.write_bytes(before)

    task_id = uuid4()
    mutator = _mutator(
        tmp_path,
        task_id=task_id,
    )

    result = mutator.write_text(
        relative_path="src/module.py",
        content=after.decode("utf-8"),
        expected_sha256=_digest_bytes(
            before
        ),
        create_if_missing=False,
    )

    assert target.read_bytes() == after
    assert len(result.applied_changes) == 1

    candidate = result.applied_changes[0]

    assert candidate.task_id == task_id
    assert (
        candidate.operation
        is AppliedChangeOperation.WRITE_TEXT
    )
    assert (
        candidate.state
        is AppliedChangeState.COMPLETE
    )
    assert (
        candidate.before_digest
        == _digest_bytes(before)
    )
    assert (
        candidate.after_digest
        == _digest_bytes(after)
    )


def test_replace_text_captures_replace_operation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"

    before = b"name = 'Luna'\n"
    after = b"name = 'Sol'\n"

    target.write_bytes(before)

    task_id = uuid4()
    mutator = _mutator(
        tmp_path,
        task_id=task_id,
    )

    result = mutator.replace_text(
        relative_path="src/module.py",
        old_text="Luna",
        new_text="Sol",
        expected_sha256=_digest_bytes(
            before
        ),
        expected_occurrences=1,
    )

    assert target.read_bytes() == after

    candidate = result.applied_changes[0]

    assert (
        candidate.operation
        is AppliedChangeOperation.REPLACE_TEXT
    )
    assert (
        candidate.state
        is AppliedChangeState.COMPLETE
    )

    deleted = tuple(
        line
        for hunk in candidate.hunks
        for segment in hunk.segments
        if segment.kind.value == "DELETE"
        for line in segment.lines
    )

    inserted = tuple(
        line
        for hunk in candidate.hunks
        for segment in hunk.segments
        if segment.kind.value == "INSERT"
        for line in segment.lines
    )

    assert deleted == ("name = 'Luna'\n",)
    assert inserted == ("name = 'Sol'\n",)


def test_write_text_creation_captures_absent_before_state(
    tmp_path: Path,
) -> None:
    task_id = uuid4()
    mutator = _mutator(
        tmp_path,
        task_id=task_id,
    )

    result = mutator.write_text(
        relative_path="new.txt",
        content="created\n",
        expected_sha256=None,
        create_if_missing=True,
    )

    candidate = result.applied_changes[0]

    assert (
        candidate.operation
        is AppliedChangeOperation.WRITE_TEXT
    )
    assert candidate.before_existed is False
    assert candidate.before_digest is None
    assert candidate.before_size_bytes == 0
    assert (
        candidate.state
        is AppliedChangeState.COMPLETE
    )


def test_write_text_invalid_utf8_before_degrades_without_blocking_mutation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "binary.dat"

    before = b"\xff\xfe"
    after = b"valid\n"

    target.write_bytes(before)

    task_id = uuid4()
    mutator = _mutator(
        tmp_path,
        task_id=task_id,
    )

    result = mutator.write_text(
        relative_path="src/binary.dat",
        content=after.decode("utf-8"),
        expected_sha256=_digest_bytes(
            before
        ),
        create_if_missing=False,
    )

    assert target.read_bytes() == after

    candidate = result.applied_changes[0]

    assert (
        candidate.state
        is AppliedChangeState.DEGRADED
    )
    assert (
        candidate.degradation_reason
        is AppliedChangeDegradationReason
        .TEXT_ENCODING_UNSUPPORTED
    )
    assert candidate.hunks == ()


def test_write_text_projection_exception_is_fail_soft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"

    before = b"before\n"
    after = b"after\n"

    target.write_bytes(before)

    def fail_projection(
        **kwargs: object,
    ) -> object:
        del kwargs
        raise RuntimeError(
            "injected projection failure"
        )

    monkeypatch.setattr(
        mutator_module,
        "project_text_change_bytes",
        fail_projection,
    )

    task_id = uuid4()
    mutator = _mutator(
        tmp_path,
        task_id=task_id,
    )

    result = mutator.write_text(
        relative_path="src/module.py",
        content=after.decode("utf-8"),
        expected_sha256=_digest_bytes(
            before
        ),
        create_if_missing=False,
    )

    assert target.read_bytes() == after

    candidate = result.applied_changes[0]

    assert (
        candidate.state
        is AppliedChangeState.DEGRADED
    )
    assert (
        candidate.degradation_reason
        is AppliedChangeDegradationReason
        .PROJECTION_UNAVAILABLE
    )


def test_write_text_same_content_captures_no_change(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    content = b"same\n"

    target.write_bytes(content)

    mutator = _mutator(
        tmp_path,
        task_id=uuid4(),
    )

    result = mutator.write_text(
        relative_path="src/module.py",
        content=content.decode("utf-8"),
        expected_sha256=_digest_bytes(
            content
        ),
        create_if_missing=False,
    )

    assert target.read_bytes() == content

    candidate = result.applied_changes[0]

    assert (
        candidate.state
        is AppliedChangeState.NO_CHANGE
    )
    assert candidate.hunks == ()



def test_non_windows_write_uses_revalidated_before_and_verified_after(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"

    before = b"before\n"
    after = b"after\n"

    target.write_bytes(before)

    mutator = _mutator(
        tmp_path,
        task_id=uuid4(),
    )

    events: list[str] = []
    captured: dict[str, object] = {}

    original_verify = (
        mutator._verify_after_write
    )
    original_project = (
        mutator_module
        .project_text_change_bytes
    )

    def verify(
        path: Path,
        expected_digest: str,
    ) -> None:
        original_verify(
            path,
            expected_digest,
        )
        events.append("VERIFY")

    def project(
        **kwargs: object,
    ) -> object:
        assert events == ["VERIFY"]

        captured["before_content"] = (
            kwargs["before_content"]
        )
        captured["after_content"] = (
            kwargs["after_content"]
        )

        events.append("PROJECT")

        return original_project(
            **kwargs
        )

    monkeypatch.setattr(
        mutator_module,
        "os",
        SimpleNamespace(name="posix"),
    )
    monkeypatch.setattr(
        mutator,
        "_verify_after_write",
        verify,
    )
    monkeypatch.setattr(
        mutator_module,
        "project_text_change_bytes",
        project,
    )

    result = mutator.write_text(
        relative_path="src/module.py",
        content=after.decode("utf-8"),
        expected_sha256=_digest_bytes(
            before
        ),
        create_if_missing=False,
    )

    assert target.read_bytes() == after
    assert events == [
        "VERIFY",
        "PROJECT",
    ]

    assert (
        captured["before_content"]
        == before
    )
    assert (
        captured["after_content"]
        == after
    )

    assert (
        result.applied_changes[0].state
        is AppliedChangeState.COMPLETE
    )


def test_non_windows_replace_captures_replace_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"

    before = b"name = 'Luna'\n"
    after = b"name = 'Sol'\n"

    target.write_bytes(before)

    mutator = _mutator(
        tmp_path,
        task_id=uuid4(),
    )

    monkeypatch.setattr(
        mutator_module,
        "os",
        SimpleNamespace(name="posix"),
    )

    result = mutator.replace_text(
        relative_path="src/module.py",
        old_text="Luna",
        new_text="Sol",
        expected_sha256=_digest_bytes(
            before
        ),
        expected_occurrences=1,
    )

    assert target.read_bytes() == after

    candidate = result.applied_changes[0]

    assert (
        candidate.operation
        is AppliedChangeOperation.REPLACE_TEXT
    )
    assert (
        candidate.state
        is AppliedChangeState.COMPLETE
    )


def test_non_windows_invalid_utf8_before_degrades_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "binary.dat"

    before = b"\xff\xfe"
    after = b"valid\n"

    target.write_bytes(before)

    mutator = _mutator(
        tmp_path,
        task_id=uuid4(),
    )

    monkeypatch.setattr(
        mutator_module,
        "os",
        SimpleNamespace(name="posix"),
    )

    result = mutator.write_text(
        relative_path="src/binary.dat",
        content=after.decode("utf-8"),
        expected_sha256=_digest_bytes(
            before
        ),
        create_if_missing=False,
    )

    assert target.read_bytes() == after

    candidate = result.applied_changes[0]

    assert (
        candidate.state
        is AppliedChangeState.DEGRADED
    )
    assert (
        candidate.degradation_reason
        is AppliedChangeDegradationReason
        .TEXT_ENCODING_UNSUPPORTED
    )
    assert candidate.hunks == ()
