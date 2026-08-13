"""Luna command-line parser and explicit command dispatch."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import cast

from luna.console.commands import (
    audit,
    capabilities,
    desktop,
    intent,
    model,
    smoke,
    status,
    tools,
)
from luna.diagnostics.catalog import SmokeGroup
from luna.version import __version__

CommandHandler = Callable[[argparse.Namespace], int]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="luna",
        description="Luna 0.1 local single-agent runtime",
    )
    parser.add_argument("--version", action="version", version=f"Luna {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    status.register(subparsers)
    capabilities.register(subparsers, parser)
    smoke.register_legacy_aliases(subparsers, SmokeGroup.CAPABILITY)
    tools.register_list_tools(subparsers)
    smoke.register_legacy_aliases(subparsers, SmokeGroup.PHASE)
    desktop.register(subparsers)
    model.register(subparsers)
    audit.register(subparsers)
    smoke.register_legacy_aliases(subparsers, SmokeGroup.FOUNDATION)
    intent.register(subparsers)
    tools.register_tool_smoke(subparsers)
    smoke.register_modern(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return cast(CommandHandler, handler)(args)
