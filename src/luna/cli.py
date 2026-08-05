"""Command-line entry point for the Luna Phase 0 scaffold."""
from __future__ import annotations
import argparse
from collections.abc import Sequence
from luna.version import __version__

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="luna", description="Luna 0.1 local single-agent runtime")
    parser.add_argument("--version", action="version", version=f"Luna {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show the current project phase and capability state.")
    return parser

def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        print("phase: 0")
        print("status: SCAFFOLD_READY")
        print("runtime_capabilities: disabled")
        return 0
    parser.print_help()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
