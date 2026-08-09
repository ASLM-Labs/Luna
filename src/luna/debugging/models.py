"""C-007 observable debugging decomposition and transfer contracts."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.experience import EvidenceOrigin
from luna.trajectories import DatasetSplit


class DebuggingStage(StrEnum):
    """Canonical observable stages in Luna's debugging capability stack."""

    ERROR_OBSERVATION = "ERROR_OBSERVATION"
    FAILURE_LOCALIZATION = "FAILURE_LOCALIZATION"
    HYPOTHESIS_GENERATION_RANKING = "HYPOTHESIS_GENERATION_RANKING"
    BROKEN_ASSUMPTION_DETECTION = "BROKEN_ASSUMPTION_DETECTION"
    STATE_CONTEXT_INSPECTION = "STATE_CONTEXT_INSPECTION"
    MINIMAL_REPAIR_PLANNING = "MINIMAL_REPAIR_PLANNING"
    TOOL_SELECTION = "TOOL_SELECTION"
    PATCH_ACTION = "PATCH_ACTION"
    TARGETED_VERIFICATION = "TARGETED_VERIFICATION"
    FULL_REGRESSION_VERIFICATION = "FULL_REGRESSION_VERIFICATION"
    CHANGED_BASIS_REPLAN = "CHANGED_BASIS_REPLAN"
    PREVENTION_PROCESS_LESSON = "PREVENTION_PROCESS_LESSON"


class DebuggingMetric(StrEnum):
    """Debugging-specific transfer metrics; generic improvement claims are forbidden."""

    REPAIR_SUCCESS = "REPAIR_SUCCESS"
    DIAGNOSIS_QUALITY = "DIAGNOSIS_QUALITY"
    FAILURE_LOCALIZATION = "FAILURE_LOCALIZATION"
    HYPOTHESIS_QUALITY = "HYPOTHESIS_QUALITY"
    BROKEN_ASSUMPTION_DETECTION = "BROKEN_ASSUMPTION_DETECTION"
    STATE_CONTEXT_INSPECTION = "STATE_CONTEXT_INSPECTION"
    MINIMAL_REPAIR_PLANNING = "MINIMAL_REPAIR_PLANNING"
    TOOL_SELECTION = "TOOL_SELECTION"
    PATCH_ACTION_QUALITY = "PATCH_ACTION_QUALITY"
    TARGETED_VERIFICATION = "TARGETED_VERIFICATION"
    FULL_REGRESSION_VERIFICATION = "FULL_REGRESSION_VERIFICATION"
    CHANGED_BASIS_REPLAN = "CHANGED_BASIS_REPLAN"
    PREVENTION_LESSON = "PREVENTION_LESSON"


class DebuggingTransferVerdict(StrEnum):
    """Evidence verdict for a controlled lesson-to-capability transfer evaluation."""

    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DebuggingStageAssessment(LunaContractModel):
    """Observable evidence and quality score for one debugging stage."""

    stage: DebuggingStage
    score: float = Field(ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    observation_summary: str = Field(min_length=1, max_length=2000)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("debugging evidence refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("debugging evidence refs must be unique")
        return cleaned


_BASE_STAGE_ORDER = (
    DebuggingStage.ERROR_OBSERVATION,
    DebuggingStage.FAILURE_LOCALIZATION,
    DebuggingStage.HYPOTHESIS_GENERATION_RANKING,
    DebuggingStage.BROKEN_ASSUMPTION_DETECTION,
    DebuggingStage.STATE_CONTEXT_INSPECTION,
    DebuggingStage.MINIMAL_REPAIR_PLANNING,
    DebuggingStage.TOOL_SELECTION,
    DebuggingStage.PATCH_ACTION,
    DebuggingStage.TARGETED_VERIFICATION,
    DebuggingStage.FULL_REGRESSION_VERIFICATION,
)


class DebuggingEvaluationCase(LunaContractModel):
    """One independently evaluated debugging behavior case."""

    case_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    task_family: str = Field(min_length=1, max_length=300)
    split_group_key: str = Field(min_length=1, max_length=500)
    dataset_split: DatasetSplit
    stage_assessments: tuple[DebuggingStageAssessment, ...] = Field(min_length=1)
    diagnosis_correct: bool
    repair_succeeded: bool
    initial_repair_failed: bool = False
    applied_lesson_ids: tuple[str, ...] = ()
    evaluator_ref: str = Field(min_length=1, max_length=500)
    evidence_origin: EvidenceOrigin
    critical_regression: bool = False

    @field_validator("applied_lesson_ids")
    @classmethod
    def validate_lesson_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("applied lesson IDs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("applied lesson IDs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_observable_stack(self) -> Self:
        if self.evidence_origin is EvidenceOrigin.MODEL_SELF_REPORT:
            raise ValueError("model self-report cannot independently score debugging transfer")

        stages = tuple(item.stage for item in self.stage_assessments)
        if len(stages) != len(set(stages)):
            raise ValueError("debugging stages must be unique within a case")

        expected: tuple[DebuggingStage, ...] = _BASE_STAGE_ORDER
        if self.initial_repair_failed:
            expected = (*expected, DebuggingStage.CHANGED_BASIS_REPLAN)
        expected = (*expected, DebuggingStage.PREVENTION_PROCESS_LESSON)
        if stages != expected:
            raise ValueError("debugging case must follow the canonical observable stage order")
        return self

    def stage_score(self, stage: DebuggingStage) -> float:
        for assessment in self.stage_assessments:
            if assessment.stage is stage:
                return assessment.score
        raise KeyError(f"debugging stage not applicable to case: {stage.value}")


class ControlledLessonTransferBinding(LunaContractModel):
    """Explicit review boundary for testing a C-003 lesson in controlled evaluation only."""

    lesson_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    reviewer_ref: str = Field(min_length=1, max_length=500)
    review_origin: EvidenceOrigin = EvidenceOrigin.HUMAN_REVIEW
    approval_scope: tuple[str, ...] = Field(min_length=1)
    approved_for_controlled_evaluation: Literal[True] = True
    evaluation_only: Literal[True] = True
    automatic_memory_commit_allowed: Literal[False] = False
    runtime_authority: Literal[False] = False
    training_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("review_origin")
    @classmethod
    def validate_review_origin(cls, value: EvidenceOrigin) -> EvidenceOrigin:
        if value is not EvidenceOrigin.HUMAN_REVIEW:
            raise ValueError("controlled lesson transfer requires explicit human review")
        return value

    @field_validator("approval_scope")
    @classmethod
    def validate_scope(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("controlled transfer scope cannot contain blanks")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("controlled transfer scope must be unique")
        return cleaned


class DebuggingTransferPolicy(LunaContractModel):
    """Frozen deterministic policy for C-007 held-out paired evaluation."""

    revision: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    min_held_out_cases: int = Field(default=2, ge=2)
    meaningful_improvement: float = Field(default=0.05, ge=0.0, le=1.0)
    regression_tolerance: float = Field(default=0.0, ge=0.0, le=1.0)
    required_outcome_metrics: tuple[DebuggingMetric, ...] = (
        DebuggingMetric.REPAIR_SUCCESS,
        DebuggingMetric.DIAGNOSIS_QUALITY,
    )
    runtime_authority: Literal[False] = False
    locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("required_outcome_metrics")
    @classmethod
    def validate_required_metrics(
        cls,
        values: tuple[DebuggingMetric, ...],
    ) -> tuple[DebuggingMetric, ...]:
        if not values:
            raise ValueError("debugging transfer policy requires outcome metrics")
        if len(values) != len(set(values)):
            raise ValueError("required outcome metrics must be unique")
        required = {DebuggingMetric.REPAIR_SUCCESS, DebuggingMetric.DIAGNOSIS_QUALITY}
        if not required.issubset(values):
            raise ValueError("debugging transfer must measure repair success and diagnosis quality")
        return values

    @staticmethod
    def _payload(
        *,
        revision: str,
        min_held_out_cases: int,
        meaningful_improvement: float,
        regression_tolerance: float,
        required_outcome_metrics: tuple[DebuggingMetric, ...],
        runtime_authority: bool,
    ) -> dict[str, object]:
        return {
            "revision": revision,
            "min_held_out_cases": min_held_out_cases,
            "meaningful_improvement": meaningful_improvement,
            "regression_tolerance": regression_tolerance,
            "required_outcome_metrics": [metric.value for metric in required_outcome_metrics],
            "runtime_authority": runtime_authority,
        }

    @classmethod
    def freeze(
        cls,
        *,
        revision: str,
        min_held_out_cases: int = 2,
        meaningful_improvement: float = 0.05,
        regression_tolerance: float = 0.0,
        required_outcome_metrics: tuple[DebuggingMetric, ...] = (
            DebuggingMetric.REPAIR_SUCCESS,
            DebuggingMetric.DIAGNOSIS_QUALITY,
        ),
    ) -> Self:
        payload = cls._payload(
            revision=revision,
            min_held_out_cases=min_held_out_cases,
            meaningful_improvement=meaningful_improvement,
            regression_tolerance=regression_tolerance,
            required_outcome_metrics=required_outcome_metrics,
            runtime_authority=False,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return cls(
            revision=revision,
            min_held_out_cases=min_held_out_cases,
            meaningful_improvement=meaningful_improvement,
            regression_tolerance=regression_tolerance,
            required_outcome_metrics=required_outcome_metrics,
            locked_sha256=sha256(serialized.encode("utf-8")).hexdigest(),
        )

    def computed_sha256(self) -> str:
        payload = self._payload(
            revision=self.revision,
            min_held_out_cases=self.min_held_out_cases,
            meaningful_improvement=self.meaningful_improvement,
            regression_tolerance=self.regression_tolerance,
            required_outcome_metrics=self.required_outcome_metrics,
            runtime_authority=self.runtime_authority,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        if self.locked_sha256 != self.computed_sha256():
            raise ValueError("debugging transfer policy digest mismatch")
        return self


class DebuggingMetricDelta(LunaContractModel):
    """Paired held-out baseline-to-transfer metric delta."""

    metric: DebuggingMetric
    case_count: int = Field(ge=1)
    baseline_mean: float = Field(ge=0.0, le=1.0)
    candidate_mean: float = Field(ge=0.0, le=1.0)
    delta: float = Field(ge=-1.0, le=1.0)


class DebuggingTransferAssessment(LunaContractModel):
    """C-007 transfer evidence report with no runtime or promotion authority."""

    lesson_id: str
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: DebuggingTransferVerdict
    held_out_case_ids: tuple[str, ...] = ()
    metric_deltas: tuple[DebuggingMetricDelta, ...] = ()
    meaningfully_improved_metrics: tuple[DebuggingMetric, ...] = ()
    regressed_metrics: tuple[DebuggingMetric, ...] = ()
    critical_regression_case_ids: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    review_required: Literal[True] = True
    automatic_memory_commit_allowed: Literal[False] = False
    runtime_authority: Literal[False] = False
    training_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    action_executed: Literal[False] = False

    @model_validator(mode="after")
    def validate_verdict(self) -> Self:
        if self.verdict is DebuggingTransferVerdict.SUPPORTED:
            if self.blocked_reasons or self.regressed_metrics or self.critical_regression_case_ids:
                raise ValueError("supported debugging transfer cannot contain blocking regressions")
            if not self.meaningfully_improved_metrics:
                raise ValueError("supported debugging transfer requires meaningful improvement")
        elif self.verdict is DebuggingTransferVerdict.INSUFFICIENT_EVIDENCE:
            if not self.blocked_reasons:
                raise ValueError("insufficient debugging transfer requires a blocking reason")
        return self
