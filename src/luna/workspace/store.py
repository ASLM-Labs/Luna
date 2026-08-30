"""Persistent hash-verified snapshot storage for bounded workspace rollback."""

from __future__ import annotations

import os
import stat
import tempfile
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from luna.tools.paths import (
    WorkspacePathError,
    canonical_workspace_path,
    ensure_no_symlink_components,
    normalize_relative_path,
)
from luna.workspace.models import (
    RollbackResult,
    RollbackStatus,
    SafeUndoReceipt,
    SnapshotEntry,
    WindowsAfterStateToken,
    WorkspaceSnapshot,
)


class SnapshotStoreError(RuntimeError):
    """Raised when snapshot creation, integrity checks, or restore fails."""


def digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def atomic_write_bytes(path: Path, content: bytes, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".luna-write-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


class WorkspaceSnapshotStore:
    """Store snapshots below the runtime-owned `.luna/snapshots` directory."""

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        if not self.workspace_root.is_dir():
            raise SnapshotStoreError("workspace root must be an existing directory")
        runtime_root = self.workspace_root / ".luna"
        self.snapshot_root = runtime_root / "snapshots"
        if runtime_root.is_symlink() or self.snapshot_root.is_symlink():
            raise SnapshotStoreError("runtime snapshot directory cannot be a symlink")
        self.workspace_root_digest = sha256(
            os.path.normcase(str(self.workspace_root)).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _validate_target_path(relative_path: str) -> str:
        normalized = normalize_relative_path(relative_path)
        first = normalized.split("/", 1)[0].casefold()
        if first == ".luna":
            raise SnapshotStoreError("runtime-owned .luna paths cannot be task targets")
        return normalized

    def target_path(self, relative_path: str) -> Path:
        normalized = self._validate_target_path(relative_path)
        try:
            ensure_no_symlink_components(str(self.workspace_root), normalized)
            return canonical_workspace_path(str(self.workspace_root), normalized)
        except WorkspacePathError as exc:
            raise SnapshotStoreError(str(exc)) from exc

    def _snapshot_directory(self, snapshot_id: UUID) -> Path:
        directory = (self.snapshot_root / str(snapshot_id)).resolve()
        expected_parent = self.snapshot_root.resolve()
        if directory.parent != expected_parent:
            raise SnapshotStoreError("invalid snapshot identifier")
        return directory

    def _undo_receipt_path(
        self,
        snapshot_id: UUID,
    ) -> Path:
        return (
            self._snapshot_directory(snapshot_id)
            / "undo.json"
        )

    def _validate_undo_receipt_binding(
        self,
        *,
        receipt: SafeUndoReceipt,
        snapshot: WorkspaceSnapshot,
        task_id: UUID,
    ) -> None:
        if receipt.snapshot_id != snapshot.snapshot_id:
            raise SnapshotStoreError(
                "safe-undo receipt snapshot_id mismatch"
            )

        if (
            receipt.snapshot_digest
            != snapshot.snapshot_digest
        ):
            raise SnapshotStoreError(
                "safe-undo receipt snapshot digest mismatch"
            )

        if receipt.task_id != snapshot.task_id:
            raise SnapshotStoreError(
                "safe-undo receipt task binding mismatch"
            )

        if receipt.task_id != task_id:
            raise SnapshotStoreError(
                "safe-undo receipt task_id does not "
                "match requesting task"
            )

        if (
            receipt.workspace_root_digest
            != self.workspace_root_digest
        ):
            raise SnapshotStoreError(
                "safe-undo receipt belongs to "
                "a different workspace"
            )

        normalized = self._validate_target_path(
            receipt.relative_path
        )

        if normalized != receipt.relative_path:
            raise SnapshotStoreError(
                "safe-undo receipt path is not normalized"
            )

        if (
            len(snapshot.entries) != 1
            or snapshot.entries[0].relative_path
            != normalized
        ):
            raise SnapshotStoreError(
                "safe-undo receipt path does not "
                "match snapshot target"
            )

    def _persist_undo_receipt(
        self,
        *,
        receipt: SafeUndoReceipt,
    ) -> SafeUndoReceipt:
        path = self._undo_receipt_path(
            receipt.snapshot_id
        )

        if path.is_symlink():
            raise SnapshotStoreError(
                "safe-undo receipt cannot be a symlink"
            )

        try:
            atomic_write_bytes(
                path,
                (
                    receipt.to_json().encode("utf-8")
                    + b"\n"
                ),
                mode=0o600,
            )
        except Exception as exc:
            raise SnapshotStoreError(
                "safe-undo receipt persistence failed: "
                f"{exc}"
            ) from exc

        persisted = self.load_undo_receipt(
            receipt.snapshot_id,
            task_id=receipt.task_id,
        )

        if persisted != receipt:
            raise SnapshotStoreError(
                "persisted safe-undo receipt "
                "does not match requested state"
            )

        return persisted

    def prepare_undo_receipt(
        self,
        *,
        snapshot: WorkspaceSnapshot,
        relative_path: str,
        expected_after_sha256: str,
        expected_after_size_bytes: int,
    ) -> SafeUndoReceipt:
        persisted_snapshot = self.load_snapshot(
            snapshot.snapshot_id
        )

        if persisted_snapshot != snapshot:
            raise SnapshotStoreError(
                "safe-undo receipt requires the exact "
                "persisted snapshot"
            )

        normalized = self._validate_target_path(
            relative_path
        )

        if (
            len(snapshot.entries) != 1
            or snapshot.entries[0].relative_path
            != normalized
        ):
            raise SnapshotStoreError(
                "safe-undo receipt path does not "
                "match snapshot target"
            )

        path = self._undo_receipt_path(
            snapshot.snapshot_id
        )

        if path.exists() or path.is_symlink():
            raise SnapshotStoreError(
                "safe-undo receipt already exists"
            )

        try:
            receipt = SafeUndoReceipt.build_prepared(
                snapshot_id=snapshot.snapshot_id,
                snapshot_digest=(
                    snapshot.snapshot_digest
                ),
                task_id=snapshot.task_id,
                workspace_root_digest=(
                    self.workspace_root_digest
                ),
                relative_path=normalized,
                expected_after_sha256=(
                    expected_after_sha256
                ),
                expected_after_size_bytes=(
                    expected_after_size_bytes
                ),
            )
        except ValueError as exc:
            raise SnapshotStoreError(
                f"safe-undo receipt is invalid: {exc}"
            ) from exc

        self._validate_undo_receipt_binding(
            receipt=receipt,
            snapshot=snapshot,
            task_id=snapshot.task_id,
        )

        return self._persist_undo_receipt(
            receipt=receipt
        )

    def load_undo_receipt(
        self,
        snapshot_id: UUID,
        *,
        task_id: UUID,
    ) -> SafeUndoReceipt:
        path = self._undo_receipt_path(
            snapshot_id
        )

        if path.is_symlink() or not path.is_file():
            raise SnapshotStoreError(
                "safe-undo receipt does not exist "
                "as a regular file"
            )

        try:
            receipt = SafeUndoReceipt.from_json(
                path.read_bytes()
            )
        except Exception as exc:
            raise SnapshotStoreError(
                f"safe-undo receipt is invalid: {exc}"
            ) from exc

        snapshot = self.load_snapshot(
            snapshot_id
        )

        self._validate_undo_receipt_binding(
            receipt=receipt,
            snapshot=snapshot,
            task_id=task_id,
        )

        return receipt

    def commit_undo_receipt(
        self,
        *,
        snapshot_id: UUID,
        task_id: UUID,
        after_token: WindowsAfterStateToken,
    ) -> SafeUndoReceipt:
        receipt = self.load_undo_receipt(
            snapshot_id,
            task_id=task_id,
        )

        try:
            committed = (
                receipt.with_committed_after_state(
                    after_token
                )
            )
        except ValueError as exc:
            raise SnapshotStoreError(
                f"safe-undo receipt commit refused: {exc}"
            ) from exc

        return self._persist_undo_receipt(
            receipt=committed
        )

    def mark_undo_receipt_undone(
        self,
        *,
        snapshot_id: UUID,
        task_id: UUID,
    ) -> SafeUndoReceipt:
        receipt = self.load_undo_receipt(
            snapshot_id,
            task_id=task_id,
        )

        try:
            undone = receipt.with_undone_state()
        except ValueError as exc:
            raise SnapshotStoreError(
                "safe-undo receipt completion "
                f"refused: {exc}"
            ) from exc

        return self._persist_undo_receipt(
            receipt=undone
        )

    def _persist_snapshot(
        self,
        *,
        task_id: UUID,
        entries: tuple[SnapshotEntry, ...],
        blobs: dict[str, bytes],
    ) -> WorkspaceSnapshot:
        """Persist already-captured snapshot state without target path I/O."""

        for digest, content in blobs.items():
            if digest_bytes(content) != digest:
                raise SnapshotStoreError(
                    "captured snapshot blob digest does not match content"
                )

        for entry in entries:
            if not entry.existed:
                continue

            assert entry.content_digest is not None

            blob_content = blobs.get(
                entry.content_digest
            )

            if blob_content is None:
                raise SnapshotStoreError(
                    "existing captured snapshot entry lacks its content blob"
                )

            if len(blob_content) != entry.size_bytes:
                raise SnapshotStoreError(
                    "captured snapshot entry size does not match content"
                )

        snapshot = WorkspaceSnapshot.build(
            task_id=task_id,
            workspace_root_digest=self.workspace_root_digest,
            entries=entries,
        )

        directory = self._snapshot_directory(
            snapshot.snapshot_id
        )
        blobs_directory = directory / "blobs"

        try:
            blobs_directory.mkdir(
                parents=True,
                exist_ok=False,
            )

            for digest, content in blobs.items():
                atomic_write_bytes(
                    blobs_directory / digest,
                    content,
                    mode=0o600,
                )

            atomic_write_bytes(
                directory / "manifest.json",
                snapshot.to_json().encode("utf-8"),
                mode=0o600,
            )

        except Exception as exc:
            if directory.exists():
                import shutil

                shutil.rmtree(
                    directory,
                    ignore_errors=True,
                )

            raise SnapshotStoreError(
                f"snapshot persistence failed: {exc}"
            ) from exc

        return snapshot

    def _create_snapshot_from_captured_state(
        self,
        *,
        task_id: UUID,
        relative_path: str,
        existed: bool,
        content: bytes | None,
        mode: int | None,
    ) -> WorkspaceSnapshot:
        """Persist one authority-bound state without re-reading its path."""

        normalized = self._validate_target_path(
            relative_path
        )

        if existed:
            if content is None or mode is None:
                raise SnapshotStoreError(
                    "existing captured state requires content and mode"
                )

            digest = digest_bytes(content)

            entry = SnapshotEntry(
                relative_path=normalized,
                existed=True,
                content_digest=digest,
                size_bytes=len(content),
                mode=mode,
            )

            return self._persist_snapshot(
                task_id=task_id,
                entries=(entry,),
                blobs={digest: content},
            )

        if content is not None or mode is not None:
            raise SnapshotStoreError(
                "absent captured state cannot carry content or mode"
            )

        entry = SnapshotEntry(
            relative_path=normalized,
            existed=False,
        )

        return self._persist_snapshot(
            task_id=task_id,
            entries=(entry,),
            blobs={},
        )

    def create_snapshot(
        self,
        *,
        task_id: UUID,
        relative_paths: tuple[str, ...],
    ) -> WorkspaceSnapshot:
        normalized_paths = tuple(
            sorted({self._validate_target_path(path) for path in relative_paths})
        )
        if not normalized_paths:
            raise SnapshotStoreError("snapshot requires at least one target path")

        entries: list[SnapshotEntry] = []
        blobs: dict[str, bytes] = {}
        for relative_path in normalized_paths:
            target = self.target_path(relative_path)
            if target.exists():
                if target.is_symlink() or not target.is_file():
                    raise SnapshotStoreError("snapshot targets must be regular non-symlink files")
                content = target.read_bytes()
                digest = digest_bytes(content)
                blobs.setdefault(digest, content)
                entries.append(
                    SnapshotEntry(
                        relative_path=relative_path,
                        existed=True,
                        content_digest=digest,
                        size_bytes=len(content),
                        mode=stat.S_IMODE(target.stat().st_mode),
                    )
                )
            else:
                entries.append(
                    SnapshotEntry(
                        relative_path=relative_path,
                        existed=False,
                    )
                )

        return self._persist_snapshot(
            task_id=task_id,
            entries=tuple(entries),
            blobs=blobs,
        )

    def load_snapshot(self, snapshot_id: UUID) -> WorkspaceSnapshot:
        manifest_path = self._snapshot_directory(snapshot_id) / "manifest.json"
        if not manifest_path.is_file():
            raise SnapshotStoreError("snapshot manifest does not exist")
        try:
            snapshot = WorkspaceSnapshot.from_json(manifest_path.read_bytes())
        except Exception as exc:
            raise SnapshotStoreError(f"snapshot manifest is invalid: {exc}") from exc
        if snapshot.snapshot_id != snapshot_id:
            raise SnapshotStoreError("snapshot manifest identifier mismatch")
        if snapshot.workspace_root_digest != self.workspace_root_digest:
            raise SnapshotStoreError("snapshot belongs to a different workspace")
        return snapshot

    def _blob(self, snapshot_id: UUID, digest: str) -> bytes:
        path = self._snapshot_directory(snapshot_id) / "blobs" / digest
        if not path.is_file():
            raise SnapshotStoreError("snapshot content blob is missing")
        content = path.read_bytes()
        if digest_bytes(content) != digest:
            raise SnapshotStoreError("snapshot content blob failed SHA-256 verification")
        return content

    def restore(self, *, snapshot_id: UUID, task_id: UUID) -> RollbackResult:
        snapshot = self.load_snapshot(snapshot_id)
        if snapshot.task_id != task_id:
            raise SnapshotStoreError("snapshot task_id does not match rollback task")

        restored: list[str] = []
        removed: list[str] = []
        for entry in snapshot.entries:
            target = self.target_path(entry.relative_path)
            if entry.existed:
                assert entry.content_digest is not None
                content = self._blob(snapshot_id, entry.content_digest)
                current_digest = digest_file(target) if target.is_file() else None
                if current_digest != entry.content_digest:
                    atomic_write_bytes(target, content, mode=entry.mode)
                    restored.append(entry.relative_path)
                if not target.is_file() or digest_file(target) != entry.content_digest:
                    raise SnapshotStoreError("restored file failed digest verification")
            elif target.exists():
                if target.is_symlink() or not target.is_file():
                    raise SnapshotStoreError("rollback refuses to remove non-regular target")
                target.unlink()
                removed.append(entry.relative_path)
                if target.exists():
                    raise SnapshotStoreError("created file still exists after rollback")

        status = (
            RollbackStatus.RESTORED
            if restored or removed
            else RollbackStatus.NO_CHANGES
        )
        return RollbackResult(
            snapshot_id=snapshot_id,
            task_id=task_id,
            status=status,
            restored_files=tuple(restored),
            removed_files=tuple(removed),
            verified=True,
        )
