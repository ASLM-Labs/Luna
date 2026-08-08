"""Controlled counterfactual-analysis contracts for Luna Phase 19D."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Self

from pydantic import Field, field_validator, model_validator

from luna.cognition import CognitiveDimension, CognitiveScorecard
from luna.contracts.base import LunaContractModel


class CounterfactualAlternativeKind(StrEnum):
    """Observable alternative families that may be tested in controlled replay."""

    PLAN = "PLAN"
    TOOL_SELECTION = "TOOL_SELECTION"
    EVIDENCE_PATH = "EVIDENCE_PATH"
    RECOVERY_PATH = "RECOVERY_PATH"
    MINIMAL_PATH = "MINIMAL_PATH"


class ReplayEnvironment(StrEnum):
    """Only isolated, non-authoritative environments are valid Phase 19D evidence."""

    CONTROLLED_REPLAY = "CONTROLLED_REPLAY"
    SANDBOX = "SANDBOX"


class CounterfactualEvidenceOrigin(StrEnum):
    """Evidence origins accepted by the counterfactual lab."""

    CANDIDATE_OUTPUT = "CANDIDATE_OUTPUT"
    CONTROLLED_REPLAY_HARNESS = "CONTROLLED_REPLAY_HARNESS"
    DETERMINISTIC_VERIFIER = "DETERMINISTIC_VERIFIER"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    SANDBOX_HARNESS = "SANDBOX_HARNESS"


class CounterfactualDisposition(StrEnum):
    """Exploratory result state; none of these states grants promotion authority."""

    HYPOTHESIS_ONLY = "HYPOTHESIS_ONLY"
    BLOCKED = "BLOCKED"
    NO_ADVANTAGE = "NO_ADVANTAGE"
    EVIDENCE_SUPPORTED = "EVIDENCE_SUPPORTED"
    REJECTED = "REJECTED"


class CounterfactualEvidence(LunaContractModel):
    evidence_id: str = Field(min_length=1, max_length=300)
    origin: CounterfactualEvidenceOrigin
    independent_from_candidate: bool
    source_ref: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def validate_independence(self) -> Self:
        if (
            self.origin is CounterfactualEvidenceOrigin.CANDIDATE_OUTPUT
            and self.independent_from_candidate
        ):
            raise ValueError("candidate output cannot declare itself independent evidence")
        return self


class CounterfactualCandidate(LunaContractModel):
    candidate_id: str = Field(min_length=1, max_length=300)
    source_case_id: str = Field(min_length=1, max_length=300)
    source_revision: str = Field(min_length=1, max_length=300)
    alternative_kind: CounterfactualAlternativeKind
    baseline_decision_ref: str = Field(min_length=1, max_length=1200)
    alternative_summary: str = Field(min_length=1, max_length=4000)
    changed_basis: tuple[str, ...] = Field(min_length=1)
    hypothesis_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("changed_basis", "hypothesis_refs")
    @classmethod
    def validate_unique_nonblank(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("counterfactual refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("counterfactual refs must be unique")
        return cleaned


class ReplayObservation(LunaContractModel):
    """One actually executed observation from a controlled replay or sandbox."""

    observation_id: str = Field(min_length=1, max_length=300)
    case_id: str = Field(min_length=1, max_length=300)
    source_revision: str = Field(min_length=1, max_length=300)
    decision_ref: str = Field(min_length=1, max_length=1200)
    environment: ReplayEnvironment
    scorecard: CognitiveScorecard
    task_success: bool
    verification_success: bool
    action_count: int = Field(ge=0)
    unnecessary_action_count: int = Field(ge=0)
    cost_units: float = Field(ge=0.0)
    critical_safety_regressions: int = Field(ge=0)
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("replay evidence IDs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("replay evidence IDs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if self.scorecard.case_id != self.case_id:
            raise ValueError("replay scorecard case must match replay observation case")
        if self.unnecessary_action_count > self.action_count:
            raise ValueError("unnecessary actions cannot exceed total actions")
        return self


class CounterfactualExperiment(LunaContractModel):
    """Baseline plus optional executed alternative for like-for-like comparison."""

    experiment_id: str = Field(min_length=1, max_length=300)
    candidate: CounterfactualCandidate
    baseline: ReplayObservation
    alternative: ReplayObservation | None = None
    evidence_catalog: tuple[CounterfactualEvidence, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_experiment(self) -> Self:
        evidence_ids = tuple(item.evidence_id for item in self.evidence_catalog)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("counterfactual evidence IDs must be unique")
        if self.baseline.case_id != self.candidate.source_case_id:
            raise ValueError("baseline case must match counterfactual source case")
        if self.baseline.source_revision != self.candidate.source_revision:
            raise ValueError("baseline revision must match counterfactual source revision")
        if self.baseline.decision_ref != self.candidate.baseline_decision_ref:
            raise ValueError("baseline decision ref must match counterfactual candidate")
        if self.alternative is None:
            return self
        if self.alternative.case_id != self.baseline.case_id:
            raise ValueError("counterfactual replay requires the same case")
        if self.alternative.source_revision != self.baseline.source_revision:
            raise ValueError("counterfactual replay requires the same source revision")
        if self.alternative.environment is not self.baseline.environment:
            raise ValueError("counterfactual replay requires the same replay environment")
        if self.alternative.decision_ref == self.baseline.decision_ref:
            raise ValueError("counterfactual alternative must change the tested decision")
        return self


class CounterfactualPolicy(LunaContractModel):
    """Frozen exploratory policy so results cannot be tuned around one candidate."""

    revision: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    require_independent_observation_evidence: bool = True
    require_same_environment: bool = True
    require_same_source_revision: bool = True
    critical_safety_zero_tolerance: bool = True
    promotion_authority: bool = False
    generalized_causal_claim_authority: bool = False
    locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @staticmethod
    def _payload(
        *,
        revision: str,
        require_independent_observation_evidence: bool,
        require_same_environment: bool,
        require_same_source_revision: bool,
        critical_safety_zero_tolerance: bool,
        promotion_authority: bool,
        generalized_causal_claim_authority: bool,
    ) -> dict[str, object]:
        return {
            "revision": revision,
            "require_independent_observation_evidence": require_independent_observation_evidence,
            "require_same_environment": require_same_environment,
            "require_same_source_revision": require_same_source_revision,
            "critical_safety_zero_tolerance": critical_safety_zero_tolerance,
            "promotion_authority": promotion_authority,
            "generalized_causal_claim_authority": generalized_causal_claim_authority,
        }

    @classmethod
    def freeze(
        cls,
        *,
        revision: str,
        require_independent_observation_evidence: bool = True,
        require_same_environment: bool = True,
        require_same_source_revision: bool = True,
        critical_safety_zero_tolerance: bool = True,
        promotion_authority: bool = False,
        generalized_causal_claim_authority: bool = False,
    ) -> Self:
        payload = cls._payload(
            revision=revision,
            require_independent_observation_evidence=require_independent_observation_evidence,
            require_same_environment=require_same_environment,
            require_same_source_revision=require_same_source_revision,
            critical_safety_zero_tolerance=critical_safety_zero_tolerance,
            promotion_authority=promotion_authority,
            generalized_causal_claim_authority=generalized_causal_claim_authority,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return cls(
            revision=revision,
            require_independent_observation_evidence=(
                require_independent_observation_evidence
            ),
            require_same_environment=require_same_environment,
            require_same_source_revision=require_same_source_revision,
            critical_safety_zero_tolerance=critical_safety_zero_tolerance,
            promotion_authority=promotion_authority,
            generalized_causal_claim_authority=generalized_causal_claim_authority,
            locked_sha256=sha256(serialized.encode("utf-8")).hexdigest(),
        )

    def computed_sha256(self) -> str:
        payload = self._payload(
            revision=self.revision,
            require_independent_observation_evidence=(
                self.require_independent_observation_evidence
            ),
            require_same_environment=self.require_same_environment,
            require_same_source_revision=self.require_same_source_revision,
            critical_safety_zero_tolerance=self.critical_safety_zero_tolerance,
            promotion_authority=self.promotion_authority,
            generalized_causal_claim_authority=self.generalized_causal_claim_authority,
        )
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.promotion_authority:
            raise ValueError("counterfactual analysis cannot authorize promotion")
        if self.generalized_causal_claim_authority:
            raise ValueError("Phase 19D cannot authorize generalized causal claims")
        if self.locked_sha256 != self.computed_sha256():
            raise ValueError("counterfactual policy digest mismatch")
        return self


class CounterfactualAssessment(LunaContractModel):
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_id: str = Field(min_length=1, max_length=300)
    disposition: CounterfactualDisposition
    dimension_deltas: dict[CognitiveDimension, float] = Field(default_factory=dict)
    improved_dimensions: tuple[CognitiveDimension, ...] = ()
    regressed_dimensions: tuple[CognitiveDimension, ...] = ()
    action_count_delta: int | None = None
    unnecessary_action_delta: int | None = None
    cost_delta: float | None = None
    verified_success_preserved: bool | None = None
    critical_safety_regression_count: int = Field(default=0, ge=0)
    evidence_refs: tuple[str, ...] = ()
    executed_counterfactual_evidence: bool = False
    generalized_causal_claim_authorized: bool = False
    promotion_authorized: bool = False

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        if self.generalized_causal_claim_authorized:
            raise ValueError("counterfactual assessment cannot generalize causal authority")
        if self.promotion_authorized:
            raise ValueError("counterfactual assessment cannot authorize promotion")
        if self.disposition is CounterfactualDisposition.HYPOTHESIS_ONLY:
            if self.executed_counterfactual_evidence:
                raise ValueError("hypothesis-only result cannot claim executed evidence")
            if self.dimension_deltas or self.evidence_refs:
                raise ValueError("hypothesis-only result cannot contain replay-derived evidence")
        return self
