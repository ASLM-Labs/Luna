"""Model compatibility console commands."""

from __future__ import annotations

import argparse

from luna.console.output import diagnostic_exit_code, write_json
from luna.modeling import LocalOpenAICompatibleBackend, ModelCompatibilityProbe


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "phase13-live-probe",
        help="Probe a loopback OpenAI-compatible real model without granting rollout authority.",
    )
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:1234/v1/chat/completions",
        help="Loopback OpenAI-compatible chat-completions endpoint.",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Model identifier exposed by the local server.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Per-request compatibility probe timeout.",
    )
    parser.set_defaults(_handler=handle)


def handle(args: argparse.Namespace) -> int:
    backend = LocalOpenAICompatibleBackend(
        endpoint=args.endpoint,
        model=args.model,
        timeout_seconds=args.timeout_seconds,
    )
    report = ModelCompatibilityProbe().run(backend)
    payload = report.model_dump(mode="json")
    payload["required_passed"] = report.required_passed
    payload["eligible_for_rollout"] = report.eligible_for_rollout
    payload["compatibility_fingerprint"] = report.fingerprint()
    payload["rollout_authority_granted"] = False
    write_json(payload)
    return diagnostic_exit_code(report.eligible_for_rollout)
