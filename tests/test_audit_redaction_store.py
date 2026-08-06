from __future__ import annotations

from pathlib import Path

import pytest

from luna.audit import ContentAddressedLogStore, LogArtifactError, SecretRedactor


def test_sensitive_output_is_redacted_before_persistent_write(tmp_path: Path) -> None:
    secret = "phase6-super-secret"
    store = ContentAddressedLogStore(
        tmp_path / "audit",
        SecretRedactor((secret,)),
    )

    captured = store.capture(
        stream_name="stdout",
        text=f"token={secret} Authorization: Bearer abcdef123456",
    )
    persisted = store.read_text(captured.ref)

    assert secret not in captured.text
    assert secret not in persisted
    assert "abcdef123456" not in persisted
    assert captured.redactions_applied
    assert captured.original_chars == len(
        f"token={secret} Authorization: Bearer abcdef123456"
    )


def test_content_addressed_artifact_detects_tampering(tmp_path: Path) -> None:
    store = ContentAddressedLogStore(tmp_path / "audit")
    captured = store.capture(stream_name="stdout", text="stable output")
    artifact = store.artifact_for(captured)
    path = store.root / artifact.relative_path
    path.write_text("tampered", encoding="utf-8")

    with pytest.raises(LogArtifactError, match="digest"):
        store.read_text(captured.ref)
