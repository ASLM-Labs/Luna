"""Content-addressed redacted log storage for large tool output."""

from __future__ import annotations

import os
import tempfile
from hashlib import sha256
from pathlib import Path

from luna.audit.models import CapturedOutput, LogArtifact
from luna.audit.redaction import SecretRedactor


class LogArtifactError(RuntimeError):
    """Raised when a log artifact is missing, unsafe, or fails digest verification."""


class ContentAddressedLogStore:
    """Store immutable UTF-8 logs under their SHA-256 digest."""

    def __init__(self, root: str | Path, redactor: SecretRedactor | None = None) -> None:
        self.root = Path(root).resolve()
        self.blob_root = self.root / "blobs"
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self._redactor = redactor or SecretRedactor()

    def capture(self, *, stream_name: str, text: str) -> CapturedOutput:
        result = self._redactor.redact_text(text)
        encoded = result.text.encode("utf-8")
        digest = sha256(encoded).hexdigest()
        path = self._path_for_digest(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != encoded:
            raise LogArtifactError("existing log artifact does not match its digest")
        if not path.exists():
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{digest}.",
                suffix=".tmp",
                dir=path.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        return CapturedOutput(
            stream_name=stream_name,
            text=result.text,
            digest=digest,
            ref=f"sha256:{digest}",
            original_chars=len(text),
            stored_chars=len(result.text),
            redactions_applied=result.redactions_applied,
        )

    def artifact_for(self, captured: CapturedOutput) -> LogArtifact:
        path = self._path_for_digest(captured.digest)
        if not path.is_file():
            raise LogArtifactError("captured output artifact is missing")
        encoded = path.read_bytes()
        if sha256(encoded).hexdigest() != captured.digest:
            raise LogArtifactError("captured output artifact digest mismatch")
        return LogArtifact(
            digest=captured.digest,
            relative_path=path.relative_to(self.root).as_posix(),
            byte_count=len(encoded),
            redactions_applied=captured.redactions_applied,
        )

    def read_text(self, digest_or_ref: str) -> str:
        digest = digest_or_ref.removeprefix("sha256:")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise LogArtifactError("invalid log artifact digest")
        path = self._path_for_digest(digest)
        if not path.is_file():
            raise LogArtifactError("log artifact is missing")
        encoded = path.read_bytes()
        if sha256(encoded).hexdigest() != digest:
            raise LogArtifactError("log artifact digest mismatch")
        return encoded.decode("utf-8")

    def _path_for_digest(self, digest: str) -> Path:
        path = (self.blob_root / digest[:2] / f"{digest}.log").resolve()
        if self.blob_root not in path.parents:
            raise LogArtifactError("log artifact path escaped the store")
        return path
