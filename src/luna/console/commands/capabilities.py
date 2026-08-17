"""Capability inspection console commands."""

from __future__ import annotations

import argparse

from luna.capabilities import build_canonical_capability_registry
from luna.console.output import write_json


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    root_parser: argparse.ArgumentParser,
) -> None:
    parser = subparsers.add_parser(
        "capability-lineage",
        help="Query canonical C-002 dependency and blast-radius metadata.",
    )
    parser.add_argument("capability_id")
    parser.add_argument(
        "--hard-only",
        action="store_true",
        help="Exclude preferred-dependency edges from blast radius.",
    )
    parser.set_defaults(_handler=handle, _root_parser=root_parser)


def handle(args: argparse.Namespace) -> int:
    registry = build_canonical_capability_registry()
    try:
        record = registry.get(args.capability_id)
        impact = registry.blast_radius(
            args.capability_id,
            include_preferred=not args.hard_only,
        )
    except KeyError as exc:
        root_parser: argparse.ArgumentParser = args._root_parser
        root_parser.error(str(exc))

    write_json(
        {
            "record": record.model_dump(mode="json"),
            "impact": impact.model_dump(mode="json"),
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return 0
