from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Event, Thread
from typing import cast
from uuid import UUID, uuid4

import pytest

from luna.actions import ActionResolver, ToolSelector, build_phase12c_routes
from luna.autonomy import AutonomyLevel, AutonomyPolicy
from luna.context import (
    ContextAuthorityRole,
    ContextBudget,
    ContextClaim,
    ContextClaimType,
    ContextFailureAction,
    ContextIntegrityGate,
    ContextInterpretation,
    ContextLayer,
    ContextRequirement,
    ContextSourceKind,
    LayeredContextCandidate,
    LayeredContextComposer,
)
from luna.continuity import ContinuityService, SQLiteContinuityStore
from luna.contracts import (
    InvalidationControlAction,
    InvalidationLayer,
    RiskLevel,
    TaskContract,
    TaskScope,
    TaskState,
)
from luna.decision_state import (
    DecisionStateService,
    KnowledgeDecisionStateBinding,
)
from luna.knowledge_evolution import (
    KnowledgeApplicabilitySignal,
    KnowledgeApplicabilitySignalState,
    KnowledgeOptionSpaceChangeSignal,
    KnowledgeValiditySignal,
    KnowledgeValiditySignalState,
)
from luna.memory import VerifiedMemoryService
from luna.modeling import (
    ModelFinishReason,
    ModelRequest,
    ModelToolCall,
    ModelUsage,
    ScriptedModelOutput,
    ScriptedTestBackend,
    ScriptedTurn,
)
from luna.planning import AdaptivePlanner
from luna.preparation import TaskPreparer
from luna.recovery import (
    FailureClassifier,
    MinimalChangePolicy,
    RecoveryPolicy,
    WorkspaceIsolationPolicy,
)
from luna.reporting import FinalReportComposer
from luna.runtime import RequestSource, RuntimeActor, RuntimeBudget, RuntimeMode, RuntimeRequest
from luna.runtime.change_inspector import WorkspaceChangeInspector
from luna.runtime.dependencies import RuntimeDependencies, RuntimeLoopDependencies
from luna.runtime.environment import DeterministicFingerprintProvider
from luna.runtime.isolation import GitWorktreeIsolationManager
from luna.runtime.journal import (
    RuntimeControlCommand,
    RuntimeJournalError,
    SideEffectStage,
    SQLiteRuntimeJournal,
)
from luna.runtime.knowledge_evolution import (
    KnowledgeEvolutionRuntimeHandoff,
    KnowledgeEvolutionRuntimeHandoffProvider,
)
from luna.runtime.loop import LunaRuntime
from luna.runtime.models import RuntimeOutcome, RuntimeStopReason
from luna.tools import (
    DispatchOutcome,
    ExactCallApproval,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    build_phase5_registry,
)
from luna.tools.lifecycle import CancellationProbe
from luna.tools.models import ToolArgumentValue
from luna.tools.policy import PolicyDecision
from luna.tools.registry import ToolExecutionContext, ToolExecutionOutput, ToolRegistry
from luna.verification import CompletionGate
from luna.workspace.models import (
    SafeUndoReceiptState,
    WorkspaceReconciliationTargetState,
)
from luna.workspace.store import WorkspaceSnapshotStore


class _CrashAfterFenceDispatcher(ToolDispatcher):
    """Simulate process loss after STARTED is durable but before handler execution."""

    def __init__(self) -> None:
        super().__init__(build_phase5_registry())
        self.call_count = 0
        self.runtime_receipt_id: UUID | None = None

    def dispatch(
        self,
        *,
        request: ToolRequest,
        task_contract: TaskContract,
        policy: ToolPolicy,
        cancellation_probe: CancellationProbe | None = None,
        approval_basis_fingerprint: str | None = None,
        runtime_receipt_id: UUID | None = None,
    ) -> DispatchOutcome:
        self.runtime_receipt_id = runtime_receipt_id
        del (
            request,
            task_contract,
            policy,
            cancellation_probe,
            approval_basis_fingerprint,
        )
        self.call_count += 1
        raise RuntimeError("synthetic crash after side-effect STARTED fence")


class _MutateAfterFirstAllowedAuthorizationDispatcher(ToolDispatcher):
    """Change authoritative workspace state after the early approval preflight."""

    def __init__(self, workspace: Path) -> None:
        super().__init__(build_phase5_registry())
        self._workspace = workspace
        self.mutated = False

    def authorize(
        self,
        *,
        request: ToolRequest,
        task_contract: TaskContract,
        policy: ToolPolicy,
        approval_basis_fingerprint: str | None = None,
    ) -> PolicyDecision:
        decision = super().authorize(
            request=request,
            task_contract=task_contract,
            policy=policy,
            approval_basis_fingerprint=approval_basis_fingerprint,
        )
        if decision.allowed and not self.mutated:
            (self._workspace / "note.txt").write_text("changed-after-preflight\n", encoding="utf-8")
            self.mutated = True
        return decision


class _CooperativeWriteTool:
    """Write once, then cooperatively observe runtime cancellation."""

    def __init__(self, started: Event) -> None:
        self._started = started
        self.call_count = 0

    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        self.call_count += 1
        relative_path = arguments["path"]
        content = arguments["content"]
        if not isinstance(relative_path, str) or not isinstance(content, str):
            raise TypeError("validated write arguments must be strings")
        target = Path(context.task_contract.scope.workspace_root) / relative_path
        target.write_text(content, encoding="utf-8")
        self._started.set()
        while True:
            context.lifecycle.raise_if_cancelled()
            self._started.wait(0.001)


def _cooperative_write_dispatcher(handler: _CooperativeWriteTool) -> ToolDispatcher:
    registry = ToolRegistry()
    registered = build_phase5_registry().get("filesystem.write_text")
    if registered is None:
        raise AssertionError("built-in write tool must remain registered")
    registry.register(registered.spec, handler)
    return ToolDispatcher(registry)


class _RecordingScriptedBackend(ScriptedTestBackend):
    """Scripted backend that retains exact model requests for context assertions."""

    def __init__(self, turns: tuple[ScriptedTurn, ...]) -> None:
        super().__init__(turns)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest):
        self.requests.append(request)
        return super().generate(request)


def _runtime(
    tmp_path,
    backend: ScriptedTestBackend,
    *,
    dispatcher: ToolDispatcher | None = None,
    state_root: Path | None = None,
    knowledge_evolution_handoff_provider: (
        KnowledgeEvolutionRuntimeHandoffProvider | None
    ) = None,
) -> LunaRuntime:
    registry = build_phase5_registry()
    persistence_root = state_root or tmp_path
    persistence_root.mkdir(parents=True, exist_ok=True)
    selector = ToolSelector(registry, build_phase12c_routes())
    core = RuntimeDependencies(
        task_preparer=TaskPreparer(),
        planner=AdaptivePlanner(),
        model_backend=backend,
        tool_dispatcher=dispatcher or ToolDispatcher(registry),
        completion_gate=cast(CompletionGate, object()),
        report_composer=cast(FinalReportComposer, object()),
        continuity_service=ContinuityService(
            SQLiteContinuityStore(persistence_root / "continuity.sqlite3")
        ),
        memory_service=cast(VerifiedMemoryService, object()),
    )
    return LunaRuntime(
        RuntimeLoopDependencies(
            core=core,
            context_composer=LayeredContextComposer(),
            context_integrity_gate=ContextIntegrityGate(),
            decision_state_service=DecisionStateService(),
            action_resolver=ActionResolver(selector),
            failure_classifier=FailureClassifier(),
            recovery_policy=RecoveryPolicy(),
            minimal_change_policy=MinimalChangePolicy(),
            isolation_policy=WorkspaceIsolationPolicy(),
            change_inspector=WorkspaceChangeInspector(),
            runtime_journal=SQLiteRuntimeJournal(persistence_root / "journal.sqlite3"),
            isolation_manager=GitWorktreeIsolationManager(),
            fingerprint_provider=DeterministicFingerprintProvider(),
            knowledge_evolution_handoff_provider=(
                knowledge_evolution_handoff_provider
            ),
        )
    )


def _request(
    tmp_path,
    *,
    task_id=None,
    allowed_tools: tuple[str, ...],
    write: bool = False,
    mode: RuntimeMode = RuntimeMode.EXECUTE,
    runtime_budget: RuntimeBudget | None = None,
    risk_level: RiskLevel = RiskLevel.LOW,
) -> RuntimeRequest:
    active_task_id = task_id or uuid4()
    autonomy_level = (
        AutonomyLevel.LEVEL_3_TASK
        if write and risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        else AutonomyLevel.LEVEL_2_CONTROLLED
        if write
        else AutonomyLevel.LEVEL_1_READ_ONLY
    )
    autonomy = AutonomyPolicy(
        task_id=active_task_id,
        level=autonomy_level,
        allowed_tools=allowed_tools,
        max_risk=(
            risk_level
            if write and risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            else RiskLevel.MEDIUM
            if write
            else RiskLevel.LOW
        ),
    )
    scope = TaskScope(
        workspace_root=str(tmp_path),
        allowed_paths=("note.txt",),
        write_allowed=write,
    )
    return RuntimeRequest(
        task_id=active_task_id,
        raw_request="Perform exactly the requested bounded task.",
        source=RequestSource.TEST,
        actor=RuntimeActor.verified_owner("test-owner"),
        scope=scope,
        autonomy=autonomy,
        runtime_budget=(
            runtime_budget
            if runtime_budget is not None
            else RuntimeBudget.controlled_write(
                max_changed_files=1,
                max_added_lines=10,
                max_deleted_lines=10,
            )
            if write
            else RuntimeBudget()
        ),
        required_conditions=("Use the single Luna runtime loop.",),
        evidence_required=("Structured tool observation.",),
        risk_level=risk_level,
        mode=mode,
        resume_task_id=active_task_id if mode is RuntimeMode.RESUME else None,
    )


def _policy(
    *,
    allowed_tools: tuple[str, ...],
    write: bool = False,
    risk_level: RiskLevel = RiskLevel.LOW,
) -> ToolPolicy:
    autonomy_level = (
        AutonomyLevel.LEVEL_3_TASK
        if write and risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        else AutonomyLevel.LEVEL_2_CONTROLLED
        if write
        else AutonomyLevel.LEVEL_1_READ_ONLY
    )
    return ToolPolicy(
        allowed_tools=allowed_tools,
        autonomy_level=autonomy_level,
        max_risk=(
            risk_level
            if write and risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            else RiskLevel.MEDIUM
            if write
            else RiskLevel.LOW
        ),
    )


def test_read_action_runs_once_then_hands_off_to_verification(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Read the bounded file.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="read-1",
                            tool_name="filesystem.read_text",
                            arguments={"path": "note.txt"},
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(tmp_path, allowed_tools=("filesystem.read_text",))

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.VERIFICATION_PENDING
    assert outcome.state.phase.value == "CHECKPOINTED"
    assert len(outcome.observation_ids) == 1
    assert outcome.usage.model_calls == 1
    assert outcome.usage.tool_calls == 1
    assert backend.call_count == 1
    observations = runtime._deps.runtime_journal.list_observations(request.task_id)
    assert len(observations) == 1
    assert observations[0].outcome.request.tool_name == "filesystem.read_text"
    assert observations[0].outcome.result.stdout_excerpt == "hello"


def test_write_action_is_write_ahead_fenced_and_never_blindly_replayed(tmp_path) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Create one bounded file.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="write-1",
                            tool_name="filesystem.write_text",
                            arguments={
                                "path": "note.txt",
                                "content": "Luna",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(tmp_path, allowed_tools=("filesystem.write_text",), write=True)
    policy = _policy(allowed_tools=("filesystem.write_text",), write=True)

    outcome = runtime.run(request=request, tool_policy=policy)

    assert outcome.stop_reason is RuntimeStopReason.VERIFICATION_PENDING
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "Luna"
    receipts = runtime._deps.runtime_journal.list_for_task(request.task_id)
    assert len(receipts) == 1
    assert receipts[0].stage is SideEffectStage.CHECKPOINTED
    assert receipts[0].outcome is not None
    assert receipts[0].outcome.result.metadata["snapshot_id"]


@pytest.mark.skipif(
    os.name != "nt",
    reason=(
        "runtime-bound SafeUndoReceipt v2 uses "
        "Windows publication evidence"
    ),
)
def test_runtime_side_effect_identity_is_durable_in_workspace_receipt_v2(
    tmp_path: Path,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text=(
                        "Create one runtime-bound "
                        "workspace file."
                    ),
                    tool_calls=(
                        ModelToolCall(
                            call_id=(
                                "write-runtime-workspace-"
                                "binding"
                            ),
                            tool_name=(
                                "filesystem.write_text"
                            ),
                            arguments={
                                "path": "note.txt",
                                "content": "Luna",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=(
                        ModelFinishReason.TOOL_CALLS
                    ),
                )
            ),
        )
    )

    runtime = _runtime(
        tmp_path,
        backend,
    )

    request = _request(
        tmp_path,
        allowed_tools=(
            "filesystem.write_text",
        ),
        write=True,
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(
            allowed_tools=(
                "filesystem.write_text",
            ),
            write=True,
        ),
    )

    assert (
        outcome.stop_reason
        is RuntimeStopReason.VERIFICATION_PENDING
    )

    runtime_receipts = (
        runtime._deps.runtime_journal
        .list_for_task(
            request.task_id
        )
    )

    assert len(runtime_receipts) == 1

    runtime_receipt = runtime_receipts[0]

    assert (
        runtime_receipt.stage
        is SideEffectStage.CHECKPOINTED
    )

    assert runtime_receipt.outcome is not None

    assert (
        runtime_receipt.outcome.request.request_id
        == runtime_receipt.request.request_id
    )

    snapshot_value = (
        runtime_receipt.outcome.result.metadata[
            "snapshot_id"
        ]
    )

    assert isinstance(
        snapshot_value,
        str,
    )

    snapshot_id = UUID(
        snapshot_value
    )

    workspace_store = WorkspaceSnapshotStore(
        runtime_receipt.execution_workspace_root
    )

    workspace_receipt = (
        workspace_store.load_undo_receipt(
            snapshot_id,
            task_id=request.task_id,
        )
    )

    assert workspace_receipt.receipt_version == 2

    assert (
        workspace_receipt.state
        is SafeUndoReceiptState.COMMITTED
    )

    assert (
        workspace_receipt.execution_binding
        is not None
    )

    assert (
        workspace_receipt
        .execution_binding
        .request_id
        == runtime_receipt.request.request_id
    )

    assert (
        workspace_receipt
        .execution_binding
        .runtime_receipt_id
        == runtime_receipt.receipt_id
    )

    assert (
        workspace_receipt
        .prepared_publication_identity
        is not None
    )

    assert (
        workspace_receipt.after_token
        is not None
    )

    assert (
        workspace_receipt
        .prepared_publication_identity
        .matches_after_state_token(
            workspace_receipt.after_token
        )
    )


def test_runtime_journal_persists_workspace_reconciliation_separately_from_dispatch_observation(
    tmp_path: Path,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text=(
                        "Create one reconciliation-"
                        "observable file."
                    ),
                    tool_calls=(
                        ModelToolCall(
                            call_id=(
                                "write-reconciliation-"
                                "journal"
                            ),
                            tool_name=(
                                "filesystem.write_text"
                            ),
                            arguments={
                                "path": "note.txt",
                                "content": "Luna",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=(
                        ModelFinishReason.TOOL_CALLS
                    ),
                )
            ),
        )
    )

    runtime = _runtime(
        tmp_path,
        backend,
    )

    request = _request(
        tmp_path,
        allowed_tools=(
            "filesystem.write_text",
        ),
        write=True,
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(
            allowed_tools=(
                "filesystem.write_text",
            ),
            write=True,
        ),
    )

    assert (
        outcome.stop_reason
        is RuntimeStopReason.VERIFICATION_PENDING
    )

    journal = (
        runtime._deps.runtime_journal
    )

    runtime_receipts = (
        journal.list_for_task(
            request.task_id
        )
    )

    assert len(runtime_receipts) == 1

    runtime_receipt = runtime_receipts[0]

    workspace_store = WorkspaceSnapshotStore(
        runtime_receipt.execution_workspace_root
    )

    reconciliation = (
        workspace_store
        .reconcile_execution_undo_receipt(
            task_id=request.task_id,
            request_id=(
                runtime_receipt
                .request
                .request_id
            ),
            runtime_receipt_id=(
                runtime_receipt.receipt_id
            ),
        )
    )

    assert (
        reconciliation.target_state
        is WorkspaceReconciliationTargetState
        .AFTER_MATCH
    )

    record = (
        journal
        .record_reconciliation_observation(
            receipt=runtime_receipt,
            reconciliation=reconciliation,
        )
    )

    assert (
        record.runtime_receipt_id
        == runtime_receipt.receipt_id
    )
    assert (
        record.request_id
        == runtime_receipt.request.request_id
    )
    assert (
        record.workspace
        == reconciliation
    )

    dispatch_observations = (
        journal.list_observations(
            request.task_id
        )
    )

    reconciliation_observations = (
        journal.list_reconciliation_observations(
            request.task_id
        )
    )

    assert len(dispatch_observations) == 1
    assert len(reconciliation_observations) == 1
    assert (
        reconciliation_observations[0]
        == record
    )

    reopened = SQLiteRuntimeJournal(
        tmp_path / "journal.sqlite3"
    )

    assert reopened.schema_version() == 4
    assert reopened.verify_integrity()

    assert (
        reopened
        .list_reconciliation_observations(
            request.task_id
        )
        == (record,)
    )




def test_runtime_journal_migrates_v2_to_v4_without_losing_existing_control(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "journal.sqlite3"

    initial = SQLiteRuntimeJournal(
        journal_path
    )

    assert initial.schema_version() == 4

    task_id = uuid4()

    control = initial.request_control(
        task_id=task_id,
        command=RuntimeControlCommand.CANCEL,
        reason="preserve across v2 to v4 migration",
    )

    # Reconstruct an on-disk v2 journal from the
    # current v4 database while preserving v1/v2 data.
    with sqlite3.connect(
        journal_path
    ) as connection:
        connection.execute(
            """
            DROP TABLE
            runtime_reconciliation_observations
            """
        )
        connection.execute(
            """
            DROP TABLE
            provider_retry_schedules
            """
        )
        connection.execute(
            """
            DELETE FROM journal_schema
            WHERE version IN (3, 4)
            """
        )
        connection.commit()

    with sqlite3.connect(
        journal_path
    ) as connection:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(version), 0)
            FROM journal_schema
            """
        ).fetchone()

    assert row is not None
    assert int(row[0]) == 2

    reopened = SQLiteRuntimeJournal(
        journal_path
    )

    assert reopened.schema_version() == 4

    assert (
        reopened.latest_control(task_id)
        == control
    )

    assert (
        reopened.list_reconciliation_observations(
            task_id
        )
        == ()
    )

    assert reopened.verify_integrity()


def test_runtime_reconciliation_observation_row_binding_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text=(
                        "Create one reconciliation "
                        "tamper target."
                    ),
                    tool_calls=(
                        ModelToolCall(
                            call_id=(
                                "write-reconciliation-"
                                "tamper"
                            ),
                            tool_name=(
                                "filesystem.write_text"
                            ),
                            arguments={
                                "path": "note.txt",
                                "content": "Luna",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=(
                        ModelFinishReason.TOOL_CALLS
                    ),
                )
            ),
        )
    )

    runtime = _runtime(
        tmp_path,
        backend,
    )

    request = _request(
        tmp_path,
        allowed_tools=(
            "filesystem.write_text",
        ),
        write=True,
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(
            allowed_tools=(
                "filesystem.write_text",
            ),
            write=True,
        ),
    )

    assert (
        outcome.stop_reason
        is RuntimeStopReason.VERIFICATION_PENDING
    )

    journal = runtime._deps.runtime_journal

    receipts = journal.list_for_task(
        request.task_id
    )

    assert len(receipts) == 1

    receipt = receipts[0]

    store = WorkspaceSnapshotStore(
        receipt.execution_workspace_root
    )

    reconciliation = (
        store.reconcile_execution_undo_receipt(
            task_id=request.task_id,
            request_id=(
                receipt.request.request_id
            ),
            runtime_receipt_id=(
                receipt.receipt_id
            ),
        )
    )

    record = (
        journal.record_reconciliation_observation(
            receipt=receipt,
            reconciliation=reconciliation,
        )
    )

    journal_path = tmp_path / "journal.sqlite3"

    with sqlite3.connect(
        journal_path
    ) as connection:
        cursor = connection.execute(
            """
            UPDATE runtime_reconciliation_observations
            SET runtime_receipt_id = ?
            WHERE observation_id = ?
            """,
            (
                str(uuid4()),
                str(record.observation_id),
            ),
        )

        assert cursor.rowcount == 1

        connection.commit()

    reopened = SQLiteRuntimeJournal(
        journal_path
    )

    assert not reopened.verify_integrity()

    with pytest.raises(
        RuntimeJournalError,
        match=(
            "runtime reconciliation observation "
            "row binding mismatch"
        ),
    ):
        reopened.list_reconciliation_observations(
            request.task_id
        )



def test_runtime_journal_resolves_exact_side_effect_execution_provenance(
    tmp_path: Path,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Create one provenance-bound file.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="write-provenance-exact",
                            tool_name="filesystem.write_text",
                            arguments={
                                "path": "note.txt",
                                "content": "Luna",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )

    runtime = _runtime(
        tmp_path,
        backend,
    )
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.write_text",),
        write=True,
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(
            allowed_tools=("filesystem.write_text",),
            write=True,
        ),
    )

    assert (
        outcome.stop_reason
        is RuntimeStopReason.VERIFICATION_PENDING
    )

    receipts = (
        runtime._deps.runtime_journal
        .list_for_task(request.task_id)
    )
    assert len(receipts) == 1

    receipt = receipts[0]
    assert receipt.outcome is not None

    reopened = SQLiteRuntimeJournal(
        tmp_path / "journal.sqlite3"
    )

    provenance = reopened.resolve_execution_provenance(
        task_id=request.task_id,
        request_id=receipt.request.request_id,
        result_id=receipt.outcome.result.result_id,
    )

    assert provenance.receipt_id == receipt.receipt_id
    assert (
        provenance.idempotency_key
        == receipt.idempotency_key
    )
    assert provenance.task_id == request.task_id
    assert (
        provenance.request_id
        == receipt.request.request_id
    )
    assert (
        provenance.result_id
        == receipt.outcome.result.result_id
    )
    assert (
        provenance.execution_workspace_root
        == receipt.execution_workspace_root
    )
    assert (
        provenance.isolation_mode
        == receipt.isolation_mode
    )


def test_runtime_journal_execution_provenance_fails_closed_when_absent(
    tmp_path: Path,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Create one provenance-bound file.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="write-provenance-absent",
                            tool_name="filesystem.write_text",
                            arguments={
                                "path": "note.txt",
                                "content": "Luna",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )

    runtime = _runtime(
        tmp_path,
        backend,
    )
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.write_text",),
        write=True,
    )

    runtime.run(
        request=request,
        tool_policy=_policy(
            allowed_tools=("filesystem.write_text",),
            write=True,
        ),
    )

    receipt = (
        runtime._deps.runtime_journal
        .list_for_task(request.task_id)[0]
    )

    with pytest.raises(
        RuntimeJournalError,
        match=r"exactly one matching receipt; found 0",
    ):
        runtime._deps.runtime_journal.resolve_execution_provenance(
            task_id=request.task_id,
            request_id=receipt.request.request_id,
            result_id=uuid4(),
        )


def test_runtime_journal_execution_provenance_rejects_ambiguous_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Create one provenance-bound file.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="write-provenance-ambiguous",
                            tool_name="filesystem.write_text",
                            arguments={
                                "path": "note.txt",
                                "content": "Luna",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )

    runtime = _runtime(
        tmp_path,
        backend,
    )
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.write_text",),
        write=True,
    )

    runtime.run(
        request=request,
        tool_policy=_policy(
            allowed_tools=("filesystem.write_text",),
            write=True,
        ),
    )

    journal = runtime._deps.runtime_journal
    receipt = journal.list_for_task(
        request.task_id
    )[0]

    assert receipt.outcome is not None

    monkeypatch.setattr(
        journal,
        "list_for_task",
        lambda task_id: (
            receipt,
            receipt,
        )
        if task_id == request.task_id
        else (),
    )

    with pytest.raises(
        RuntimeJournalError,
        match=r"exactly one matching receipt; found 2",
    ):
        journal.resolve_execution_provenance(
            task_id=request.task_id,
            request_id=receipt.request.request_id,
            result_id=receipt.outcome.result.result_id,
        )


@pytest.mark.parametrize(
    "column",
    (
        "idempotency_key",
        "task_id",
        "semantic_fingerprint",
        "stage",
    ),
)
def test_runtime_journal_rejects_side_effect_receipt_locator_row_binding_tamper(
    tmp_path: Path,
    column: str,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Create one bounded file.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="write-row-binding",
                            tool_name="filesystem.write_text",
                            arguments={
                                "path": "note.txt",
                                "content": "Luna",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )

    runtime = _runtime(
        tmp_path,
        backend,
    )

    request = _request(
        tmp_path,
        allowed_tools=("filesystem.write_text",),
        write=True,
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(
            allowed_tools=("filesystem.write_text",),
            write=True,
        ),
    )

    assert (
        outcome.stop_reason
        is RuntimeStopReason.VERIFICATION_PENDING
    )

    receipts = (
        runtime._deps.runtime_journal
        .list_for_task(request.task_id)
    )

    assert len(receipts) == 1

    receipt = receipts[0]

    assert (
        receipt.stage
        is SideEffectStage.CHECKPOINTED
    )

    journal_path = tmp_path / "journal.sqlite3"
    fake_task_id = uuid4()

    replacements = {
        "idempotency_key": sha256(
            b"tampered-side-effect-idempotency-key"
        ).hexdigest(),
        "task_id": str(fake_task_id),
        "semantic_fingerprint": sha256(
            b"tampered-side-effect-semantic-fingerprint"
        ).hexdigest(),
        "stage": SideEffectStage.STARTED.value,
    }

    statements = {
        "idempotency_key": """
            UPDATE side_effect_receipts
            SET idempotency_key = ?
            WHERE idempotency_key = ?
        """,
        "task_id": """
            UPDATE side_effect_receipts
            SET task_id = ?
            WHERE idempotency_key = ?
        """,
        "semantic_fingerprint": """
            UPDATE side_effect_receipts
            SET semantic_fingerprint = ?
            WHERE idempotency_key = ?
        """,
        "stage": """
            UPDATE side_effect_receipts
            SET stage = ?
            WHERE idempotency_key = ?
        """,
    }

    with sqlite3.connect(
        journal_path
    ) as connection:
        cursor = connection.execute(
            statements[column],
            (
                replacements[column],
                receipt.idempotency_key,
            ),
        )

        assert cursor.rowcount == 1

        connection.commit()

    reopened = SQLiteRuntimeJournal(
        journal_path
    )

    assert not reopened.verify_integrity()

    lookup_task_id = (
        fake_task_id
        if column == "task_id"
        else request.task_id
    )

    with pytest.raises(
        RuntimeJournalError,
        match="side-effect receipt row binding mismatch",
    ):
        reopened.list_for_task(
            lookup_task_id
        )


def test_multiple_model_tool_calls_are_blocked_before_dispatch(tmp_path) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Two reads at once.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="a",
                            tool_name="filesystem.read_text",
                            arguments={"path": "a.txt"},
                        ),
                        ModelToolCall(
                            call_id="b",
                            tool_name="filesystem.read_text",
                            arguments={"path": "b.txt"},
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(tmp_path, allowed_tools=("filesystem.read_text",))

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    assert outcome.usage.tool_calls == 0
    assert "exactly one proposed action" in " ".join(outcome.reasons)
    assert outcome.state.invalidation_state is not None
    invalidation = outcome.state.invalidation_state.latest_report
    assert invalidation is not None
    assert invalidation.control_action is InvalidationControlAction.REPLAN
    assert any(item.layer is InvalidationLayer.PLAN_STEP for item in invalidation.impacts)


def test_length_response_is_checkpointed_as_incomplete_without_dispatch(tmp_path) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    finish_reason=ModelFinishReason.LENGTH,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(tmp_path, allowed_tools=("filesystem.read_text",))

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    assert outcome.usage.model_calls == 1
    assert outcome.usage.tool_calls == 0
    assert backend.call_count == 1
    assert "ended with LENGTH and is incomplete" in " ".join(outcome.reasons)
    assert "never blindly retried" in " ".join(outcome.reasons)


def test_length_response_with_partial_tool_call_is_never_dispatched(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Partial proposal",
                    tool_calls=(
                        ModelToolCall(
                            call_id="partial-read",
                            tool_name="filesystem.read_text",
                            arguments={"path": "note.txt"},
                        ),
                    ),
                    finish_reason=ModelFinishReason.LENGTH,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(tmp_path, allowed_tools=("filesystem.read_text",))

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    assert outcome.usage.model_calls == 1
    assert outcome.usage.tool_calls == 0
    assert runtime._deps.runtime_journal.list_observations(request.task_id) == ()
    assert "never executed" in " ".join(outcome.reasons)


def test_length_response_at_runtime_output_limit_reports_budget_exhausted(tmp_path) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    finish_reason=ModelFinishReason.LENGTH,
                    usage=ModelUsage(output_tokens=1),
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_model_output_tokens=1),
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.BUDGET_EXHAUSTED
    assert outcome.usage.model_output_tokens == 1
    assert outcome.usage.tool_calls == 0
    assert "ended with LENGTH and is incomplete" in " ".join(outcome.reasons)


def test_pending_cancel_is_acknowledged_at_safe_boundary_without_model_or_tool_call(
    tmp_path,
) -> None:
    backend = ScriptedTestBackend(())
    runtime = _runtime(tmp_path, backend)
    request = _request(tmp_path, allowed_tools=("filesystem.read_text",))
    control = runtime.cancel(task_id=request.task_id, reason="owner cancelled test")
    assert control.command is RuntimeControlCommand.CANCEL

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.CANCELLED
    assert outcome.usage.model_calls == 0
    assert outcome.usage.tool_calls == 0
    acknowledged = runtime._deps.runtime_journal.latest_control(request.task_id)
    assert acknowledged is not None
    assert acknowledged.acknowledged_at is not None


def test_resume_of_started_side_effect_never_replays_handler(tmp_path) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Create one bounded file.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="write-crash",
                            tool_name="filesystem.write_text",
                            arguments={
                                "path": "note.txt",
                                "content": "must-not-replay",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )
    crashing_dispatcher = _CrashAfterFenceDispatcher()
    runtime = _runtime(tmp_path, backend, dispatcher=crashing_dispatcher)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.write_text",),
        write=True,
    )
    policy = _policy(allowed_tools=("filesystem.write_text",), write=True)

    with pytest.raises(
        RuntimeError,
        match="synthetic crash after side-effect STARTED fence",
    ):
        runtime.run(request=request, tool_policy=policy)

    receipts = runtime._deps.runtime_journal.list_for_task(request.task_id)
    assert len(receipts) == 1
    assert receipts[0].stage is SideEffectStage.STARTED
    assert crashing_dispatcher.call_count == 1
    assert (
        crashing_dispatcher.runtime_receipt_id
        == receipts[0].receipt_id
    )
    assert not (tmp_path / "note.txt").exists()

    resume_backend = ScriptedTestBackend(())
    resumed_runtime = _runtime(tmp_path, resume_backend)
    resume_request = _request(
        tmp_path,
        task_id=request.task_id,
        allowed_tools=("filesystem.write_text",),
        write=True,
        mode=RuntimeMode.RESUME,
    )
    outcome = resumed_runtime.resume(request=resume_request, tool_policy=policy)

    assert outcome.stop_reason is RuntimeStopReason.INTERRUPTED
    assert outcome.usage.tool_calls == 0
    assert resume_backend.call_count == 0
    assert not (tmp_path / "note.txt").exists()
    assert "automatic replay is forbidden" in " ".join(outcome.reasons)

    reconciliations = (
        resumed_runtime._deps.runtime_journal
        .list_reconciliation_observations(
            request.task_id
        )
    )

    assert len(reconciliations) == 1

    reconciliation = reconciliations[0]

    assert (
        reconciliation.runtime_receipt_id
        == receipts[0].receipt_id
    )
    assert (
        reconciliation.request_id
        == receipts[0].request.request_id
    )
    assert (
        reconciliation.workspace.target_state
        is WorkspaceReconciliationTargetState
        .NO_BOUND_RECEIPT
    )
    assert (
        reconciliation.workspace.receipt_state
        is None
    )

    still_started = (
        resumed_runtime._deps.runtime_journal
        .load(receipts[0].idempotency_key)
    )

    assert (
        still_started.stage
        is SideEffectStage.STARTED
    )
    assert still_started.outcome is None


def test_repeated_resume_of_same_started_receipt_reuses_identical_reconciliation_observation(
    tmp_path: Path,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text=(
                        "Create one bounded file for "
                        "repeated resume reconciliation."
                    ),
                    tool_calls=(
                        ModelToolCall(
                            call_id=(
                                "repeat-started-"
                                "reconciliation"
                            ),
                            tool_name=(
                                "filesystem.write_text"
                            ),
                            arguments={
                                "path": "note.txt",
                                "content": "Luna",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=(
                        ModelFinishReason.TOOL_CALLS
                    ),
                )
            ),
        )
    )

    crashing_dispatcher = (
        _CrashAfterFenceDispatcher()
    )

    runtime = _runtime(
        tmp_path,
        backend,
        dispatcher=crashing_dispatcher,
    )

    request = _request(
        tmp_path,
        allowed_tools=(
            "filesystem.write_text",
        ),
        write=True,
    )

    policy = _policy(
        allowed_tools=(
            "filesystem.write_text",
        ),
        write=True,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "synthetic crash after side-effect "
            "STARTED fence"
        ),
    ):
        runtime.run(
            request=request,
            tool_policy=policy,
        )

    receipts = (
        runtime._deps.runtime_journal
        .list_for_task(request.task_id)
    )

    assert len(receipts) == 1

    receipt = receipts[0]

    assert (
        receipt.stage
        is SideEffectStage.STARTED
    )

    resume_request = _request(
        tmp_path,
        task_id=request.task_id,
        allowed_tools=(
            "filesystem.write_text",
        ),
        write=True,
        mode=RuntimeMode.RESUME,
    )

    first_runtime = _runtime(
        tmp_path,
        ScriptedTestBackend(()),
    )

    first = first_runtime.resume(
        request=resume_request,
        tool_policy=policy,
    )

    assert (
        first.stop_reason
        is RuntimeStopReason.INTERRUPTED
    )
    assert first.usage.tool_calls == 0

    first_records = (
        first_runtime._deps.runtime_journal
        .list_reconciliation_observations(
            request.task_id
        )
    )

    assert len(first_records) == 1

    first_record = first_records[0]

    assert (
        first_record.workspace.target_state
        is WorkspaceReconciliationTargetState
        .NO_BOUND_RECEIPT
    )

    second_runtime = _runtime(
        tmp_path,
        ScriptedTestBackend(()),
    )

    second = second_runtime.resume(
        request=resume_request,
        tool_policy=policy,
    )

    assert (
        second.stop_reason
        is RuntimeStopReason.INTERRUPTED
    )
    assert second.usage.tool_calls == 0

    second_records = (
        second_runtime._deps.runtime_journal
        .list_reconciliation_observations(
            request.task_id
        )
    )

    assert second_records == (
        first_record,
    )

    still_started = (
        second_runtime._deps.runtime_journal
        .load(receipt.idempotency_key)
    )

    assert (
        still_started.stage
        is SideEffectStage.STARTED
    )

    assert still_started.outcome is None

    assert (
        second_runtime._deps.runtime_journal
        .list_observations(request.task_id)
        == ()
    )



def test_resume_of_started_workspace_side_effect_records_after_match_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text=(
                        "Create one bounded file before "
                        "the synthetic runtime crash."
                    ),
                    tool_calls=(
                        ModelToolCall(
                            call_id=(
                                "write-crash-after-"
                                "workspace-commit"
                            ),
                            tool_name=(
                                "filesystem.write_text"
                            ),
                            arguments={
                                "path": "note.txt",
                                "content": "Luna",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=(
                        ModelFinishReason.TOOL_CALLS
                    ),
                )
            ),
        )
    )

    runtime = _runtime(
        tmp_path,
        backend,
    )

    request = _request(
        tmp_path,
        allowed_tools=(
            "filesystem.write_text",
        ),
        write=True,
    )

    policy = _policy(
        allowed_tools=(
            "filesystem.write_text",
        ),
        write=True,
    )

    def crash_before_runtime_completion(
        *,
        idempotency_key: str,
        outcome: DispatchOutcome,
    ):
        del idempotency_key, outcome
        raise RuntimeError(
            "synthetic crash after workspace commit "
            "before runtime completion"
        )

    monkeypatch.setattr(
        runtime._deps.runtime_journal,
        "mark_completed",
        crash_before_runtime_completion,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "synthetic crash after workspace commit "
            "before runtime completion"
        ),
    ):
        runtime.run(
            request=request,
            tool_policy=policy,
        )

    assert (
        tmp_path / "note.txt"
    ).read_text(
        encoding="utf-8"
    ) == "Luna"

    receipts = (
        runtime._deps.runtime_journal
        .list_for_task(request.task_id)
    )

    assert len(receipts) == 1

    receipt = receipts[0]

    assert (
        receipt.stage
        is SideEffectStage.STARTED
    )
    assert receipt.outcome is None

    replay_probe = (
        _CrashAfterFenceDispatcher()
    )

    resumed_runtime = _runtime(
        tmp_path,
        ScriptedTestBackend(()),
        dispatcher=replay_probe,
    )

    outcome = resumed_runtime.resume(
        request=_request(
            tmp_path,
            task_id=request.task_id,
            allowed_tools=(
                "filesystem.write_text",
            ),
            write=True,
            mode=RuntimeMode.RESUME,
        ),
        tool_policy=policy,
    )

    assert (
        outcome.stop_reason
        is RuntimeStopReason.INTERRUPTED
    )

    assert replay_probe.call_count == 0
    assert outcome.usage.tool_calls == 0

    assert (
        tmp_path / "note.txt"
    ).read_text(
        encoding="utf-8"
    ) == "Luna"

    assert (
        "automatic replay is forbidden"
        in " ".join(outcome.reasons)
    )

    reconciliations = (
        resumed_runtime._deps.runtime_journal
        .list_reconciliation_observations(
            request.task_id
        )
    )

    assert len(reconciliations) == 1

    reconciliation = reconciliations[0]

    assert (
        reconciliation.runtime_receipt_id
        == receipt.receipt_id
    )
    assert (
        reconciliation.request_id
        == receipt.request.request_id
    )

    assert (
        reconciliation.workspace.receipt_state
        is SafeUndoReceiptState.COMMITTED
    )

    assert (
        reconciliation.workspace.target_state
        is WorkspaceReconciliationTargetState
        .AFTER_MATCH
    )

    assert (
        reconciliation.workspace
        .observed_after_token
        is not None
    )

    still_started = (
        resumed_runtime._deps.runtime_journal
        .load(receipt.idempotency_key)
    )

    assert (
        still_started.stage
        is SideEffectStage.STARTED
    )
    assert still_started.outcome is None

    assert (
        resumed_runtime._deps.runtime_journal
        .list_observations(request.task_id)
        == ()
    )



def test_cancellation_after_side_effect_started_is_fenced_without_replay(tmp_path) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Create one bounded file.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="write-cancelled",
                            tool_name="filesystem.write_text",
                            arguments={
                                "path": "note.txt",
                                "content": "may-have-executed",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )
    started = Event()
    handler = _CooperativeWriteTool(started)
    runtime = _runtime(
        tmp_path,
        backend,
        dispatcher=_cooperative_write_dispatcher(handler),
    )
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.write_text",),
        write=True,
    )
    policy = _policy(allowed_tools=("filesystem.write_text",), write=True)
    outcomes: list[RuntimeOutcome] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            outcomes.append(runtime.run(request=request, tool_policy=policy))
        except BaseException as exc:  # pragma: no cover - assertion reports thread failure
            errors.append(exc)

    worker = Thread(target=run)
    worker.start()
    assert started.wait(timeout=10)
    runtime.cancel(task_id=request.task_id, reason="cancel after handler start")
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert errors == []
    assert len(outcomes) == 1
    assert outcomes[0].stop_reason is RuntimeStopReason.INTERRUPTED
    assert "automatic replay is forbidden" in " ".join(outcomes[0].reasons)
    assert handler.call_count == 1
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "may-have-executed"

    receipts = runtime._deps.runtime_journal.list_for_task(request.task_id)
    assert len(receipts) == 1
    assert receipts[0].stage is SideEffectStage.CHECKPOINTED
    assert receipts[0].outcome is not None
    assert receipts[0].outcome.result.error_class == "ToolExecutionCancellationAmbiguous"

    replay_probe = _CrashAfterFenceDispatcher()
    resumed = _runtime(
        tmp_path,
        ScriptedTestBackend(()),
        dispatcher=replay_probe,
    ).resume(
        request=_request(
            tmp_path,
            task_id=request.task_id,
            allowed_tools=("filesystem.write_text",),
            write=True,
            mode=RuntimeMode.RESUME,
        ),
        tool_policy=policy,
    )

    assert replay_probe.call_count == 0
    assert resumed.usage.tool_calls == 0


def test_zero_model_call_budget_blocks_without_invalid_budget_outcome(tmp_path) -> None:
    backend = ScriptedTestBackend(())
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_model_calls=0),
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    assert outcome.usage.model_calls == 0
    assert outcome.usage.tool_calls == 0
    assert backend.call_count == 0
    assert "disables model calls" in " ".join(outcome.reasons)


def test_zero_tool_call_budget_blocks_before_dispatch(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Read one file.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="read-disabled",
                            tool_name="filesystem.read_text",
                            arguments={"path": "note.txt"},
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_tool_calls=0),
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    assert outcome.usage.model_calls == 1
    assert outcome.usage.tool_calls == 0
    assert "disables tool calls" in " ".join(outcome.reasons)


def test_high_risk_worktree_stays_effective_and_observation_reaches_next_turn(
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "luna-test@example.invalid"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Luna Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "core.autocrlf", "true"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "note.txt").write_bytes(b"original\n")
    subprocess.run(["git", "add", "note.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    backend = _RecordingScriptedBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Perform the isolated high-risk write.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="high-risk-write",
                            tool_name="filesystem.write_text",
                            arguments={
                                "path": "note.txt",
                                "content": "isolated\n",
                                "expected_sha256": sha256(
                                    b"original\n"
                                ).hexdigest(),
                                "create_if_missing": False,
                            },
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Reinspect the isolated result before verification handoff.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="isolated-read",
                            tool_name="filesystem.read_text",
                            arguments={"path": "note.txt"},
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )
    runtime = _runtime(
        repo,
        backend,
        state_root=tmp_path / "runtime-state",
    )
    runtime_budget = RuntimeBudget.controlled_write(
        max_changed_files=1,
        max_added_lines=20,
        max_deleted_lines=20,
    )
    allowed_tools = ("filesystem.write_text", "filesystem.read_text")
    request = _request(
        repo,
        allowed_tools=allowed_tools,
        write=True,
        risk_level=RiskLevel.HIGH,
        runtime_budget=runtime_budget,
    )
    policy = _policy(
        allowed_tools=allowed_tools,
        write=True,
        risk_level=RiskLevel.HIGH,
    )

    outcome = runtime.run(request=request, tool_policy=policy)
    receipts = runtime._deps.runtime_journal.list_for_task(request.task_id)
    observations = runtime._deps.runtime_journal.list_observations(request.task_id)

    assert outcome.stop_reason is RuntimeStopReason.VERIFICATION_PENDING
    assert len(receipts) == 1
    assert receipts[0].stage is SideEffectStage.CHECKPOINTED
    assert receipts[0].isolation_mode == "WORKTREE"
    isolated_root = Path(receipts[0].execution_workspace_root)

    isolated_revision = subprocess.run(
        [
            "git",
            "-C",
            str(isolated_root),
            "rev-parse",
            "HEAD",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert receipts[0].execution_revision is not None
    assert (
        receipts[0].execution_revision
        == isolated_revision
    )
    assert isolated_root != repo.resolve()
    assert (repo / "note.txt").read_text(encoding="utf-8") == "original\n"
    assert (isolated_root / "note.txt").read_text(encoding="utf-8") == "isolated\n"
    assert len(observations) == 2
    assert observations[-1].outcome.request.tool_name == "filesystem.read_text"
    assert observations[-1].outcome.result.stdout_excerpt == "isolated"
    assert len(backend.requests) == 2
    first_turn_text = "\n".join(message.content for message in backend.requests[0].messages)
    assert '"primary_source": "WORKSPACE_TOOL"' in first_turn_text
    assert '"query": "OBSERVE_STATE:' in first_turn_text
    assert '"stop_conditions": [' in first_turn_text
    second_turn_text = "\n".join(message.content for message in backend.requests[1].messages)
    assert "runtime://observation/" in second_turn_text
    assert str(observations[0].observation_id) in second_turn_text
    assert '"local_judgment"' in second_turn_text
    assert '"decision_compression"' in second_turn_text
    assert '"decision_alternatives"' in second_turn_text
    assert '"decision_control"' in second_turn_text
    assert '"retrieval_strategy"' in second_turn_text
    assert '"tool_advice"' in second_turn_text
    assert '"capability_selection"' not in second_turn_text
    assert "advisory_only_no_authority" in second_turn_text
    assert '"c2_authority_granted": false' in second_turn_text
    assert "expected_sha256" not in second_turn_text
    observed_searches = runtime._policy_agent.observed_retrieval_strategy_fingerprints(
        request.task_id
    )
    assert len(observed_searches) == 1

    runtime.cancel(task_id=request.task_id, reason="test cleanup")
    resume_request = _request(
        repo,
        task_id=request.task_id,
        allowed_tools=allowed_tools,
        write=True,
        risk_level=RiskLevel.HIGH,
        runtime_budget=runtime_budget,
        mode=RuntimeMode.RESUME,
    )
    cancelled = runtime.resume(request=resume_request, tool_policy=policy)
    assert cancelled.stop_reason is RuntimeStopReason.CANCELLED
    assert not isolated_root.exists()


def test_wave1_context_integrity_blocks_conflicting_critical_context(tmp_path) -> None:
    backend = ScriptedTestBackend(())
    runtime = _runtime(tmp_path, backend)
    request = _request(tmp_path, allowed_tools=("read_text_file",))
    observed_at = datetime(2026, 8, 9, 17, 0, tzinfo=UTC)
    claims = (
        ContextClaim(
            task_id=request.task_id,
            key="current_branch",
            value="main",
            claim_type=ContextClaimType.REPOSITORY_STATE,
            source_kind=ContextSourceKind.COMMAND_OUTPUT,
            source_ref="git://branch/main",
            authority_role=ContextAuthorityRole.CURRENT_OBSERVATION,
            observed_at=observed_at,
            verified=True,
            evidence_refs=("git:branch:main",),
        ),
        ContextClaim(
            task_id=request.task_id,
            key="current_branch",
            value="feature/wave1",
            claim_type=ContextClaimType.REPOSITORY_STATE,
            source_kind=ContextSourceKind.COMMAND_OUTPUT,
            source_ref="git://branch/feature-wave1",
            authority_role=ContextAuthorityRole.CURRENT_OBSERVATION,
            observed_at=observed_at,
            verified=True,
            evidence_refs=("git:branch:feature-wave1",),
        ),
    )
    payload = request.model_dump(mode="json")
    payload.update(
        {
            "context_claims": [item.model_dump(mode="json") for item in claims],
            "context_requirements": [
                ContextRequirement(
                    key="current_branch",
                    claim_type=ContextClaimType.REPOSITORY_STATE,
                    failure_action=ContextFailureAction.STOP,
                ).model_dump(mode="json")
            ],
        }
    )
    request = RuntimeRequest.model_validate(payload)

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("read_text_file",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.CONFLICTING_EVIDENCE
    assert "conflicting_context:current_branch" in outcome.reasons
    assert backend.requests == [] if hasattr(backend, "requests") else True


def test_c4_soft_preference_reaches_model_as_advisory_without_state_bloat(tmp_path) -> None:
    backend = _RecordingScriptedBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Yield after reading C4 advisory context.",
                    finish_reason=ModelFinishReason.STOP,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
    ).model_copy(update={"soft_preferences": ("Prefer concise output.",)})

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.usage.model_calls == 1
    assert outcome.state.specification_judgment is not None
    assert outcome.state.specification_judgment.accepted_preference_refs
    model_request = backend.requests[0]
    c4_messages = tuple(
        message for message in model_request.messages if message.name == "c4_specification"
    )
    assert len(c4_messages) == 1
    assert '"accepted_preference_count": 1' in c4_messages[0].content
    assert '"preference_details_optional": true' in c4_messages[0].content
    assert '"authority": false' in c4_messages[0].content
    preference_message = next(
        message for message in model_request.messages if message.name == "c4_preferences"
    )
    assert '"preferences": ["Prefer concise output."]' in preference_message.content
    assert '"optional": true' in preference_message.content
    assert '"authority": false' in preference_message.content
    task_state_message = next(
        message for message in model_request.messages if "runtime://task-state" in message.content
    )
    assert '"specification_judgment"' not in task_state_message.content


def test_c4_large_soft_preference_is_omitted_instead_of_blocking_tight_model_window(
    tmp_path,
) -> None:
    backend = _RecordingScriptedBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Yield without optional preference detail.",
                    finish_reason=ModelFinishReason.STOP,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_model_request_estimated_tokens=2200),
    ).model_copy(update={"soft_preferences": ("p" * 4000,)})

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.usage.model_calls == 1
    model_request = backend.requests[0]
    c4_message = next(
        message for message in model_request.messages if message.name == "c4_specification"
    )
    assert '"accepted_preference_count": 1' in c4_message.content
    assert '"preference_details_optional": true' in c4_message.content
    assert not any(
        message.name == "c4_preferences" for message in model_request.messages
    )


def test_c4_verified_project_policy_refines_model_advisory_after_c1_readiness(
    tmp_path,
) -> None:
    backend = _RecordingScriptedBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Yield after respecting verified project policy.",
                    finish_reason=ModelFinishReason.STOP,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
    )
    policy_statement = "Do not modify generated files."
    claim = ContextClaim(
        task_id=request.task_id,
        key="generated_files_policy",
        value=policy_statement,
        claim_type=ContextClaimType.PROJECT_POLICY,
        source_kind=ContextSourceKind.DOCUMENT,
        source_ref="repo://CONTRIBUTING.md",
        authority_role=ContextAuthorityRole.CANONICAL_PROJECT,
        verified=True,
        evidence_refs=("repo:CONTRIBUTING.md#generated-files",),
    )
    payload = request.model_dump(mode="json")
    payload.update(
        {
            "context_claims": [claim.model_dump(mode="json")],
            "context_requirements": [
                ContextRequirement(
                    key="generated_files_policy",
                    claim_type=ContextClaimType.PROJECT_POLICY,
                ).model_dump(mode="json")
            ],
        }
    )
    request = RuntimeRequest.model_validate(payload)

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.usage.model_calls == 1
    assert outcome.state.decision_state is not None
    assert outcome.state.specification_judgment is not None
    assert any(
        item.kind.value == "PROJECT_POLICY"
        for item in outcome.state.specification_judgment.constraints
    )
    assert outcome.state.specification_judgment.context_basis_refs
    current = DecisionStateService.current_assumptions(outcome.state.decision_state)
    project_policy = next(
        item for item in current if item.claim_type == ContextClaimType.PROJECT_POLICY.value
    )
    assert project_policy.status.value == "SUPPORTED"
    model_request = backend.requests[0]
    c4_message = next(
        message for message in model_request.messages if message.name == "c4_specification"
    )
    assert policy_statement in c4_message.content
    assert (
        '"project_policies": ["Do not modify generated files."]'
        in c4_message.content
    )
    assert '"authority": false' in c4_message.content
    task_state_message = next(
        message for message in model_request.messages if "runtime://task-state" in message.content
    )
    assert '"specification_judgment"' not in task_state_message.content


def test_c4_new_verified_project_policy_on_resume_requires_replan_before_model_call(
    tmp_path,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Yield before any action.",
                    finish_reason=ModelFinishReason.STOP,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
    )
    policy = _policy(allowed_tools=("filesystem.read_text",))

    initial = runtime.run(request=request, tool_policy=policy)

    assert initial.stop_reason is RuntimeStopReason.BLOCKED
    assert initial.state.plan is not None
    assert backend.call_count == 1

    policy_statement = "Do not modify generated files."
    claim = ContextClaim(
        task_id=request.task_id,
        key="generated_files_policy",
        value=policy_statement,
        claim_type=ContextClaimType.PROJECT_POLICY,
        source_kind=ContextSourceKind.DOCUMENT,
        source_ref="repo://CONTRIBUTING.md",
        authority_role=ContextAuthorityRole.CANONICAL_PROJECT,
        verified=True,
        evidence_refs=("repo:CONTRIBUTING.md#generated-files",),
    )
    resume_request = _request(
        tmp_path,
        task_id=request.task_id,
        allowed_tools=("filesystem.read_text",),
        mode=RuntimeMode.RESUME,
    )
    payload = resume_request.model_dump(mode="json")
    payload.update(
        {
            "context_claims": [claim.model_dump(mode="json")],
            "context_requirements": [
                ContextRequirement(
                    key="generated_files_policy",
                    claim_type=ContextClaimType.PROJECT_POLICY,
                ).model_dump(mode="json")
            ],
        }
    )
    resume_request = RuntimeRequest.model_validate(payload)

    resumed = runtime.resume(request=resume_request, tool_policy=policy)

    assert resumed.stop_reason is RuntimeStopReason.BLOCKED
    assert resumed.state.plan is not None
    assert resumed.state.specification_judgment is not None
    assert any(
        item.kind.value == "PROJECT_POLICY"
        and item.statement == policy_statement
        for item in resumed.state.specification_judgment.constraints
    )
    assert "acceptance_backchain_basis_invalidated" in resumed.reasons
    assert "changed_basis_replan_required" in resumed.reasons
    assert any(
        reason.startswith("invalidated_basis:acceptance_backchain:")
        for reason in resumed.reasons
    )
    assert resumed.state.invalidation_state is not None
    invalidation = resumed.state.invalidation_state.latest_report
    assert invalidation is not None
    assert any(
        item.layer is InvalidationLayer.ACCEPTANCE_BACKCHAIN
        for item in invalidation.impacts
    )
    assert backend.call_count == 1


def test_c4_hard_project_policy_conflict_blocks_before_planning_and_model_call(
    tmp_path,
) -> None:
    backend = ScriptedTestBackend(())
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
    )
    claim = ContextClaim(
        task_id=request.task_id,
        key="write_policy",
        value="write_allowed:true",
        claim_type=ContextClaimType.PROJECT_POLICY,
        source_kind=ContextSourceKind.DOCUMENT,
        source_ref="repo://CONTRIBUTING.md",
        authority_role=ContextAuthorityRole.CANONICAL_PROJECT,
        verified=True,
        evidence_refs=("repo:CONTRIBUTING.md#write-policy",),
    )
    payload = request.model_dump(mode="json")
    payload.update(
        {
            "context_claims": [claim.model_dump(mode="json")],
            "context_requirements": [
                ContextRequirement(
                    key="write_policy",
                    claim_type=ContextClaimType.PROJECT_POLICY,
                ).model_dump(mode="json")
            ],
        }
    )
    request = RuntimeRequest.model_validate(payload)

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    assert outcome.usage.model_calls == 0
    assert backend.call_count == 0
    assert outcome.state.specification_judgment is not None
    assert outcome.state.specification_judgment.action.value == "STOP_VERIFY"
    assert any(
        conflict.reason_code == "project_policy_cannot_widen_authority_boundary"
        for conflict in outcome.state.specification_judgment.conflicts
    )


def test_model_request_window_compacts_optional_context_before_backend_call(tmp_path) -> None:
    backend = _RecordingScriptedBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Yield after observing the projected request.",
                    finish_reason=ModelFinishReason.STOP,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_model_request_estimated_tokens=2200),
    )
    large_optional = LayeredContextCandidate.from_text(
        layer=ContextLayer.WORKSPACE,
        kind=ContextSourceKind.DOCUMENT,
        locator="file://large-optional",
        text="x" * 4000,
        priority=1,
        required=False,
        interpretation=ContextInterpretation.DATA_ONLY,
        verified=True,
    )
    request = request.model_copy(
        update={"layered_context_candidates": (large_optional,)}
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.usage.model_calls == 1
    assert len(backend.requests) == 1
    model_request = backend.requests[0]
    message_text = "\n".join(message.content for message in model_request.messages)
    message_names = {message.name for message in model_request.messages}
    assert "context_window_projection" in message_names
    assert "file://large-optional" not in message_text
    assert "runtime://task-contract" in message_text
    assert "runtime://task-state" in message_text
    assert '"invalidation_state"' not in message_text
    assert '"specification_judgment"' not in message_text
    assert tuple(spec.name for spec in model_request.available_tools) == (
        "filesystem.read_text",
    )


def test_model_request_window_blocks_before_backend_call(tmp_path) -> None:
    backend = ScriptedTestBackend(())
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_model_request_estimated_tokens=1),
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    assert outcome.usage.model_calls == 0
    assert outcome.usage.model_input_tokens == 0
    assert outcome.usage.tool_calls == 0
    assert backend.call_count == 0
    assert "model request cannot fit within per-request estimated window" in " ".join(
        outcome.reasons
    )


def test_zero_model_request_window_disables_provider_call(tmp_path) -> None:
    backend = ScriptedTestBackend(())
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_model_request_estimated_tokens=0),
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    assert outcome.usage.model_calls == 0
    assert backend.call_count == 0
    assert "disables estimated model request tokens" in " ".join(outcome.reasons)


def test_default_model_request_window_exceeds_canonical_context_budget() -> None:
    runtime_budget = RuntimeBudget()
    context_budget = ContextBudget()

    assert (
        runtime_budget.max_model_request_estimated_tokens
        > context_budget.max_estimated_tokens
    )


def test_high_risk_exact_call_approval_blocks_before_side_effect_preparation(
    tmp_path,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Request one exact rollback action.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="rollback-needs-approval",
                            tool_name="workspace.rollback",
                            arguments={"snapshot_id": str(uuid4())},
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("workspace.rollback",),
        write=True,
        risk_level=RiskLevel.HIGH,
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(
            allowed_tools=("workspace.rollback",),
            write=True,
            risk_level=RiskLevel.HIGH,
        ),
    )

    assert outcome.stop_reason is RuntimeStopReason.PERMISSION_DENIED
    assert outcome.usage.model_calls == 1
    assert outcome.usage.tool_calls == 0
    assert runtime._deps.runtime_journal.list_for_task(request.task_id) == ()
    assert any(
        "exact call is not owner-approved" in reason
        and "call=" in reason
        and "basis=" in reason
        for reason in outcome.reasons
    )


def test_exact_call_approval_can_resume_same_call_on_unchanged_runtime_basis(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    snapshot_id = str(uuid4())
    turn = ScriptedTurn(
        output=ScriptedModelOutput(
            text="Request the same bounded rollback.",
            tool_calls=(
                ModelToolCall(
                    call_id="rollback-exact",
                    tool_name="workspace.rollback",
                    arguments={"snapshot_id": snapshot_id},
                ),
            ),
            finish_reason=ModelFinishReason.TOOL_CALLS,
        )
    )
    backend = ScriptedTestBackend((turn, turn))
    runtime = _runtime(workspace, backend, state_root=state_root)
    request = _request(
        workspace,
        allowed_tools=("workspace.rollback",),
        write=True,
        risk_level=RiskLevel.HIGH,
    )
    base_policy = _policy(
        allowed_tools=("workspace.rollback",),
        write=True,
        risk_level=RiskLevel.HIGH,
    )

    denied = runtime.run(request=request, tool_policy=base_policy)
    approval_reason = next(
        reason
        for reason in denied.reasons
        if "exact call is not owner-approved" in reason
    )
    call_fingerprint = approval_reason.split("call=", 1)[1].split(";", 1)[0]
    basis_fingerprint = approval_reason.split("basis=", 1)[1]
    proposed_request = ToolRequest(
        task_id=request.task_id,
        trace_id=uuid4(),
        tool_name="workspace.rollback",
        arguments={"snapshot_id": snapshot_id},
    )
    assert proposed_request.exact_call_fingerprint() == call_fingerprint
    approval = ExactCallApproval.bind(
        proposed_request,
        basis_fingerprint=basis_fingerprint,
        approved_by="owner:test",
        evidence_ref="phase12e:test:exact-call-approval",
    )
    approved_policy = base_policy.model_copy(
        update={"exact_call_approvals": (approval,)}
    )
    resume_request = _request(
        workspace,
        task_id=request.task_id,
        allowed_tools=("workspace.rollback",),
        write=True,
        risk_level=RiskLevel.HIGH,
        mode=RuntimeMode.RESUME,
    )

    resumed = runtime.resume(request=resume_request, tool_policy=approved_policy)

    assert denied.stop_reason is RuntimeStopReason.PERMISSION_DENIED
    assert denied.usage.tool_calls == 0
    assert resumed.usage.tool_calls == 1
    assert not any("exact-call approval basis" in reason for reason in resumed.reasons)


def test_runtime_rechecks_fresh_basis_after_early_exact_call_preflight(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    snapshot_id = str(uuid4())
    turn = ScriptedTurn(
        output=ScriptedModelOutput(
            text="Request the same bounded rollback.",
            tool_calls=(
                ModelToolCall(
                    call_id="rollback-stale-basis",
                    tool_name="workspace.rollback",
                    arguments={"snapshot_id": snapshot_id},
                ),
            ),
            finish_reason=ModelFinishReason.TOOL_CALLS,
        )
    )
    dispatcher = _MutateAfterFirstAllowedAuthorizationDispatcher(workspace)
    runtime = _runtime(
        workspace,
        ScriptedTestBackend((turn, turn)),
        dispatcher=dispatcher,
        state_root=state_root,
    )
    request = _request(
        workspace,
        allowed_tools=("workspace.rollback",),
        write=True,
        risk_level=RiskLevel.HIGH,
    )
    base_policy = _policy(
        allowed_tools=("workspace.rollback",),
        write=True,
        risk_level=RiskLevel.HIGH,
    )

    denied = runtime.run(request=request, tool_policy=base_policy)
    approval_reason = next(
        reason
        for reason in denied.reasons
        if "exact call is not owner-approved" in reason
    )
    basis_fingerprint = approval_reason.split("basis=", 1)[1]
    proposed_request = ToolRequest(
        task_id=request.task_id,
        trace_id=uuid4(),
        tool_name="workspace.rollback",
        arguments={"snapshot_id": snapshot_id},
    )
    approval = ExactCallApproval.bind(
        proposed_request,
        basis_fingerprint=basis_fingerprint,
        approved_by="owner:test",
        evidence_ref="phase12e:test:stale-basis",
    )
    approved_policy = base_policy.model_copy(
        update={"exact_call_approvals": (approval,)}
    )
    resume_request = _request(
        workspace,
        task_id=request.task_id,
        allowed_tools=("workspace.rollback",),
        write=True,
        risk_level=RiskLevel.HIGH,
        mode=RuntimeMode.RESUME,
    )

    resumed = runtime.resume(request=resume_request, tool_policy=approved_policy)

    assert dispatcher.mutated
    assert resumed.stop_reason is RuntimeStopReason.PERMISSION_DENIED
    assert resumed.usage.tool_calls == 0
    assert runtime._deps.runtime_journal.list_for_task(request.task_id) == ()
    assert any("basis no longer matches" in reason for reason in resumed.reasons)


def test_runtime_exact_call_approval_basis_tracks_fresh_workspace_state(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    runtime = _runtime(workspace, ScriptedTestBackend(()), state_root=state_root)
    contract = TaskContract(
        objective="Bind approval to fresh workspace state.",
        required_conditions=("Workspace changes invalidate stale approval basis.",),
        evidence_required=("Runtime-owned workspace fingerprint",),
        scope=TaskScope(
            workspace_root=str(workspace),
            allowed_paths=("note.txt",),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
    )
    state = TaskState(task_id=contract.task_id, contract=contract)

    first = runtime._approval_basis_fingerprint(
        state=state,
        task_contract=contract,
        workspace_root=str(workspace),
    )
    repeated = runtime._approval_basis_fingerprint(
        state=state,
        task_contract=contract,
        workspace_root=str(workspace),
    )
    (workspace / "note.txt").write_text("changed\n", encoding="utf-8")
    changed = runtime._approval_basis_fingerprint(
        state=state,
        task_contract=contract,
        workspace_root=str(workspace),
    )

    assert repeated == first
    assert changed != first
# C2B-G1_RUNTIME_POLICY_CONTINUITY_TESTS_BEGIN

def _c2b_g1_requirement(key: str) -> ContextRequirement:
    return ContextRequirement(
        key=key,
        claim_type=ContextClaimType.REPOSITORY_STATE,
    )


def test_c2b_g1_fresh_runtime_checkpoint_persists_explicit_empty_policy(tmp_path) -> None:
    backend = ScriptedTestBackend(())
    runtime = _runtime(tmp_path, backend)
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_model_calls=0),
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    store = runtime._deps.core.continuity_service.store
    stored = store.load_latest(request.task_id)
    bound = store.load_checkpoint_cognitive_policy(
        stored.envelope.checkpoint.checkpoint_id
    )
    assert bound.policy.requirements == ()


def test_c2b_g1_resume_gate_failure_forward_carries_current_policy(tmp_path) -> None:
    runtime = _runtime(tmp_path, ScriptedTestBackend(()))
    initial_request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_model_calls=0),
    )
    policy = _policy(allowed_tools=("filesystem.read_text",))
    runtime.run(request=initial_request, tool_policy=policy)

    store = runtime._deps.core.continuity_service.store
    source = store.load_latest(initial_request.task_id)
    requirement = _c2b_g1_requirement("g1_current_repository_state")
    resume_request = _request(
        tmp_path,
        task_id=initial_request.task_id,
        allowed_tools=("filesystem.read_text",),
        mode=RuntimeMode.RESUME,
    )
    payload = resume_request.model_dump(mode="json")
    payload["context_requirements"] = [requirement.model_dump(mode="json")]
    resume_request = RuntimeRequest.model_validate(payload)
    caller_requirements = resume_request.context_requirements

    resumed = runtime.resume(request=resume_request, tool_policy=policy)

    assert resumed.stop_reason is RuntimeStopReason.CONTEXT_INCOMPLETE
    assert resume_request.context_requirements == caller_requirements
    latest = store.load_latest(initial_request.task_id)
    assert latest.envelope.checkpoint.checkpoint_id != source.envelope.checkpoint.checkpoint_id
    bound = store.load_checkpoint_cognitive_policy(
        latest.envelope.checkpoint.checkpoint_id
    )
    assert bound.policy.requirements == caller_requirements


def test_c2b_g1_legacy_checkpoint_upgrades_current_policy_forward(tmp_path) -> None:
    import sqlite3

    runtime = _runtime(tmp_path, ScriptedTestBackend(()))
    initial_request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_model_calls=0),
    )
    policy = _policy(allowed_tools=("filesystem.read_text",))
    runtime.run(request=initial_request, tool_policy=policy)

    store = runtime._deps.core.continuity_service.store
    source = store.load_latest(initial_request.task_id)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "DELETE FROM checkpoint_cognitive_policies WHERE checkpoint_id = ?",
            (str(source.envelope.checkpoint.checkpoint_id),),
        )
    assert store.verify_integrity().valid

    requirement = _c2b_g1_requirement("g1_legacy_current_repository_state")
    resume_request = _request(
        tmp_path,
        task_id=initial_request.task_id,
        allowed_tools=("filesystem.read_text",),
        mode=RuntimeMode.RESUME,
    )
    payload = resume_request.model_dump(mode="json")
    payload["context_requirements"] = [requirement.model_dump(mode="json")]
    resume_request = RuntimeRequest.model_validate(payload)

    resumed = runtime.resume(request=resume_request, tool_policy=policy)

    assert resumed.stop_reason is RuntimeStopReason.CONTEXT_INCOMPLETE
    latest = store.load_latest(initial_request.task_id)
    assert latest.envelope.checkpoint.checkpoint_id != source.envelope.checkpoint.checkpoint_id
    bound = store.load_checkpoint_cognitive_policy(
        latest.envelope.checkpoint.checkpoint_id
    )
    assert bound.policy.requirements == resume_request.context_requirements


def test_c2b_g1_corrupt_bound_policy_fails_safe_without_advancing_checkpoint(tmp_path) -> None:
    import sqlite3

    backend = ScriptedTestBackend(())
    runtime = _runtime(tmp_path, backend)
    initial_request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_model_calls=0),
    )
    policy = _policy(allowed_tools=("filesystem.read_text",))
    runtime.run(request=initial_request, tool_policy=policy)

    store = runtime._deps.core.continuity_service.store
    source = store.load_latest(initial_request.task_id)
    source_id = source.envelope.checkpoint.checkpoint_id
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE checkpoint_cognitive_policies SET policy_id = ? WHERE checkpoint_id = ?",
            ("missing-cognitive-policy-artifact", str(source_id)),
        )

    resume_request = _request(
        tmp_path,
        task_id=initial_request.task_id,
        allowed_tools=("filesystem.read_text",),
        mode=RuntimeMode.RESUME,
    )
    resumed = runtime.resume(request=resume_request, tool_policy=policy)

    assert resumed.stop_reason is RuntimeStopReason.INTEGRITY_FAILURE
    assert backend.call_count == 0
    assert store.load_latest(initial_request.task_id).envelope.checkpoint.checkpoint_id == source_id
    assert "cognitive rehydration policy integrity failure" in " ".join(resumed.reasons)

# C2B-G1_RUNTIME_POLICY_CONTINUITY_TESTS_END


# KE_RUNTIME_HANDOFF_TESTS_BEGIN


class _KnowledgeEvolutionHandoffTestProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, int]] = []
        self._assumption_id: UUID | None = None
        self._mode: str | None = None
        self._revision_delta = 0

    def configure(
        self,
        *,
        assumption_id: UUID,
        mode: str,
        revision_delta: int = 0,
    ) -> None:
        if mode not in {"VERIFY", "CONTRADICT"}:
            raise ValueError("unsupported KE runtime test mode")
        self._assumption_id = assumption_id
        self._mode = mode
        self._revision_delta = revision_delta

    def handoff_for_turn(
        self,
        *,
        task_id: UUID,
        step_id: UUID,
        decision_state_revision: int,
    ) -> KnowledgeEvolutionRuntimeHandoff | None:
        self.calls.append(
            (
                task_id,
                step_id,
                decision_state_revision,
            )
        )

        if self._assumption_id is None or self._mode is None:
            return None

        knowledge_ref = "knowledge:test:runtime-owner-output"

        validity = KnowledgeValiditySignal(
            knowledge_ref=knowledge_ref,
            state=(
                KnowledgeValiditySignalState.CONTRADICTED
                if self._mode == "CONTRADICT"
                else KnowledgeValiditySignalState.UNRESOLVED
            ),
            source_ref="owner://ke-runtime/validity",
            evidence_refs=(
                ("evidence:ke-runtime:contradiction",)
                if self._mode == "CONTRADICT"
                else ()
            ),
            provenance_refs=("owner:ke-runtime:validity",),
        )

        applicability = KnowledgeApplicabilitySignal(
            knowledge_ref=knowledge_ref,
            state=KnowledgeApplicabilitySignalState.UNRESOLVED,
            source_ref="owner://ke-runtime/applicability",
            condition_refs=("condition:ke-runtime:active-task",),
            provenance_refs=("owner:ke-runtime:applicability",),
        )

        option_space_change = KnowledgeOptionSpaceChangeSignal(
            knowledge_ref=knowledge_ref,
            material_change=False,
            source_ref="owner://ke-runtime/option-space",
            provenance_refs=("owner:ke-runtime:option-space",),
        )

        binding = KnowledgeDecisionStateBinding(
            task_id=task_id,
            knowledge_ref=knowledge_ref,
            assumption_id=self._assumption_id,
            provenance_refs=("owner:ke-runtime:decision-state-binding",),
        )

        return KnowledgeEvolutionRuntimeHandoff(
            task_id=task_id,
            step_id=step_id,
            source_decision_state_revision=(
                decision_state_revision + self._revision_delta
            ),
            validity=validity,
            applicability=applicability,
            option_space_change=option_space_change,
            binding=binding,
        )


def _ke_runtime_owner_request(
    request: RuntimeRequest,
) -> RuntimeRequest:
    claim = ContextClaim(
        task_id=request.task_id,
        key="ke_runtime_owner_fact",
        value="owner-observed-current-value",
        claim_type=ContextClaimType.PROJECT_POLICY,
        source_kind=ContextSourceKind.DOCUMENT,
        source_ref="owner://ke-runtime/context",
        authority_role=ContextAuthorityRole.CANONICAL_PROJECT,
        verified=True,
        evidence_refs=("evidence:ke-runtime:context",),
    )

    payload = request.model_dump(mode="json")
    payload.update(
        {
            "context_claims": [
                claim.model_dump(mode="json")
            ],
            "context_requirements": [
                ContextRequirement(
                    key="ke_runtime_owner_fact",
                    claim_type=ContextClaimType.PROJECT_POLICY,
                ).model_dump(mode="json")
            ],
        }
    )
    return RuntimeRequest.model_validate(payload)


def _ke_runtime_resume_request(
    *,
    root: Path,
    initial_request: RuntimeRequest,
) -> RuntimeRequest:
    """Resume with the exact owner context identity from the initial turn."""

    base = _request(
        root,
        task_id=initial_request.task_id,
        allowed_tools=("filesystem.read_text",),
        mode=RuntimeMode.RESUME,
    )

    payload = base.model_dump(mode="json")
    payload.update(
        {
            "context_claims": [
                claim.model_dump(mode="json")
                for claim in initial_request.context_claims
            ],
            "context_requirements": [
                requirement.model_dump(mode="json")
                for requirement
                in initial_request.context_requirements
            ],
        }
    )

    return RuntimeRequest.model_validate(payload)


def _ke_runtime_owner_assumption_id(
    state: TaskState,
) -> UUID:
    assert state.decision_state is not None

    matches = tuple(
        item
        for item in DecisionStateService.current_assumptions(
            state.decision_state
        )
        if item.claim_type
        == ContextClaimType.PROJECT_POLICY.value
    )

    assert len(matches) == 1
    return matches[0].assumption_id


def _ke_runtime_two_turn_backend() -> _RecordingScriptedBackend:
    return _RecordingScriptedBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Yield after the first owner-state turn.",
                    finish_reason=ModelFinishReason.STOP,
                )
            ),
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Yield after the KE owner-output turn.",
                    finish_reason=ModelFinishReason.STOP,
                )
            ),
        )
    )


def test_ke_runtime_zero_model_budget_does_not_consume_owner_handoff(
    tmp_path: Path,
) -> None:
    provider = _KnowledgeEvolutionHandoffTestProvider()
    backend = ScriptedTestBackend(())
    runtime = _runtime(
        tmp_path,
        backend,
        knowledge_evolution_handoff_provider=provider,
    )
    request = _request(
        tmp_path,
        allowed_tools=("filesystem.read_text",),
        runtime_budget=RuntimeBudget(max_model_calls=0),
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(
            allowed_tools=("filesystem.read_text",)
        ),
    )

    assert outcome.stop_reason is RuntimeStopReason.BLOCKED
    assert outcome.usage.model_calls == 0
    assert provider.calls == []


def test_ke_runtime_verify_handoff_refreshes_information_gain_and_basis(
    tmp_path: Path,
) -> None:
    provider = _KnowledgeEvolutionHandoffTestProvider()
    backend = _ke_runtime_two_turn_backend()
    runtime = _runtime(
        tmp_path,
        backend,
        knowledge_evolution_handoff_provider=provider,
    )
    policy = _policy(
        allowed_tools=("filesystem.read_text",)
    )

    initial_request = _ke_runtime_owner_request(
        _request(
            tmp_path,
            allowed_tools=("filesystem.read_text",),
        )
    )
    initial = runtime.run(
        request=initial_request,
        tool_policy=policy,
    )

    assumption_id = _ke_runtime_owner_assumption_id(
        initial.state
    )
    provider.configure(
        assumption_id=assumption_id,
        mode="VERIFY",
    )
    provider.calls.clear()

    resume_request = _ke_runtime_resume_request(
        root=tmp_path,
        initial_request=initial_request,
    )
    resumed = runtime.resume(
        request=resume_request,
        tool_policy=policy,
    )

    assert resumed.usage.model_calls == 1
    assert len(provider.calls) == 1
    assert len(backend.requests) == 2

    judgment_message = next(
        message
        for message in backend.requests[-1].messages
        if message.name == "local_judgment"
    )
    payload = json.loads(judgment_message.content)
    local_judgment = payload["local_judgment"]
    information_gain = local_judgment["information_gain"]
    decision_basis = local_judgment["decision_basis"]

    assert (
        "ke_owner_validated_signal_consumed"
        in information_gain["reason_codes"]
    )
    assert (
        "ke_verify_stop_candidate_prioritized"
        in information_gain["reason_codes"]
    )
    assert (
        decision_basis["selected_information_need_id"]
        == information_gain["selected_need_id"]
    )


def test_ke_runtime_contradiction_mutates_only_through_decision_state_owner(
    tmp_path: Path,
) -> None:
    provider = _KnowledgeEvolutionHandoffTestProvider()
    backend = _ke_runtime_two_turn_backend()
    runtime = _runtime(
        tmp_path,
        backend,
        knowledge_evolution_handoff_provider=provider,
    )
    policy = _policy(
        allowed_tools=("filesystem.read_text",)
    )

    initial_request = _ke_runtime_owner_request(
        _request(
            tmp_path,
            allowed_tools=("filesystem.read_text",),
        )
    )
    initial = runtime.run(
        request=initial_request,
        tool_policy=policy,
    )
    assert initial.state.decision_state is not None

    assumption_id = _ke_runtime_owner_assumption_id(
        initial.state
    )
    previous_decision_revision = (
        initial.state.decision_state.revision
    )

    provider.configure(
        assumption_id=assumption_id,
        mode="CONTRADICT",
    )
    provider.calls.clear()

    resume_request = _ke_runtime_resume_request(
        root=tmp_path,
        initial_request=initial_request,
    )
    resumed = runtime.resume(
        request=resume_request,
        tool_policy=policy,
    )

    assert len(provider.calls) == 1
    assert resumed.state.decision_state is not None
    assert (
        resumed.state.decision_state.revision
        > previous_decision_revision
    )

    target = next(
        item
        for item in resumed.state.decision_state.assumptions
        if item.assumption_id == assumption_id
    )
    assert target.status.value == "CONTRADICTED"


def test_ke_runtime_stale_owner_handoff_fails_closed_before_model_call(
    tmp_path: Path,
) -> None:
    provider = _KnowledgeEvolutionHandoffTestProvider()
    backend = _ke_runtime_two_turn_backend()
    runtime = _runtime(
        tmp_path,
        backend,
        knowledge_evolution_handoff_provider=provider,
    )
    policy = _policy(
        allowed_tools=("filesystem.read_text",)
    )

    initial_request = _ke_runtime_owner_request(
        _request(
            tmp_path,
            allowed_tools=("filesystem.read_text",),
        )
    )
    initial = runtime.run(
        request=initial_request,
        tool_policy=policy,
    )

    provider.configure(
        assumption_id=_ke_runtime_owner_assumption_id(
            initial.state
        ),
        mode="VERIFY",
        revision_delta=1,
    )
    provider.calls.clear()
    prior_model_requests = len(backend.requests)

    resume_request = _ke_runtime_resume_request(
        root=tmp_path,
        initial_request=initial_request,
    )
    resumed = runtime.resume(
        request=resume_request,
        tool_policy=policy,
    )

    assert (
        resumed.stop_reason
        is RuntimeStopReason.INTEGRITY_FAILURE
    )
    assert len(provider.calls) == 1
    assert len(backend.requests) == prior_model_requests
    assert (
        "knowledge_evolution_handoff_integrity_failure"
        in resumed.reasons
    )


# KE_RUNTIME_HANDOFF_TESTS_END



def test_runtime_journal_loads_legacy_receipt_and_migrates_on_rewrite(
    tmp_path: Path,
) -> None:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Create one bounded file.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="write-legacy-receipt",
                            tool_name="filesystem.write_text",
                            arguments={
                                "path": "note.txt",
                                "content": "Luna",
                                "create_if_missing": True,
                            },
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )

    runtime = _runtime(
        tmp_path,
        backend,
    )

    request = _request(
        tmp_path,
        allowed_tools=(
            "filesystem.write_text",
        ),
        write=True,
    )

    outcome = runtime.run(
        request=request,
        tool_policy=_policy(
            allowed_tools=(
                "filesystem.write_text",
            ),
            write=True,
        ),
    )

    assert (
        outcome.stop_reason
        is RuntimeStopReason.VERIFICATION_PENDING
    )

    receipts = (
        runtime._deps.runtime_journal
        .list_for_task(
            request.task_id
        )
    )

    assert len(receipts) == 1

    receipt = receipts[0]

    assert (
        receipt.stage
        is SideEffectStage.CHECKPOINTED
    )
    assert receipt.checkpoint_id is not None

    checkpoint_id = (
        receipt.checkpoint_id
    )

    journal_path = (
        tmp_path
        / "journal.sqlite3"
    )

    with sqlite3.connect(
        journal_path
    ) as connection:
        row = connection.execute(
            """
            SELECT
                payload_json
            FROM side_effect_receipts
            WHERE idempotency_key = ?
            """,
            (
                receipt.idempotency_key,
            ),
        ).fetchone()

        assert row is not None

        current_payload = json.loads(
            str(row[0])
        )

        assert (
            "execution_revision"
            in current_payload
        )

        # Reconstruct the canonical shape of a receipt
        # written before execution_revision existed.
        legacy_payload = dict(
            current_payload
        )

        legacy_payload.pop(
            "execution_revision"
        )

        # Move the otherwise-valid terminal receipt back
        # to OBSERVED so a normal journal transition can
        # rewrite it without inventing state.
        legacy_payload[
            "stage"
        ] = SideEffectStage.OBSERVED.value

        legacy_payload[
            "checkpoint_id"
        ] = None

        legacy_payload[
            "checkpointed_at"
        ] = None

        legacy_json = json.dumps(
            legacy_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        legacy_digest = sha256(
            legacy_json.encode(
                "utf-8"
            )
        ).hexdigest()

        cursor = connection.execute(
            """
            UPDATE side_effect_receipts
            SET
                stage = ?,
                payload_json = ?,
                payload_sha256 = ?
            WHERE idempotency_key = ?
            """,
            (
                SideEffectStage.OBSERVED.value,
                legacy_json,
                legacy_digest,
                receipt.idempotency_key,
            ),
        )

        assert cursor.rowcount == 1
        connection.commit()

    reopened = SQLiteRuntimeJournal(
        journal_path
    )

    legacy = reopened.load(
        receipt.idempotency_key
    )

    assert (
        legacy.stage
        is SideEffectStage.OBSERVED
    )

    assert (
        legacy.execution_revision
        is None
    )

    assert (
        "execution_revision"
        not in legacy.model_fields_set
    )

    # This transition must validate the old stored
    # digest first, then serialize the current model
    # shape with execution_revision explicitly present.
    migrated = (
        reopened.mark_checkpointed(
            idempotency_key=(
                receipt.idempotency_key
            ),
            checkpoint_id=(
                checkpoint_id
            ),
        )
    )

    assert (
        migrated.stage
        is SideEffectStage.CHECKPOINTED
    )

    assert (
        migrated.execution_revision
        is None
    )

    assert (
        "execution_revision"
        in migrated.model_fields_set
    )

    with sqlite3.connect(
        journal_path
    ) as connection:
        row = connection.execute(
            """
            SELECT
                stage,
                payload_json,
                payload_sha256
            FROM side_effect_receipts
            WHERE idempotency_key = ?
            """,
            (
                receipt.idempotency_key,
            ),
        ).fetchone()

        assert row is not None

        assert (
            str(row[0])
            == SideEffectStage.CHECKPOINTED.value
        )

        migrated_json = str(
            row[1]
        )

        migrated_digest = str(
            row[2]
        )

        migrated_payload = json.loads(
            migrated_json
        )

        assert (
            "execution_revision"
            in migrated_payload
        )

        assert (
            migrated_payload[
                "execution_revision"
            ]
            is None
        )

        assert (
            sha256(
                migrated_json.encode(
                    "utf-8"
                )
            ).hexdigest()
            == migrated_digest
        )

    assert reopened.verify_integrity()
