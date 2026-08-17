"""Catalog-backed diagnostic discovery, execution, and legacy aliases."""

from __future__ import annotations

import argparse
from functools import partial

from luna.console.output import diagnostic_exit_code, write_json
from luna.diagnostics.catalog import (
    SmokeGroup,
    SmokeSpec,
    all_smoke_specs,
    smoke_specs_for_group,
)
from luna.diagnostics.models import SmokeReport


def register_legacy_aliases(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    group: SmokeGroup,
) -> None:
    for spec in smoke_specs_for_group(group):
        parser = subparsers.add_parser(spec.legacy_name, help=spec.help)
        parser.set_defaults(_handler=partial(_handle_spec, spec=spec))


def register_modern(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "smoke",
        help="Discover or run production-owned Luna diagnostics.",
    )
    parser.set_defaults(_handler=partial(_show_help, parser=parser))
    scenario_parsers = parser.add_subparsers(dest="scenario")

    list_parser = scenario_parsers.add_parser(
        "list",
        help="List all cataloged diagnostic scenarios.",
    )
    list_parser.set_defaults(_handler=_handle_list)

    all_parser = scenario_parsers.add_parser(
        "all",
        help="Run every cataloged diagnostic scenario.",
    )
    all_parser.set_defaults(_handler=_handle_all)

    for spec in all_smoke_specs():
        scenario_parser = scenario_parsers.add_parser(spec.scenario_id, help=spec.help)
        scenario_parser.set_defaults(_handler=partial(_handle_spec, spec=spec))


def render_report(spec: SmokeSpec, report: SmokeReport) -> int:
    if report.emit_payload:
        write_json(
            report.payload,
            ensure_ascii=spec.ensure_ascii,
            sort_keys=spec.sort_keys,
            indent=spec.indent,
        )
    return diagnostic_exit_code(report.passed)


def _show_help(_args: argparse.Namespace, *, parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 0


def _handle_spec(_args: argparse.Namespace, *, spec: SmokeSpec) -> int:
    return render_report(spec, spec.runner())


def _handle_list(_args: argparse.Namespace) -> int:
    for spec in all_smoke_specs():
        print(f"{spec.scenario_id}\t{spec.legacy_name}\t{spec.help}")
    return 0


def _handle_all(_args: argparse.Namespace) -> int:
    reports = tuple((spec, spec.runner()) for spec in all_smoke_specs())
    failed_scenarios = tuple(
        report.scenario_id for _spec, report in reports if not report.passed
    )
    payload = {
        "passed": not failed_scenarios,
        "scenario_count": len(reports),
        "failed_scenarios": failed_scenarios,
        "results": [
            {
                "scenario_id": report.scenario_id,
                "passed": report.passed,
                "failed_checks": [check.name for check in report.failed_checks],
            }
            for _spec, report in reports
        ],
    }
    write_json(payload, ensure_ascii=True)
    return diagnostic_exit_code(not failed_scenarios)
