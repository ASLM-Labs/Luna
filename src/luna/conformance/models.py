"""Locked Phase 12G runtime behavior-conformance contracts."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Self
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


def canonical_sha256(payload: object) -> str:
    """Return a stable SHA-256 digest for JSON-compatible conformance payloads."""
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(serialized.encode()).hexdigest()


class ConformanceDomain(StrEnum):
    """Cross-layer behavior owned by the Phase 12 runtime foundation."""

    COMPLETION_TRUTH = "COMPLETION_TRUTH"
    EVIDENCE_DISCIPLINE = "EVIDENCE_DISCIPLINE"
    POLICY_BOUNDARY = "POLICY_BOUNDARY"
    SAFE_CONTROL = "SAFE_CONTROL"
    SIDE_EFFECT_REPLAY = "SIDE_EFFECT_REPLAY"
    SCOPE_INTEGRITY = "SCOPE_INTEGRITY"
    ISOLATION = "ISOLATION"
    BUDGET = "BUDGET"


class ConformanceCaseStatus(StrEnum):
    """Deterministic result for one locked conformance case."""

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class ConformanceCase(LunaContractModel):
    """One immutable runtime scenario and its expected observable oracle."""

    case_id: str = Field(pattern=r"^L12G-[0-9]{2}-[a-z0-9-]+$")
    title: str = Field(min_length=1, max_length=500)
    domain: ConformanceDomain
    scenario: str = Field(min_length=1, max_length=200)
    oracle: dict[str, object]
    critical: bool = True
    tags: tuple[str, ...] = ()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("conformance tags cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("conformance tags must be unique")
        return cleaned

    def integrity_payload(self) -> dict[str, object]:
        """Return fields protected by the locked-suite digest."""
        return {
            "case_id": self.case_id,
            "title": self.title,
            "domain": self.domain.value,
            "scenario": self.scenario,
            "oracle": self.oracle,
            "critical": self.critical,
            "tags": self.tags,
        }


class LockedConformanceSuite(LunaContractModel):
    """Versioned runtime behavior suite whose cases and oracles are hash locked."""

    suite_name: str = Field(min_length=1, max_length=500)
    revision: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    cases: tuple[ConformanceCase, ...] = Field(min_length=1)
    locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def lock(
        cls,
        *,
        suite_name: str,
        revision: str,
        cases: tuple[ConformanceCase, ...],
    ) -> Self:
        payload = cls.integrity_payload_for(
            suite_name=suite_name,
            revision=revision,
            cases=cases,
        )
        return cls(
            suite_name=suite_name,
            revision=revision,
            cases=cases,
            locked_sha256=canonical_sha256(payload),
        )

    @staticmethod
    def integrity_payload_for(
        *,
        suite_name: str,
        revision: str,
        cases: tuple[ConformanceCase, ...],
    ) -> dict[str, object]:
        return {
            "suite_name": suite_name,
            "revision": revision,
            "cases": [case.integrity_payload() for case in cases],
        }

    def computed_sha256(self) -> str:
        return canonical_sha256(
            self.integrity_payload_for(
                suite_name=self.suite_name,
                revision=self.revision,
                cases=self.cases,
            )
        )

    @model_validator(mode="after")
    def validate_integrity(self) -> LockedConformanceSuite:
        ids = tuple(case.case_id for case in self.cases)
        if len(ids) != len(set(ids)):
            raise ValueError("conformance case IDs must be unique")
        scenarios = tuple(case.scenario for case in self.cases)
        if len(scenarios) != len(set(scenarios)):
            raise ValueError("conformance scenario names must be unique")
        if self.locked_sha256 != self.computed_sha256():
            raise ValueError("conformance suite fixture/oracle digest mismatch")
        return self


class ConformanceObservation(LunaContractModel):
    """Normalized observable values returned by one real runtime scenario."""

    case_id: str
    actual: dict[str, object]
    duration_ms: int = Field(default=0, ge=0)


class ConformanceCaseResult(LunaContractModel):
    """One exact oracle comparison."""

    case_id: str
    domain: ConformanceDomain
    critical: bool
    status: ConformanceCaseStatus
    expected: dict[str, object]
    actual: dict[str, object]
    mismatches: tuple[str, ...] = ()
    duration_ms: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_status(self) -> ConformanceCaseResult:
        if self.status is ConformanceCaseStatus.PASS and self.mismatches:
            raise ValueError("passing conformance case cannot contain mismatches")
        if self.status is not ConformanceCaseStatus.PASS and not self.mismatches:
            raise ValueError("non-passing conformance case requires mismatches")
        return self


class ConformanceReport(LunaContractModel):
    """Hash-bound result of one complete Phase 12G conformance run."""

    report_id: UUID = Field(default_factory=uuid4)
    suite_name: str
    suite_revision: str
    suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    results: tuple[ConformanceCaseResult, ...]
    total_cases: int = Field(ge=1)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    critical_failures: int = Field(ge=0)
    generated_at: datetime = Field(default_factory=utc_now)

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_counts(self) -> ConformanceReport:
        if self.passed_cases + self.failed_cases != self.total_cases:
            raise ValueError("conformance pass/fail counts must equal total cases")
        if len(self.results) != self.total_cases:
            raise ValueError("conformance result count must equal total cases")
        ids = tuple(item.case_id for item in self.results)
        if len(ids) != len(set(ids)):
            raise ValueError("conformance report contains duplicate case IDs")
        return self

    @property
    def all_passed(self) -> bool:
        return self.failed_cases == 0 and self.critical_failures == 0

    def semantic_signature(self) -> tuple[object, ...]:
        """Stable fields used to compare repeated deterministic runs."""
        return (
            self.suite_name,
            self.suite_revision,
            self.suite_sha256,
            tuple(
                (
                    item.case_id,
                    item.domain,
                    item.critical,
                    item.status,
                    item.expected,
                    item.actual,
                    item.mismatches,
                )
                for item in self.results
            ),
            self.total_cases,
            self.passed_cases,
            self.failed_cases,
            self.critical_failures,
        )
