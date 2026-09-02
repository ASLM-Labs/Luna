from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from luna.applied_changes.models import AppliedChangeRecord
from luna.applied_changes.replay import (
    AppliedChangeReplayResult,
    AppliedChangeReplayState,
)
from luna.recovery.models import IsolationMode
from luna.runtime.isolation import WorkspaceIsolationError
from luna.runtime.journal import (
    RuntimeJournalError,
    SideEffectExecutionProvenance,
    SideEffectReceipt,
)
from luna.workspace.windows_publication import (
    BoundPublicationParent,
    WindowsObservationLimitError,
    WindowsPublicationError,
)


class AppliedChangeComparisonAvailability(StrEnum):
    """Whether current-state comparison had a trustworthy execution basis."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class AppliedChangeComparisonEntryState(StrEnum):
    """Claim-neutral relationship between one durable after-state and current state."""

    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    MISSING = "MISSING"
    BLOCKED = "BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"


class AppliedChangeComparisonUnavailableReason(StrEnum):
    """Result-level reasons that prevent trustworthy target comparison."""

    REPLAY_ABSENT = "REPLAY_ABSENT"
    REPLAY_UNAVAILABLE = "REPLAY_UNAVAILABLE"
    REPLAY_INTEGRITY_FAILURE = "REPLAY_INTEGRITY_FAILURE"
    JOURNAL_UNAVAILABLE = "JOURNAL_UNAVAILABLE"
    RECEIPT_UNAVAILABLE = "RECEIPT_UNAVAILABLE"
    RECEIPT_BINDING_MISMATCH = "RECEIPT_BINDING_MISMATCH"
    ISOLATION_UNSUPPORTED = "ISOLATION_UNSUPPORTED"
    EXECUTION_REVISION_MISSING = "EXECUTION_REVISION_MISSING"
    HISTORICAL_WORKTREE_UNAVAILABLE = "HISTORICAL_WORKTREE_UNAVAILABLE"
    PLATFORM_UNAVAILABLE = "PLATFORM_UNAVAILABLE"


class AppliedChangeComparisonEntryReason(StrEnum):
    """Per-target reason when a durable record cannot be directly compared."""

    OBSERVATION_LIMIT = "OBSERVATION_LIMIT"
    TARGET_OBSERVATION_UNAVAILABLE = "TARGET_OBSERVATION_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CurrentTargetDigest:
    """Bound current content evidence sufficient for W4C equality comparison."""

    content_sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if (
            len(self.content_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.content_sha256
            )
        ):
            raise ValueError(
                "current target digest must be lowercase SHA-256"
            )
        if self.size_bytes < 0:
            raise ValueError(
                "current target size must be non-negative"
            )


@dataclass(frozen=True, slots=True)
class AppliedChangeComparisonEntry:
    """Current-state comparison for one exact durable applied-change record."""

    record_id: UUID
    relative_path: str

    expected_sha256: str
    expected_size_bytes: int

    state: AppliedChangeComparisonEntryState

    observed_sha256: str | None = None
    observed_size_bytes: int | None = None
    reason: AppliedChangeComparisonEntryReason | None = None

    def __post_init__(self) -> None:
        observed_pair = (
            self.observed_sha256 is not None,
            self.observed_size_bytes is not None,
        )

        if observed_pair[0] != observed_pair[1]:
            raise ValueError(
                "observed digest and size must be recorded together"
            )

        if self.state in {
            AppliedChangeComparisonEntryState.MATCH,
            AppliedChangeComparisonEntryState.MISMATCH,
        }:
            if not observed_pair[0]:
                raise ValueError(
                    "MATCH/MISMATCH requires observed content evidence"
                )
            if self.reason is not None:
                raise ValueError(
                    "MATCH/MISMATCH cannot carry an unavailable reason"
                )
            return

        if observed_pair[0]:
            raise ValueError(
                "non-comparable entry cannot carry observed content evidence"
            )

        if self.state is AppliedChangeComparisonEntryState.MISSING:
            if self.reason is not None:
                raise ValueError(
                    "MISSING cannot carry an unavailable reason"
                )
            return

        if self.reason is None:
            raise ValueError(
                "BLOCKED/UNAVAILABLE requires a reason"
            )


@dataclass(frozen=True, slots=True)
class AppliedChangeComparisonResult:
    """Claim-neutral current-state view for one exact historical tool result."""

    availability: AppliedChangeComparisonAvailability

    task_id: UUID
    request_id: UUID
    result_id: UUID

    replay_state: AppliedChangeReplayState

    reason: AppliedChangeComparisonUnavailableReason | None = None
    entries: tuple[AppliedChangeComparisonEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.availability is AppliedChangeComparisonAvailability.AVAILABLE:
            if self.reason is not None:
                raise ValueError(
                    "AVAILABLE comparison cannot carry a result-level reason"
                )
            if not self.entries:
                raise ValueError(
                    "AVAILABLE comparison requires per-record entries"
                )
            return

        if self.reason is None:
            raise ValueError(
                "UNAVAILABLE comparison requires a result-level reason"
            )

        if self.entries:
            raise ValueError(
                "UNAVAILABLE comparison cannot fabricate record entries"
            )


class AppliedChangeComparisonJournal(Protocol):
    """Read-only journal surface needed by claim-neutral W4C comparison."""

    def resolve_execution_provenance(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> SideEffectExecutionProvenance: ...

    def load(
        self,
        idempotency_key: str,
    ) -> SideEffectReceipt: ...


class HistoricalWorktreeRevalidator(Protocol):
    """Narrow historical identity capability required by Windows WORKTREE W4C."""

    def revalidate_historical_worktree(
        self,
        *,
        source_workspace_root: str,
        execution_workspace_root: str,
        execution_revision: str,
        task_id: UUID,
    ) -> str: ...


class AppliedChangeTargetObserver(Protocol):
    """Read-only current-target observation seam for deterministic tests."""

    @property
    def supported(self) -> bool: ...

    def observe(
        self,
        *,
        workspace_root: str,
        relative_path: str,
        max_bytes: int,
    ) -> CurrentTargetDigest | None: ...


class WindowsBoundTargetObserver:
    """Windows implementation backed by Luna's existing handle-bound observer."""

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    def observe(
        self,
        *,
        workspace_root: str,
        relative_path: str,
        max_bytes: int,
    ) -> CurrentTargetDigest | None:
        with BoundPublicationParent.bind(
            workspace_root,
            relative_path,
        ) as authority:
            state = authority.observe_target_with_token(
                max_bytes=max_bytes,
            )

        if state is None:
            return None

        return CurrentTargetDigest(
            content_sha256=state.token.content_sha256,
            size_bytes=state.token.size_bytes,
        )


def _unavailable(
    replay: AppliedChangeReplayResult,
    reason: AppliedChangeComparisonUnavailableReason,
) -> AppliedChangeComparisonResult:
    return AppliedChangeComparisonResult(
        availability=AppliedChangeComparisonAvailability.UNAVAILABLE,
        task_id=replay.task_id,
        request_id=replay.request_id,
        result_id=replay.result_id,
        replay_state=replay.state,
        reason=reason,
    )


def _replay_unavailable_reason(
    state: AppliedChangeReplayState,
) -> AppliedChangeComparisonUnavailableReason:
    if state is AppliedChangeReplayState.ABSENT:
        return AppliedChangeComparisonUnavailableReason.REPLAY_ABSENT
    if state is AppliedChangeReplayState.UNAVAILABLE:
        return AppliedChangeComparisonUnavailableReason.REPLAY_UNAVAILABLE
    if state is AppliedChangeReplayState.INTEGRITY_FAILURE:
        return AppliedChangeComparisonUnavailableReason.REPLAY_INTEGRITY_FAILURE
    raise ValueError(
        "AVAILABLE replay does not have an unavailable reason"
    )


def _receipt_matches_provenance(
    *,
    replay: AppliedChangeReplayResult,
    provenance: SideEffectExecutionProvenance,
    receipt: SideEffectReceipt,
) -> bool:
    outcome = receipt.outcome

    if outcome is None:
        return False

    return (
        receipt.receipt_id == provenance.receipt_id
        and receipt.idempotency_key == provenance.idempotency_key
        and receipt.task_id == replay.task_id == provenance.task_id
        and receipt.request.request_id
        == replay.request_id
        == provenance.request_id
        and outcome.request.request_id == replay.request_id
        and outcome.result.request_id == replay.request_id
        and outcome.result.result_id
        == replay.result_id
        == provenance.result_id
        and receipt.execution_workspace_root
        == provenance.execution_workspace_root
        and receipt.isolation_mode
        == provenance.isolation_mode
    )


def _entry_from_current(
    record: AppliedChangeRecord,
    current: CurrentTargetDigest,
) -> AppliedChangeComparisonEntry:
    candidate = record.candidate

    state = (
        AppliedChangeComparisonEntryState.MATCH
        if (
            current.content_sha256 == candidate.after_digest
            and current.size_bytes == candidate.after_size_bytes
        )
        else AppliedChangeComparisonEntryState.MISMATCH
    )

    return AppliedChangeComparisonEntry(
        record_id=record.record_id,
        relative_path=candidate.relative_path,
        expected_sha256=candidate.after_digest,
        expected_size_bytes=candidate.after_size_bytes,
        state=state,
        observed_sha256=current.content_sha256,
        observed_size_bytes=current.size_bytes,
    )


def compare_applied_change_replay_current_state(
    *,
    replay: AppliedChangeReplayResult,
    journal: AppliedChangeComparisonJournal,
    isolation_manager: HistoricalWorktreeRevalidator,
    observer: AppliedChangeTargetObserver,
    max_bytes: int,
) -> AppliedChangeComparisonResult:
    """Compare trusted durable after-state records with current Windows WORKTREE state.

    This function does not create verification claims, satisfy acceptance
    criteria, authorize recovery, reconstruct replay evidence, or mutate the
    workspace.
    """

    if max_bytes < 1:
        raise ValueError(
            "comparison max_bytes must be positive"
        )

    if replay.state is not AppliedChangeReplayState.AVAILABLE:
        return _unavailable(
            replay,
            _replay_unavailable_reason(
                replay.state
            ),
        )

    try:
        provenance = journal.resolve_execution_provenance(
            task_id=replay.task_id,
            request_id=replay.request_id,
            result_id=replay.result_id,
        )
    except RuntimeJournalError:
        return _unavailable(
            replay,
            AppliedChangeComparisonUnavailableReason.JOURNAL_UNAVAILABLE,
        )

    try:
        receipt = journal.load(
            provenance.idempotency_key
        )
    except RuntimeJournalError:
        return _unavailable(
            replay,
            AppliedChangeComparisonUnavailableReason.RECEIPT_UNAVAILABLE,
        )

    if not _receipt_matches_provenance(
        replay=replay,
        provenance=provenance,
        receipt=receipt,
    ):
        return _unavailable(
            replay,
            AppliedChangeComparisonUnavailableReason.RECEIPT_BINDING_MISMATCH,
        )

    if (
        receipt.isolation_mode
        != IsolationMode.WORKTREE.value
    ):
        return _unavailable(
            replay,
            AppliedChangeComparisonUnavailableReason.ISOLATION_UNSUPPORTED,
        )

    execution_revision = (
        receipt.execution_revision
    )

    if execution_revision is None:
        return _unavailable(
            replay,
            AppliedChangeComparisonUnavailableReason.EXECUTION_REVISION_MISSING,
        )

    if not observer.supported:
        return _unavailable(
            replay,
            AppliedChangeComparisonUnavailableReason.PLATFORM_UNAVAILABLE,
        )

    source_workspace_root = (
        receipt.pre_action_state
        .contract
        .scope
        .workspace_root
    )

    try:
        execution_workspace_root = (
            isolation_manager.revalidate_historical_worktree(
                source_workspace_root=source_workspace_root,
                execution_workspace_root=(
                    receipt.execution_workspace_root
                ),
                execution_revision=execution_revision,
                task_id=replay.task_id,
            )
        )
    except WorkspaceIsolationError:
        return _unavailable(
            replay,
            AppliedChangeComparisonUnavailableReason.HISTORICAL_WORKTREE_UNAVAILABLE,
        )

    entries: list[
        AppliedChangeComparisonEntry
    ] = []

    for record in replay.records:
        candidate = record.candidate

        try:
            current = observer.observe(
                workspace_root=execution_workspace_root,
                relative_path=candidate.relative_path,
                max_bytes=max_bytes,
            )
        except WindowsObservationLimitError:
            entries.append(
                AppliedChangeComparisonEntry(
                    record_id=record.record_id,
                    relative_path=candidate.relative_path,
                    expected_sha256=candidate.after_digest,
                    expected_size_bytes=candidate.after_size_bytes,
                    state=AppliedChangeComparisonEntryState.BLOCKED,
                    reason=(
                        AppliedChangeComparisonEntryReason.OBSERVATION_LIMIT
                    ),
                )
            )
            continue
        except WindowsPublicationError:
            entries.append(
                AppliedChangeComparisonEntry(
                    record_id=record.record_id,
                    relative_path=candidate.relative_path,
                    expected_sha256=candidate.after_digest,
                    expected_size_bytes=candidate.after_size_bytes,
                    state=AppliedChangeComparisonEntryState.UNAVAILABLE,
                    reason=(
                        AppliedChangeComparisonEntryReason.TARGET_OBSERVATION_UNAVAILABLE
                    ),
                )
            )
            continue

        if current is None:
            entries.append(
                AppliedChangeComparisonEntry(
                    record_id=record.record_id,
                    relative_path=candidate.relative_path,
                    expected_sha256=candidate.after_digest,
                    expected_size_bytes=candidate.after_size_bytes,
                    state=AppliedChangeComparisonEntryState.MISSING,
                )
            )
            continue

        entries.append(
            _entry_from_current(
                record,
                current,
            )
        )

    return AppliedChangeComparisonResult(
        availability=AppliedChangeComparisonAvailability.AVAILABLE,
        task_id=replay.task_id,
        request_id=replay.request_id,
        result_id=replay.result_id,
        replay_state=replay.state,
        entries=tuple(entries),
    )
