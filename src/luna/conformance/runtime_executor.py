"""Real-runtime executor for the locked Phase 12G behavior-conformance suite."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from luna.actions import ActionResolver, ToolSelector, build_phase12c_routes
from luna.audit import AuditSession, EvidenceLedger
from luna.autonomy import AutonomyLevel, AutonomyPolicy
from luna.conformance.models import ConformanceCase, ConformanceObservation
from luna.context import ContextIntegrityGate, LayeredContextComposer
from luna.continuity import ContinuityService, SQLiteContinuityStore
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.contracts.enums import EvidenceResult, EvidenceSourceKind
from luna.contracts.evidence import Evidence
from luna.decision_state import DecisionStateService
from luna.identity import IdentityProfile
from luna.learning import LearningCandidateBuilder
from luna.memory import VerifiedMemoryService
from luna.modeling import (
    ModelBackend,
    ModelFinishReason,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
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
from luna.runtime import (
    DeterministicFingerprintProvider,
    GitWorktreeIsolationManager,
    LunaRuntime,
    Phase12FServices,
    RequestSource,
    RuntimeActor,
    RuntimeBudget,
    RuntimeDependencies,
    RuntimeLoopDependencies,
    RuntimeMode,
    RuntimeRequest,
    SQLiteRuntimeJournal,
    WorkspaceChangeInspector,
)
from luna.runtime.environment import RuntimeFingerprintProvider
from luna.tools import (
    DispatchOutcome,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    build_phase5_registry,
)
from luna.tools.lifecycle import CancellationProbe
from luna.verification import (
    CompletionGate,
    SQLiteEvidenceStore,
    VerifiedEvidenceRegistry,
    required_condition_claim_id,
)
from luna.verification.coordinator import VerificationCoordinator

_REQUIRED_CONDITION = "Runtime conformance condition passes."


class _RecordingScriptedBackend(ScriptedTestBackend):
    """Scripted backend retaining exact requests for observation-order assertions."""

    def __init__(self, turns: tuple[ScriptedTurn, ...]) -> None:
        super().__init__(turns)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return super().generate(request)


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
        approval_basis_fingerprint: str | None = None,
    ) -> DispatchOutcome:
        del request, task_contract, policy, cancellation_probe, approval_basis_fingerprint
        self.call_count += 1
        raise RuntimeError("synthetic crash after side-effect STARTED fence")


@dataclass(frozen=True, slots=True)
class _Harness:
    runtime: LunaRuntime
    audit: AuditSession
    fingerprint_provider: RuntimeFingerprintProvider


def _scripted_read_turn(call_id: str = "read") -> ScriptedTurn:
    return ScriptedTurn(
        output=ScriptedModelOutput(
            text="Read the bounded file.",
            tool_calls=(
                ModelToolCall(
                    call_id=call_id,
                    tool_name="filesystem.read_text",
                    arguments={"path": "note.txt"},
                ),
            ),
            finish_reason=ModelFinishReason.TOOL_CALLS,
        )
    )


def _build_runtime(
    *,
    workspace: Path,
    state_root: Path,
    backend: ModelBackend,
    dispatcher: ToolDispatcher | None = None,
    fingerprint_provider: RuntimeFingerprintProvider | None = None,
) -> _Harness:
    state_root.mkdir(parents=True, exist_ok=True)
    registry = build_phase5_registry()
    selector = ToolSelector(registry, build_phase12c_routes())
    audit = AuditSession(state_root / "audit")
    continuity = ContinuityService(
        SQLiteContinuityStore(state_root / "continuity.sqlite3"),
        audit,
    )
    completion_gate = CompletionGate(audit)
    report_composer = FinalReportComposer(audit)
    evidence_registry = VerifiedEvidenceRegistry(
        SQLiteEvidenceStore(state_root / "evidence.sqlite3"),
        EvidenceLedger(audit.ledger),
    )
    coordinator = VerificationCoordinator(
        completion_gate=completion_gate,
        report_composer=report_composer,
        identity=IdentityProfile(),
        learning_builder=LearningCandidateBuilder(audit),
    )
    fingerprints = fingerprint_provider or DeterministicFingerprintProvider(
        runtime_revision="luna-0.1-phase12g-conformance"
    )
    core = RuntimeDependencies(
        task_preparer=TaskPreparer(),
        planner=AdaptivePlanner(),
        model_backend=backend,
        tool_dispatcher=dispatcher or ToolDispatcher(registry),
        completion_gate=completion_gate,
        report_composer=report_composer,
        continuity_service=continuity,
        memory_service=cast(VerifiedMemoryService, object()),
    )
    return _Harness(
        runtime=LunaRuntime(
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
                runtime_journal=SQLiteRuntimeJournal(state_root / "journal.sqlite3"),
                isolation_manager=GitWorktreeIsolationManager(),
                fingerprint_provider=fingerprints,
                phase12f=Phase12FServices(
                    evidence_registry=evidence_registry,
                    verification_coordinator=coordinator,
                ),
            )
        ),
        audit=audit,
        fingerprint_provider=fingerprints,
    )


def _request(
    workspace: Path,
    *,
    task_id: UUID | None = None,
    allowed_tools: tuple[str, ...],
    write: bool = False,
    risk_level: RiskLevel = RiskLevel.LOW,
    mode: RuntimeMode = RuntimeMode.EXECUTE,
    runtime_budget: RuntimeBudget | None = None,
    allowed_paths: tuple[str, ...] = ("note.txt",),
) -> RuntimeRequest:
    active_task_id = task_id or uuid4()
    autonomy_level = (
        AutonomyLevel.LEVEL_3_TASK
        if write and risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        else AutonomyLevel.LEVEL_2_CONTROLLED
        if write
        else AutonomyLevel.LEVEL_1_READ_ONLY
    )
    max_risk = (
        risk_level
        if write and risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        else RiskLevel.MEDIUM
        if write
        else RiskLevel.LOW
    )
    autonomy = AutonomyPolicy(
        task_id=active_task_id,
        level=autonomy_level,
        allowed_tools=allowed_tools,
        max_risk=max_risk,
    )
    scope = TaskScope(
        workspace_root=str(workspace),
        allowed_paths=allowed_paths,
        write_allowed=write,
    )
    budget = (
        runtime_budget
        if runtime_budget is not None
        else RuntimeBudget.controlled_write(
            max_changed_files=1,
            max_added_lines=20,
            max_deleted_lines=20,
        )
        if write
        else RuntimeBudget()
    )
    return RuntimeRequest(
        task_id=active_task_id,
        raw_request="Execute the locked Phase 12G runtime conformance scenario.",
        source=RequestSource.TEST,
        actor=RuntimeActor.verified_owner("phase12g-conformance"),
        scope=scope,
        autonomy=autonomy,
        runtime_budget=budget,
        required_conditions=(_REQUIRED_CONDITION,),
        evidence_required=("test result",),
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
    max_risk = (
        risk_level
        if write and risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        else RiskLevel.MEDIUM
        if write
        else RiskLevel.LOW
    )
    return ToolPolicy(
        allowed_tools=allowed_tools,
        autonomy_level=autonomy_level,
        max_risk=max_risk,
    )


def _evidence_for_current_state(
    *,
    harness: _Harness,
    contract: TaskContract,
    result: EvidenceResult = EvidenceResult.PASS,
    source_kind: EvidenceSourceKind = EvidenceSourceKind.TEST_RESULT,
    revision: str | None = None,
) -> Evidence:
    workspace_revision = harness.fingerprint_provider.workspace_fingerprint(
        task_contract=contract
    )
    return Evidence(
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id(_REQUIRED_CONDITION),
        source_kind=source_kind,
        source_ref="conformance:phase12g",
        result=result,
        environment_fingerprint=harness.fingerprint_provider.environment_fingerprint(),
        revision=revision if revision is not None else workspace_revision,
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )


class RuntimeBehaviorExecutor:
    """Execute locked Phase 12G cases through LunaRuntime and durable stores."""

    def execute(self, case: ConformanceCase, workspace_root: Path) -> ConformanceObservation:
        handlers = {
            "verified_completion": self._verified_completion,
            "no_evidence_pending": self._no_evidence_pending,
            "weak_evidence_resumable": self._weak_evidence_resumable,
            "conflicting_evidence": self._conflicting_evidence,
            "multiple_actions_blocked": self._multiple_actions_blocked,
            "cancel_safe_boundary": self._cancel_safe_boundary,
            "started_side_effect_no_replay": self._started_side_effect_no_replay,
            "scope_denial_no_dispatch": self._scope_denial_no_dispatch,
            "high_risk_worktree": self._high_risk_worktree,
            "tool_budget_pre_dispatch": self._tool_budget_pre_dispatch,
            "stale_evidence_rejected": self._stale_evidence_rejected,
        }
        handler = handlers.get(case.scenario)
        if handler is None:
            raise ValueError(f"unknown Phase 12G scenario: {case.scenario}")
        return ConformanceObservation(case_id=case.case_id, actual=handler(workspace_root))

    @staticmethod
    def _read_runtime(root: Path) -> tuple[_Harness, RuntimeRequest, ToolPolicy]:
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
        backend = ScriptedTestBackend((_scripted_read_turn(),))
        harness = _build_runtime(
            workspace=workspace,
            state_root=root / "state",
            backend=backend,
        )
        request = _request(workspace, allowed_tools=("filesystem.read_text",))
        policy = _policy(allowed_tools=("filesystem.read_text",))
        return harness, request, policy

    def _verified_completion(self, root: Path) -> dict[str, object]:
        harness, request, policy = self._read_runtime(root)
        first = harness.runtime.run(request=request, tool_policy=policy)
        evidence = _evidence_for_current_state(
            harness=harness,
            contract=first.state.contract,
        )
        harness.runtime.record_evidence(evidence=evidence, trace_id=request.trace_id)
        resume_request = _request(
            Path(first.state.contract.scope.workspace_root),
            task_id=request.task_id,
            allowed_tools=("filesystem.read_text",),
            mode=RuntimeMode.RESUME,
        )
        final = harness.runtime.resume(request=resume_request, tool_policy=policy)
        latest = harness.runtime._deps.core.continuity_service.store.load_latest(request.task_id)
        return {
            "first_stop": first.stop_reason.value,
            "final_stop": final.stop_reason.value,
            "completion_status": (
                final.completion_status.value if final.completion_status is not None else None
            ),
            "closed": final.state.phase.value == "CLOSED",
            "final_report_bound": final.final_report_id is not None,
            "terminal_checkpoint": latest.envelope.terminal,
        }

    def _no_evidence_pending(self, root: Path) -> dict[str, object]:
        harness, request, policy = self._read_runtime(root)
        outcome = harness.runtime.run(request=request, tool_policy=policy)
        return {
            "stop_reason": outcome.stop_reason.value,
            "completion_status": (
                outcome.completion_status.value
                if outcome.completion_status is not None
                else None
            ),
            "closed": outcome.state.phase.value == "CLOSED",
            "final_report_bound": outcome.final_report_id is not None,
        }

    def _weak_evidence_resumable(self, root: Path) -> dict[str, object]:
        harness, request, policy = self._read_runtime(root)
        first = harness.runtime.run(request=request, tool_policy=policy)
        weak = _evidence_for_current_state(
            harness=harness,
            contract=first.state.contract,
            source_kind=EvidenceSourceKind.TOOL_OUTPUT,
        )
        harness.runtime.record_evidence(evidence=weak, trace_id=request.trace_id)
        resumed = harness.runtime.resume(
            request=_request(
                Path(first.state.contract.scope.workspace_root),
                task_id=request.task_id,
                allowed_tools=("filesystem.read_text",),
                mode=RuntimeMode.RESUME,
            ),
            tool_policy=policy,
        )
        latest = harness.runtime._deps.core.continuity_service.store.load_latest(request.task_id)
        assert latest.envelope.resume_phase is not None
        return {
            "stop_reason": resumed.stop_reason.value,
            "completion_status": (
                resumed.completion_status.value
                if resumed.completion_status is not None
                else None
            ),
            "checkpointed": resumed.state.phase.value == "CHECKPOINTED",
            "terminal": latest.envelope.terminal,
            "resume_phase": latest.envelope.resume_phase.value,
        }

    def _conflicting_evidence(self, root: Path) -> dict[str, object]:
        harness, request, policy = self._read_runtime(root)
        first = harness.runtime.run(request=request, tool_policy=policy)
        passed = _evidence_for_current_state(
            harness=harness,
            contract=first.state.contract,
        )
        failed = _evidence_for_current_state(
            harness=harness,
            contract=first.state.contract,
            result=EvidenceResult.FAIL,
        )
        harness.runtime.record_evidence(evidence=passed, trace_id=request.trace_id)
        harness.runtime.record_evidence(evidence=failed, trace_id=request.trace_id)
        resumed = harness.runtime.resume(
            request=_request(
                Path(first.state.contract.scope.workspace_root),
                task_id=request.task_id,
                allowed_tools=("filesystem.read_text",),
                mode=RuntimeMode.RESUME,
            ),
            tool_policy=policy,
        )
        latest = harness.runtime._deps.core.continuity_service.store.load_latest(request.task_id)
        return {
            "stop_reason": resumed.stop_reason.value,
            "completion_status": (
                resumed.completion_status.value
                if resumed.completion_status is not None
                else None
            ),
            "closed": resumed.state.phase.value == "CLOSED",
            "terminal": latest.envelope.terminal,
        }

    def _multiple_actions_blocked(self, root: Path) -> dict[str, object]:
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
        backend = ScriptedTestBackend(
            (
                ScriptedTurn(
                    output=ScriptedModelOutput(
                        text="Attempt two actions in one turn.",
                        tool_calls=(
                            ModelToolCall(
                                call_id="read-1",
                                tool_name="filesystem.read_text",
                                arguments={"path": "note.txt"},
                            ),
                            ModelToolCall(
                                call_id="read-2",
                                tool_name="filesystem.read_text",
                                arguments={"path": "note.txt"},
                            ),
                        ),
                        finish_reason=ModelFinishReason.TOOL_CALLS,
                    )
                ),
            )
        )
        harness = _build_runtime(
            workspace=workspace,
            state_root=root / "state",
            backend=backend,
        )
        request = _request(workspace, allowed_tools=("filesystem.read_text",))
        outcome = harness.runtime.run(
            request=request,
            tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
        )
        observations = harness.runtime._deps.runtime_journal.list_observations(request.task_id)
        return {
            "stop_reason": outcome.stop_reason.value,
            "model_calls": outcome.usage.model_calls,
            "tool_calls": outcome.usage.tool_calls,
            "observation_count": len(observations),
            "invalid_turn_visible": any(
                "exactly one proposed action" in reason for reason in outcome.reasons
            ),
        }

    def _cancel_safe_boundary(self, root: Path) -> dict[str, object]:
        workspace = root / "workspace"
        workspace.mkdir()
        backend = ScriptedTestBackend(())
        harness = _build_runtime(
            workspace=workspace,
            state_root=root / "state",
            backend=backend,
        )
        request = _request(workspace, allowed_tools=("filesystem.read_text",))
        harness.runtime.cancel(task_id=request.task_id, reason="Phase 12G owner cancel")
        outcome = harness.runtime.run(
            request=request,
            tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
        )
        control = harness.runtime._deps.runtime_journal.latest_control(request.task_id)
        return {
            "stop_reason": outcome.stop_reason.value,
            "model_calls": outcome.usage.model_calls,
            "tool_calls": outcome.usage.tool_calls,
            "control_acknowledged": control is not None and control.acknowledged_at is not None,
        }

    def _started_side_effect_no_replay(self, root: Path) -> dict[str, object]:
        workspace = root / "workspace"
        workspace.mkdir()
        state_root = root / "state"
        backend = ScriptedTestBackend(
            (
                ScriptedTurn(
                    output=ScriptedModelOutput(
                        text="Create the bounded file.",
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
        crashing = _CrashAfterFenceDispatcher()
        first = _build_runtime(
            workspace=workspace,
            state_root=state_root,
            backend=backend,
            dispatcher=crashing,
        )
        request = _request(
            workspace,
            allowed_tools=("filesystem.write_text",),
            write=True,
        )
        policy = _policy(allowed_tools=("filesystem.write_text",), write=True)
        try:
            first.runtime.run(request=request, tool_policy=policy)
        except RuntimeError as exc:
            if "synthetic crash after side-effect STARTED fence" not in str(exc):
                raise
        else:
            raise AssertionError("synthetic crash did not occur")

        receipt = first.runtime._deps.runtime_journal.list_for_task(request.task_id)[0]
        resumed_backend = ScriptedTestBackend(())
        resumed_harness = _build_runtime(
            workspace=workspace,
            state_root=state_root,
            backend=resumed_backend,
        )
        resumed = resumed_harness.runtime.resume(
            request=_request(
                workspace,
                task_id=request.task_id,
                allowed_tools=("filesystem.write_text",),
                write=True,
                mode=RuntimeMode.RESUME,
            ),
            tool_policy=policy,
        )
        return {
            "fence_stage": receipt.stage.value,
            "initial_dispatch_calls": crashing.call_count,
            "resume_stop": resumed.stop_reason.value,
            "resume_model_calls": resumed.usage.model_calls,
            "resume_tool_calls": resumed.usage.tool_calls,
            "file_created": (workspace / "note.txt").exists(),
            "replay_forbidden_visible": "automatic replay is forbidden" in " ".join(
                resumed.reasons
            ),
        }

    def _scope_denial_no_dispatch(self, root: Path) -> dict[str, object]:
        workspace = root / "workspace"
        workspace.mkdir()
        backend = ScriptedTestBackend(
            (
                ScriptedTurn(
                    output=ScriptedModelOutput(
                        text="Attempt an out-of-scope write.",
                        tool_calls=(
                            ModelToolCall(
                                call_id="scope-write",
                                tool_name="filesystem.write_text",
                                arguments={
                                    "path": "outside.txt",
                                    "content": "outside",
                                    "create_if_missing": True,
                                },
                            ),
                        ),
                        finish_reason=ModelFinishReason.TOOL_CALLS,
                    )
                ),
            )
        )
        harness = _build_runtime(
            workspace=workspace,
            state_root=root / "state",
            backend=backend,
        )
        request = _request(
            workspace,
            allowed_tools=("filesystem.write_text",),
            write=True,
            allowed_paths=("note.txt",),
        )
        outcome = harness.runtime.run(
            request=request,
            tool_policy=_policy(allowed_tools=("filesystem.write_text",), write=True),
        )
        return {
            "stop_reason": outcome.stop_reason.value,
            "model_calls": outcome.usage.model_calls,
            "tool_calls": outcome.usage.tool_calls,
            "outside_file_created": (workspace / "outside.txt").exists(),
            "denial_observed": len(outcome.observation_ids) == 1,
        }

    def _high_risk_worktree(self, root: Path) -> dict[str, object]:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "luna-conformance@example.invalid"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Luna Conformance"],
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
                        text="Perform the isolated write.",
                        tool_calls=(
                            ModelToolCall(
                                call_id="high-risk-write",
                                tool_name="filesystem.write_text",
                                arguments={
                                    "path": "note.txt",
                                    "content": "isolated\n",
                                    "expected_sha256": sha256(b"original\n").hexdigest(),
                                    "create_if_missing": False,
                                },
                            ),
                        ),
                        finish_reason=ModelFinishReason.TOOL_CALLS,
                    )
                ),
                ScriptedTurn(
                    output=ScriptedModelOutput(
                        text="Reinspect the isolated result.",
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
        harness = _build_runtime(
            workspace=repo,
            state_root=root / "state",
            backend=backend,
        )
        budget = RuntimeBudget.controlled_write(
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
            runtime_budget=budget,
        )
        policy = _policy(
            allowed_tools=allowed_tools,
            write=True,
            risk_level=RiskLevel.HIGH,
        )
        outcome = harness.runtime.run(request=request, tool_policy=policy)
        receipts = harness.runtime._deps.runtime_journal.list_for_task(request.task_id)
        observations = harness.runtime._deps.runtime_journal.list_observations(request.task_id)
        receipt = receipts[0] if receipts else None
        isolated_root = (
            Path(receipt.execution_workspace_root)
            if receipt is not None
            else repo.resolve()
        )
        second_turn = (
            "\n".join(message.content for message in backend.requests[1].messages)
            if len(backend.requests) > 1
            else ""
        )

        original_preserved = (repo / "note.txt").read_bytes() == b"original\n"
        isolated_changed = (
            receipt is not None
            and isolated_root != repo.resolve()
            and (isolated_root / "note.txt").is_file()
            and (isolated_root / "note.txt").read_text(encoding="utf-8") == "isolated\n"
        )
        saw_observation = bool(
            second_turn
            and observations
            and "runtime://observation/" in second_turn
            and str(observations[0].observation_id) in second_turn
        )
        proposal_secret_not_replayed = bool(second_turn) and "expected_sha256" not in second_turn

        harness.runtime.cancel(task_id=request.task_id, reason="Phase 12G isolation cleanup")
        cancelled = harness.runtime.resume(
            request=_request(
                repo,
                task_id=request.task_id,
                allowed_tools=allowed_tools,
                write=True,
                risk_level=RiskLevel.HIGH,
                runtime_budget=budget,
                mode=RuntimeMode.RESUME,
            ),
            tool_policy=policy,
        )
        del cancelled
        return {
            "stop_reason": outcome.stop_reason.value,
            "isolation_mode": receipt.isolation_mode if receipt is not None else None,
            "original_preserved": original_preserved,
            "isolated_changed": isolated_changed,
            "bounded_worktree_path": (
                receipt is not None and repo.parent not in isolated_root.parents
            ),
            "second_turn_saw_observation": saw_observation,
            "proposal_secret_not_replayed": proposal_secret_not_replayed,
            "cleanup_verified": receipt is not None and not isolated_root.exists(),
        }

    def _tool_budget_pre_dispatch(self, root: Path) -> dict[str, object]:
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
        backend = ScriptedTestBackend((_scripted_read_turn("budget-read"),))
        harness = _build_runtime(
            workspace=workspace,
            state_root=root / "state",
            backend=backend,
        )
        request = _request(
            workspace,
            allowed_tools=("filesystem.read_text",),
            runtime_budget=RuntimeBudget(max_tool_calls=0),
        )
        outcome = harness.runtime.run(
            request=request,
            tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
        )
        return {
            "stop_reason": outcome.stop_reason.value,
            "model_calls": outcome.usage.model_calls,
            "tool_calls": outcome.usage.tool_calls,
            "budget_reason_visible": "disables tool calls" in " ".join(outcome.reasons),
        }

    def _stale_evidence_rejected(self, root: Path) -> dict[str, object]:
        harness, request, policy = self._read_runtime(root)
        first = harness.runtime.run(request=request, tool_policy=policy)
        stale = _evidence_for_current_state(
            harness=harness,
            contract=first.state.contract,
            revision="old-workspace-revision",
        )
        harness.runtime.record_evidence(evidence=stale, trace_id=request.trace_id)
        resumed = harness.runtime.resume(
            request=_request(
                Path(first.state.contract.scope.workspace_root),
                task_id=request.task_id,
                allowed_tools=("filesystem.read_text",),
                mode=RuntimeMode.RESUME,
            ),
            tool_policy=policy,
        )
        latest = harness.runtime._deps.core.continuity_service.store.load_latest(request.task_id)
        assert latest.envelope.resume_phase is not None
        return {
            "stop_reason": resumed.stop_reason.value,
            "completion_status": (
                resumed.completion_status.value
                if resumed.completion_status is not None
                else None
            ),
            "closed": resumed.state.phase.value == "CLOSED",
            "terminal": latest.envelope.terminal,
            "resume_phase": latest.envelope.resume_phase.value,
        }
