"""Learning-integrity contracts for Luna Phase 19C."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Self

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel


class LearningIntegrityRisk(StrEnum):
    """Observable failure modes that can make apparent learning misleading."""

    SHORTCUT_LEARNING = "SHORTCUT_LEARNING"
    BENCHMARK_GAMING = "BENCHMARK_GAMING"
    EVALUATOR_GAMING = "EVALUATOR_GAMING"
    PROXY_SPECIFICATION_OPTIMIZATION = "PROXY_SPECIFICATION_OPTIMIZATION"
    CONFIRMATION_BIAS = "CONFIRMATION_BIAS"
    OVERFITTING = "OVERFITTING"
    SELF_CONFIRMATION = "SELF_CONFIRMATION"


class IntegritySeverity(StrEnum):
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class LearningIntegrityStatus(StrEnum):
    """Learning-lab disposition only; never a runtime promotion decision."""

    CLEAN = "CLEAN"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REJECT_CANDIDATE = "REJECT_CANDIDATE"


class EvidenceOrigin(StrEnum):
    """Origin classes used to distinguish self-support from independent evidence."""

    CANDIDATE_OUTPUT = "CANDIDATE_OUTPUT"
    TRAINING_ARTIFACT = "TRAINING_ARTIFACT"
    DATASET_LINEAGE = "DATASET_LINEAGE"
    DETERMINISTIC_VERIFIER = "DETERMINISTIC_VERIFIER"
    INDEPENDENT_EVALUATOR = "INDEPENDENT_EVALUATOR"
    EXTERNAL_OBSERVATION = "EXTERNAL_OBSERVATION"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class IntegrityEvidence(LunaContractModel):
    evidence_id: str = Field(min_length=1, max_length=300)
    origin: EvidenceOrigin
    independent_from_candidate: bool

    @model_validator(mode="after")
    def validate_independence(self) -> Self:
        if self.origin is EvidenceOrigin.CANDIDATE_OUTPUT and self.independent_from_candidate:
            raise ValueError("candidate output cannot be independent evidence about itself")
        return self


class GeneralizationProfile(LunaContractModel):
    """Same-metric scores across train, validation, held-out, and OOD partitions."""

    profile_id: str = Field(min_length=1, max_length=300)
    training_score: float = Field(ge=0.0, le=1.0)
    validation_score: float = Field(ge=0.0, le=1.0)
    held_out_score: float = Field(ge=0.0, le=1.0)
    ood_score: float = Field(ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def validate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique_refs(values, "generalization evidence refs")


class ShortcutSliceProbe(LunaContractModel):
    """Matched observational slices; this is not a counterfactual replay claim."""

    probe_id: str = Field(min_length=1, max_length=300)
    shortcut_present_score: float = Field(ge=0.0, le=1.0)
    shortcut_absent_score: float = Field(ge=0.0, le=1.0)
    matched_observational_slices: bool = True
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def validate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique_refs(values, "shortcut probe evidence refs")

    @model_validator(mode="after")
    def validate_probe(self) -> Self:
        if not self.matched_observational_slices:
            raise ValueError("shortcut probe requires matched observational slices")
        return self

    @property
    def observed_gap(self) -> float:
        return self.shortcut_present_score - self.shortcut_absent_score


class EvaluatorAgreementProbe(LunaContractModel):
    """Compare a governed evaluator with a separately independent evaluator."""

    probe_id: str = Field(min_length=1, max_length=300)
    primary_evaluator_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_evaluator_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    primary_score: float = Field(ge=0.0, le=1.0)
    independent_score: float = Field(ge=0.0, le=1.0)
    independent_evaluator_verified: bool
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def validate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique_refs(values, "evaluator agreement evidence refs")

    @model_validator(mode="after")
    def validate_evaluator_independence(self) -> Self:
        if self.primary_evaluator_fingerprint == self.independent_evaluator_fingerprint:
            raise ValueError("agreement probe requires a distinct independent evaluator")
        if not self.independent_evaluator_verified:
            raise ValueError("independent evaluator must be verified")
        return self

    @property
    def absolute_gap(self) -> float:
        return abs(self.primary_score - self.independent_score)


class LearningExposureRecord(LunaContractModel):
    """Explicit learning-time exposure to benchmark or evaluator identities."""

    benchmark_case_ids: tuple[str, ...] = ()
    evaluator_fingerprints: tuple[str, ...] = ()
    optimization_metric_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "benchmark_case_ids",
        "evaluator_fingerprints",
        "optimization_metric_ids",
        "evidence_refs",
    )
    @classmethod
    def validate_unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique_refs(values, "learning exposure values")

    @field_validator("evaluator_fingerprints")
    @classmethod
    def validate_evaluator_fingerprints(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
            for value in values
        ):
            raise ValueError("evaluator exposure fingerprints must be lowercase SHA-256")
        return values


class ProxyMetricOutcome(LunaContractModel):
    metric_id: str = Field(min_length=1, max_length=300)
    baseline_value: float
    candidate_value: float
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def validate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique_refs(values, "proxy metric evidence refs")

    @property
    def improved(self) -> bool:
        return self.candidate_value > self.baseline_value + 1e-12


class ClaimEvidenceReview(LunaContractModel):
    """Evidence accounting for one candidate claim or conclusion."""

    claim_id: str = Field(min_length=1, max_length=300)
    supporting_evidence_ids: tuple[str, ...] = Field(min_length=1)
    contradicting_evidence_ids: tuple[str, ...] = ()
    considered_evidence_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "considered_evidence_ids",
    )
    @classmethod
    def validate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique_refs(values, "claim evidence IDs")

    @model_validator(mode="after")
    def validate_evidence_accounting(self) -> Self:
        referenced = set(self.supporting_evidence_ids) | set(self.contradicting_evidence_ids)
        if not set(self.considered_evidence_ids).issubset(referenced):
            raise ValueError("considered evidence must be supporting or contradicting evidence")
        return self


class LearningIntegrityPolicy(LunaContractModel):
    """Frozen thresholds for integrity checks before any real training candidate is promoted."""

    revision: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    max_train_held_out_gap: float = Field(gt=0.0, le=1.0)
    max_train_ood_gap: float = Field(gt=0.0, le=1.0)
    max_shortcut_slice_gap: float = Field(gt=0.0, le=1.0)
    max_evaluator_disagreement: float = Field(gt=0.0, le=1.0)
    block_benchmark_identity_exposure: bool = True
    block_evaluator_identity_exposure: bool = True
    require_independent_claim_evidence: bool = True
    critical_regression_zero_tolerance: bool = True
    locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @staticmethod
    def _payload(
        *,
        revision: str,
        max_train_held_out_gap: float,
        max_train_ood_gap: float,
        max_shortcut_slice_gap: float,
        max_evaluator_disagreement: float,
        block_benchmark_identity_exposure: bool,
        block_evaluator_identity_exposure: bool,
        require_independent_claim_evidence: bool,
        critical_regression_zero_tolerance: bool,
    ) -> dict[str, object]:
        return {
            "revision": revision,
            "max_train_held_out_gap": max_train_held_out_gap,
            "max_train_ood_gap": max_train_ood_gap,
            "max_shortcut_slice_gap": max_shortcut_slice_gap,
            "max_evaluator_disagreement": max_evaluator_disagreement,
            "block_benchmark_identity_exposure": block_benchmark_identity_exposure,
            "block_evaluator_identity_exposure": block_evaluator_identity_exposure,
            "require_independent_claim_evidence": require_independent_claim_evidence,
            "critical_regression_zero_tolerance": critical_regression_zero_tolerance,
        }

    @classmethod
    def freeze(
        cls,
        *,
        revision: str,
        max_train_held_out_gap: float = 0.15,
        max_train_ood_gap: float = 0.20,
        max_shortcut_slice_gap: float = 0.20,
        max_evaluator_disagreement: float = 0.15,
        block_benchmark_identity_exposure: bool = True,
        block_evaluator_identity_exposure: bool = True,
        require_independent_claim_evidence: bool = True,
        critical_regression_zero_tolerance: bool = True,
    ) -> Self:
        payload = cls._payload(
            revision=revision,
            max_train_held_out_gap=max_train_held_out_gap,
            max_train_ood_gap=max_train_ood_gap,
            max_shortcut_slice_gap=max_shortcut_slice_gap,
            max_evaluator_disagreement=max_evaluator_disagreement,
            block_benchmark_identity_exposure=block_benchmark_identity_exposure,
            block_evaluator_identity_exposure=block_evaluator_identity_exposure,
            require_independent_claim_evidence=require_independent_claim_evidence,
            critical_regression_zero_tolerance=critical_regression_zero_tolerance,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return cls(
            revision=revision,
            max_train_held_out_gap=max_train_held_out_gap,
            max_train_ood_gap=max_train_ood_gap,
            max_shortcut_slice_gap=max_shortcut_slice_gap,
            max_evaluator_disagreement=max_evaluator_disagreement,
            block_benchmark_identity_exposure=block_benchmark_identity_exposure,
            block_evaluator_identity_exposure=block_evaluator_identity_exposure,
            require_independent_claim_evidence=require_independent_claim_evidence,
            critical_regression_zero_tolerance=critical_regression_zero_tolerance,
            locked_sha256=sha256(serialized.encode("utf-8")).hexdigest(),
        )

    def computed_sha256(self) -> str:
        payload = self._payload(
            revision=self.revision,
            max_train_held_out_gap=self.max_train_held_out_gap,
            max_train_ood_gap=self.max_train_ood_gap,
            max_shortcut_slice_gap=self.max_shortcut_slice_gap,
            max_evaluator_disagreement=self.max_evaluator_disagreement,
            block_benchmark_identity_exposure=self.block_benchmark_identity_exposure,
            block_evaluator_identity_exposure=self.block_evaluator_identity_exposure,
            require_independent_claim_evidence=self.require_independent_claim_evidence,
            critical_regression_zero_tolerance=self.critical_regression_zero_tolerance,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        if self.locked_sha256 != self.computed_sha256():
            raise ValueError("learning integrity policy digest mismatch")
        return self


class LearningIntegrityFinding(LunaContractModel):
    risk: LearningIntegrityRisk
    severity: IntegritySeverity
    subject_id: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=2000)
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def validate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique_refs(values, "integrity finding evidence refs")


class LearningIntegrityReport(LunaContractModel):
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    findings: tuple[LearningIntegrityFinding, ...] = ()
    status: LearningIntegrityStatus
    promotion_authorized: bool = False

    @model_validator(mode="after")
    def validate_status_and_authority(self) -> Self:
        if self.promotion_authorized:
            raise ValueError("learning integrity cannot authorize promotion")
        has_blocking = any(
            finding.severity is IntegritySeverity.BLOCKING for finding in self.findings
        )
        has_warning = any(
            finding.severity is IntegritySeverity.WARNING for finding in self.findings
        )
        expected = (
            LearningIntegrityStatus.REJECT_CANDIDATE
            if has_blocking
            else LearningIntegrityStatus.REVIEW_REQUIRED
            if has_warning
            else LearningIntegrityStatus.CLEAN
        )
        if self.status is not expected:
            raise ValueError("learning integrity status does not match findings")
        return self

    @property
    def risk_set(self) -> set[LearningIntegrityRisk]:
        return {finding.risk for finding in self.findings}


def _clean_unique_refs(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    cleaned = tuple(value.strip() for value in values)
    if any(not value for value in cleaned):
        raise ValueError(f"{label} cannot be blank")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"{label} must be unique")
    return cleaned
