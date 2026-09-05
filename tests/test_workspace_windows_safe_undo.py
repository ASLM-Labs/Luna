from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import luna.workspace.windows_publication as wp
from luna.workspace.models import WindowsAfterStateToken

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows conditional safe-undo primitive suite",
)


AFTER = b"LUNA-AFTER"
BEFORE = b"BEFORE"


def _publish_after(
    workspace: Path,
    relative_path: str,
    *,
    existed: bool,
) -> WindowsAfterStateToken:
    with wp.BoundPublicationParent.bind(
        str(workspace),
        relative_path,
    ) as authority:
        before = authority.observe_target()

        assert before.existed is existed

        with authority.create_stage(
            source=before if existed else None,
        ) as stage:
            stage.write_bytes(AFTER)

            result = stage.publish(
                authority.leaf_name,
                replace=existed,
            )

            assert (
                result.state
                is wp.PublicationState.PUBLISHED
            )

            published = (
                stage.observe_published_with_token()
            )

            assert published.observation.content == AFTER
            assert published.token.content_sha256 == (
                wp.sha256(AFTER).hexdigest()
            )
            assert published.token.size_bytes == len(AFTER)
            assert len(published.token.file_id) == 32

            return published.token


def test_fresh_existing_fence_matches_durable_published_token_and_restores_same_object(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    target.write_bytes(BEFORE)

    token = _publish_after(
        tmp_path,
        "src/module.py",
        existed=True,
    )

    replacement = source / "replacement.py"
    replacement.write_bytes(AFTER)

    renamed = source / "renamed.py"

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/module.py",
    ) as authority, authority.fence_existing_restore(
        token
    ) as fenced:
        assert (
            fenced.verify_expected().token
            == token
        )

        with pytest.raises(OSError):
            target.write_bytes(
                b"FOREIGN-WRITE"
            )

        with pytest.raises(OSError):
            os.replace(
                replacement,
                target,
            )

        with pytest.raises(OSError):
            target.rename(
                renamed
            )

        restored = (
            fenced.restore_existing_content(
                BEFORE,
                mode=token.mode,
            )
        )

        assert (
            restored.observation.content
            == BEFORE
        )
        assert (
            restored.token.file_id
            == token.file_id
        )
        assert (
            restored.token.volume_serial_number
            == token.volume_serial_number
        )
        assert (
            restored.token.creation_time
            == token.creation_time
        )
        assert (
            restored.token.dacl_sha256
            == token.dacl_sha256
        )
        assert (
            restored.token.dacl_protected
            is token.dacl_protected
        )

    assert target.read_bytes() == BEFORE
    assert replacement.read_bytes() == AFTER
    assert not renamed.exists()


def test_fresh_created_fence_deletes_exact_object_and_preserves_foreign_candidates(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "new.txt"

    token = _publish_after(
        tmp_path,
        "src/new.txt",
        existed=False,
    )

    replacement = source / "replacement.txt"
    replacement.write_bytes(AFTER)

    renamed = source / "renamed.txt"

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/new.txt",
    ) as authority, authority.fence_created_delete(
        token
    ) as fenced:
        assert (
            fenced.verify_expected().token
            == token
        )

        with pytest.raises(OSError):
            target.write_bytes(
                b"FOREIGN-WRITE"
            )

        with pytest.raises(OSError):
            os.replace(
                replacement,
                target,
            )

        with pytest.raises(OSError):
            target.rename(
                renamed
            )

        absent = (
            fenced.delete_created_target()
        )

        assert not absent.existed

    assert not target.exists()
    assert replacement.read_bytes() == AFTER
    assert not renamed.exists()


def test_same_object_same_bytes_rewrite_invalidates_expected_after_token(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    target.write_bytes(BEFORE)

    token = _publish_after(
        tmp_path,
        "src/module.py",
        existed=True,
    )

    time.sleep(0.05)
    target.write_bytes(AFTER)

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/module.py",
    ) as authority, pytest.raises(
        wp.WindowsPublicationError,
        match="does not match committed after-state token",
    ):
        authority.fence_existing_restore(
            token
        )

    assert target.read_bytes() == AFTER


def test_same_bytes_replacement_invalidates_expected_after_token(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    target.write_bytes(BEFORE)

    token = _publish_after(
        tmp_path,
        "src/module.py",
        existed=True,
    )

    replacement = source / "foreign.py"
    replacement.write_bytes(AFTER)

    os.replace(
        replacement,
        target,
    )

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/module.py",
    ) as authority, pytest.raises(
        wp.WindowsPublicationError,
        match="does not match committed after-state token",
    ):
        authority.fence_existing_restore(
            token
        )

    assert target.read_bytes() == AFTER

def test_existing_restore_failure_before_write_preserves_exact_after_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    target.write_bytes(BEFORE)

    token = _publish_after(
        tmp_path,
        "src/module.py",
        existed=True,
    )

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/module.py",
    ) as authority, authority.fence_existing_restore(
        token
    ) as fenced:

        def fail_without_write(
            handle: int,
            content: bytes,
        ) -> None:
            del handle, content

            raise wp.WindowsPublicationError(
                "forced pre-write inverse failure"
            )

        monkeypatch.setattr(
            wp,
            "_replace_all",
            fail_without_write,
        )

        with pytest.raises(
            wp.WindowsPublicationError,
            match="failed before target state changed",
        ):
            fenced.restore_existing_content(
                BEFORE,
                mode=token.mode,
            )

        assert (
            fenced.verify_expected().token
            == token
        )

    assert target.read_bytes() == AFTER


def test_existing_restore_partial_failure_recovers_after_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    target = source / "module.py"
    target.write_bytes(BEFORE)

    token = _publish_after(
        tmp_path,
        "src/module.py",
        existed=True,
    )

    original_replace = wp._replace_all
    calls = 0

    def fail_after_partial_write(
        handle: int,
        content: bytes,
    ) -> None:
        nonlocal calls

        calls += 1

        if calls == 1:
            original_replace(
                handle,
                b"PARTIAL-INVERSE",
            )

            time.sleep(0.05)

            raise wp.WindowsPublicationError(
                "forced partial inverse failure"
            )

        original_replace(
            handle,
            content,
        )

    monkeypatch.setattr(
        wp,
        "_replace_all",
        fail_after_partial_write,
    )

    with wp.BoundPublicationParent.bind(
        str(tmp_path),
        "src/module.py",
    ) as authority, authority.fence_existing_restore(
        token
    ) as fenced:
        with pytest.raises(
            wp.WindowsPublicationError,
            match="accepted after-state content was recovered",
        ):
            fenced.restore_existing_content(
                BEFORE,
                mode=token.mode,
            )

        assert calls == 2

        with pytest.raises(
            wp.WindowsPublicationError,
            match="does not match committed after-state token",
        ):
            fenced.verify_expected()

    assert target.read_bytes() == AFTER
