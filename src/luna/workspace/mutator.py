"""Atomic scoped text mutations with preconditions and automatic rollback."""

from __future__ import annotations

import stat
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from luna.tools.paths import path_is_allowed
from luna.workspace.models import (
    FileChange,
    MutationStatus,
    RollbackResult,
    WorkspaceMutationResult,
)
from luna.workspace.store import (
    SnapshotStoreError,
    WorkspaceSnapshotStore,
    atomic_write_bytes,
    digest_file,
)


class WorkspaceMutationError(RuntimeError):
    """Mutation failure carrying rollback evidence when a write had begun."""

    def __init__(
        self,
        message: str,
        *,
        rollback: RollbackResult | None = None,
    ) -> None:
        super().__init__(message)
        self.rollback = rollback


class WorkspaceMutator:
    """Perform minimal UTF-8 text changes inside an explicit TaskScope."""

    def __init__(
        self,
        *,
        workspace_root: str,
        task_id: UUID,
        allowed_paths: tuple[str, ...],
        protected_paths: tuple[str, ...],
    ) -> None:
        self.task_id = task_id
        self.allowed_paths = allowed_paths
        self.protected_paths = protected_paths
        self.store = WorkspaceSnapshotStore(workspace_root)

    def _target(self, relative_path: str) -> tuple[str, Path]:
        normalized = self.store._validate_target_path(relative_path)
        if not path_is_allowed(normalized, self.allowed_paths):
            raise WorkspaceMutationError("target is outside allowed_paths")
        if self.protected_paths and path_is_allowed(normalized, self.protected_paths):
            raise WorkspaceMutationError("target is protected by task scope")
        try:
            target = self.store.target_path(normalized)
        except SnapshotStoreError as exc:
            raise WorkspaceMutationError(str(exc)) from exc
        return normalized, target

    @staticmethod
    def _verify_after_write(path: Path, expected_digest: str) -> None:
        if not path.is_file() or digest_file(path) != expected_digest:
            raise WorkspaceMutationError("post-write digest verification failed")

    def _commit_text(
        self,
        *,
        relative_path: str,
        target: Path,
        before_digest: str | None,
        before_size: int,
        before_mode: int | None,
        content: str,
    ) -> WorkspaceMutationResult:
        snapshot = self.store.create_snapshot(
            task_id=self.task_id,
            relative_paths=(relative_path,),
        )
        encoded = content.encode("utf-8")
        after_digest = sha256(encoded).hexdigest()
        try:
            atomic_write_bytes(target, encoded, mode=before_mode)
            self._verify_after_write(target, after_digest)
        except Exception as exc:
            rollback: RollbackResult | None = None
            try:
                rollback = self.store.restore(
                    snapshot_id=snapshot.snapshot_id,
                    task_id=self.task_id,
                )
            except Exception as rollback_exc:
                raise WorkspaceMutationError(
                    f"mutation failed and rollback failed: {rollback_exc}",
                ) from exc
            raise WorkspaceMutationError(
                f"mutation failed and was rolled back: {exc}",
                rollback=rollback,
            ) from exc

        change = FileChange(
            relative_path=relative_path,
            before_digest=before_digest,
            after_digest=after_digest,
            before_size_bytes=before_size,
            after_size_bytes=len(encoded),
            created=before_digest is None,
        )
        return WorkspaceMutationResult(
            task_id=self.task_id,
            snapshot=snapshot,
            status=MutationStatus.COMMITTED,
            changes=(change,),
        )

    def write_text(
        self,
        *,
        relative_path: str,
        content: str,
        expected_sha256: str | None,
        create_if_missing: bool,
    ) -> WorkspaceMutationResult:
        normalized, target = self._target(relative_path)
        before_digest: str | None = None
        before_size = 0
        before_mode: int | None = None
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise WorkspaceMutationError("existing target must be a regular file")
            before_digest = digest_file(target)
            before_size = target.stat().st_size
            before_mode = stat.S_IMODE(target.stat().st_mode)
            if expected_sha256 is None:
                raise WorkspaceMutationError("existing file write requires expected_sha256")
            if before_digest != expected_sha256:
                raise WorkspaceMutationError("existing file digest does not match precondition")
        else:
            if not create_if_missing:
                raise WorkspaceMutationError("target is missing and creation was not approved")
            if expected_sha256 is not None:
                raise WorkspaceMutationError("new file creation cannot carry expected_sha256")

        return self._commit_text(
            relative_path=normalized,
            target=target,
            before_digest=before_digest,
            before_size=before_size,
            before_mode=before_mode,
            content=content,
        )

    def replace_text(
        self,
        *,
        relative_path: str,
        old_text: str,
        new_text: str,
        expected_sha256: str,
        expected_occurrences: int,
    ) -> WorkspaceMutationResult:
        normalized, target = self._target(relative_path)
        if not target.is_file() or target.is_symlink():
            raise WorkspaceMutationError("replace target must be an existing regular file")
        before_digest = digest_file(target)
        if before_digest != expected_sha256:
            raise WorkspaceMutationError("replace target digest does not match precondition")
        try:
            original = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceMutationError("replace target is not valid UTF-8") from exc
        actual_occurrences = original.count(old_text)
        if actual_occurrences != expected_occurrences:
            raise WorkspaceMutationError(
                "replace occurrence count does not match explicit expectation"
            )
        updated = original.replace(old_text, new_text)
        if updated == original:
            raise WorkspaceMutationError("replace operation would produce no change")
        return self._commit_text(
            relative_path=normalized,
            target=target,
            before_digest=before_digest,
            before_size=target.stat().st_size,
            before_mode=stat.S_IMODE(target.stat().st_mode),
            content=updated,
        )

    def rollback(self, snapshot_id: UUID) -> RollbackResult:
        try:
            return self.store.restore(snapshot_id=snapshot_id, task_id=self.task_id)
        except SnapshotStoreError as exc:
            raise WorkspaceMutationError(str(exc)) from exc
