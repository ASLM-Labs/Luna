"""Intent-resolution console command."""

from __future__ import annotations

import argparse

from luna.intent import DeterministicIntentResolver


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "resolve-intent",
        help="Run the transparent deterministic intent baseline.",
    )
    parser.add_argument("request", help="Request text to resolve.")
    parser.set_defaults(_handler=handle)


def handle(args: argparse.Namespace) -> int:
    print(DeterministicIntentResolver().resolve(args.request).to_json())
    return 0
