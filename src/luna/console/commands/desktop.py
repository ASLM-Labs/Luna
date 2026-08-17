"""Desktop product-shell console command."""

from __future__ import annotations

import argparse
from pathlib import Path

from luna.desktop import build_local_desktop_controller, launch_desktop_shell


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "desktop",
        help="Launch the local Phase 16 Luna desktop product shell.",
    )
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root shown by the desktop shell.",
    )
    parser.add_argument(
        "--database",
        default=str(Path.home() / ".luna" / "operations.sqlite3"),
        help="Local operations SQLite database used by the desktop shell.",
    )
    parser.add_argument(
        "--actor-id",
        default="desktop-local-session",
        help="Local-session actor identifier bound outside model output.",
    )
    parser.set_defaults(_handler=handle)


def handle(args: argparse.Namespace) -> int:
    controller = build_local_desktop_controller(
        workspace_root=args.workspace,
        database_path=args.database,
        actor_id=args.actor_id,
    )
    return launch_desktop_shell(controller)
