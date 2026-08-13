from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from luna.console.app import build_parser
from luna.diagnostics import SmokeSpec, all_smoke_specs, validate_smoke_specs
from luna.diagnostics.models import CheckResult, SmokeReport
from luna.diagnostics.scenarios import (
    c001,
    capabilities,
    foundational,
    learning,
    model_research,
    phase12f,
    product,
    runtime,
)


def test_c001_diagnostic_returns_structured_truth() -> None:
    report = c001.run()

    assert report.scenario_id == "c001"
    assert report.passed is True
    assert report.failed_checks == ()
    assert report.payload == {
        "stable_source": "INTERNAL",
        "stable_decision": "ANSWER_DIRECT",
        "current_source": "STRUCTURED_API",
        "research_source": "RESEARCH_GATEWAY",
        "contradiction_decision": "STOP_REINSPECT",
        "automatic_memory_commit_allowed": False,
        "runtime_authority": False,
        "external_action_allowed": False,
    }


def test_phase12f_diagnostic_accepts_injected_workspace(tmp_path: Path) -> None:
    report = phase12f.run(tmp_path)

    assert report.scenario_id == "phase12f"
    assert report.passed is True
    assert report.failed_checks == ()
    assert report.payload["strong_status"] == "VERIFIED_COMPLETE"
    assert report.payload["strong_strength"] == "DETERMINISTIC"
    assert report.payload["weak_status"] == "INCONCLUSIVE"
    assert report.payload["conflict_status"] == "CONFLICTING_EVIDENCE"
    assert report.payload["evidence_store_integrity"] is True
    assert (tmp_path / "evidence.sqlite3").is_file()


def test_catalog_has_unique_stable_identity() -> None:
    specs = all_smoke_specs()

    scenario_ids = tuple(spec.scenario_id for spec in specs)
    legacy_names = tuple(spec.legacy_name for spec in specs)
    assert len(scenario_ids) == len(set(scenario_ids))
    assert len(legacy_names) == len(set(legacy_names))
    assert {"c001", "phase12f"} <= set(scenario_ids)
    assert {"c001-smoke", "phase12f-smoke"} <= set(legacy_names)


@pytest.mark.parametrize(
    "runner",
    (
        foundational.run_workspace,
        foundational.run_process,
        foundational.run_audit,
        foundational.run_verify,
        foundational.run_checkpoint,
        foundational.run_memory,
    ),
)
def test_foundational_diagnostics_return_structured_truth(
    runner: Callable[[], SmokeReport],
) -> None:
    report = runner()

    assert report.passed is True
    assert report.failed_checks == ()
    assert report.payload


@pytest.mark.parametrize(
    "runner",
    (
        runtime.run_phase10,
        runtime.run_phase11,
        runtime.run_phase12a,
        runtime.run_phase12b,
        runtime.run_phase12c,
        runtime.run_phase12d,
        runtime.run_phase12e,
        runtime.run_phase12g,
    ),
)
def test_runtime_diagnostics_return_structured_truth(
    runner: Callable[[], SmokeReport],
) -> None:
    report = runner()

    assert report.passed is True
    assert report.failed_checks == ()
    assert report.payload


@pytest.mark.parametrize(
    "runner",
    (capabilities.run_c003, capabilities.run_c007),
)
def test_capability_diagnostics_return_structured_truth(
    runner: Callable[[], SmokeReport],
) -> None:
    report = runner()

    assert report.passed is True
    assert report.failed_checks == ()
    assert report.payload


@pytest.mark.parametrize(
    "runner",
    (model_research.run_phase13, model_research.run_phase14),
)
def test_model_research_diagnostics_return_structured_truth(
    runner: Callable[[], SmokeReport],
) -> None:
    report = runner()

    assert report.passed is True
    assert report.failed_checks == ()
    assert report.payload


@pytest.mark.parametrize(
    "runner",
    (
        product.run_phase15,
        product.run_phase16,
        product.run_phase17,
        product.run_phase18,
    ),
)
def test_product_diagnostics_return_structured_truth(
    runner: Callable[[], SmokeReport],
) -> None:
    report = runner()

    assert report.passed is True
    assert report.failed_checks == ()
    assert report.payload


@pytest.mark.parametrize(
    "runner",
    (
        learning.run_phase19,
        learning.run_phase19b,
        learning.run_phase19c,
        learning.run_phase19d,
        learning.run_phase19e,
        learning.run_phase19f,
    ),
)
def test_learning_diagnostics_return_structured_truth(
    runner: Callable[[], SmokeReport],
) -> None:
    report = runner()

    assert report.passed is True
    assert report.failed_checks == ()
    assert report.payload


def test_duplicate_legacy_smoke_names_are_rejected() -> None:
    spec = all_smoke_specs()[0]
    duplicate = SmokeSpec(
        scenario_id="duplicate-id",
        legacy_name=spec.legacy_name,
        help="Duplicate fixture.",
        runner=spec.runner,
    )

    with pytest.raises(ValueError, match="duplicate legacy smoke command name"):
        validate_smoke_specs((spec, duplicate))


def test_catalog_and_parser_cannot_silently_drift() -> None:
    parser = build_parser()
    root_subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    specs = all_smoke_specs()

    assert {spec.legacy_name for spec in specs} <= set(root_subparsers.choices)
    assert all("_handler" in command._defaults for command in root_subparsers.choices.values())

    modern_parser = root_subparsers.choices["smoke"]
    modern_subparsers = next(
        action
        for action in modern_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert set(modern_subparsers.choices) == {
        "list",
        "all",
        *(spec.scenario_id for spec in specs),
    }


def test_modern_and_legacy_c001_commands_share_output_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from luna.cli import main

    legacy_exit = main(["c001-smoke"])
    legacy_output = capsys.readouterr().out
    modern_exit = main(["smoke", "c001"])
    modern_output = capsys.readouterr().out

    assert modern_exit == legacy_exit == 0
    assert modern_output == legacy_output


def test_smoke_list_reflects_catalog(capsys: pytest.CaptureFixture[str]) -> None:
    from luna.cli import main

    exit_code = main(["smoke", "list"])
    lines = capsys.readouterr().out.splitlines()

    assert exit_code == 0
    assert tuple(line.split("\t", maxsplit=1)[0] for line in lines) == tuple(
        spec.scenario_id for spec in all_smoke_specs()
    )


def test_diagnostic_runners_are_order_independent_in_same_process() -> None:
    c001_before = c001.run()
    phase12f_report = phase12f.run()
    c001_after = c001.run()

    assert phase12f_report.passed is True
    assert c001_before == c001_after


def test_smoke_all_preserves_failure_identities(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from luna.cli import main
    from luna.console.commands import smoke

    failing_spec = SmokeSpec(
        scenario_id="injected-failure",
        legacy_name="injected-failure-smoke",
        help="Injected aggregate failure fixture.",
        runner=lambda: SmokeReport(
            scenario_id="injected-failure",
            payload={"observed": "unsafe"},
            checks=(
                CheckResult(
                    name="injected_failed_check",
                    passed=False,
                    observed="unsafe",
                    expected="safe",
                ),
            ),
        ),
    )
    monkeypatch.setattr(smoke, "all_smoke_specs", lambda: (failing_spec,))

    exit_code = main(["smoke", "all"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["passed"] is False
    assert payload["scenario_count"] == 1
    assert payload["failed_scenarios"] == ["injected-failure"]
    assert payload["results"] == [
        {
            "scenario_id": "injected-failure",
            "passed": False,
            "failed_checks": ["injected_failed_check"],
        }
    ]
