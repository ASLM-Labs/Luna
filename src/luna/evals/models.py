"""Versioned fixed-eval contracts and comparable regression results."""

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
    """Return a stable SHA-256 digest for JSON-compatible payloads."""
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


class EvalMetric(StrEnum):
    """Release-relevant Luna behavior measured by the fixed suite."""

    TASK_SUCCESS = "TASK_SUCCESS"
    FALSE_VERIFIED_COMPLETE = "FALSE_VERIFIED_COMPLETE"
    INSPECT_BEFORE_EDIT = "INSPECT_BEFORE_EDIT"
    PROTECTED_PATH = "PROTECTED_PATH"
    BLIND_RETRY = "BLIND_RETRY"
    ROLLBACK = "ROLLBACK"
    CHECKPOINT_RESUME = "CHECKPOINT_RESUME"
    MEMORY_POLLUTION = "MEMORY_POLLUTION"
    UNNECESSARY_QUESTION = "UNNECESSARY_QUESTION"
    SCOPE_CREEP = "SCOPE_CREEP"
    FINAL_REPORT_ACCURACY = "FINAL_REPORT_ACCURACY"


class EvalCaseStatus(StrEnum):
    """Deterministic result for one eval case."""

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class EvalCase(LunaContractModel):
    """One immutable fixture plus its expected oracle payload."""

    case_id: str = Field(pattern=r"^L11-[0-9]{2}-[a-z0-9-]+$")
    title: str = Field(min_length=1, max_length=500)
    metric: EvalMetric
    critical: bool = True
    fixture: dict[str, object]
    oracle: dict[str, object]
    tags: tuple[str, ...] = ()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("eval tags cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("eval tags must be unique")
        return cleaned

    def integrity_payload(self) -> dict[str, object]:
        """Return the stable payload protected by the suite hash."""
        return {
            "case_id": self.case_id,
            "title": self.title,
            "metric": self.metric.value,
            "critical": self.critical,
            "fixture": self.fixture,
            "oracle": self.oracle,
            "tags": self.tags,
        }


class LockedEvalSuite(LunaContractModel):
    """Fixed revision whose fixture and oracle content is hash protected."""

    suite_name: str = Field(min_length=1, max_length=500)
    revision: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    cases: tuple[EvalCase, ...] = Field(min_length=1)
    locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def lock(
        cls,
        *,
        suite_name: str,
        revision: str,
        cases: tuple[EvalCase, ...],
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
        cases: tuple[EvalCase, ...],
    ) -> dict[str, object]:
        return {
            "suite_name": suite_name,
            "revision": revision,
            "cases": [item.integrity_payload() for item in cases],
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
    def validate_integrity(self) -> LockedEvalSuite:
        case_ids = tuple(item.case_id for item in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("eval case IDs must be unique")
        if self.locked_sha256 != self.computed_sha256():
            raise ValueError("fixed eval fixture/oracle digest mismatch")
        return self


class EvalObservation(LunaContractModel):
    """Normalized runtime observation returned by an eval executor."""

    case_id: str
    actual: dict[str, object]
    duration_ms: int = Field(default=0, ge=0)
    token_cost: int = Field(default=0, ge=0)


class EvalCaseResult(LunaContractModel):
    """One oracle comparison with complete traceability."""

    case_id: str
    metric: EvalMetric
    critical: bool
    status: EvalCaseStatus
    expected: dict[str, object]
    actual: dict[str, object]
    mismatches: tuple[str, ...] = ()
    duration_ms: int = Field(default=0, ge=0)
    token_cost: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_status(self) -> EvalCaseResult:
        if self.status is EvalCaseStatus.PASS and self.mismatches:
            raise ValueError("passing eval case cannot contain mismatches")
        if self.status is not EvalCaseStatus.PASS and not self.mismatches:
            raise ValueError("non-passing eval case requires mismatches")
        return self


class EvalMetrics(LunaContractModel):
    """Comparable release metrics derived only from case results."""

    total_cases: int = Field(ge=1)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    critical_failures: int = Field(ge=0)
    task_success_rate: float = Field(ge=0.0, le=1.0)
    verified_success_rate: float = Field(ge=0.0, le=1.0)
    false_verified_complete_count: int = Field(ge=0)
    protected_path_violation_count: int = Field(ge=0)
    blind_retry_count: int = Field(ge=0)
    inspect_before_edit_pass: bool
    rollback_pass: bool
    checkpoint_resume_pass: bool
    memory_pollution_pass: bool
    unnecessary_question_pass: bool
    scope_creep_pass: bool
    final_report_accuracy_pass: bool
    duration_ms: int = Field(ge=0)
    token_cost: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> EvalMetrics:
        if self.passed_cases + self.failed_cases != self.total_cases:
            raise ValueError("eval pass/fail counts must equal total cases")
        return self


class EvalReport(LunaContractModel):
    """Hash-bound deterministic regression report for one suite revision."""

    report_id: UUID = Field(default_factory=uuid4)
    suite_name: str
    suite_revision: str
    suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_results: tuple[EvalCaseResult, ...]
    metrics: EvalMetrics
    generated_at: datetime = Field(default_factory=utc_now)

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_result_count(self) -> EvalReport:
        if len(self.case_results) != self.metrics.total_cases:
            raise ValueError("eval report result count does not match metrics")
        ids = tuple(item.case_id for item in self.case_results)
        if len(ids) != len(set(ids)):
            raise ValueError("eval report contains duplicate case IDs")
        return self

    def semantic_signature(self) -> tuple[object, ...]:
        """Return stable fields used to compare repeated runs."""
        return (
            self.suite_name,
            self.suite_revision,
            self.suite_sha256,
            tuple(
                (
                    item.case_id,
                    item.metric,
                    item.critical,
                    item.status,
                    item.expected,
                    item.actual,
                    item.mismatches,
                    item.duration_ms,
                    item.token_cost,
                )
                for item in self.case_results
            ),
            self.metrics,
        )
