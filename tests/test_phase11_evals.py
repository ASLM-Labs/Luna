from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from luna.evals import (
    CORE_EVAL_SUITE_SHA256,
    EvalCase,
    EvalMetric,
    EvalObservation,
    LockedEvalSuite,
    RegressionRunner,
    build_core_eval_suite,
)


class _MismatchExecutor:
    def execute(self, case: EvalCase, workspace_root: Path) -> EvalObservation:
        del workspace_root
        return EvalObservation(case_id=case.case_id, actual={"ok": False})


def test_fixed_suite_revision_and_hash_are_locked() -> None:
    suite = build_core_eval_suite()

    assert suite.revision == "1.0.0"
    assert len(suite.cases) == 11
    assert suite.locked_sha256 == CORE_EVAL_SUITE_SHA256
    assert suite.computed_sha256() == CORE_EVAL_SUITE_SHA256


def test_tampered_fixture_or_oracle_is_rejected() -> None:
    suite = build_core_eval_suite()
    changed = suite.cases[0].model_copy(update={"oracle": {"completion_status": "FAILED"}})

    with pytest.raises(ValidationError, match="digest mismatch"):
        LockedEvalSuite(
            suite_name=suite.suite_name,
            revision=suite.revision,
            cases=(changed, *suite.cases[1:]),
            locked_sha256=suite.locked_sha256,
        )


def test_runner_surfaces_oracle_mismatch(tmp_path: Path) -> None:
    case = EvalCase(
        case_id="L11-99-mismatch",
        title="Mismatch fixture",
        metric=EvalMetric.TASK_SUCCESS,
        fixture={"scenario": "synthetic"},
        oracle={"ok": True},
    )
    suite = LockedEvalSuite.lock(
        suite_name="Synthetic",
        revision="1.0.0",
        cases=(case,),
    )

    report = RegressionRunner().run(
        suite=suite,
        executor=_MismatchExecutor(),
        workspace_root=tmp_path,
    )

    assert report.metrics.failed_cases == 1
    assert report.case_results[0].status.value == "FAIL"
    assert "actual.ok" in report.case_results[0].mismatches[0]
