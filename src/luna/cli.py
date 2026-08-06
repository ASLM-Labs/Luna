"""Command-line entry point for the Luna Phase 5 controlled workspace runtime."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from luna.contracts.enums import RiskLevel
from luna.contracts.task import TaskContract, TaskScope
from luna.intent import DeterministicIntentResolver
from luna.tools import (
    AutonomyLevel,
    ProcessApproval,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    build_phase5_registry,
)
from luna.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="luna",
        description="Luna 0.1 local single-agent runtime",
    )
    parser.add_argument("--version", action="version", version=f"Luna {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show the current project phase and capability state.")
    subparsers.add_parser("list-tools", help="List registered Phase 5 tools.")
    subparsers.add_parser(
        "workspace-smoke",
        help="Create a temporary file through the dispatcher, then restore its snapshot.",
    )
    subparsers.add_parser(
        "process-smoke",
        help="Run the exact approved Python --version argv through the dispatcher.",
    )
    resolve_parser = subparsers.add_parser(
        "resolve-intent",
        help="Run the transparent deterministic intent baseline.",
    )
    resolve_parser.add_argument("request", help="Request text to resolve.")
    echo_parser = subparsers.add_parser(
        "tool-smoke",
        help="Run the controlled core.echo tool through the dispatcher.",
    )
    echo_parser.add_argument("message", help="Message passed to core.echo.")
    return parser


def _echo_contract(task_id: UUID) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Run the controlled echo smoke test.",
        required_conditions=("Dispatcher must return the supplied message.",),
        evidence_required=("ToolResult and Observation",),
        scope=TaskScope(workspace_root=str(Path.cwd())),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def _workspace_contract(task_id: UUID, root: Path) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Verify snapshot-first write and rollback in a temporary workspace.",
        required_conditions=("Temporary write must be fully rolled back.",),
        evidence_required=("Write ToolResult and rollback ToolResult",),
        scope=TaskScope(
            workspace_root=str(root),
            allowed_paths=("smoke.txt",),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
        owner="user",
    )


def _process_contract(task_id: UUID) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Verify exact-argv process execution without a shell.",
        required_conditions=("Python version command must exit successfully.",),
        evidence_required=("Process ToolResult and Observation",),
        scope=TaskScope(
            workspace_root=str(Path.cwd()),
            process_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
        owner="user",
    )


def _run_workspace_smoke() -> int:
    registry = build_phase5_registry()
    dispatcher = ToolDispatcher(registry)
    with TemporaryDirectory(prefix="luna-phase5-") as directory:
        root = Path(directory)
        task_id = uuid4()
        contract = _workspace_contract(task_id, root)
        write = dispatcher.dispatch(
            request=ToolRequest(
                task_id=task_id,
                trace_id=uuid4(),
                tool_name="filesystem.write_text",
                arguments={
                    "path": "smoke.txt",
                    "content": "phase5",
                    "create_if_missing": True,
                },
                expectation_id=uuid4(),
            ),
            task_contract=contract,
            policy=ToolPolicy(
                allowed_tools=("filesystem.write_text",),
                autonomy_level=AutonomyLevel.BOUNDED,
                max_risk=RiskLevel.MEDIUM,
            ),
        )
        snapshot_id = write.result.metadata.get("snapshot_id")
        if write.result.status.value != "SUCCESS" or not isinstance(snapshot_id, str):
            print(write.to_json())
            return 2

        rollback = dispatcher.dispatch(
            request=ToolRequest(
                task_id=task_id,
                trace_id=uuid4(),
                tool_name="workspace.rollback",
                arguments={"snapshot_id": snapshot_id},
                expectation_id=uuid4(),
            ),
            task_contract=contract,
            policy=ToolPolicy(
                allowed_tools=("workspace.rollback",),
                owner_approved_tools=("workspace.rollback",),
                autonomy_level=AutonomyLevel.OWNER_APPROVED,
                max_risk=RiskLevel.HIGH,
            ),
        )
        payload = {
            "write_status": write.result.status.value,
            "rollback_status": rollback.result.status.value,
            "snapshot_id": snapshot_id,
            "file_exists_after_rollback": (root / "smoke.txt").exists(),
            "rollback_verified": rollback.result.metadata.get("verified", False),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if (
            rollback.result.status.value == "SUCCESS"
            and not payload["file_exists_after_rollback"]
            and payload["rollback_verified"] is True
        ) else 2


def _run_process_smoke() -> int:
    registry = build_phase5_registry()
    task_id = uuid4()
    argv = (sys.executable, "--version")
    outcome = ToolDispatcher(registry).dispatch(
        request=ToolRequest(
            task_id=task_id,
            trace_id=uuid4(),
            tool_name="process.run_argv",
            arguments={"argv": list(argv)},
            working_directory=".",
            expectation_id=uuid4(),
        ),
        task_contract=_process_contract(task_id),
        policy=ToolPolicy(
            allowed_tools=("process.run_argv",),
            owner_approved_tools=("process.run_argv",),
            process_approvals=(ProcessApproval(argv=argv),),
            autonomy_level=AutonomyLevel.OWNER_APPROVED,
            max_risk=RiskLevel.HIGH,
        ),
    )
    print(outcome.to_json())
    return 0 if outcome.result.status.value == "SUCCESS" else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print("phase: 5")
        print("status: WORKSPACE_SHELL_IMPLEMENTED_UNVERIFIED")
        print("tool_dispatcher: deny_by_default")
        print("registered_tools: 7")
        print("workspace_writes: snapshot_first_atomic")
        print("rollback: sha256_verified")
        print("process_execution: exact_argv_owner_approved")
        print("shell_parsing: disabled")
        print("file_delete: disabled")
        print("network_tools: disabled")
        return 0

    if args.command == "resolve-intent":
        print(DeterministicIntentResolver().resolve(args.request).to_json())
        return 0

    registry = build_phase5_registry()
    if args.command == "list-tools":
        for spec in registry.specs():
            capabilities = ",".join(item.value for item in spec.capabilities) or "NONE"
            print(f"{spec.name}\t{spec.risk_level.value}\t{capabilities}")
        return 0

    if args.command == "tool-smoke":
        task_id = uuid4()
        contract = _echo_contract(task_id)
        outcome = ToolDispatcher(registry).dispatch(
            request=ToolRequest(
                task_id=task_id,
                trace_id=uuid4(),
                tool_name="core.echo",
                arguments={"message": args.message},
            ),
            task_contract=contract,
            policy=ToolPolicy(
                allowed_tools=("core.echo",),
                autonomy_level=AutonomyLevel.OBSERVE_ONLY,
                max_risk=RiskLevel.LOW,
            ),
        )
        print(outcome.to_json())
        return 0 if outcome.result.status.value == "SUCCESS" else 2

    if args.command == "workspace-smoke":
        return _run_workspace_smoke()

    if args.command == "process-smoke":
        return _run_process_smoke()

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
