"""Structural and behavioral verifier for Luna Phase 4."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.modeling import (
    LocalOpenAICompatibleBackend,
    MessageRole,
    ModelMessage,
    ModelRequest,
    ScriptedModelOutput,
    ScriptedTestBackend,
    ScriptedTurn,
)
from luna.tools import (
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    build_phase4_registry,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    required_files = [
        ROOT / "src" / "luna" / "modeling" / "backend.py",
        ROOT / "src" / "luna" / "modeling" / "scripted.py",
        ROOT / "src" / "luna" / "modeling" / "local_openai.py",
        ROOT / "src" / "luna" / "tools" / "models.py",
        ROOT / "src" / "luna" / "tools" / "registry.py",
        ROOT / "src" / "luna" / "tools" / "dispatcher.py",
        ROOT / "src" / "luna" / "tools" / "builtins.py",
    ]
    missing = [path.relative_to(ROOT).as_posix() for path in required_files if not path.is_file()]

    model_request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="hello"),),
    )
    backend = ScriptedTestBackend(
        turns=(ScriptedTurn(output=ScriptedModelOutput(text="world")),)
    )
    model_response = backend.generate(model_request)
    scripted_backend_ok = (
        model_response.request_id == model_request.request_id
        and model_response.text == "world"
        and backend.remaining_turns == 0
    )

    loopback_guard_ok = False
    try:
        LocalOpenAICompatibleBackend(
            endpoint="https://example.com/v1/chat/completions",
            model="forbidden",
        )
    except ValueError:
        loopback_guard_ok = True

    registry = build_phase4_registry()
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("Luna", encoding="utf-8")
        task = TaskContract(
            objective="Phase 4 verification",
            required_conditions=("Tool calls are policy checked",),
            evidence_required=("ToolResult and ToolEvent",),
            scope=TaskScope(
                workspace_root=str(root),
                allowed_paths=("README.md",),
            ),
            risk_level=RiskLevel.LOW,
        )
        dispatcher = ToolDispatcher(registry)
        denied = dispatcher.dispatch(
            request=ToolRequest(
                task_id=task.task_id,
                trace_id=uuid4(),
                tool_name="core.echo",
                arguments={"message": "denied"},
            ),
            task_contract=task,
            policy=ToolPolicy(),
        )
        allowed = dispatcher.dispatch(
            request=ToolRequest(
                task_id=task.task_id,
                trace_id=uuid4(),
                tool_name="core.echo",
                arguments={"message": "allowed"},
            ),
            task_contract=task,
            policy=ToolPolicy(allowed_tools=("core.echo",)),
        )
        read = dispatcher.dispatch(
            request=ToolRequest(
                task_id=task.task_id,
                trace_id=uuid4(),
                tool_name="filesystem.read_text",
                arguments={"path": "README.md"},
            ),
            task_contract=task,
            policy=ToolPolicy(allowed_tools=("filesystem.read_text",)),
        )
        unregistered = dispatcher.dispatch(
            request=ToolRequest(
                task_id=task.task_id,
                trace_id=uuid4(),
                tool_name="shell.exec",
            ),
            task_contract=task,
            policy=ToolPolicy(allowed_tools=("shell.exec",)),
        )

    checks = {
        "required_files_present": not missing,
        "scripted_backend_without_model_access": scripted_backend_ok,
        "local_adapter_loopback_only": loopback_guard_ok,
        "default_deny": denied.result.status is ToolResultStatus.BLOCKED,
        "explicit_permission_executes": allowed.result.status is ToolResultStatus.SUCCESS,
        "scoped_read_executes": read.result.status is ToolResultStatus.SUCCESS,
        "unregistered_shell_blocked": unregistered.result.status is ToolResultStatus.BLOCKED,
        "tool_result_event_observation_linked": (
            allowed.event.result_id == allowed.result.result_id
            and allowed.observation.tool_event_id == allowed.event.event_id
        ),
        "workspace_writes_disabled": all(
            "WRITE" not in {capability.value for capability in spec.capabilities}
            for spec in registry.specs()
        ),
        "network_tools_disabled": all(
            "NETWORK" not in {capability.value for capability in spec.capabilities}
            for spec in registry.specs()
        ),
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    result = {"phase": 4, "checks": checks, "missing_files": missing, "status": status}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
