"""Versioned snapshot, mutation, and rollback contracts."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


def _snapshot_digest_payload(
    *,
    snapshot_id: UUID,
    task_id: UUID,
    workspace_root_digest: str,
    entries: tuple[SnapshotEntry, ...],
    created_at: datetime,
) -> bytes:
    payload = {
        "snapshot_id": str(snapshot_id),
        "task_id": str(task_id),
        "workspace_root_digest": workspace_root_digest,
        "entries": [entry.model_dump(mode="json") for entry in entries],
        "created_at": created_at.isoformat(),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class MutationStatus(StrEnum):
    """Final state of a controlled workspace mutation."""

    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"


class RollbackStatus(StrEnum):
    """Outcome of restoring one persisted workspace snapshot."""

    RESTORED = "RESTORED"
    NO_CHANGES = "NO_CHANGES"


class SnapshotEntry(LunaContractModel):
    """Original state of one explicitly scoped regular file path."""

    relative_path: str = Field(min_length=1, max_length=4000)
    existed: bool
    content_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(default=0, ge=0)
    mode: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_original_state(self) -> SnapshotEntry:
        if self.existed:
            if self.content_digest is None or self.mode is None:
                raise ValueError("existing snapshot entry requires digest and mode")
        elif self.content_digest is not None or self.size_bytes != 0 or self.mode is not None:
            raise ValueError("absent snapshot entry cannot carry file content metadata")
        return self


class WorkspaceSnapshot(LunaContractModel):
    """Immutable manifest for files captured before a workspace mutation."""

    snapshot_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    workspace_root_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[SnapshotEntry, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("entries")
    @classmethod
    def validate_unique_paths(
        cls,
        values: tuple[SnapshotEntry, ...],
    ) -> tuple[SnapshotEntry, ...]:
        paths = tuple(entry.relative_path for entry in values)
        if len(paths) != len(set(paths)):
            raise ValueError("snapshot paths must be unique")
        return values

    @model_validator(mode="after")
    def validate_snapshot_digest(self) -> WorkspaceSnapshot:
        expected = sha256(
            _snapshot_digest_payload(
                snapshot_id=self.snapshot_id,
                task_id=self.task_id,
                workspace_root_digest=self.workspace_root_digest,
                entries=self.entries,
                created_at=self.created_at,
            )
        ).hexdigest()
        if self.snapshot_digest != expected:
            raise ValueError("snapshot_digest does not match snapshot manifest")
        return self

    @classmethod
    def build(
        cls,
        *,
        task_id: UUID,
        workspace_root_digest: str,
        entries: tuple[SnapshotEntry, ...],
        snapshot_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> WorkspaceSnapshot:
        active_snapshot_id = snapshot_id or uuid4()
        active_created_at = created_at or utc_now()
        digest = sha256(
            _snapshot_digest_payload(
                snapshot_id=active_snapshot_id,
                task_id=task_id,
                workspace_root_digest=workspace_root_digest,
                entries=entries,
                created_at=active_created_at,
            )
        ).hexdigest()
        return cls(
            snapshot_id=active_snapshot_id,
            task_id=task_id,
            workspace_root_digest=workspace_root_digest,
            entries=entries,
            created_at=active_created_at,
            snapshot_digest=digest,
        )


class FileChange(LunaContractModel):
    """Hash-addressed evidence for one committed file mutation."""

    relative_path: str = Field(min_length=1, max_length=4000)
    before_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    after_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    before_size_bytes: int = Field(default=0, ge=0)
    after_size_bytes: int = Field(default=0, ge=0)
    created: bool = False
    deleted: bool = False

    @model_validator(mode="after")
    def validate_change(self) -> FileChange:
        if self.created and self.before_digest is not None:
            raise ValueError("created change cannot have a before digest")
        if self.deleted and self.after_digest is not None:
            raise ValueError("deleted change cannot have an after digest")
        if self.created and self.deleted:
            raise ValueError("change cannot be both created and deleted")
        if not self.created and not self.deleted and (
            self.before_digest is None or self.after_digest is None
        ):
            raise ValueError("modified change requires before and after digests")
        return self


class RollbackResult(LunaContractModel):
    """Verified result of restoring one snapshot."""

    snapshot_id: UUID
    task_id: UUID
    status: RollbackStatus
    restored_files: tuple[str, ...] = ()
    removed_files: tuple[str, ...] = ()
    verified: bool = True

    @model_validator(mode="after")
    def validate_result(self) -> RollbackResult:
        if self.status is RollbackStatus.NO_CHANGES and (
            self.restored_files or self.removed_files
        ):
            raise ValueError("NO_CHANGES rollback cannot list mutations")
        if not self.verified:
            raise ValueError("rollback result must be verified before publication")
        return self


class WorkspaceMutationResult(LunaContractModel):
    """Committed workspace mutation linked to its pre-change snapshot."""

    task_id: UUID
    snapshot: WorkspaceSnapshot
    status: MutationStatus
    changes: tuple[FileChange, ...] = Field(min_length=1)
    rollback: RollbackResult | None = None

    @model_validator(mode="after")
    def validate_links(self) -> WorkspaceMutationResult:
        if self.snapshot.task_id != self.task_id:
            raise ValueError("snapshot task_id must match mutation task_id")

        if self.status is MutationStatus.COMMITTED and self.rollback is not None:
            raise ValueError("committed mutation cannot carry rollback result")

        if (
            self.status is MutationStatus.ROLLED_BACK
            and (
                self.rollback is None
                or self.rollback.snapshot_id != self.snapshot.snapshot_id
            )
        ):
            raise ValueError(
                "rolled-back mutation requires matching rollback result"
            )

        return self
