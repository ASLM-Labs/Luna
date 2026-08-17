"""Minimal structured results shared by production diagnostic scenarios."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One named diagnostic observation and its pass/fail result."""

    name: str
    passed: bool
    observed: object
    expected: object | None = None


@dataclass(frozen=True, slots=True)
class SmokeReport:
    """Structured scenario truth, independent of console rendering."""

    scenario_id: str
    payload: Mapping[str, object]
    checks: tuple[CheckResult, ...]
    emit_payload: bool = True

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed_checks(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if not check.passed)


def equals(name: str, observed: object, expected: object) -> CheckResult:
    """Build a named equality check without production assert semantics."""

    return CheckResult(
        name=name,
        passed=observed == expected,
        observed=observed,
        expected=expected,
    )


def legacy_contract_report(
    scenario_id: str,
    payload: Mapping[str, object],
    passed: bool,
) -> SmokeReport:
    """Preserve an established scenario predicate while exposing structured truth."""

    return SmokeReport(
        scenario_id=scenario_id,
        payload=payload,
        checks=(equals("scenario_contract", passed, True),),
    )
