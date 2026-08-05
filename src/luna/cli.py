"""Command-line entry point for the Luna Phase 4 model/tool boundary."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

from luna.contracts.enums import RiskLevel
from luna.contracts.task import TaskContract, TaskScope
from luna.intent import DeterministicIntentResolver
from luna.tools import (
    AutonomyLevel,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    build_phase4_registry,
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
    subparsers.add_parser("list-tools", help="List registered Phase 4 tools.")
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
        objective="Run the controlled Phase 4 echo smoke test.",
        required_conditions=("Dispatcher must return the supplied message.",),
        evidence_required=("ToolResult and Observation",),
        scope=TaskScope(workspace_root=str(Path.cwd())),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print("phase: 4")
        print("status: MODEL_TOOL_BOUNDARY_IMPLEMENTED_UNVERIFIED")
        print("model_backend: provider_independent")
        print("scripted_test_backend: enabled")
        print("local_model_adapter: loopback_openai_compatible")
        print("tool_dispatcher: deny_by_default")
        print("registered_tools: 3")
        print("shell: disabled")
        print("network_tools: disabled")
        print("workspace_writes: disabled")
        return 0

    if args.command == "resolve-intent":
        print(DeterministicIntentResolver().resolve(args.request).to_json())
        return 0

    registry = build_phase4_registry()
    if args.command == "list-tools":
        for spec in registry.specs():
            capabilities = ",".join(item.value for item in spec.capabilities) or "NONE"
            print(f"{spec.name}	{spec.risk_level.value}	{capabilities}")
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

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
