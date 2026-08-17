"""Tool registry and controlled tool-smoke console commands."""

from __future__ import annotations

import argparse

from luna.console.commands.smoke import render_report
from luna.diagnostics.catalog import get_smoke_spec
from luna.diagnostics.scenarios import foundational
from luna.tools import build_phase5_registry


def register_list_tools(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("list-tools", help="List registered Phase 5 tools.")
    parser.set_defaults(_handler=handle_list_tools)


def register_tool_smoke(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    spec = get_smoke_spec("tool")
    parser = subparsers.add_parser(
        spec.legacy_name,
        help=spec.help,
    )
    parser.add_argument("message", help="Message passed to core.echo.")
    parser.set_defaults(_handler=handle_tool_smoke)


def handle_list_tools(_args: argparse.Namespace) -> int:
    registry = build_phase5_registry()
    for spec in registry.specs():
        capabilities = ",".join(item.value for item in spec.capabilities) or "NONE"
        print(f"{spec.name}\t{spec.risk_level.value}\t{capabilities}")
    return 0


def handle_tool_smoke(args: argparse.Namespace) -> int:
    spec = get_smoke_spec("tool")
    return render_report(spec, foundational.run_tool(args.message))
