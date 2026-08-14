from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Event, Thread
from typing import cast
from uuid import uuid4

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
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.decision_state import DecisionStateService
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
from luna.runtime.journal import RuntimeControlCommand, SideEffectStage, SQLiteRuntimeJournal
from luna.runtime.loop import LunaRuntime
from luna.runtime.models import RuntimeOutcome, RuntimeStopReason
from luna.tools import (
    DispatchOutcome,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    build_phase5_registry,
)
from luna.tools.lifecycle import CancellationProbe
from luna.tools.models import ToolArgumentValue
from luna.tools.registry import ToolExecutionContext, ToolExecutionOutput, ToolRegistry
from luna.verification import CompletionGate


class _CrashAfterFenceDispatcher(ToolDispatcher):
    """Simulate process loss after STARTED is durable but before handler execution."""

    def __init__(self) -> None:
        super().__init__(build_phase5_registry())
        self.call_count = 0

    def dispatch(
        self,
        *,
        request: ToolRequest,
        task_contract: TaskContract,
        policy: ToolPolicy,
        cancellation_probe: CancellationProbe | None = None,
    ) -> DispatchOutcome:
        del request, task_contract, policy, cancellation_probe
        self.call_count += 1
        raise RuntimeError("synthetic crash after side-effect STARTED fence")


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
    assert started.wait(timeout=2)
    runtime.cancel(task_id=request.task_id, reason="cancel after handler start")
    worker.join(timeout=2)

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
    assert isolated_root != repo.resolve()
    assert (repo / "note.txt").read_text(encoding="utf-8") == "original\n"
    assert (isolated_root / "note.txt").read_text(encoding="utf-8") == "isolated"
    assert len(observations) == 2
    assert observations[-1].outcome.request.tool_name == "filesystem.read_text"
    assert observations[-1].outcome.result.stdout_excerpt == "isolated"
    assert len(backend.requests) == 2
    second_turn_text = "\n".join(message.content for message in backend.requests[1].messages)
    assert "runtime://observation/" in second_turn_text
    assert str(observations[0].observation_id) in second_turn_text
    assert '"local_judgment"' in second_turn_text
    assert '"tool_advice"' in second_turn_text
    assert "advisory_only_no_authority" in second_turn_text
    assert "expected_sha256" not in second_turn_text

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
