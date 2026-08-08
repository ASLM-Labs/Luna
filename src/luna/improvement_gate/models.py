"""Phase 19F improvement-gate contracts."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from typing import Self

from pydantic import Field, field_validator, model_validator

from luna.cognition import CognitiveDimension
from luna.contracts.base import LunaContractModel
from luna.learning_integrity import LearningIntegrityStatus


class ImprovementGateDecision(StrEnum):
    """Governance decision; runtime execution remains outside this layer."""

    PROMOTE = "PROMOTE"
    REJECT = "REJECT"
    ROLLBACK = "ROLLBACK"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class MetricDisposition(StrEnum):
    """Confidence-aware interpretation of one paired score delta."""

    MEANINGFUL_IMPROVEMENT = "MEANINGFUL_IMPROVEMENT"
    NO_CLEAR_CHANGE = "NO_CLEAR_CHANGE"
    MEANINGFUL_REGRESSION = "MEANINGFUL_REGRESSION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EvaluationSlice(StrEnum):
    """Slices that Phase 19F evaluates separately before promotion."""

    ALL = "ALL"
    HELD_OUT = "HELD_OUT"
    OOD = "OOD"


class DimensionThreshold(LunaContractModel):
    """Meaningful-change bounds for one cognitive dimension."""

    meaningful_improvement: float = Field(ge=0.0, le=1.0)
    regression_tolerance: float = Field(ge=0.0, le=1.0)


class ImprovementGatePolicy(LunaContractModel):
    """Frozen Phase 19F promotion-evidence policy."""

    revision: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    confidence_level: float = Field(gt=0.5, lt=1.0)
    min_cases_per_slice: int = Field(ge=2)
    min_meaningful_improved_dimensions: int = Field(ge=1)
    dimension_thresholds: dict[CognitiveDimension, DimensionThreshold]
    require_clean_learning_integrity: bool = True
    require_held_out_and_ood: bool = True
    critical_regression_zero_tolerance: bool = True
    runtime_authority: bool = False
    locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("dimension_thresholds")
    @classmethod
    def validate_dimensions(
        cls,
        values: dict[CognitiveDimension, DimensionThreshold],
    ) -> dict[CognitiveDimension, DimensionThreshold]:
        if set(values) != set(CognitiveDimension):
            raise ValueError("improvement policy must define every cognitive dimension")
        return values

    @staticmethod
    def _payload(
        *,
        revision: str,
        confidence_level: float,
        min_cases_per_slice: int,
        min_meaningful_improved_dimensions: int,
        dimension_thresholds: dict[CognitiveDimension, DimensionThreshold],
        require_clean_learning_integrity: bool,
        require_held_out_and_ood: bool,
        critical_regression_zero_tolerance: bool,
        runtime_authority: bool,
    ) -> dict[str, object]:
        return {
            "revision": revision,
            "confidence_level": confidence_level,
            "min_cases_per_slice": min_cases_per_slice,
            "min_meaningful_improved_dimensions": min_meaningful_improved_dimensions,
            "dimension_thresholds": {
                dimension.value: dimension_thresholds[dimension].model_dump(mode="json")
                for dimension in CognitiveDimension
            },
            "require_clean_learning_integrity": require_clean_learning_integrity,
            "require_held_out_and_ood": require_held_out_and_ood,
            "critical_regression_zero_tolerance": critical_regression_zero_tolerance,
            "runtime_authority": runtime_authority,
        }

    @classmethod
    def freeze(
        cls,
        *,
        revision: str,
        confidence_level: float = 0.95,
        min_cases_per_slice: int = 2,
        min_meaningful_improved_dimensions: int = 1,
        dimension_thresholds: dict[CognitiveDimension, DimensionThreshold],
        require_clean_learning_integrity: bool = True,
        require_held_out_and_ood: bool = True,
        critical_regression_zero_tolerance: bool = True,
        runtime_authority: bool = False,
    ) -> Self:
        payload = cls._payload(
            revision=revision,
            confidence_level=confidence_level,
            min_cases_per_slice=min_cases_per_slice,
            min_meaningful_improved_dimensions=min_meaningful_improved_dimensions,
            dimension_thresholds=dimension_thresholds,
            require_clean_learning_integrity=require_clean_learning_integrity,
            require_held_out_and_ood=require_held_out_and_ood,
            critical_regression_zero_tolerance=critical_regression_zero_tolerance,
            runtime_authority=runtime_authority,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return cls(
            revision=revision,
            confidence_level=confidence_level,
            min_cases_per_slice=min_cases_per_slice,
            min_meaningful_improved_dimensions=min_meaningful_improved_dimensions,
            dimension_thresholds=dimension_thresholds,
            require_clean_learning_integrity=require_clean_learning_integrity,
            require_held_out_and_ood=require_held_out_and_ood,
            critical_regression_zero_tolerance=critical_regression_zero_tolerance,
            runtime_authority=runtime_authority,
            locked_sha256=sha256(serialized.encode("utf-8")).hexdigest(),
        )

    def computed_sha256(self) -> str:
        payload = self._payload(
            revision=self.revision,
            confidence_level=self.confidence_level,
            min_cases_per_slice=self.min_cases_per_slice,
            min_meaningful_improved_dimensions=self.min_meaningful_improved_dimensions,
            dimension_thresholds=self.dimension_thresholds,
            require_clean_learning_integrity=self.require_clean_learning_integrity,
            require_held_out_and_ood=self.require_held_out_and_ood,
            critical_regression_zero_tolerance=self.critical_regression_zero_tolerance,
            runtime_authority=self.runtime_authority,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.runtime_authority:
            raise ValueError("improvement gate cannot grant runtime authority")
        if self.min_meaningful_improved_dimensions > len(CognitiveDimension):
            raise ValueError("minimum improved dimensions exceeds dimension count")
        if self.locked_sha256 != self.computed_sha256():
            raise ValueError("improvement gate policy digest mismatch")
        return self


class DimensionEstimate(LunaContractModel):
    """Paired baseline-to-candidate delta with a two-sided confidence interval."""

    dimension: CognitiveDimension
    evaluation_slice: EvaluationSlice
    case_count: int = Field(ge=0)
    mean_delta: float
    confidence_level: float = Field(gt=0.5, lt=1.0)
    ci_lower: float | None = None
    ci_upper: float | None = None
    meaningful_improvement: float = Field(ge=0.0, le=1.0)
    regression_tolerance: float = Field(ge=0.0, le=1.0)
    disposition: MetricDisposition

    @model_validator(mode="after")
    def validate_estimate(self) -> Self:
        numeric = (self.mean_delta, self.meaningful_improvement, self.regression_tolerance)
        if any(not isfinite(value) for value in numeric):
            raise ValueError("dimension estimate values must be finite")
        if (self.ci_lower is None) != (self.ci_upper is None):
            raise ValueError("confidence interval bounds must be both present or both absent")
        if self.ci_lower is not None and self.ci_upper is not None:
            if not isfinite(self.ci_lower) or not isfinite(self.ci_upper):
                raise ValueError("confidence interval bounds must be finite")
            if self.ci_lower > self.ci_upper:
                raise ValueError("confidence interval lower bound cannot exceed upper bound")
        if self.disposition is MetricDisposition.INSUFFICIENT_EVIDENCE:
            if self.ci_lower is not None or self.ci_upper is not None:
                raise ValueError("insufficient estimate cannot claim a confidence interval")
        elif self.ci_lower is None or self.ci_upper is None:
            raise ValueError("evaluated estimate requires confidence interval bounds")
        return self


class ImprovementGateReport(LunaContractModel):
    """Phase 19F evidence decision without direct runtime execution authority."""

    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: ImprovementGateDecision
    candidate_id: str | None = Field(default=None, min_length=1, max_length=300)
    candidate_evidence_verified: bool = False
    candidate_currently_active: bool = False
    evaluation_suite_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evaluator_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    learning_integrity_status: LearningIntegrityStatus | None = None
    contamination_detected: bool = False
    estimates: tuple[DimensionEstimate, ...] = ()
    meaningfully_improved_dimensions: tuple[CognitiveDimension, ...] = ()
    meaningfully_regressed_dimensions: tuple[CognitiveDimension, ...] = ()
    critical_regressed_case_ids: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    runtime_authority: bool = False
    action_executed: bool = False

    @field_validator(
        "meaningfully_improved_dimensions",
        "meaningfully_regressed_dimensions",
    )
    @classmethod
    def validate_unique_dimensions(
        cls,
        values: tuple[CognitiveDimension, ...],
    ) -> tuple[CognitiveDimension, ...]:
        if len(values) != len(set(values)):
            raise ValueError("improvement gate dimension lists must be unique")
        return values

    @field_validator("critical_regressed_case_ids", "blocked_reasons")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("improvement gate text values cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("improvement gate text values must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.runtime_authority or self.action_executed:
            raise ValueError("Phase 19F may decide but cannot execute runtime release actions")
        if self.decision is ImprovementGateDecision.PROMOTE:
            if not self.candidate_evidence_verified:
                raise ValueError("PROMOTE requires verified real candidate evidence")
            if self.blocked_reasons:
                raise ValueError("PROMOTE cannot contain blocked reasons")
            if self.meaningfully_regressed_dimensions or self.critical_regressed_case_ids:
                raise ValueError("PROMOTE cannot contain regressions")
            if not self.meaningfully_improved_dimensions:
                raise ValueError("PROMOTE requires meaningful multi-metric improvement evidence")
        elif not self.blocked_reasons:
            raise ValueError("non-PROMOTE decision requires an explicit reason")
        if (
            self.decision is ImprovementGateDecision.ROLLBACK
            and not self.candidate_currently_active
        ):
            raise ValueError("ROLLBACK requires an active candidate")
        return self
