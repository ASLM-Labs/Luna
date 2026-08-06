from __future__ import annotations

from pathlib import Path

from luna.acceptance import ReleaseGate, ReleaseStatus, run_core_acceptance
from luna.evals import build_core_eval_suite


def test_real_core_acceptance_suite_passes(tmp_path: Path) -> None:
    report, decision = run_core_acceptance(tmp_path)

    assert report.metrics.total_cases == 11
    assert report.metrics.passed_cases == 11
    assert report.metrics.critical_failures == 0
    assert report.metrics.false_verified_complete_count == 0
    assert report.metrics.protected_path_violation_count == 0
    assert report.metrics.blind_retry_count == 0
    assert report.metrics.rollback_pass
    assert report.metrics.checkpoint_resume_pass
    assert report.metrics.memory_pollution_pass
    assert report.metrics.final_report_accuracy_pass
    assert decision.status is ReleaseStatus.PASS
    assert decision.known_limitations


def test_repeated_runs_have_same_semantic_result(tmp_path: Path) -> None:
    first, _ = run_core_acceptance(tmp_path / "first")
    second, _ = run_core_acceptance(tmp_path / "second")

    assert first.semantic_signature() == second.semantic_signature()


def test_release_gate_blocks_when_limitations_are_not_published(tmp_path: Path) -> None:
    report, _ = run_core_acceptance(tmp_path)
    decision = ReleaseGate().evaluate(
        report=report,
        suite=build_core_eval_suite(),
        known_limitations=(),
    )

    assert decision.status is ReleaseStatus.BLOCKED
    assert any("known limitations" in reason for reason in decision.reasons)
