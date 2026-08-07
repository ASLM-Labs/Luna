"""Deterministic runner for the locked Phase 12G runtime behavior suite."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from luna.conformance.models import (
    ConformanceCase,
    ConformanceCaseResult,
    ConformanceCaseStatus,
    ConformanceObservation,
    ConformanceReport,
    LockedConformanceSuite,
)


class ConformanceExecutor(Protocol):
    """Adapter that executes one locked scenario against real Luna components."""

    def execute(self, case: ConformanceCase, workspace_root: Path) -> ConformanceObservation:
        """Execute one case and return normalized observable values."""
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


class ConformanceRunner:
    """Run every locked case exactly once and fail closed on executor errors."""

    def run(
        self,
        *,
        suite: LockedConformanceSuite,
        executor: ConformanceExecutor,
        workspace_root: Path,
    ) -> ConformanceReport:
        if suite.computed_sha256() != suite.locked_sha256:
            raise ValueError("conformance suite integrity check failed")

        results: list[ConformanceCaseResult] = []
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
                    status = ConformanceCaseStatus.ERROR
                else:
                    mismatches = _compare_expected(case.oracle, observation.actual)
                    status = (
                        ConformanceCaseStatus.PASS
                        if not mismatches
                        else ConformanceCaseStatus.FAIL
                    )
                result = ConformanceCaseResult(
                    case_id=case.case_id,
                    domain=case.domain,
                    critical=case.critical,
                    status=status,
                    expected=case.oracle,
                    actual=observation.actual,
                    mismatches=mismatches,
                    duration_ms=observation.duration_ms,
                )
            except Exception as exc:  # conformance must surface, never hide, failures
                result = ConformanceCaseResult(
                    case_id=case.case_id,
                    domain=case.domain,
                    critical=case.critical,
                    status=ConformanceCaseStatus.ERROR,
                    expected=case.oracle,
                    actual={"error_class": type(exc).__name__},
                    mismatches=(f"executor_error:{type(exc).__name__}:{exc}",),
                )
            results.append(result)

        frozen = tuple(results)
        passed = sum(item.status is ConformanceCaseStatus.PASS for item in frozen)
        failed = len(frozen) - passed
        critical_failures = sum(
            item.critical and item.status is not ConformanceCaseStatus.PASS
            for item in frozen
        )
        return ConformanceReport(
            suite_name=suite.suite_name,
            suite_revision=suite.revision,
            suite_sha256=suite.locked_sha256,
            results=frozen,
            total_cases=len(frozen),
            passed_cases=passed,
            failed_cases=failed,
            critical_failures=critical_failures,
        )
