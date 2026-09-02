"""Atomic scoped text mutations with preconditions and automatic rollback."""

from __future__ import annotations

import os
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
    RollbackStatus,
    SafeUndoReceiptState,
    SnapshotEntry,
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
from luna.workspace.windows_publication import (
    BoundPublicationParent,
    PublicationState,
    TargetObservation,
    WindowsPublicationError,
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

    @staticmethod
    def _basis_from_bound_observation(
        *,
        relative_path: str,
        observation: TargetObservation,
    ) -> WorkspaceTargetBasis:
        if not observation.existed:
            if any(
                value is not None
                for value in (
                    observation.content,
                    observation.mode,
                    observation.security_descriptor,
                    observation.dacl,
                    observation.dacl_protected,
                )
            ):
                raise WorkspaceMutationError(
                    "absent bound observation contains target state"
                )

            return WorkspaceTargetBasis(
                relative_path=relative_path,
                existed=False,
            )

        if (
            observation.content is None
            or observation.mode is None
            or observation.security_descriptor is None
            or observation.dacl_protected is None
        ):
            raise WorkspaceMutationError(
                "existing bound observation lacks required "
                "content, mode, or security evidence"
            )

        return WorkspaceTargetBasis(
            relative_path=relative_path,
            existed=True,
            content_digest=sha256(observation.content).hexdigest(),
            size_bytes=len(observation.content),
            mode=observation.mode,
        )

    def _snapshot_from_bound_observation(
        self,
        *,
        relative_path: str,
        accepted_basis: WorkspaceTargetBasis,
        observation: TargetObservation,
    ) -> WorkspaceSnapshot:
        try:
            snapshot = self.store._create_snapshot_from_captured_state(
                task_id=self.task_id,
                relative_path=relative_path,
                existed=observation.existed,
                content=observation.content,
                mode=observation.mode,
            )
        except SnapshotStoreError as exc:
            raise WorkspaceMutationError(str(exc)) from exc

        if not self._snapshot_matches_basis(
            snapshot,
            accepted_basis,
        ):
            raise WorkspaceMutationError(
                "snapshot state does not match accepted mutation basis"
            )

        return snapshot

    def _require_current_bound_basis(
        self,
        *,
        authority: BoundPublicationParent,
        accepted_basis: WorkspaceTargetBasis,
    ) -> TargetObservation:
        observation = authority.observe_target()

        current_basis = self._basis_from_bound_observation(
            relative_path=accepted_basis.relative_path,
            observation=observation,
        )

        if current_basis != accepted_basis:
            raise WorkspaceMutationError(
                "target basis changed before mutation publication"
            )

        return observation

    @staticmethod
    def _verify_bound_publication(
        *,
        observation: TargetObservation,
        expected_content: bytes,
        source: TargetObservation,
    ) -> int:
        if (
            not observation.existed
            or observation.content is None
            or observation.mode is None
            or observation.content != expected_content
        ):
            raise WorkspaceMutationError(
                "post-write bound content verification failed"
            )

        if source.existed:
            if (
                source.mode is None
                or source.dacl_protected is None
            ):
                raise WorkspaceMutationError(
                    "publication source lacks required mode "
                    "or DACL evidence"
                )

            if (
                observation.mode != source.mode
                or observation.dacl != source.dacl
                or observation.dacl_protected
                is not source.dacl_protected
            ):
                raise WorkspaceMutationError(
                    "post-write bound mode or DACL "
                    "verification failed"
                )

        return observation.mode

    def _bound_rollback_result(
        self,
        *,
        snapshot: WorkspaceSnapshot,
        relative_path: str,
        original: TargetObservation,
    ) -> RollbackResult:
        return RollbackResult(
            snapshot_id=snapshot.snapshot_id,
            task_id=self.task_id,
            status=RollbackStatus.RESTORED,
            restored_files=(
                (relative_path,)
                if original.existed
                else ()
            ),
            removed_files=(
                ()
                if original.existed
                else (relative_path,)
            ),
            verified=True,
        )

    def _commit_text_windows(
        self,
        *,
        relative_path: str,
        authority: BoundPublicationParent,
        accepted_basis: WorkspaceTargetBasis,
        accepted_observation: TargetObservation,
        content: str,
    ) -> WorkspaceMutationResult:
        snapshot = self._snapshot_from_bound_observation(
            relative_path=relative_path,
            accepted_basis=accepted_basis,
            observation=accepted_observation,
        )

        encoded = content.encode("utf-8")
        after_digest = sha256(encoded).hexdigest()

        current_observation = self._require_current_bound_basis(
            authority=authority,
            accepted_basis=accepted_basis,
        )

        try:
            self.store.prepare_undo_receipt(
                snapshot=snapshot,
                relative_path=relative_path,
                expected_after_sha256=after_digest,
                expected_after_size_bytes=len(encoded),
            )

        except Exception as exc:
            raise WorkspaceMutationError(
                "safe-undo receipt preparation failed: "
                f"{exc}"
            ) from exc

        stage = authority.create_stage(
            source=(
                current_observation
                if current_observation.existed
                else None
            )
        )

        try:
            try:
                stage.write_bytes(encoded)

            except Exception as exc:
                try:
                    stage.discard()
                except Exception as cleanup_exc:
                    raise WorkspaceMutationError(
                        "mutation staging failed and private "
                        "stage cleanup failed: "
                        f"{cleanup_exc}"
                    ) from exc

                raise WorkspaceMutationError(
                    f"mutation staging failed: {exc}"
                ) from exc

            try:
                publication = stage.publish(
                    authority.leaf_name,
                    replace=accepted_basis.existed,
                )

            except Exception as exc:
                state = stage.publication_state

                if state is None:
                    try:
                        stage.discard()
                    except Exception as cleanup_exc:
                        raise WorkspaceMutationError(
                            "mutation publication failed before "
                            "native publication and private "
                            "stage cleanup failed: "
                            f"{cleanup_exc}"
                        ) from exc

                    raise WorkspaceMutationError(
                        "mutation publication failed before "
                        f"native publication: {exc}"
                    ) from exc

                if state is PublicationState.UNKNOWN:
                    raise WorkspaceMutationError(
                        "mutation publication outcome is unknown; "
                        "manual verification is required"
                    ) from exc

                raise WorkspaceMutationError(
                    "mutation publication lifecycle is inconsistent; "
                    "manual verification is required"
                ) from exc

            if publication.state is PublicationState.COLLISION:
                try:
                    stage.discard()
                except Exception as cleanup_exc:
                    raise WorkspaceMutationError(
                        "mutation publication collided and private "
                        "stage cleanup failed: "
                        f"{cleanup_exc}"
                    ) from cleanup_exc

                raise WorkspaceMutationError(
                    "target namespace changed before "
                    "mutation publication"
                )

            if publication.state is PublicationState.UNKNOWN:
                raise WorkspaceMutationError(
                    "mutation publication outcome is unknown; "
                    "manual verification is required"
                )

            if publication.state is not PublicationState.PUBLISHED:
                raise WorkspaceMutationError(
                    "mutation publication returned an "
                    "unsupported state"
                )

            try:
                published = (
                    stage.observe_published_with_token()
                )

                after_mode = self._verify_bound_publication(
                    observation=published.observation,
                    expected_content=encoded,
                    source=current_observation,
                )

                change = FileChange(
                    relative_path=relative_path,
                    before_digest=(
                        accepted_basis.content_digest
                    ),
                    after_digest=after_digest,
                    before_size_bytes=(
                        accepted_basis.size_bytes
                    ),
                    after_size_bytes=len(encoded),
                    after_mode=after_mode,
                    created=not accepted_basis.existed,
                )

                result = WorkspaceMutationResult(
                    task_id=self.task_id,
                    snapshot=snapshot,
                    status=MutationStatus.COMMITTED,
                    changes=(change,),
                )

                self.store.commit_undo_receipt(
                    snapshot_id=snapshot.snapshot_id,
                    task_id=self.task_id,
                    after_token=published.token,
                )

            except Exception as exc:
                try:
                    stage.rollback_published(
                        current_observation
                    )

                    rollback = self._bound_rollback_result(
                        snapshot=snapshot,
                        relative_path=relative_path,
                        original=current_observation,
                    )

                except Exception as rollback_exc:
                    raise WorkspaceMutationError(
                        "mutation failed after confirmed "
                        "publication and bound rollback failed: "
                        f"{rollback_exc}"
                    ) from exc

                raise WorkspaceMutationError(
                    "mutation failed after confirmed publication "
                    f"and was rolled back: {exc}",
                    rollback=rollback,
                ) from exc

            return result

        finally:
            stage.close()

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
            if os.name == "nt":
                try:
                    with BoundPublicationParent.bind(
                        str(self.store.workspace_root),
                        normalized,
                        create_missing_parents=(
                            create_if_missing
                            and expected_sha256 is None
                        ),
                    ) as authority:
                        accepted_observation = (
                            authority.observe_target()
                        )

                        accepted_basis = (
                            self._basis_from_bound_observation(
                                relative_path=normalized,
                                observation=accepted_observation,
                            )
                        )

                        if accepted_basis.existed:
                            if expected_sha256 is None:
                                raise WorkspaceMutationError(
                                    "existing file write requires "
                                    "expected_sha256"
                                )

                            if (
                                accepted_basis.content_digest
                                != expected_sha256
                            ):
                                raise WorkspaceMutationError(
                                    "existing file digest does not "
                                    "match precondition"
                                )

                        else:
                            if not create_if_missing:
                                raise WorkspaceMutationError(
                                    "target is missing and creation "
                                    "was not approved"
                                )

                            if expected_sha256 is not None:
                                raise WorkspaceMutationError(
                                    "new file creation cannot carry "
                                    "expected_sha256"
                                )

                        return self._commit_text_windows(
                            relative_path=normalized,
                            authority=authority,
                            accepted_basis=accepted_basis,
                            accepted_observation=(
                                accepted_observation
                            ),
                            content=content,
                        )

                except WorkspaceMutationError:
                    raise

                except WindowsPublicationError as exc:
                    raise WorkspaceMutationError(
                        str(exc)
                    ) from exc

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
            if os.name == "nt":
                try:
                    with BoundPublicationParent.bind(
                        str(self.store.workspace_root),
                        normalized,
                    ) as authority:
                        accepted_observation = (
                            authority.observe_target()
                        )

                        accepted_basis = (
                            self._basis_from_bound_observation(
                                relative_path=normalized,
                                observation=accepted_observation,
                            )
                        )

                        original_bytes = accepted_observation.content

                        if (
                            not accepted_basis.existed
                            or original_bytes is None
                        ):
                            raise WorkspaceMutationError(
                                "replace target must be an "
                                "existing regular file"
                            )

                        if (
                            accepted_basis.content_digest
                            != expected_sha256
                        ):
                            raise WorkspaceMutationError(
                                "replace target digest does not "
                                "match precondition"
                            )

                        try:
                            original = original_bytes.decode(
                                "utf-8"
                            )
                        except UnicodeDecodeError as exc:
                            raise WorkspaceMutationError(
                                "replace target is not valid UTF-8"
                            ) from exc

                        actual_occurrences = original.count(
                            old_text
                        )

                        if (
                            actual_occurrences
                            != expected_occurrences
                        ):
                            raise WorkspaceMutationError(
                                "replace occurrence count does "
                                "not match explicit expectation"
                            )

                        updated = original.replace(
                            old_text,
                            new_text,
                        )

                        if updated == original:
                            raise WorkspaceMutationError(
                                "replace operation would produce "
                                "no change"
                            )

                        return self._commit_text_windows(
                            relative_path=normalized,
                            authority=authority,
                            accepted_basis=accepted_basis,
                            accepted_observation=(
                                accepted_observation
                            ),
                            content=updated,
                        )

                except WorkspaceMutationError:
                    raise

                except WindowsPublicationError as exc:
                    raise WorkspaceMutationError(
                        str(exc)
                    ) from exc

            normalized, target = self._target(normalized)

            if not target.is_file() or target.is_symlink():
                raise WorkspaceMutationError(
                    "replace target must be an existing regular file"
                )

            accepted_basis, original_bytes = (
                self._capture_target_basis(
                    relative_path=normalized,
                    target=target,
                )
            )

            if (
                not accepted_basis.existed
                or original_bytes is None
            ):
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

    @staticmethod
    def _basis_from_snapshot_entry(
        entry: SnapshotEntry,
    ) -> WorkspaceTargetBasis:
        return WorkspaceTargetBasis(
            relative_path=entry.relative_path,
            existed=entry.existed,
            content_digest=entry.content_digest,
            size_bytes=entry.size_bytes,
            mode=entry.mode,
        )

    def safe_undo(
        self,
        snapshot_id: UUID,
    ) -> RollbackResult:
        """Conditionally undo one committed Windows mutation."""

        if os.name != "nt":
            raise WorkspaceMutationError(
                "conditional safe undo is supported "
                "only on Windows"
            )

        try:
            initial_receipt = (
                self.store.load_undo_receipt(
                    snapshot_id,
                    task_id=self.task_id,
                )
            )

        except SnapshotStoreError as exc:
            raise WorkspaceMutationError(
                str(exc)
            ) from exc

        relative_path = (
            initial_receipt.relative_path
        )

        with self._serializer.hold(
            relative_path
        ):
            try:
                receipt = (
                    self.store.load_undo_receipt(
                        snapshot_id,
                        task_id=self.task_id,
                    )
                )

                snapshot = (
                    self.store.load_snapshot(
                        snapshot_id
                    )
                )

                if (
                    len(snapshot.entries) != 1
                    or snapshot.entries[0].relative_path
                    != receipt.relative_path
                ):
                    raise WorkspaceMutationError(
                        "safe-undo snapshot target "
                        "binding is invalid"
                    )

                entry = snapshot.entries[0]

                expected_before = (
                    self._basis_from_snapshot_entry(
                        entry
                    )
                )

                if (
                    receipt.state
                    is SafeUndoReceiptState.PREPARED
                ):
                    raise WorkspaceMutationError(
                        "PREPARED safe-undo receipt "
                        "does not authorize undo"
                    )

                if (
                    receipt.state
                    is SafeUndoReceiptState.UNDONE
                ):
                    with BoundPublicationParent.bind(
                        str(
                            self.store.workspace_root
                        ),
                        receipt.relative_path,
                    ) as authority:
                        current = (
                            authority.observe_target()
                        )

                        current_basis = (
                            self._basis_from_bound_observation(
                                relative_path=(
                                    receipt.relative_path
                                ),
                                observation=current,
                            )
                        )

                    if current_basis != expected_before:
                        raise WorkspaceMutationError(
                            "UNDONE safe-undo receipt "
                            "target does not match "
                            "snapshot before-state"
                        )

                    return RollbackResult(
                        snapshot_id=snapshot_id,
                        task_id=self.task_id,
                        status=RollbackStatus.NO_CHANGES,
                        verified=True,
                    )

                if (
                    receipt.state
                    is not SafeUndoReceiptState.COMMITTED
                    or receipt.after_token is None
                ):
                    raise WorkspaceMutationError(
                        "safe-undo receipt is not "
                        "in an authorized state"
                    )

                before_content: bytes | None = None

                if entry.existed:
                    if (
                        entry.content_digest is None
                        or entry.mode is None
                    ):
                        raise WorkspaceMutationError(
                            "existing safe-undo snapshot "
                            "entry lacks before-state evidence"
                        )

                    before_content = self.store._blob(
                        snapshot_id,
                        entry.content_digest,
                    )

                    if (
                        len(before_content)
                        != entry.size_bytes
                    ):
                        raise WorkspaceMutationError(
                            "safe-undo snapshot blob "
                            "size does not match manifest"
                        )

                with BoundPublicationParent.bind(
                    str(
                        self.store.workspace_root
                    ),
                    receipt.relative_path,
                ) as authority:
                    if entry.existed:
                        assert before_content is not None
                        assert entry.mode is not None

                        with (
                            authority
                            .fence_existing_restore(
                                receipt.after_token
                            )
                        ) as fenced:
                            restored = (
                                fenced
                                .restore_existing_content(
                                    before_content,
                                    mode=entry.mode,
                                )
                            )

                            restored_basis = (
                                self
                                ._basis_from_bound_observation(
                                    relative_path=(
                                        receipt.relative_path
                                    ),
                                    observation=(
                                        restored.observation
                                    ),
                                )
                            )

                        if (
                            restored_basis
                            != expected_before
                        ):
                            raise WorkspaceMutationError(
                                "safe undo restored target "
                                "failed independent "
                                "before-state verification"
                            )

                    else:
                        with (
                            authority
                            .fence_created_delete(
                                receipt.after_token
                            )
                        ) as fenced:
                            absent = (
                                fenced
                                .delete_created_target()
                            )

                        if absent.existed:
                            raise WorkspaceMutationError(
                                "safe undo created-target "
                                "delete did not yield absence"
                            )

                        fresh_absent = (
                            authority.observe_target()
                        )

                        if fresh_absent.existed:
                            raise WorkspaceMutationError(
                                "safe undo created-target "
                                "absence verification failed"
                            )

                result = RollbackResult(
                    snapshot_id=snapshot_id,
                    task_id=self.task_id,
                    status=RollbackStatus.RESTORED,
                    restored_files=(
                        (receipt.relative_path,)
                        if entry.existed
                        else ()
                    ),
                    removed_files=(
                        ()
                        if entry.existed
                        else (
                            receipt.relative_path,
                        )
                    ),
                    verified=True,
                )

                try:
                    undone = (
                        self.store
                        .mark_undo_receipt_undone(
                            snapshot_id=snapshot_id,
                            task_id=self.task_id,
                        )
                    )

                except SnapshotStoreError as exc:
                    try:
                        durable = (
                            self.store
                            .load_undo_receipt(
                                snapshot_id,
                                task_id=self.task_id,
                            )
                        )

                    except SnapshotStoreError:
                        raise WorkspaceMutationError(
                            "safe undo filesystem "
                            "inverse was verified but "
                            "receipt completion is "
                            "uncertain; manual "
                            "verification is required"
                        ) from exc

                    if (
                        durable.state
                        is not SafeUndoReceiptState.UNDONE
                    ):
                        raise WorkspaceMutationError(
                            "safe undo filesystem "
                            "inverse was verified but "
                            "receipt remains incomplete; "
                            "manual verification is required"
                        ) from exc

                    return result

                if (
                    undone.state
                    is not SafeUndoReceiptState.UNDONE
                ):
                    raise WorkspaceMutationError(
                        "safe undo receipt completion "
                        "returned an unexpected state"
                    )

                return result

            except WorkspaceMutationError:
                raise

            except (
                SnapshotStoreError,
                WindowsPublicationError,
            ) as exc:
                raise WorkspaceMutationError(
                    str(exc)
                ) from exc

    def rollback(
        self,
        snapshot_id: UUID,
    ) -> RollbackResult:
        """Compatibility alias for conditional safe undo."""
        return self.safe_undo(snapshot_id)
