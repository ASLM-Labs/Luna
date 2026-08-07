from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from luna.acceptance import ReleaseStatus, run_core_acceptance
from luna.conformance import (
    RUNTIME_CONFORMANCE_SUITE_SHA256,
    ConformanceDomain,
    ConformanceRunner,
    LockedConformanceSuite,
    RuntimeBehaviorExecutor,
    build_runtime_conformance_suite,
)


def test_runtime_conformance_suite_is_revision_and_hash_locked() -> None:
    suite = build_runtime_conformance_suite()

    assert suite.revision == "1.0.0"
    assert len(suite.cases) == 11
    assert suite.locked_sha256 == RUNTIME_CONFORMANCE_SUITE_SHA256
    assert suite.computed_sha256() == RUNTIME_CONFORMANCE_SUITE_SHA256
    assert {case.domain for case in suite.cases} == set(ConformanceDomain)
    assert all(case.critical for case in suite.cases)


def test_runtime_conformance_oracle_tampering_is_rejected() -> None:
    suite = build_runtime_conformance_suite()
    changed = suite.cases[0].model_copy(
        update={"oracle": {"final_stop": "COMPLETED"}}
    )

    with pytest.raises(ValidationError, match="digest mismatch"):
        LockedConformanceSuite(
            suite_name=suite.suite_name,
            revision=suite.revision,
            cases=(changed, *suite.cases[1:]),
            locked_sha256=suite.locked_sha256,
        )


def test_real_runtime_conformance_suite_passes_all_cases(tmp_path: Path) -> None:
    report = ConformanceRunner().run(
        suite=build_runtime_conformance_suite(),
        executor=RuntimeBehaviorExecutor(),
        workspace_root=tmp_path,
    )

    assert report.total_cases == 11
    assert report.passed_cases == 11
    assert report.failed_cases == 0
    assert report.critical_failures == 0
    assert report.all_passed is True

    by_id = {item.case_id: item for item in report.results}
    assert by_id["L12G-01-verified-completion"].actual["final_stop"] == "COMPLETED"
    assert by_id["L12G-02-no-false-complete"].actual["stop_reason"] == "VERIFICATION_PENDING"
    assert by_id["L12G-08-scope-denial-no-dispatch"].actual["stop_reason"] == "PERMISSION_DENIED"
    assert by_id["L12G-08-scope-denial-no-dispatch"].actual["tool_calls"] == 0
    assert by_id["L12G-09-high-risk-worktree"].actual["bounded_worktree_path"] is True
    assert by_id["L12G-09-high-risk-worktree"].actual["cleanup_verified"] is True
    assert by_id["L12G-11-stale-evidence-rejected"].actual["completion_status"] == "UNVERIFIED"


def test_runtime_conformance_semantics_are_repeatable(tmp_path: Path) -> None:
    runner = ConformanceRunner()
    suite = build_runtime_conformance_suite()
    first = runner.run(
        suite=suite,
        executor=RuntimeBehaviorExecutor(),
        workspace_root=tmp_path / "first",
    )
    second = runner.run(
        suite=suite,
        executor=RuntimeBehaviorExecutor(),
        workspace_root=tmp_path / "second",
    )

    assert first.semantic_signature() == second.semantic_signature()


def test_phase11_locked_core_acceptance_stays_green_with_phase12g(tmp_path: Path) -> None:
    report, decision = run_core_acceptance(tmp_path)

    assert report.metrics.total_cases == 11
    assert report.metrics.passed_cases == 11
    assert report.metrics.failed_cases == 0
    assert report.metrics.critical_failures == 0
    assert decision.status is ReleaseStatus.PASS
