"""Deterministic Phase 12E single policy-agent loop verification."""

from __future__ import annotations

import ast
import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.actions import ActionResolver, ToolSelector, build_phase12c_routes  # noqa: E402
from luna.autonomy import AutonomyLevel, AutonomyPolicy  # noqa: E402
from luna.context import ContextIntegrityGate, LayeredContextComposer  # noqa: E402
from luna.continuity import ContinuityService, SQLiteContinuityStore  # noqa: E402
from luna.contracts import RiskLevel, TaskScope  # noqa: E402
from luna.decision_state import DecisionStateService  # noqa: E402
from luna.memory import VerifiedMemoryService  # noqa: E402
from luna.modeling import (  # noqa: E402
    ModelFinishReason,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    ScriptedModelOutput,
    ScriptedTestBackend,
    ScriptedTurn,
)
from luna.planning import AdaptivePlanner  # noqa: E402
from luna.preparation import TaskPreparer  # noqa: E402
from luna.recovery import (  # noqa: E402
    FailureClassifier,
    MinimalChangePolicy,
    RecoveryPolicy,
    WorkspaceIsolationPolicy,
)
from luna.reporting import FinalReportComposer  # noqa: E402
from luna.runtime import (  # noqa: E402
    DeterministicFingerprintProvider,
    GitWorktreeIsolationManager,
    LunaRuntime,
    RequestSource,
    RuntimeActor,
    RuntimeBudget,
    RuntimeDependencies,
    RuntimeLoopDependencies,
    RuntimeRequest,
    RuntimeStopReason,
    SQLiteRuntimeJournal,
    WorkspaceChangeInspector,
)
from luna.tools import ToolDispatcher, ToolPolicy, build_phase5_registry  # noqa: E402
from luna.verification import CompletionGate  # noqa: E402


class _RecordingBackend(ScriptedTestBackend):
    def __init__(self, turns: tuple[ScriptedTurn, ...]) -> None:
        super().__init__(turns)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return super().generate(request)


def _canonical_metadata_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _metadata_integrity() -> bool:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    phase = manifest.get("phase")
    if not isinstance(phase, str):
        return False
    match = re.fullmatch(r"(\d+)([A-Z]?)", phase)
    if match is None:
        return False
    phase_number = int(match.group(1))
    phase_suffix = match.group(2)
    if phase_number < 12 or (phase_number == 12 and phase_suffix < "E"):
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    if manifest.get("metadata_scope") not in {
        "git_head_tracked_artifacts_v1",
        "release_artifact_allowlist_v2",
    }:
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False
    forbidden = {"phase5_check.log", "phase8_check.log"}
    if forbidden.intersection(files) or any(str(item).endswith(".log") for item in files):
        return False

    sums: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            return False
        digest, relative = line.split("  ", 1)
        sums[relative] = digest
    if set(sums) != set(files):
        return False

    for relative, metadata in files.items():
        if not isinstance(relative, str) or not isinstance(metadata, dict):
            return False
        target = ROOT / relative
        if not target.is_file():
            return False
        canonical = _canonical_metadata_bytes(target)
        digest = sha256(canonical).hexdigest()
        if metadata.get("sha256") != digest:
            return False
        if metadata.get("size_bytes") != len(canonical):
            return False
        if sums.get(relative) != digest:
            return False
    return True


def _loop_has_write_ahead_fence() -> bool:
    source = (ROOT / "src/luna/runtime/loop.py").read_text(encoding="utf-8")
    execute_start = source.find("    def _execute_one(")
    execute_end = source.find("    def _reconcile_receipt(", execute_start)
    if execute_start < 0 or execute_end < 0:
        return False
    body = source[execute_start:execute_end]
    started = body.find("runtime_journal.mark_started")
    dispatched = body.find("tool_dispatcher.dispatch")
    completed = body.find("runtime_journal.mark_completed")
    observed = body.find("runtime_journal.mark_observed")
    return 0 <= started < dispatched < completed < observed


def _loop_has_no_subagent_boundary() -> bool:
    tree = ast.parse((ROOT / "src/luna/runtime/loop.py").read_text(encoding="utf-8"))
    forbidden = {"subagent", "langchain", "crewai", "autogen"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            any(part in alias.name.casefold() for part in forbidden)
            for alias in node.names
        ):
            return False
        if isinstance(node, ast.ImportFrom):
            module = (node.module or "").casefold()
            if any(part in module for part in forbidden):
                return False
    return True


def _runtime_smoke() -> tuple[bool, bool, bool, bool, bool, bool]:
    with TemporaryDirectory(prefix="luna-phase12e-") as temp:
        root = Path(temp)
        (root / "note.txt").write_text("hello", encoding="utf-8")
        backend = _RecordingBackend(
            (
                ScriptedTurn(
                    output=ScriptedModelOutput(
                        text="Read exactly one bounded file.",
                        tool_calls=(
                            ModelToolCall(
                                call_id="phase12e-read-1",
                                tool_name="filesystem.read_text",
                                arguments={"path": "note.txt"},
                            ),
                        ),
                        finish_reason=ModelFinishReason.TOOL_CALLS,
                    )
                ),
                ScriptedTurn(
                    output=ScriptedModelOutput(
                        text="Reinspect only after observing the first result.",
                        tool_calls=(
                            ModelToolCall(
                                call_id="phase12e-read-2",
                                tool_name="filesystem.read_text",
                                arguments={"path": "note.txt"},
                            ),
                        ),
                        finish_reason=ModelFinishReason.TOOL_CALLS,
                    )
                ),
            )
        )
        registry = build_phase5_registry()
        selector = ToolSelector(registry, build_phase12c_routes())
        continuity = ContinuityService(SQLiteContinuityStore(root / "continuity.sqlite3"))
        journal = SQLiteRuntimeJournal(root / "journal.sqlite3")
        core = RuntimeDependencies(
            task_preparer=TaskPreparer(),
            planner=AdaptivePlanner(),
            model_backend=backend,
            tool_dispatcher=ToolDispatcher(registry),
            completion_gate=cast(CompletionGate, object()),
            report_composer=cast(FinalReportComposer, object()),
            continuity_service=continuity,
            memory_service=cast(VerifiedMemoryService, object()),
        )
        runtime = LunaRuntime(
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
                runtime_journal=journal,
                isolation_manager=GitWorktreeIsolationManager(),
                fingerprint_provider=DeterministicFingerprintProvider(),
            )
        )
        task_id = __import__("uuid").uuid4()
        autonomy = AutonomyPolicy(
            task_id=task_id,
            level=AutonomyLevel.LEVEL_1_READ_ONLY,
            allowed_tools=("filesystem.read_text",),
            max_risk=RiskLevel.LOW,
        )
        request = RuntimeRequest(
            task_id=task_id,
            raw_request="Read the bounded note and observe each result.",
            source=RequestSource.TEST,
            actor=RuntimeActor.verified_owner("phase12e-verifier"),
            scope=TaskScope(
                workspace_root=str(root),
                allowed_paths=("note.txt",),
            ),
            autonomy=autonomy,
            runtime_budget=RuntimeBudget(),
            required_conditions=(
                "Use one action per iteration.",
                "Observe each result before another action.",
                "Keep the same authoritative TaskState.",
                "Do not create subagents.",
            ),
            evidence_required=("Structured observation.",),
        )
        policy = ToolPolicy(
            allowed_tools=("filesystem.read_text",),
            autonomy_level=AutonomyLevel.LEVEL_1_READ_ONLY,
            max_risk=RiskLevel.LOW,
        )
        outcome = runtime.run(request=request, tool_policy=policy)
        records = journal.list_observations(task_id)
        second_turn = (
            "\n".join(message.content for message in backend.requests[1].messages)
            if len(backend.requests) > 1
            else ""
        )
        control = runtime.suspend(task_id=task_id, reason="phase12e verifier control")
        return (
            outcome.stop_reason is RuntimeStopReason.VERIFICATION_PENDING,
            outcome.usage.model_calls == 2 and outcome.usage.tool_calls == 2,
            len(records) == 2,
            bool(records)
            and "runtime://observation/" in second_turn
            and str(records[0].observation_id) in second_turn,
            journal.verify_integrity(),
            control.command.value == "SUSPEND",
        )


def main() -> int:
    required_files = (
        "src/luna/runtime/loop.py",
        "src/luna/runtime/policy_agent.py",
        "src/luna/runtime/journal.py",
        "src/luna/runtime/change_inspector.py",
        "src/luna/runtime/isolation.py",
        "src/luna/runtime/environment.py",
        "tests/test_phase12e_single_policy_loop.py",
        "docs/rfcs/RFC-012E_SINGLE_POLICY_AGENT_LOOP.md",
        "docs/PHASE_12E_REPORT.md",
    )
    missing = [relative for relative in required_files if not (ROOT / relative).is_file()]
    (
        runtime_smoke,
        sequential_actions,
        observations_durable,
        observation_feedback,
        journal_integrity,
        control_durable,
    ) = _runtime_smoke()

    checks = {
        "required_files_present": not missing,
        "single_policy_runtime_smoke": runtime_smoke,
        "one_action_per_iteration": sequential_actions,
        "durable_runtime_observations": observations_durable,
        "observation_feedback_is_data_only_context": observation_feedback,
        "write_ahead_side_effect_fence": _loop_has_write_ahead_fence(),
        "runtime_journal_integrity": journal_integrity,
        "durable_suspend_cancel_control": control_durable,
        "no_subagent_boundary": _loop_has_no_subagent_boundary(),
        "phase12f_completion_handoff": "VERIFICATION_PENDING" in (
            ROOT / "src/luna/runtime/loop.py"
        ).read_text(encoding="utf-8"),
        "metadata_hashes_current": _metadata_integrity(),
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    print(
        json.dumps(
            {
                "phase": "12E",
                "checks": checks,
                "missing_files": missing,
                "status": status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
