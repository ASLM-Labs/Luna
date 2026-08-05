"""Command-line entry point for the Luna Phase 3 planning package."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from luna.intent import DeterministicIntentResolver
from luna.version import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the Luna command-line parser."""
    parser = argparse.ArgumentParser(
        prog="luna",
        description="Luna 0.1 local single-agent runtime",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Luna {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "status",
        help="Show the current project phase and capability state.",
    )
    resolve_parser = subparsers.add_parser(
        "resolve-intent",
        help="Run the transparent deterministic Phase 2 intent baseline.",
    )
    resolve_parser.add_argument("request", help="Request text to resolve.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Luna command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print("phase: 3")
        print("status: PLANNING_REPLANNING_IMPLEMENTED_UNVERIFIED")
        print("contracts: 8")
        print("intent_resolver: deterministic_baseline")
        print("planner: adaptive_deterministic_baseline")
        print("blind_retry_guard: enabled")
        print("context_io: disabled")
        print("runtime_capabilities: disabled")
        return 0

    if args.command == "resolve-intent":
        resolution = DeterministicIntentResolver().resolve(args.request)
        print(resolution.to_json())
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
