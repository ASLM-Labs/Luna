from __future__ import annotations

import os
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest

from luna.applied_changes import (
    AppliedChangeCandidate,
    AppliedChangeOperation,
    AppliedChangeRecord,
    AppliedChangeState,
    applied_change_manifest_sha256,
)
from luna.applied_changes.models import AppliedChangeBindingState
from luna.applied_changes.replay import (
    AppliedChangeReplayResult,
    AppliedChangeReplayState,
    resolve_applied_change_replay,
)
from luna.applied_changes.store import SQLiteAppliedChangeStore
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.planning.models import AttemptBasis
from luna.recovery import ChangeEstimate, WorkspaceIsolationPolicy
from luna.runtime.applied_change_comparison import (
    AppliedChangeComparisonAvailability,
    AppliedChangeComparisonEntryReason,
    AppliedChangeComparisonEntryState,
    AppliedChangeComparisonUnavailableReason,
    AppliedChangeTargetObserver,
    CurrentTargetDigest,
    HistoricalWorktreeRevalidator,
    WindowsBoundTargetObserver,
    compare_applied_change_replay_current_state,
)
from luna.runtime.isolation import GitWorktreeIsolationManager, WorkspaceIsolationError
from luna.runtime.journal import (
    RuntimeJournalError,
    SideEffectExecutionProvenance,
    SideEffectReceipt,
    SQLiteRuntimeJournal,
)
from luna.tools import (
    AutonomyLevel,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    build_phase5_registry,
)
from luna.workspace.windows_publication import (
    WindowsObservationLimitError,
    WindowsPublicationError,
)

TASK_ID = UUID("11111111-1111-4111-8111-111111111111")
REQUEST_ID = UUID("22222222-2222-4222-8222-222222222222")
RESULT_ID = UUID("33333333-3333-4333-8333-333333333333")
RECEIPT_ID = UUID("44444444-4444-4444-8444-444444444444")

IDEMPOTENCY_KEY = "a" * 64
EXECUTION_REVISION = "b" * 40

SOURCE_ROOT = "C:/source"
EXECUTION_ROOT = "C:/historical-worktree"


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _record(
    *,
    relative_path: str,
    content: bytes,
    record_id: UUID,
) -> AppliedChangeRecord:
    digest = _digest(content)

    candidate = AppliedChangeCandidate(
        task_id=TASK_ID,
        operation=AppliedChangeOperation.WRITE_TEXT,
        relative_path=relative_path,
        state=AppliedChangeState.NO_CHANGE,
        before_existed=True,
        before_digest=digest,
        after_digest=digest,
        before_size_bytes=len(content),
        after_size_bytes=len(content),
    )

    return AppliedChangeRecord.build(
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
        candidate=candidate,
        record_id=record_id,
    )


def _replay(
    *records: AppliedChangeRecord,
) -> AppliedChangeReplayResult:
    return AppliedChangeReplayResult(
        state=AppliedChangeReplayState.AVAILABLE,
        task_id=TASK_ID,
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
        expected_count=len(records),
        expected_manifest_sha256=(
            applied_change_manifest_sha256(
                records
            )
        ),
        records=records,
    )


def _receipt(
    *,
    isolation_mode: str = "WORKTREE",
    execution_revision: str | None = EXECUTION_REVISION,
) -> object:
    request = SimpleNamespace(
        request_id=REQUEST_ID,
    )

    result = SimpleNamespace(
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
    )

    outcome = SimpleNamespace(
        request=request,
        result=result,
    )

    scope = SimpleNamespace(
        workspace_root=SOURCE_ROOT,
    )

    contract = SimpleNamespace(
        scope=scope,
    )

    pre_action_state = SimpleNamespace(
        contract=contract,
    )

    return SimpleNamespace(
        receipt_id=RECEIPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        task_id=TASK_ID,
        request=request,
        outcome=outcome,
        execution_workspace_root=EXECUTION_ROOT,
        isolation_mode=isolation_mode,
        execution_revision=execution_revision,
        pre_action_state=pre_action_state,
    )


class FakeJournal:
    def __init__(
        self,
        *,
        receipt: object | None = None,
        resolve_error: bool = False,
        load_error: bool = False,
    ) -> None:
        self.receipt = receipt or _receipt()
        self.resolve_error = resolve_error
        self.load_error = load_error
        self.resolve_calls = 0
        self.load_calls = 0

    def resolve_execution_provenance(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> SideEffectExecutionProvenance:
        self.resolve_calls += 1

        if self.resolve_error:
            raise RuntimeJournalError(
                "forced provenance failure"
            )

        assert task_id == TASK_ID
        assert request_id == REQUEST_ID
        assert result_id == RESULT_ID

        return SideEffectExecutionProvenance(
            receipt_id=RECEIPT_ID,
            idempotency_key=IDEMPOTENCY_KEY,
            task_id=TASK_ID,
            request_id=REQUEST_ID,
            result_id=RESULT_ID,
            execution_workspace_root=EXECUTION_ROOT,
            isolation_mode=(
                cast(
                    object,
                    self.receipt,
                ).isolation_mode
            ),
        )

    def load(
        self,
        idempotency_key: str,
    ) -> SideEffectReceipt:
        self.load_calls += 1

        if self.load_error:
            raise RuntimeJournalError(
                "forced receipt load failure"
            )

        assert (
            idempotency_key
            == IDEMPOTENCY_KEY
        )

        return cast(
            SideEffectReceipt,
            self.receipt,
        )


class FakeRevalidator:
    def __init__(
        self,
        *,
        fail: bool = False,
    ) -> None:
        self.fail = fail
        self.calls = 0

    def revalidate_historical_worktree(
        self,
        *,
        source_workspace_root: str,
        execution_workspace_root: str,
        execution_revision: str,
        task_id: UUID,
    ) -> str:
        self.calls += 1

        assert source_workspace_root == SOURCE_ROOT
        assert execution_workspace_root == EXECUTION_ROOT
        assert execution_revision == EXECUTION_REVISION
        assert task_id == TASK_ID

        if self.fail:
            raise WorkspaceIsolationError(
                "forced historical failure"
            )

        return EXECUTION_ROOT


class FakeObserver:
    def __init__(
        self,
        outcomes: dict[
            str,
            CurrentTargetDigest | BaseException | None,
        ],
        *,
        supported: bool = True,
    ) -> None:
        self._outcomes = outcomes
        self._supported = supported
        self.calls: list[str] = []

    @property
    def supported(self) -> bool:
        return self._supported

    def observe(
        self,
        *,
        workspace_root: str,
        relative_path: str,
        max_bytes: int,
    ) -> CurrentTargetDigest | None:
        assert workspace_root == EXECUTION_ROOT
        assert max_bytes == 1024

        self.calls.append(
            relative_path
        )

        outcome = self._outcomes[
            relative_path
        ]

        if isinstance(
            outcome,
            BaseException,
        ):
            raise outcome

        return outcome


def _compare(
    replay: AppliedChangeReplayResult,
    *,
    journal: FakeJournal | None = None,
    revalidator: FakeRevalidator | None = None,
    observer: FakeObserver | None = None,
):
    active_journal = journal or FakeJournal()
    active_revalidator = (
        revalidator
        or FakeRevalidator()
    )
    active_observer = (
        observer
        or FakeObserver({})
    )

    return compare_applied_change_replay_current_state(
        replay=replay,
        journal=cast(
            object,
            active_journal,
        ),
        isolation_manager=cast(
            HistoricalWorktreeRevalidator,
            active_revalidator,
        ),
        observer=cast(
            AppliedChangeTargetObserver,
            active_observer,
        ),
        max_bytes=1024,
    )


def test_replay_absent_is_result_level_unavailable_without_journal_access() -> None:
    replay = AppliedChangeReplayResult(
        state=AppliedChangeReplayState.ABSENT,
        task_id=TASK_ID,
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
    )

    journal = FakeJournal()

    result = _compare(
        replay,
        journal=journal,
        observer=FakeObserver({}),
    )

    assert (
        result.availability
        is AppliedChangeComparisonAvailability.UNAVAILABLE
    )
    assert (
        result.reason
        is AppliedChangeComparisonUnavailableReason.REPLAY_ABSENT
    )
    assert result.entries == ()
    assert journal.resolve_calls == 0


def test_journal_resolution_failure_is_result_level_unavailable() -> None:
    record = _record(
        relative_path="a.txt",
        content=b"alpha",
        record_id=UUID(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        ),
    )

    result = _compare(
        _replay(record),
        journal=FakeJournal(
            resolve_error=True,
        ),
        observer=FakeObserver({}),
    )

    assert (
        result.reason
        is AppliedChangeComparisonUnavailableReason.JOURNAL_UNAVAILABLE
    )
    assert result.entries == ()


def test_non_worktree_and_missing_revision_fail_neutral() -> None:
    record = _record(
        relative_path="a.txt",
        content=b"alpha",
        record_id=UUID(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        ),
    )
    replay = _replay(record)

    unsupported = _compare(
        replay,
        journal=FakeJournal(
            receipt=_receipt(
                isolation_mode="NONE",
            )
        ),
        observer=FakeObserver({}),
    )

    assert (
        unsupported.reason
        is AppliedChangeComparisonUnavailableReason.ISOLATION_UNSUPPORTED
    )

    legacy = _compare(
        replay,
        journal=FakeJournal(
            receipt=_receipt(
                execution_revision=None,
            )
        ),
        observer=FakeObserver({}),
    )

    assert (
        legacy.reason
        is AppliedChangeComparisonUnavailableReason.EXECUTION_REVISION_MISSING
    )


def test_platform_and_historical_identity_fail_neutral() -> None:
    record = _record(
        relative_path="a.txt",
        content=b"alpha",
        record_id=UUID(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        ),
    )
    replay = _replay(record)

    platform = _compare(
        replay,
        observer=FakeObserver(
            {},
            supported=False,
        ),
    )

    assert (
        platform.reason
        is AppliedChangeComparisonUnavailableReason.PLATFORM_UNAVAILABLE
    )

    historical = _compare(
        replay,
        revalidator=FakeRevalidator(
            fail=True,
        ),
        observer=FakeObserver({}),
    )

    assert (
        historical.reason
        is AppliedChangeComparisonUnavailableReason.HISTORICAL_WORKTREE_UNAVAILABLE
    )


def test_available_replay_preserves_durable_record_order_and_compares_each_target() -> None:
    first_content = b"alpha"
    second_content = b"zeta"

    first = _record(
        relative_path="z.txt",
        content=first_content,
        record_id=UUID(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        ),
    )
    second = _record(
        relative_path="a.txt",
        content=second_content,
        record_id=UUID(
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        ),
    )

    observer = FakeObserver(
        {
            "z.txt": CurrentTargetDigest(
                content_sha256=_digest(
                    first_content
                ),
                size_bytes=len(
                    first_content
                ),
            ),
            "a.txt": CurrentTargetDigest(
                content_sha256=_digest(
                    b"different"
                ),
                size_bytes=len(
                    second_content
                ),
            ),
        }
    )

    result = _compare(
        _replay(
            first,
            second,
        ),
        observer=observer,
    )

    assert (
        result.availability
        is AppliedChangeComparisonAvailability.AVAILABLE
    )
    assert result.reason is None

    assert tuple(
        entry.record_id
        for entry in result.entries
    ) == (
        first.record_id,
        second.record_id,
    )

    assert tuple(
        entry.relative_path
        for entry in result.entries
    ) == (
        "z.txt",
        "a.txt",
    )

    assert tuple(
        entry.state
        for entry in result.entries
    ) == (
        AppliedChangeComparisonEntryState.MATCH,
        AppliedChangeComparisonEntryState.MISMATCH,
    )

    assert observer.calls == [
        "z.txt",
        "a.txt",
    ]


def test_missing_blocked_and_observer_failure_remain_per_record_states() -> None:
    missing = _record(
        relative_path="missing.txt",
        content=b"missing",
        record_id=UUID(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        ),
    )
    blocked = _record(
        relative_path="large.txt",
        content=b"large",
        record_id=UUID(
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        ),
    )
    unavailable = _record(
        relative_path="unavailable.txt",
        content=b"unavailable",
        record_id=UUID(
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        ),
    )

    observer = FakeObserver(
        {
            "missing.txt": None,
            "large.txt": (
                WindowsObservationLimitError(
                    max_bytes=1024
                )
            ),
            "unavailable.txt": (
                WindowsPublicationError(
                    "forced observer failure"
                )
            ),
        }
    )

    result = _compare(
        _replay(
            missing,
            blocked,
            unavailable,
        ),
        observer=observer,
    )

    assert tuple(
        entry.state
        for entry in result.entries
    ) == (
        AppliedChangeComparisonEntryState.MISSING,
        AppliedChangeComparisonEntryState.BLOCKED,
        AppliedChangeComparisonEntryState.UNAVAILABLE,
    )

    assert result.entries[0].reason is None

    assert (
        result.entries[1].reason
        is AppliedChangeComparisonEntryReason.OBSERVATION_LIMIT
    )

    assert (
        result.entries[2].reason
        is AppliedChangeComparisonEntryReason.TARGET_OBSERVATION_UNAVAILABLE
    )


def test_comparison_rejects_non_positive_observation_limit() -> None:
    replay = AppliedChangeReplayResult(
        state=AppliedChangeReplayState.ABSENT,
        task_id=TASK_ID,
        request_id=REQUEST_ID,
        result_id=RESULT_ID,
    )

    with pytest.raises(
        ValueError,
        match="max_bytes must be positive",
    ):
        compare_applied_change_replay_current_state(
            replay=replay,
            journal=cast(
                object,
                FakeJournal(),
            ),
            isolation_manager=cast(
                HistoricalWorktreeRevalidator,
                FakeRevalidator(),
            ),
            observer=cast(
                AppliedChangeTargetObserver,
                FakeObserver({}),
            ),
            max_bytes=0,
        )


def _integration_git(
    repo: Path,
    *args: str,
) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_integration_repo(
    path: Path,
) -> None:
    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    subprocess.run(
        ["git", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )

    _integration_git(
        path,
        "config",
        "user.email",
        "luna-w4c@example.invalid",
    )
    _integration_git(
        path,
        "config",
        "user.name",
        "Luna W4C",
    )

    (
        path
        / "notes.txt"
    ).write_bytes(
        b"before\n"
    )

    _integration_git(
        path,
        "add",
        "notes.txt",
    )
    _integration_git(
        path,
        "commit",
        "-m",
        "baseline",
    )


@pytest.mark.skipif(
    os.name != "nt",
    reason=(
        "W4C current-state comparison is presently "
        "verified only for Windows WORKTREE execution"
    ),
)
def test_real_windows_worktree_comparison_tracks_match_drift_missing_and_revision_fence(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "source"
    )

    _init_integration_repo(
        source
    )

    task_id = uuid4()

    contract = TaskContract(
        task_id=task_id,
        objective=(
            "Compare one durable applied change "
            "against its historical execution worktree."
        ),
        required_conditions=(
            "Current-state comparison remains claim-neutral.",
        ),
        evidence_required=(
            "Durable applied-change record and bounded current observation.",
        ),
        scope=TaskScope(
            workspace_root=str(source),
            allowed_paths=(
                "notes.txt",
            ),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
        owner="w4c-test",
    )

    # Keep the real Git worktree outside pytest's long per-test
    # path so snapshot digest filenames remain within the current
    # Windows filesystem path budget.
    worktree_temp = tempfile.TemporaryDirectory(
        prefix="w4c-wt-",
    )
    worktree_base = Path(
        worktree_temp.name
    )

    manager = (
        GitWorktreeIsolationManager(
            worktree_base_root=str(worktree_base),
        )
    )

    decision = (
        WorkspaceIsolationPolicy()
        .plan(
            task_contract=contract,
            change=ChangeEstimate(
                touched_paths=(
                    "notes.txt",
                ),
                added_lines=1,
                deleted_lines=1,
            ),
            worktree_available=(
                manager.worktree_available(
                    contract
                )
            ),
        )
    )

    assert decision.allowed

    lease = manager.acquire(
        task_contract=contract,
        decision=decision,
        task_id=task_id,
    )

    assert (
        lease.execution_revision
        is not None
    )

    historical_root = Path(
        lease.workspace_root
    ).resolve()

    try:
        execution_contract = (
            TaskContract(
                task_id=(
                    contract.task_id
                ),
                objective=(
                    contract.objective
                ),
                required_conditions=(
                    contract.required_conditions
                ),
                forbidden_outcomes=(
                    contract.forbidden_outcomes
                ),
                evidence_required=(
                    contract.evidence_required
                ),
                scope=TaskScope(
                    workspace_root=str(
                        historical_root
                    ),
                    allowed_paths=(
                        contract
                        .scope
                        .allowed_paths
                    ),
                    protected_paths=(
                        contract
                        .scope
                        .protected_paths
                    ),
                    write_allowed=True,
                    network_allowed=(
                        contract
                        .scope
                        .network_allowed
                    ),
                    process_allowed=(
                        contract
                        .scope
                        .process_allowed
                    ),
                ),
                risk_level=(
                    contract.risk_level
                ),
                unknowns=(
                    contract.unknowns
                ),
                owner=(
                    contract.owner
                ),
                created_at=(
                    contract.created_at
                ),
            )
        )

        historical_target = (
            historical_root
            / "notes.txt"
        )

        before = (
            historical_target
            .read_bytes()
        )

        request = ToolRequest(
            task_id=task_id,
            trace_id=uuid4(),
            tool_name=(
                "filesystem.write_text"
            ),
            arguments={
                "path": "notes.txt",
                "content": "after\n",
                "expected_sha256": (
                    sha256(
                        before
                    ).hexdigest()
                ),
                "create_if_missing": False,
            },
            expectation_id=uuid4(),
        )

        store_path = (
            tmp_path
            / "applied-changes.sqlite3"
        )
        journal_path = (
            tmp_path
            / "journal.sqlite3"
        )

        store = (
            SQLiteAppliedChangeStore(
                store_path
            )
        )
        journal = (
            SQLiteRuntimeJournal(
                journal_path
            )
        )

        dispatcher = ToolDispatcher(
            build_phase5_registry(),
            applied_change_store=store,
        )

        pre_state = TaskState(
            task_id=task_id,
            contract=contract,
        )

        attempt_basis = (
            AttemptBasis(
                action_key=(
                    "w4c-real-worktree-write"
                ),
                context_fingerprint=(
                    "1" * 64
                ),
                execution_strategy=(
                    "execute once in the "
                    "task-owned detached worktree"
                ),
                verification_strategy=(
                    "compare durable after-state "
                    "against bounded current observation"
                ),
                scope_fingerprint=(
                    "2" * 64
                ),
            )
        )

        receipt = SideEffectReceipt(
            idempotency_key=(
                sha256(
                    b"w4c-integration-idempotency"
                ).hexdigest()
            ),
            semantic_fingerprint=(
                sha256(
                    b"w4c-integration-semantic"
                ).hexdigest()
            ),
            task_id=task_id,
            trace_id=(
                request.trace_id
            ),
            step_id=uuid4(),
            proposal_id=uuid4(),
            request=request,
            attempt_basis=(
                attempt_basis
            ),
            pre_action_state=(
                pre_state
            ),
            execution_workspace_root=(
                lease.workspace_root
            ),
            isolation_mode=(
                lease.mode.value
            ),
            execution_revision=(
                lease.execution_revision
            ),
        )

        reserved = (
            journal.reserve(
                receipt
            )
        )

        journal.mark_started(
            reserved.idempotency_key
        )

        outcome = (
            dispatcher.dispatch(
                request=request,
                task_contract=(
                    execution_contract
                ),
                policy=ToolPolicy(
                    allowed_tools=(
                        "filesystem.write_text",
                    ),
                    autonomy_level=(
                        AutonomyLevel.BOUNDED
                    ),
                    max_risk=(
                        RiskLevel.MEDIUM
                    ),
                ),
            )
        )

        assert (
            outcome.result.status
            is ToolResultStatus.SUCCESS
        )

        assert (
            outcome.result.metadata[
                "applied_change_binding_state"
            ]
            == (
                AppliedChangeBindingState
                .BOUND
                .value
            )
        )

        journal.mark_completed(
            idempotency_key=(
                receipt.idempotency_key
            ),
            outcome=outcome,
        )

        journal.record_outcome(
            outcome
        )

        post_state = (
            pre_state.revise(
                observation_ids=(
                    outcome
                    .observation
                    .observation_id,
                )
            )
        )

        journal.mark_observed(
            idempotency_key=(
                receipt.idempotency_key
            ),
            post_action_state=(
                post_state
            ),
        )

        assert journal.verify_integrity()

        # Force cold durable readback.
        reopened_journal = (
            SQLiteRuntimeJournal(
                journal_path
            )
        )

        provenance = (
            reopened_journal
            .resolve_execution_provenance(
                task_id=task_id,
                request_id=(
                    request.request_id
                ),
                result_id=(
                    outcome
                    .result
                    .result_id
                ),
            )
        )

        durable_receipt = (
            reopened_journal.load(
                provenance.idempotency_key
            )
        )

        assert (
            Path(
                durable_receipt
                .execution_workspace_root
            ).resolve()
            == historical_root
        )

        assert (
            durable_receipt
            .execution_revision
            == lease.execution_revision
        )

        assert (
            Path(
                durable_receipt
                .pre_action_state
                .contract
                .scope
                .workspace_root
            ).resolve()
            == source.resolve()
        )

        reopened_store = (
            SQLiteAppliedChangeStore(
                store_path
            )
        )

        replay = (
            resolve_applied_change_replay(
                task_id=task_id,
                request_id=(
                    request.request_id
                ),
                result_id=(
                    outcome
                    .result
                    .result_id
                ),
                metadata=(
                    outcome
                    .result
                    .metadata
                ),
                store=reopened_store,
            )
        )

        assert (
            replay.state
            is AppliedChangeReplayState.AVAILABLE
        )
        assert len(
            replay.records
        ) == 1

        observer = (
            WindowsBoundTargetObserver()
        )

        initial = (
            compare_applied_change_replay_current_state(
                replay=replay,
                journal=(
                    reopened_journal
                ),
                isolation_manager=(
                    manager
                ),
                observer=observer,
                max_bytes=1024,
            )
        )

        assert (
            initial.availability
            is (
                AppliedChangeComparisonAvailability
                .AVAILABLE
            )
        )
        assert len(
            initial.entries
        ) == 1
        assert (
            initial.entries[0].state
            is (
                AppliedChangeComparisonEntryState
                .MATCH
            )
        )

        # Current source HEAD may advance after execution.
        (
            source
            / "next.txt"
        ).write_text(
            "NEXT\n",
            encoding="utf-8",
        )

        _integration_git(
            source,
            "add",
            "next.txt",
        )
        _integration_git(
            source,
            "commit",
            "-m",
            "advance source head",
        )

        after_source_advance = (
            compare_applied_change_replay_current_state(
                replay=replay,
                journal=(
                    reopened_journal
                ),
                isolation_manager=(
                    manager
                ),
                observer=observer,
                max_bytes=1024,
            )
        )

        assert (
            after_source_advance
            .entries[0]
            .state
            is (
                AppliedChangeComparisonEntryState
                .MATCH
            )
        )

        # Working-tree bytes may drift while detached HEAD
        # remains the same historical execution revision.
        historical_target.write_bytes(
            b"current drift\n"
        )

        mismatch = (
            compare_applied_change_replay_current_state(
                replay=replay,
                journal=(
                    reopened_journal
                ),
                isolation_manager=(
                    manager
                ),
                observer=observer,
                max_bytes=1024,
            )
        )

        assert (
            mismatch.availability
            is (
                AppliedChangeComparisonAvailability
                .AVAILABLE
            )
        )
        assert (
            mismatch.entries[0].state
            is (
                AppliedChangeComparisonEntryState
                .MISMATCH
            )
        )

        historical_target.unlink()

        missing = (
            compare_applied_change_replay_current_state(
                replay=replay,
                journal=(
                    reopened_journal
                ),
                isolation_manager=(
                    manager
                ),
                observer=observer,
                max_bytes=1024,
            )
        )

        assert (
            missing.availability
            is (
                AppliedChangeComparisonAvailability
                .AVAILABLE
            )
        )
        assert (
            missing.entries[0].state
            is (
                AppliedChangeComparisonEntryState
                .MISSING
            )
        )

        # Changing detached HEAD changes the historical
        # workspace incarnation and must fail closed.
        original_revision = (
            lease.execution_revision
        )

        _integration_git(
            historical_root,
            "add",
            "-A",
        )
        _integration_git(
            historical_root,
            "commit",
            "-m",
            "advance historical revision",
        )

        assert (
            _integration_git(
                historical_root,
                "rev-parse",
                "HEAD",
            )
            != original_revision
        )

        fenced = (
            compare_applied_change_replay_current_state(
                replay=replay,
                journal=(
                    reopened_journal
                ),
                isolation_manager=(
                    manager
                ),
                observer=observer,
                max_bytes=1024,
            )
        )

        assert (
            fenced.availability
            is (
                AppliedChangeComparisonAvailability
                .UNAVAILABLE
            )
        )
        assert (
            fenced.reason
            is (
                AppliedChangeComparisonUnavailableReason
                .HISTORICAL_WORKTREE_UNAVAILABLE
            )
        )
        assert fenced.entries == ()

    finally:
        manager.cleanup(
            task_contract=contract,
            task_id=task_id,
        )
        worktree_temp.cleanup()
