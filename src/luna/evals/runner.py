"""Deterministic fixed-suite regression runner."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from luna.evals.models import (
    EvalCase,
    EvalCaseResult,
    EvalCaseStatus,
    EvalMetric,
    EvalMetrics,
    EvalObservation,
    EvalReport,
    LockedEvalSuite,
)


class EvalExecutor(Protocol):
    """Runtime adapter used by the regression runner."""

    def execute(self, case: EvalCase, workspace_root: Path) -> EvalObservation:
        """Execute one case and return normalized actual values."""
        ...


def _compare_expected(
    expected: object,
    actual: object,
    *,
    path: str = "actual",
) -> tuple[str, ...]:
    mismatches: list[str] = []
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return (f"{path}: expected mapping, got {type(actual).__name__}",)
        for key, expected_value in expected.items():
            if key not in actual:
                mismatches.append(f"{path}.{key}: missing")
                continue
            mismatches.extend(
                _compare_expected(
                    expected_value,
                    actual[key],
                    path=f"{path}.{key}",
                )
            )
        return tuple(mismatches)
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return (f"{path}: expected list, got {type(actual).__name__}",)
        if expected != actual:
            return (f"{path}: expected {expected!r}, got {actual!r}",)
        return ()
    if expected != actual:
        return (f"{path}: expected {expected!r}, got {actual!r}",)
    return ()


def _metric_pass(results: tuple[EvalCaseResult, ...], metric: EvalMetric) -> bool:
    matches = tuple(item for item in results if item.metric is metric)
    return bool(matches) and all(item.status is EvalCaseStatus.PASS for item in matches)


def _integer_metric(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    raise TypeError(f"eval counter must be int, got {type(value).__name__}")


class RegressionRunner:
    """Run every locked case exactly once and derive comparable metrics."""

    def run(
        self,
        *,
        suite: LockedEvalSuite,
        executor: EvalExecutor,
        workspace_root: Path,
    ) -> EvalReport:
        if suite.computed_sha256() != suite.locked_sha256:
            raise ValueError("fixed eval suite integrity check failed")

        results: list[EvalCaseResult] = []
        for case in suite.cases:
            case_root = workspace_root / case.case_id
            case_root.mkdir(parents=True, exist_ok=True)
            try:
                observation = executor.execute(case, case_root)
                mismatches: tuple[str, ...]
                if observation.case_id != case.case_id:
                    mismatches = (
                        f"case_id: expected {case.case_id}, got {observation.case_id}",
                    )
                    status = EvalCaseStatus.ERROR
                else:
                    mismatches = _compare_expected(case.oracle, observation.actual)
                    status = (
                        EvalCaseStatus.PASS
                        if not mismatches
                        else EvalCaseStatus.FAIL
                    )
                result = EvalCaseResult(
                    case_id=case.case_id,
                    metric=case.metric,
                    critical=case.critical,
                    status=status,
                    expected=case.oracle,
                    actual=observation.actual,
                    mismatches=mismatches,
                    duration_ms=observation.duration_ms,
                    token_cost=observation.token_cost,
                )
            except Exception as exc:  # acceptance runner must report, not hide, failures
                result = EvalCaseResult(
                    case_id=case.case_id,
                    metric=case.metric,
                    critical=case.critical,
                    status=EvalCaseStatus.ERROR,
                    expected=case.oracle,
                    actual={"error_class": type(exc).__name__},
                    mismatches=(f"executor_error:{type(exc).__name__}:{exc}",),
                )
            results.append(result)

        frozen = tuple(results)
        passed = sum(item.status is EvalCaseStatus.PASS for item in frozen)
        failed = len(frozen) - passed
        critical_failures = sum(
            item.critical and item.status is not EvalCaseStatus.PASS
            for item in frozen
        )
        false_complete = sum(
            _integer_metric(item.actual.get("false_verified_complete_count", 0))
            for item in frozen
            if item.metric is EvalMetric.FALSE_VERIFIED_COMPLETE
        )
        protected_violations = sum(
            _integer_metric(item.actual.get("protected_path_violation_count", 0))
            for item in frozen
            if item.metric is EvalMetric.PROTECTED_PATH
        )
        blind_retries = sum(
            _integer_metric(item.actual.get("blind_retry_count", 0))
            for item in frozen
            if item.metric is EvalMetric.BLIND_RETRY
        )
        task_cases = tuple(item for item in frozen if item.metric is EvalMetric.TASK_SUCCESS)
        task_passes = sum(item.status is EvalCaseStatus.PASS for item in task_cases)
        task_success_rate = task_passes / len(task_cases) if task_cases else 0.0
        verified_success_rate = passed / len(frozen)

        metrics = EvalMetrics(
            total_cases=len(frozen),
            passed_cases=passed,
            failed_cases=failed,
            critical_failures=critical_failures,
            task_success_rate=task_success_rate,
            verified_success_rate=verified_success_rate,
            false_verified_complete_count=false_complete,
            protected_path_violation_count=protected_violations,
            blind_retry_count=blind_retries,
            inspect_before_edit_pass=_metric_pass(
                frozen,
                EvalMetric.INSPECT_BEFORE_EDIT,
            ),
            rollback_pass=_metric_pass(frozen, EvalMetric.ROLLBACK),
            checkpoint_resume_pass=_metric_pass(
                frozen,
                EvalMetric.CHECKPOINT_RESUME,
            ),
            memory_pollution_pass=_metric_pass(
                frozen,
                EvalMetric.MEMORY_POLLUTION,
            ),
            unnecessary_question_pass=_metric_pass(
                frozen,
                EvalMetric.UNNECESSARY_QUESTION,
            ),
            scope_creep_pass=_metric_pass(frozen, EvalMetric.SCOPE_CREEP),
            final_report_accuracy_pass=_metric_pass(
                frozen,
                EvalMetric.FINAL_REPORT_ACCURACY,
            ),
            duration_ms=sum(item.duration_ms for item in frozen),
            token_cost=sum(item.token_cost for item in frozen),
        )
        return EvalReport(
            suite_name=suite.suite_name,
            suite_revision=suite.revision,
            suite_sha256=suite.locked_sha256,
            case_results=frozen,
            metrics=metrics,
        )
