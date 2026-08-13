"""Audit inspection console command."""

from __future__ import annotations

import argparse
from pathlib import Path
from uuid import UUID

from luna.audit import AuditSession
from luna.console.output import write_json


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "audit-inspect",
        help="Print one task audit from an owner-selected audit root.",
    )
    parser.add_argument("root", help="Audit root containing events.jsonl.")
    parser.add_argument("task_id", help="Task UUID to inspect.")
    parser.set_defaults(_handler=handle)


def handle(args: argparse.Namespace) -> int:
    task_id = UUID(args.task_id)
    events = AuditSession(Path(args.root)).events_for_task(task_id)
    write_json([event.model_dump(mode="json") for event in events])
    return 0
