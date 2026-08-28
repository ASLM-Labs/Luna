"""Atomic scoped text mutations with preconditions and automatic rollback."""

from __future__ import annotations

import stat
from hashlib import sha256
from os import fstat
from pathlib import Path
from uuid import UUID

from luna.tools.paths import path_is_allowed
from luna.workspace.coordination import WorkspaceTargetSerializer
from luna.workspace.models import (
    FileChange,
    MutationStatus,
    RollbackResult,
    WorkspaceMutationResult,
    WorkspaceSnapshot,
    WorkspaceTargetBasis,
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
        self._serializer = WorkspaceTargetSerializer(
            workspace_root_digest=self.store.workspace_root_digest,
        )

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

    @staticmethod
    def _capture_target_basis(
        *,
        relative_path: str,
        target: Path,
    ) -> tuple[WorkspaceTargetBasis, bytes | None]:
        if target.is_symlink():
            raise WorkspaceMutationError(
                "existing target must be a regular file"
            )

        if not target.exists():
            return (
                WorkspaceTargetBasis(
                    relative_path=relative_path,
                    existed=False,
                ),
                None,
            )

        if not target.is_file():
            raise WorkspaceMutationError(
                "existing target must be a regular file"
            )

        try:
            with target.open("rb") as stream:
                metadata = fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode):
                    raise WorkspaceMutationError(
                        "existing target must be a regular file"
                    )
                content = stream.read()
        except WorkspaceMutationError:
            raise
        except OSError as exc:
            raise WorkspaceMutationError(
                "target changed while capturing mutation basis"
            ) from exc

        return (
            WorkspaceTargetBasis(
                relative_path=relative_path,
                existed=True,
                content_digest=sha256(content).hexdigest(),
                size_bytes=len(content),
                mode=stat.S_IMODE(metadata.st_mode),
            ),
            content,
        )

    @staticmethod
    def _snapshot_matches_basis(
        snapshot: WorkspaceSnapshot,
        basis: WorkspaceTargetBasis,
    ) -> bool:
        if len(snapshot.entries) != 1:
            return False

        entry = snapshot.entries[0]
        return (
            entry.relative_path == basis.relative_path
            and entry.existed == basis.existed
            and entry.content_digest == basis.content_digest
            and entry.size_bytes == basis.size_bytes
            and entry.mode == basis.mode
        )

    def _require_current_basis(
        self,
        *,
        accepted_basis: WorkspaceTargetBasis,
        target: Path,
    ) -> None:
        current_basis, _ = self._capture_target_basis(
            relative_path=accepted_basis.relative_path,
            target=target,
        )
        if current_basis != accepted_basis:
            raise WorkspaceMutationError(
                "target basis changed before mutation publication"
            )

    def _commit_text(
        self,
        *,
        relative_path: str,
        target: Path,
        accepted_basis: WorkspaceTargetBasis,
        content: str,
    ) -> WorkspaceMutationResult:
        snapshot = self.store.create_snapshot(
            task_id=self.task_id,
            relative_paths=(relative_path,),
        )
        if not self._snapshot_matches_basis(snapshot, accepted_basis):
            raise WorkspaceMutationError(
                "snapshot state does not match accepted mutation basis"
            )

        encoded = content.encode("utf-8")
        after_digest = sha256(encoded).hexdigest()

        self._require_current_basis(
            accepted_basis=accepted_basis,
            target=target,
        )

        try:
            atomic_write_bytes(
                target,
                encoded,
                mode=accepted_basis.mode,
            )
            self._verify_after_write(target, after_digest)
            after_mode = stat.S_IMODE(target.stat().st_mode)
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
            before_digest=accepted_basis.content_digest,
            after_digest=after_digest,
            before_size_bytes=accepted_basis.size_bytes,
            after_size_bytes=len(encoded),
            after_mode=after_mode,
            created=not accepted_basis.existed,
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
        normalized, _ = self._target(relative_path)

        with self._serializer.hold(normalized):
            normalized, target = self._target(normalized)
            accepted_basis, _ = self._capture_target_basis(
                relative_path=normalized,
                target=target,
            )

            if accepted_basis.existed:
                if expected_sha256 is None:
                    raise WorkspaceMutationError(
                        "existing file write requires expected_sha256"
                    )
                if accepted_basis.content_digest != expected_sha256:
                    raise WorkspaceMutationError(
                        "existing file digest does not match precondition"
                    )
            else:
                if not create_if_missing:
                    raise WorkspaceMutationError(
                        "target is missing and creation was not approved"
                    )
                if expected_sha256 is not None:
                    raise WorkspaceMutationError(
                        "new file creation cannot carry expected_sha256"
                    )

            return self._commit_text(
                relative_path=normalized,
                target=target,
                accepted_basis=accepted_basis,
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
        normalized, _ = self._target(relative_path)

        with self._serializer.hold(normalized):
            normalized, target = self._target(normalized)

            if not target.is_file() or target.is_symlink():
                raise WorkspaceMutationError(
                    "replace target must be an existing regular file"
                )

            accepted_basis, original_bytes = self._capture_target_basis(
                relative_path=normalized,
                target=target,
            )

            if not accepted_basis.existed or original_bytes is None:
                raise WorkspaceMutationError(
                    "replace target must be an existing regular file"
                )

            if accepted_basis.content_digest != expected_sha256:
                raise WorkspaceMutationError(
                    "replace target digest does not match precondition"
                )

            try:
                original = original_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WorkspaceMutationError(
                    "replace target is not valid UTF-8"
                ) from exc

            actual_occurrences = original.count(old_text)
            if actual_occurrences != expected_occurrences:
                raise WorkspaceMutationError(
                    "replace occurrence count does not match "
                    "explicit expectation"
                )

            updated = original.replace(old_text, new_text)
            if updated == original:
                raise WorkspaceMutationError(
                    "replace operation would produce no change"
                )

            return self._commit_text(
                relative_path=normalized,
                target=target,
                accepted_basis=accepted_basis,
                content=updated,
            )

    def rollback(self, snapshot_id: UUID) -> RollbackResult:
        try:
            return self.store.restore(snapshot_id=snapshot_id, task_id=self.task_id)
        except SnapshotStoreError as exc:
            raise WorkspaceMutationError(str(exc)) from exc
