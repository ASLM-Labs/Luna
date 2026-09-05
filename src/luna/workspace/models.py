"""Versioned snapshot, mutation, and rollback contracts."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, field_validator, model_validator

from luna.applied_changes.models import AppliedChangeCandidate
from luna.contracts.base import SCHEMA_VERSION, LunaContractModel, require_utc, utc_now


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


class WorkspaceTargetBasis(LunaContractModel):
    """Immutable state accepted before mutating one workspace target."""

    model_config = ConfigDict(frozen=True)

    relative_path: str = Field(min_length=1, max_length=4000)
    existed: bool
    content_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    size_bytes: int = Field(default=0, ge=0)
    mode: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_basis(self) -> WorkspaceTargetBasis:
        if self.existed:
            if self.content_digest is None or self.mode is None:
                raise ValueError(
                    "existing target basis requires digest and mode"
                )
        elif (
            self.content_digest is not None
            or self.size_bytes != 0
            or self.mode is not None
        ):
            raise ValueError(
                "absent target basis cannot carry file content metadata"
            )
        return self


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



class SafeUndoReceiptState(StrEnum):
    """Durable lifecycle state for one conditional safe-undo receipt."""

    PREPARED = "PREPARED"
    PUBLICATION_PREPARED = "PUBLICATION_PREPARED"
    COMMITTED = "COMMITTED"
    UNDONE = "UNDONE"


class WindowsAfterStateToken(LunaContractModel):
    """Durable Windows identity, freshness, content, and policy evidence."""

    model_config = ConfigDict(frozen=True)

    volume_serial_number: int = Field(ge=0)
    file_id: str = Field(
        pattern=r"^[0-9a-f]{32}$",
    )
    creation_time: int = Field(ge=0)
    last_write_time: int = Field(ge=0)
    change_time: int = Field(ge=0)
    content_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )
    size_bytes: int = Field(ge=0)
    mode: int = Field(ge=0)
    dacl_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    dacl_protected: bool


class WindowsPreparedPublicationIdentity(
    LunaContractModel
):
    """Stable object/content/policy identity captured before publication."""

    model_config = ConfigDict(frozen=True)

    volume_serial_number: int = Field(ge=0)
    file_id: str = Field(
        pattern=r"^[0-9a-f]{32}$",
    )
    creation_time: int = Field(ge=0)
    last_write_time: int = Field(ge=0)
    content_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )
    size_bytes: int = Field(ge=0)
    mode: int = Field(ge=0)
    dacl_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    dacl_protected: bool

    @classmethod
    def from_after_state_token(
        cls,
        token: WindowsAfterStateToken,
    ) -> WindowsPreparedPublicationIdentity:
        """Project only fields proven stable across native publication."""

        return cls(
            volume_serial_number=(
                token.volume_serial_number
            ),
            file_id=token.file_id,
            creation_time=token.creation_time,
            last_write_time=(
                token.last_write_time
            ),
            content_sha256=(
                token.content_sha256
            ),
            size_bytes=token.size_bytes,
            mode=token.mode,
            dacl_sha256=token.dacl_sha256,
            dacl_protected=(
                token.dacl_protected
            ),
        )

    def matches_after_state_token(
        self,
        token: WindowsAfterStateToken,
    ) -> bool:
        """Return observational stable-projection equality only."""

        return self == type(self).from_after_state_token(
            token
        )


class WorkspaceExecutionBinding(LunaContractModel):
    """Exact runtime identities bound to one workspace side-effect attempt."""

    model_config = ConfigDict(frozen=True)

    request_id: UUID
    runtime_receipt_id: UUID


def _safe_undo_receipt_digest_payload(
    *,
    schema_version: str,
    receipt_version: int,
    state: SafeUndoReceiptState,
    snapshot_id: UUID,
    snapshot_digest: str,
    task_id: UUID,
    workspace_root_digest: str,
    relative_path: str,
    expected_after_sha256: str,
    expected_after_size_bytes: int,
    execution_binding: WorkspaceExecutionBinding | None,
    prepared_publication_identity: (
        WindowsPreparedPublicationIdentity | None
    ),
    after_token: WindowsAfterStateToken | None,
) -> bytes:
    payload = {
        "schema_version": schema_version,
        "receipt_version": receipt_version,
        "state": state.value,
        "snapshot_id": str(snapshot_id),
        "snapshot_digest": snapshot_digest,
        "task_id": str(task_id),
        "workspace_root_digest": workspace_root_digest,
        "relative_path": relative_path,
        "expected_after_sha256": expected_after_sha256,
        "expected_after_size_bytes": expected_after_size_bytes,
        "after_token": (
            None
            if after_token is None
            else after_token.model_dump(mode="json")
        ),
    }

    # Preserve the exact v1 digest payload. New identity material
    # participates in the digest only for receipt_version == 2.
    if receipt_version == 2:
        payload["execution_binding"] = (
            None
            if execution_binding is None
            else execution_binding.model_dump(mode="json")
        )
        payload["prepared_publication_identity"] = (
            None
            if prepared_publication_identity is None
            else prepared_publication_identity.model_dump(
                mode="json"
            )
        )

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class SafeUndoReceipt(LunaContractModel):
    """Integrity-bound durable authority record for conditional safe undo."""

    model_config = ConfigDict(frozen=True)

    receipt_version: Literal[1, 2] = 1
    state: SafeUndoReceiptState

    snapshot_id: UUID
    snapshot_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )

    task_id: UUID
    workspace_root_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )

    relative_path: str = Field(
        min_length=1,
        max_length=4000,
    )

    expected_after_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_after_size_bytes: int = Field(
        ge=0,
    )

    execution_binding: WorkspaceExecutionBinding | None = None
    prepared_publication_identity: (
        WindowsPreparedPublicationIdentity | None
    ) = None
    after_token: WindowsAfterStateToken | None = None

    receipt_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_receipt(
        self,
    ) -> SafeUndoReceipt:
        if self.receipt_version == 1:
            if self.execution_binding is not None:
                raise ValueError(
                    "v1 safe-undo receipt cannot carry "
                    "execution binding"
                )

            if (
                self.prepared_publication_identity
                is not None
            ):
                raise ValueError(
                    "v1 safe-undo receipt cannot carry "
                    "prepared publication identity"
                )

            if (
                self.state
                is SafeUndoReceiptState.PUBLICATION_PREPARED
            ):
                raise ValueError(
                    "v1 safe-undo receipt cannot enter "
                    "PUBLICATION_PREPARED"
                )

            if (
                self.state
                is SafeUndoReceiptState.PREPARED
            ):
                if self.after_token is not None:
                    raise ValueError(
                        "PREPARED safe-undo receipt "
                        "cannot carry an after token"
                    )

            elif self.after_token is None:
                raise ValueError(
                    "COMMITTED or UNDONE safe-undo "
                    "receipt requires an after token"
                )

        else:
            if self.execution_binding is None:
                raise ValueError(
                    "v2 safe-undo receipt requires "
                    "an execution binding"
                )

            if (
                self.state
                is SafeUndoReceiptState.PREPARED
            ):
                if (
                    self.prepared_publication_identity
                    is not None
                    or self.after_token is not None
                ):
                    raise ValueError(
                        "v2 PREPARED safe-undo receipt "
                        "cannot carry publication evidence"
                    )

            elif (
                self.state
                is SafeUndoReceiptState.PUBLICATION_PREPARED
            ):
                if (
                    self.prepared_publication_identity
                    is None
                ):
                    raise ValueError(
                        "PUBLICATION_PREPARED safe-undo "
                        "receipt requires prepared identity"
                    )

                if self.after_token is not None:
                    raise ValueError(
                        "PUBLICATION_PREPARED safe-undo "
                        "receipt cannot carry an after token"
                    )

            else:
                if (
                    self.prepared_publication_identity
                    is None
                    or self.after_token is None
                ):
                    raise ValueError(
                        "v2 COMMITTED or UNDONE receipt "
                        "requires prepared and after evidence"
                    )

        if (
            self.prepared_publication_identity is not None
            and (
                self.prepared_publication_identity.content_sha256
                != self.expected_after_sha256
                or self.prepared_publication_identity.size_bytes
                != self.expected_after_size_bytes
            )
        ):
            raise ValueError(
                "prepared publication identity does not "
                "match expected after-state semantics"
            )

        if (
            self.after_token is not None
            and (
                self.after_token.content_sha256
                != self.expected_after_sha256
                or self.after_token.size_bytes
                != self.expected_after_size_bytes
            )
        ):
            raise ValueError(
                "safe-undo after token does not "
                "match expected after-state semantics"
            )

        if (
            self.prepared_publication_identity is not None
            and self.after_token is not None
            and not (
                self.prepared_publication_identity
                .matches_after_state_token(
                    self.after_token
                )
            )
        ):
            raise ValueError(
                "published after token does not match "
                "durable prepared publication identity"
            )

        expected = sha256(
            _safe_undo_receipt_digest_payload(
                schema_version=self.schema_version,
                receipt_version=self.receipt_version,
                state=self.state,
                snapshot_id=self.snapshot_id,
                snapshot_digest=self.snapshot_digest,
                task_id=self.task_id,
                workspace_root_digest=(
                    self.workspace_root_digest
                ),
                relative_path=self.relative_path,
                expected_after_sha256=(
                    self.expected_after_sha256
                ),
                expected_after_size_bytes=(
                    self.expected_after_size_bytes
                ),
                execution_binding=(
                    self.execution_binding
                ),
                prepared_publication_identity=(
                    self.prepared_publication_identity
                ),
                after_token=self.after_token,
            )
        ).hexdigest()

        if self.receipt_digest != expected:
            raise ValueError(
                "receipt_digest does not match "
                "safe-undo receipt"
            )

        return self

    @classmethod
    def _build(
        cls,
        *,
        receipt_version: Literal[1, 2],
        state: SafeUndoReceiptState,
        snapshot_id: UUID,
        snapshot_digest: str,
        task_id: UUID,
        workspace_root_digest: str,
        relative_path: str,
        expected_after_sha256: str,
        expected_after_size_bytes: int,
        execution_binding: WorkspaceExecutionBinding | None,
        prepared_publication_identity: (
            WindowsPreparedPublicationIdentity | None
        ),
        after_token: WindowsAfterStateToken | None,
    ) -> SafeUndoReceipt:
        digest = sha256(
            _safe_undo_receipt_digest_payload(
                schema_version=SCHEMA_VERSION,
                receipt_version=receipt_version,
                state=state,
                snapshot_id=snapshot_id,
                snapshot_digest=snapshot_digest,
                task_id=task_id,
                workspace_root_digest=(
                    workspace_root_digest
                ),
                relative_path=relative_path,
                expected_after_sha256=(
                    expected_after_sha256
                ),
                expected_after_size_bytes=(
                    expected_after_size_bytes
                ),
                execution_binding=execution_binding,
                prepared_publication_identity=(
                    prepared_publication_identity
                ),
                after_token=after_token,
            )
        ).hexdigest()

        return cls(
            receipt_version=receipt_version,
            state=state,
            snapshot_id=snapshot_id,
            snapshot_digest=snapshot_digest,
            task_id=task_id,
            workspace_root_digest=(
                workspace_root_digest
            ),
            relative_path=relative_path,
            expected_after_sha256=(
                expected_after_sha256
            ),
            expected_after_size_bytes=(
                expected_after_size_bytes
            ),
            execution_binding=execution_binding,
            prepared_publication_identity=(
                prepared_publication_identity
            ),
            after_token=after_token,
            receipt_digest=digest,
        )

    @classmethod
    def build_prepared(
        cls,
        *,
        snapshot_id: UUID,
        snapshot_digest: str,
        task_id: UUID,
        workspace_root_digest: str,
        relative_path: str,
        expected_after_sha256: str,
        expected_after_size_bytes: int,
        execution_binding: WorkspaceExecutionBinding | None = None,
    ) -> SafeUndoReceipt:
        receipt_version: Literal[1, 2] = (
            2
            if execution_binding is not None
            else 1
        )

        return cls._build(
            receipt_version=receipt_version,
            state=SafeUndoReceiptState.PREPARED,
            snapshot_id=snapshot_id,
            snapshot_digest=snapshot_digest,
            task_id=task_id,
            workspace_root_digest=(
                workspace_root_digest
            ),
            relative_path=relative_path,
            expected_after_sha256=(
                expected_after_sha256
            ),
            expected_after_size_bytes=(
                expected_after_size_bytes
            ),
            execution_binding=execution_binding,
            prepared_publication_identity=None,
            after_token=None,
        )

    def with_prepared_publication_identity(
        self,
        identity: WindowsPreparedPublicationIdentity,
    ) -> SafeUndoReceipt:
        if self.receipt_version != 2:
            raise ValueError(
                "prepared publication transition "
                "requires a v2 safe-undo receipt"
            )

        if (
            self.state
            is not SafeUndoReceiptState.PREPARED
        ):
            raise ValueError(
                "prepared publication transition "
                "requires PREPARED state"
            )

        return type(self)._build(
            receipt_version=2,
            state=(
                SafeUndoReceiptState
                .PUBLICATION_PREPARED
            ),
            snapshot_id=self.snapshot_id,
            snapshot_digest=self.snapshot_digest,
            task_id=self.task_id,
            workspace_root_digest=(
                self.workspace_root_digest
            ),
            relative_path=self.relative_path,
            expected_after_sha256=(
                self.expected_after_sha256
            ),
            expected_after_size_bytes=(
                self.expected_after_size_bytes
            ),
            execution_binding=self.execution_binding,
            prepared_publication_identity=identity,
            after_token=None,
        )

    def with_committed_after_state(
        self,
        after_token: WindowsAfterStateToken,
    ) -> SafeUndoReceipt:
        required_state = (
            SafeUndoReceiptState.PUBLICATION_PREPARED
            if self.receipt_version == 2
            else SafeUndoReceiptState.PREPARED
        )

        if self.state is not required_state:
            raise ValueError(
                "safe-undo receipt commit requires "
                f"{required_state.value} state"
            )

        return type(self)._build(
            receipt_version=self.receipt_version,
            state=SafeUndoReceiptState.COMMITTED,
            snapshot_id=self.snapshot_id,
            snapshot_digest=self.snapshot_digest,
            task_id=self.task_id,
            workspace_root_digest=(
                self.workspace_root_digest
            ),
            relative_path=self.relative_path,
            expected_after_sha256=(
                self.expected_after_sha256
            ),
            expected_after_size_bytes=(
                self.expected_after_size_bytes
            ),
            execution_binding=self.execution_binding,
            prepared_publication_identity=(
                self.prepared_publication_identity
            ),
            after_token=after_token,
        )

    def with_undone_state(
        self,
    ) -> SafeUndoReceipt:
        if (
            self.state
            is not SafeUndoReceiptState.COMMITTED
        ):
            raise ValueError(
                "safe-undo receipt completion "
                "requires COMMITTED state"
            )

        assert self.after_token is not None

        return type(self)._build(
            receipt_version=self.receipt_version,
            state=SafeUndoReceiptState.UNDONE,
            snapshot_id=self.snapshot_id,
            snapshot_digest=self.snapshot_digest,
            task_id=self.task_id,
            workspace_root_digest=(
                self.workspace_root_digest
            ),
            relative_path=self.relative_path,
            expected_after_sha256=(
                self.expected_after_sha256
            ),
            expected_after_size_bytes=(
                self.expected_after_size_bytes
            ),
            execution_binding=self.execution_binding,
            prepared_publication_identity=(
                self.prepared_publication_identity
            ),
            after_token=self.after_token,
        )


class WorkspaceReconciliationTargetState(StrEnum):
    """Observed target relation to one exact runtime-bound workspace receipt."""

    NO_BOUND_RECEIPT = "NO_BOUND_RECEIPT"
    BEFORE_MATCH = "BEFORE_MATCH"
    AFTER_MATCH = "AFTER_MATCH"
    DIVERGED = "DIVERGED"
    UNOBSERVABLE = "UNOBSERVABLE"


class WorkspaceExecutionReconciliation(LunaContractModel):
    """Read-only cold observation for one exact runtime side-effect attempt."""

    model_config = ConfigDict(frozen=True)

    task_id: UUID
    request_id: UUID
    runtime_receipt_id: UUID

    workspace_root_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )

    receipt_state: SafeUndoReceiptState | None = None

    snapshot_id: UUID | None = None
    snapshot_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    receipt_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    relative_path: str | None = Field(
        default=None,
        min_length=1,
        max_length=4000,
    )

    target_state: WorkspaceReconciliationTargetState

    observed_after_token: WindowsAfterStateToken | None = None

    reason: str | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
    )

    @model_validator(mode="after")
    def validate_reconciliation(
        self,
    ) -> WorkspaceExecutionReconciliation:
        bound_values = (
            self.snapshot_id,
            self.snapshot_digest,
            self.receipt_digest,
            self.relative_path,
        )

        if self.receipt_state is None:
            if any(
                value is not None
                for value in bound_values
            ):
                raise ValueError(
                    "unbound reconciliation cannot "
                    "carry receipt evidence"
                )

            if (
                self.target_state
                is not WorkspaceReconciliationTargetState
                .NO_BOUND_RECEIPT
            ):
                raise ValueError(
                    "missing receipt requires "
                    "NO_BOUND_RECEIPT target state"
                )

            if self.observed_after_token is not None:
                raise ValueError(
                    "unbound reconciliation cannot "
                    "carry target token evidence"
                )

        else:
            if any(
                value is None
                for value in bound_values
            ):
                raise ValueError(
                    "bound reconciliation requires "
                    "complete receipt evidence"
                )

            if (
                self.target_state
                is WorkspaceReconciliationTargetState
                .NO_BOUND_RECEIPT
            ):
                raise ValueError(
                    "bound reconciliation cannot report "
                    "NO_BOUND_RECEIPT"
                )

        if (
            self.target_state
            is WorkspaceReconciliationTargetState.AFTER_MATCH
            and self.observed_after_token is None
        ):
            raise ValueError(
                "AFTER_MATCH reconciliation requires "
                "an observed after-state token"
            )

        if (
            self.target_state
            is WorkspaceReconciliationTargetState.UNOBSERVABLE
            and self.reason is None
        ):
            raise ValueError(
                "UNOBSERVABLE reconciliation requires "
                "an explicit reason"
            )

        return self


class FileChange(LunaContractModel):
    """Hash-addressed evidence for one committed file mutation."""

    relative_path: str = Field(min_length=1, max_length=4000)
    before_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    after_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    before_size_bytes: int = Field(default=0, ge=0)
    after_size_bytes: int = Field(default=0, ge=0)
    after_mode: int | None = Field(default=None, ge=0)
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
    applied_changes: tuple[AppliedChangeCandidate, ...] = ()
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

        if self.applied_changes:
            if self.status is not MutationStatus.COMMITTED:
                raise ValueError(
                    "applied-change evidence requires a committed mutation"
                )

            if len(self.applied_changes) != len(self.changes):
                raise ValueError(
                    "applied-change evidence must cover every file change"
                )

            change_paths = tuple(
                change.relative_path
                for change in self.changes
            )
            candidate_paths = tuple(
                candidate.relative_path
                for candidate in self.applied_changes
            )

            if len(change_paths) != len(set(change_paths)):
                raise ValueError(
                    "file changes must have unique paths when "
                    "applied-change evidence is present"
                )

            if len(candidate_paths) != len(set(candidate_paths)):
                raise ValueError(
                    "applied-change candidates must have unique paths"
                )

            if set(change_paths) != set(candidate_paths):
                raise ValueError(
                    "applied-change paths must exactly match file changes"
                )

            snapshot_by_path = {
                entry.relative_path: entry
                for entry in self.snapshot.entries
            }
            change_by_path = {
                change.relative_path: change
                for change in self.changes
            }

            for candidate in self.applied_changes:
                if candidate.task_id != self.task_id:
                    raise ValueError(
                        "applied-change task_id must match mutation task_id"
                    )

                change = change_by_path[
                    candidate.relative_path
                ]

                if change.deleted:
                    raise ValueError(
                        "text applied-change evidence cannot bind "
                        "a deleted file change"
                    )

                if (
                    change.created
                    is candidate.before_existed
                ):
                    raise ValueError(
                        "applied-change existence state does not "
                        "match file change"
                    )

                if (
                    candidate.before_digest
                    != change.before_digest
                    or candidate.after_digest
                    != change.after_digest
                ):
                    raise ValueError(
                        "applied-change digests do not match file change"
                    )

                if (
                    candidate.before_size_bytes
                    != change.before_size_bytes
                    or candidate.after_size_bytes
                    != change.after_size_bytes
                ):
                    raise ValueError(
                        "applied-change sizes do not match file change"
                    )

                snapshot_entry = snapshot_by_path.get(
                    candidate.relative_path
                )

                if snapshot_entry is None:
                    raise ValueError(
                        "applied-change path is missing from "
                        "the mutation snapshot"
                    )

                if (
                    candidate.before_existed
                    != snapshot_entry.existed
                    or candidate.before_digest
                    != snapshot_entry.content_digest
                    or candidate.before_size_bytes
                    != snapshot_entry.size_bytes
                ):
                    raise ValueError(
                        "applied-change before-state does not "
                        "match mutation snapshot"
                    )

        return self
