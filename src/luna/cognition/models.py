"""Observable cognitive-quality contracts for Phase 19."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Self

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel


class FailureLabel(StrEnum):
    """Why a trajectory failed or degraded, beyond a binary pass/fail label."""

    INTENT_ERROR = "INTENT_ERROR"
    CONTEXT_ERROR = "CONTEXT_ERROR"
    PLANNING_ERROR = "PLANNING_ERROR"
    TOOL_SELECTION_ERROR = "TOOL_SELECTION_ERROR"
    TOOL_ARGUMENT_ERROR = "TOOL_ARGUMENT_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    OBSERVATION_INTERPRETATION_ERROR = "OBSERVATION_INTERPRETATION_ERROR"
    EVIDENCE_ERROR = "EVIDENCE_ERROR"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"
    UNCERTAINTY_ERROR = "UNCERTAINTY_ERROR"
    SELF_CORRECTION_ERROR = "SELF_CORRECTION_ERROR"


class CognitiveDimension(StrEnum):
    """Measurable behavior dimensions used for frozen baseline comparison."""

    REASONING = "REASONING"
    PLANNING = "PLANNING"
    TOOL_SELECTION = "TOOL_SELECTION"
    FAILURE_RECOVERY = "FAILURE_RECOVERY"
    EVIDENCE_USAGE = "EVIDENCE_USAGE"
    UNCERTAINTY_CALIBRATION = "UNCERTAINTY_CALIBRATION"
    SELF_CORRECTION = "SELF_CORRECTION"


class ConfidenceBand(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EvidenceState(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    SUFFICIENT = "SUFFICIENT"
    STRONG = "STRONG"
    CONTRADICTORY = "CONTRADICTORY"


class UncertaintyDirective(StrEnum):
    PROCEED = "PROCEED"
    INSPECT = "INSPECT"
    RESEARCH = "RESEARCH"
    ASK = "ASK"
    STOP = "STOP"


class UncertaintyAssessment(LunaContractModel):
    """Evidence-bound confidence decision; confidence alone never grants progress."""

    confidence: ConfidenceBand
    evidence: EvidenceState
    directive: UncertaintyDirective
    evidence_refs: tuple[str, ...] = ()

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("evidence refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("evidence refs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_calibration(self) -> Self:
        if self.evidence is EvidenceState.CONTRADICTORY:
            if self.directive is not UncertaintyDirective.STOP:
                raise ValueError("contradictory evidence requires STOP")
            return self
        if self.evidence is EvidenceState.INSUFFICIENT:
            if self.directive is UncertaintyDirective.PROCEED:
                raise ValueError("insufficient evidence cannot PROCEED")
            return self
        if (
            self.confidence is ConfidenceBand.HIGH
            and self.evidence in {
                EvidenceState.SUFFICIENT,
                EvidenceState.STRONG,
            }
            and self.directive is not UncertaintyDirective.PROCEED
        ):
            raise ValueError("high evidence-bound confidence should PROCEED")
        return self


class SelfCorrectionAssessment(LunaContractModel):
    """Distinguish changed-basis replanning from blind retry/pseudo-learning."""

    failed_assumption_identified: bool
    new_evidence_observed: bool
    strategy_changed: bool
    changed_dimensions: tuple[str, ...] = ()
    blind_retry: bool = False

    @field_validator("changed_dimensions")
    @classmethod
    def validate_changed_dimensions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("changed dimensions cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("changed dimensions must be unique")
        return cleaned

    @property
    def changed_basis(self) -> bool:
        return bool(
            self.failed_assumption_identified
            and self.new_evidence_observed
            and self.strategy_changed
            and self.changed_dimensions
            and not self.blind_retry
        )


class CognitiveScorecard(LunaContractModel):
    """Evidence-backed scores for one held-out or validation behavior case."""

    case_id: str = Field(min_length=1, max_length=300)
    scores: dict[CognitiveDimension, float]
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    failure_labels: tuple[FailureLabel, ...] = ()
    critical_regression: bool = False

    @field_validator("scores")
    @classmethod
    def validate_scores(
        cls,
        values: dict[CognitiveDimension, float],
    ) -> dict[CognitiveDimension, float]:
        if set(values) != set(CognitiveDimension):
            raise ValueError("scorecard must contain every cognitive dimension")
        if any(score < 0.0 or score > 1.0 for score in values.values()):
            raise ValueError("cognitive scores must be between 0 and 1")
        return values

    @field_validator("evidence_refs")
    @classmethod
    def validate_score_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("score evidence refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("score evidence refs must be unique")
        return cleaned


class FrozenCognitiveBaseline(LunaContractModel):
    """Pre-training baseline locked before any training transformation is evaluated."""

    baseline_name: str = Field(min_length=1, max_length=300)
    revision: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    scorecards: tuple[CognitiveScorecard, ...] = Field(min_length=1)
    locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @staticmethod
    def _payload(
        *,
        baseline_name: str,
        revision: str,
        scorecards: tuple[CognitiveScorecard, ...],
    ) -> dict[str, object]:
        return {
            "baseline_name": baseline_name,
            "revision": revision,
            "scorecards": [card.model_dump(mode="json") for card in scorecards],
        }

    @classmethod
    def freeze(
        cls,
        *,
        baseline_name: str,
        revision: str,
        scorecards: tuple[CognitiveScorecard, ...],
    ) -> Self:
        payload = cls._payload(
            baseline_name=baseline_name,
            revision=revision,
            scorecards=scorecards,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return cls(
            baseline_name=baseline_name,
            revision=revision,
            scorecards=scorecards,
            locked_sha256=sha256(serialized.encode("utf-8")).hexdigest(),
        )

    def computed_sha256(self) -> str:
        serialized = json.dumps(
            self._payload(
                baseline_name=self.baseline_name,
                revision=self.revision,
                scorecards=self.scorecards,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        ids = tuple(card.case_id for card in self.scorecards)
        if len(ids) != len(set(ids)):
            raise ValueError("baseline case IDs must be unique")
        if self.locked_sha256 != self.computed_sha256():
            raise ValueError("cognitive baseline digest mismatch")
        return self

    def dimension_means(self) -> dict[CognitiveDimension, float]:
        return {
            dimension: sum(card.scores[dimension] for card in self.scorecards)
            / len(self.scorecards)
            for dimension in CognitiveDimension
        }


class CognitiveComparisonVerdict(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class CognitiveComparison(LunaContractModel):
    """Comparison against a frozen pre-training baseline, never a generic claim."""

    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimension_deltas: dict[CognitiveDimension, float]
    regressed_dimensions: tuple[CognitiveDimension, ...] = ()
    critical_regression_count: int = Field(ge=0)
    held_out_contamination_detected: bool = False
    verdict: CognitiveComparisonVerdict

    @field_validator("dimension_deltas")
    @classmethod
    def validate_dimension_deltas(
        cls,
        values: dict[CognitiveDimension, float],
    ) -> dict[CognitiveDimension, float]:
        if set(values) != set(CognitiveDimension):
            raise ValueError("comparison must contain every cognitive dimension")
        return values

    @model_validator(mode="after")
    def validate_verdict(self) -> Self:
        if (
            (
                self.regressed_dimensions
                or self.critical_regression_count
                or self.held_out_contamination_detected
            )
            and self.verdict is not CognitiveComparisonVerdict.REJECT
        ):
            raise ValueError("regression or contamination requires REJECT")
        return self
