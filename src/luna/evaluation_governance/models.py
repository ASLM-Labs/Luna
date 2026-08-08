"""Evaluation-governance contracts for Luna Phase 19B."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Self

from pydantic import Field, field_validator, model_validator

from luna.cognition import CognitiveDimension, CognitiveScorecard
from luna.contracts.base import LunaContractModel


class EvaluationPartition(StrEnum):
    """Partitions that must remain outside training exposure."""

    HELD_OUT = "HELD_OUT"
    OOD = "OOD"


class EvaluatorKind(StrEnum):
    """Supported evaluator classes with explicit provenance."""

    DETERMINISTIC = "DETERMINISTIC"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    MODEL_JUDGE = "MODEL_JUDGE"


class ContaminationReason(StrEnum):
    """Why an evaluation case is contaminated by training exposure."""

    EXACT_CONTENT = "EXACT_CONTENT"
    SOURCE_TRAJECTORY = "SOURCE_TRAJECTORY"
    TASK_FAMILY = "TASK_FAMILY"
    REPOSITORY_FAMILY = "REPOSITORY_FAMILY"
    TRAJECTORY_FAMILY = "TRAJECTORY_FAMILY"


class ReleaseComparisonStatus(StrEnum):
    """Comparison state only; it is not a promotion decision."""

    COMPARABLE = "COMPARABLE"
    REGRESSION_DETECTED = "REGRESSION_DETECTED"
    BLOCKED = "BLOCKED"


class EvaluatorSpec(LunaContractModel):
    """Versioned evaluator identity that cannot silently depend on the candidate."""

    evaluator_id: str = Field(min_length=1, max_length=300)
    revision: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    kind: EvaluatorKind
    implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_from_candidate_artifacts: bool
    independent_from_training_data: bool
    model_identity: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_independence(self) -> Self:
        if not self.independent_from_candidate_artifacts:
            raise ValueError("evaluator must be independent from candidate artifacts")
        if not self.independent_from_training_data:
            raise ValueError("evaluator must be independent from training data")
        if self.kind is EvaluatorKind.MODEL_JUDGE and self.model_identity is None:
            raise ValueError("model judge evaluator requires model identity")
        if self.kind is not EvaluatorKind.MODEL_JUDGE and self.model_identity is not None:
            raise ValueError("only model judge evaluator may declare model identity")
        return self

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def assert_independent_for_candidate(self, candidate_model_id: str) -> None:
        candidate = candidate_model_id.strip()
        if not candidate:
            raise ValueError("candidate model identity is required")
        if self.kind is EvaluatorKind.MODEL_JUDGE and self.model_identity == candidate:
            raise ValueError("candidate model cannot judge itself")


class EvaluationCase(LunaContractModel):
    """One immutable held-out or OOD evaluation case identity."""

    case_id: str = Field(min_length=1, max_length=300)
    source_trajectory_id: str = Field(min_length=1, max_length=300)
    partition: EvaluationPartition
    task_family: str = Field(min_length=1, max_length=300)
    repository_family: str = Field(min_length=1, max_length=300)
    trajectory_family: str = Field(min_length=1, max_length=300)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("evaluation evidence refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("evaluation evidence refs must be unique")
        return cleaned

    @property
    def group_key(self) -> str:
        return "|".join(
            (
                self.task_family,
                self.repository_family,
                self.trajectory_family,
            )
        )


class TrainingExposure(LunaContractModel):
    """Minimal training-side fingerprint used only for contamination checks."""

    source_trajectory_id: str = Field(min_length=1, max_length=300)
    task_family: str = Field(min_length=1, max_length=300)
    repository_family: str = Field(min_length=1, max_length=300)
    trajectory_family: str = Field(min_length=1, max_length=300)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ContaminationFinding(LunaContractModel):
    case_id: str = Field(min_length=1, max_length=300)
    exposure_source_trajectory_id: str = Field(min_length=1, max_length=300)
    reason: ContaminationReason


class BenchmarkContaminationReport(LunaContractModel):
    findings: tuple[ContaminationFinding, ...] = ()

    @property
    def contaminated(self) -> bool:
        return bool(self.findings)


class FrozenEvaluationSuite(LunaContractModel):
    """Versioned held-out/OOD suite locked before candidate training comparison."""

    suite_name: str = Field(min_length=1, max_length=300)
    revision: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    evaluator: EvaluatorSpec
    cases: tuple[EvaluationCase, ...] = Field(min_length=2)
    locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @staticmethod
    def _payload(
        *,
        suite_name: str,
        revision: str,
        evaluator: EvaluatorSpec,
        cases: tuple[EvaluationCase, ...],
    ) -> dict[str, object]:
        return {
            "suite_name": suite_name,
            "revision": revision,
            "evaluator": evaluator.model_dump(mode="json"),
            "cases": [case.model_dump(mode="json") for case in cases],
        }

    @classmethod
    def freeze(
        cls,
        *,
        suite_name: str,
        revision: str,
        evaluator: EvaluatorSpec,
        cases: tuple[EvaluationCase, ...],
    ) -> Self:
        payload = cls._payload(
            suite_name=suite_name,
            revision=revision,
            evaluator=evaluator,
            cases=cases,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return cls(
            suite_name=suite_name,
            revision=revision,
            evaluator=evaluator,
            cases=cases,
            locked_sha256=sha256(serialized.encode("utf-8")).hexdigest(),
        )

    def computed_sha256(self) -> str:
        payload = self._payload(
            suite_name=self.suite_name,
            revision=self.revision,
            evaluator=self.evaluator,
            cases=self.cases,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_suite(self) -> Self:
        case_ids = tuple(case.case_id for case in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation case IDs must be unique")
        source_ids = tuple(case.source_trajectory_id for case in self.cases)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("evaluation source trajectory IDs must be unique")
        partitions = {case.partition for case in self.cases}
        if partitions != {EvaluationPartition.HELD_OUT, EvaluationPartition.OOD}:
            raise ValueError("evaluation suite requires both HELD_OUT and OOD cases")
        group_partitions: dict[str, EvaluationPartition] = {}
        for case in self.cases:
            previous = group_partitions.setdefault(case.group_key, case.partition)
            if previous is not case.partition:
                raise ValueError("evaluation group cannot span held-out and OOD partitions")
        if self.locked_sha256 != self.computed_sha256():
            raise ValueError("evaluation suite digest mismatch")
        return self

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases)


class FrozenRegressionSuite(LunaContractModel):
    """Locked case inventory for repeatable release-to-release regression runs."""

    revision: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    evaluation_suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_case_ids: tuple[str, ...] = Field(min_length=1)
    critical_case_ids: tuple[str, ...] = ()
    locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @staticmethod
    def _payload(
        *,
        revision: str,
        evaluation_suite_sha256: str,
        required_case_ids: tuple[str, ...],
        critical_case_ids: tuple[str, ...],
    ) -> dict[str, object]:
        return {
            "revision": revision,
            "evaluation_suite_sha256": evaluation_suite_sha256,
            "required_case_ids": list(required_case_ids),
            "critical_case_ids": list(critical_case_ids),
        }

    @classmethod
    def freeze(
        cls,
        *,
        revision: str,
        evaluation_suite: FrozenEvaluationSuite,
        critical_case_ids: tuple[str, ...] = (),
    ) -> Self:
        required = evaluation_suite.case_ids
        payload = cls._payload(
            revision=revision,
            evaluation_suite_sha256=evaluation_suite.locked_sha256,
            required_case_ids=required,
            critical_case_ids=critical_case_ids,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return cls(
            revision=revision,
            evaluation_suite_sha256=evaluation_suite.locked_sha256,
            required_case_ids=required,
            critical_case_ids=critical_case_ids,
            locked_sha256=sha256(serialized.encode("utf-8")).hexdigest(),
        )

    def computed_sha256(self) -> str:
        payload = self._payload(
            revision=self.revision,
            evaluation_suite_sha256=self.evaluation_suite_sha256,
            required_case_ids=self.required_case_ids,
            critical_case_ids=self.critical_case_ids,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_regression_suite(self) -> Self:
        if len(self.required_case_ids) != len(set(self.required_case_ids)):
            raise ValueError("regression required case IDs must be unique")
        if len(self.critical_case_ids) != len(set(self.critical_case_ids)):
            raise ValueError("regression critical case IDs must be unique")
        if not set(self.critical_case_ids).issubset(self.required_case_ids):
            raise ValueError("critical cases must be part of required regression cases")
        if self.locked_sha256 != self.computed_sha256():
            raise ValueError("regression suite digest mismatch")
        return self


class ReleaseEvaluationSnapshot(LunaContractModel):
    """One release's immutable scorecard set under a specific suite/evaluator."""

    release_id: str = Field(min_length=1, max_length=300)
    candidate_model_id: str = Field(min_length=1, max_length=300)
    evaluation_suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    scorecards: tuple[CognitiveScorecard, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scorecards(self) -> Self:
        ids = tuple(card.case_id for card in self.scorecards)
        if len(ids) != len(set(ids)):
            raise ValueError("release evaluation case IDs must be unique")
        return self


class ReleaseComparison(LunaContractModel):
    """Like-for-like release comparison without any promotion authority."""

    baseline_release_id: str = Field(min_length=1, max_length=300)
    candidate_release_id: str = Field(min_length=1, max_length=300)
    evaluation_suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimension_deltas: dict[CognitiveDimension, float]
    regressed_case_ids: tuple[str, ...] = ()
    critical_regressed_case_ids: tuple[str, ...] = ()
    contamination_detected: bool
    blocked_reasons: tuple[str, ...] = ()
    status: ReleaseComparisonStatus
    promotion_authorized: bool = False

    @field_validator("dimension_deltas")
    @classmethod
    def validate_dimension_deltas(
        cls,
        values: dict[CognitiveDimension, float],
    ) -> dict[CognitiveDimension, float]:
        if set(values) != set(CognitiveDimension):
            raise ValueError("release comparison must contain every cognitive dimension")
        return values

    @model_validator(mode="after")
    def validate_authority_and_status(self) -> Self:
        if self.promotion_authorized:
            raise ValueError("evaluation governance cannot authorize promotion")
        if self.blocked_reasons and self.status is not ReleaseComparisonStatus.BLOCKED:
            raise ValueError("blocked comparison reasons require BLOCKED status")
        if self.contamination_detected and self.status is not ReleaseComparisonStatus.BLOCKED:
            raise ValueError("contamination requires BLOCKED comparison status")
        if (
            self.regressed_case_ids
            and self.status is ReleaseComparisonStatus.COMPARABLE
        ):
            raise ValueError("observed regressions cannot be marked COMPARABLE")
        return self
