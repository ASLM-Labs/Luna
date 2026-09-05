"""Fail-closed S5D external-evidence and promotion-review contracts.

This module evaluates supplied evidence only. It cannot execute a provider, change a
rollout stage, mutate task state, or authorize CANARY/ACTIVE transition.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import require_utc
from luna.parallel_cognition.models import C011ContractModel, Sha256

GitObjectId = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _content_identity(
    model: C011ContractModel,
    *,
    identity_field: str,
    prefix: str,
) -> str:
    basis = {
        "contract_type": f"{type(model).__module__}.{type(model).__qualname__}",
        "schema_version": model.schema_version,
        "payload": model.model_dump(mode="json", exclude={identity_field}),
    }
    return f"{prefix}{sha256(_canonical_json(basis).encode('utf-8')).hexdigest()}"


def _unique_text(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError(f"{label} cannot contain blank values")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(normalized))


class S5DEvidenceRequirement(StrEnum):
    REAL_PROVIDER_EXECUTION = "REAL_PROVIDER_EXECUTION"
    HARDWARE_RESOURCE_ATTESTATION = "HARDWARE_RESOURCE_ATTESTATION"
    SAFETY_CONTAINMENT_ATTESTATION = "SAFETY_CONTAINMENT_ATTESTATION"
    S5C_LEDGER_INTEGRITY = "S5C_LEDGER_INTEGRITY"
    REAL_EQUAL_COMPUTE_NON_INFERIORITY = "REAL_EQUAL_COMPUTE_NON_INFERIORITY"
    EVALUATOR_INDEPENDENCE_ATTESTATION = "EVALUATOR_INDEPENDENCE_ATTESTATION"
    CONTAMINATION_PROVENANCE_ATTESTATION = "CONTAMINATION_PROVENANCE_ATTESTATION"
    EXTERNAL_LEDGER_ANCHOR = "EXTERNAL_LEDGER_ANCHOR"


_REQUIREMENT_ORDER = tuple(S5DEvidenceRequirement)


class S5DEvidenceState(StrEnum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    OPEN = "OPEN"
    REJECTED = "REJECTED"


class S5DEvidenceClass(StrEnum):
    NONE = "NONE"
    REPOSITORY_RECEIPT = "REPOSITORY_RECEIPT"
    REAL_PROVIDER_OBSERVATION = "REAL_PROVIDER_OBSERVATION"
    DETERMINISTIC_FIXTURE = "DETERMINISTIC_FIXTURE"
    EXTERNAL_ATTESTATION = "EXTERNAL_ATTESTATION"
    REAL_EQUAL_COMPUTE_COMPARISON = "REAL_EQUAL_COMPUTE_COMPARISON"


class S5DRequestedTransition(StrEnum):
    CANARY = "CANARY"
    ACTIVE = "ACTIVE"


class S5DPromotionDisposition(StrEnum):
    BLOCKED_INSUFFICIENT_EVIDENCE = "BLOCKED_INSUFFICIENT_EVIDENCE"
    BLOCKED_REJECTED_EVIDENCE = "BLOCKED_REJECTED_EVIDENCE"
    READY_FOR_OWNER_REVIEW = "READY_FOR_OWNER_REVIEW"


_VERIFIED_CLASS = {
    S5DEvidenceRequirement.REAL_PROVIDER_EXECUTION: (
        S5DEvidenceClass.REAL_PROVIDER_OBSERVATION
    ),
    S5DEvidenceRequirement.HARDWARE_RESOURCE_ATTESTATION: (
        S5DEvidenceClass.EXTERNAL_ATTESTATION
    ),
    S5DEvidenceRequirement.SAFETY_CONTAINMENT_ATTESTATION: (
        S5DEvidenceClass.EXTERNAL_ATTESTATION
    ),
    S5DEvidenceRequirement.S5C_LEDGER_INTEGRITY: (
        S5DEvidenceClass.REPOSITORY_RECEIPT
    ),
    S5DEvidenceRequirement.REAL_EQUAL_COMPUTE_NON_INFERIORITY: (
        S5DEvidenceClass.REAL_EQUAL_COMPUTE_COMPARISON
    ),
    S5DEvidenceRequirement.EVALUATOR_INDEPENDENCE_ATTESTATION: (
        S5DEvidenceClass.EXTERNAL_ATTESTATION
    ),
    S5DEvidenceRequirement.CONTAMINATION_PROVENANCE_ATTESTATION: (
        S5DEvidenceClass.EXTERNAL_ATTESTATION
    ),
    S5DEvidenceRequirement.EXTERNAL_LEDGER_ANCHOR: (
        S5DEvidenceClass.EXTERNAL_ATTESTATION
    ),
}
_REQUIRES_INDEPENDENT_ATTESTATION = frozenset(
    {
        S5DEvidenceRequirement.HARDWARE_RESOURCE_ATTESTATION,
        S5DEvidenceRequirement.SAFETY_CONTAINMENT_ATTESTATION,
        S5DEvidenceRequirement.REAL_EQUAL_COMPUTE_NON_INFERIORITY,
        S5DEvidenceRequirement.EVALUATOR_INDEPENDENCE_ATTESTATION,
        S5DEvidenceRequirement.CONTAMINATION_PROVENANCE_ATTESTATION,
        S5DEvidenceRequirement.EXTERNAL_LEDGER_ANCHOR,
    }
)


class S5DEvidenceReference(C011ContractModel):
    locator: str = Field(min_length=1, max_length=2000)
    content_sha256: Sha256
    source_revision: str = Field(min_length=1, max_length=500)


class S5DEvidenceItem(C011ContractModel):
    """One explicit requirement state; OPEN gaps cannot masquerade as zero evidence."""

    evidence_id: str = ""
    requirement: S5DEvidenceRequirement
    state: S5DEvidenceState
    evidence_class: S5DEvidenceClass
    evidence_refs: tuple[S5DEvidenceReference, ...] = Field(default=(), max_length=32)
    observed_at_utc: datetime | None = None
    valid_until_utc: datetime | None = None
    provenance_complete: bool = False
    independently_attested: bool = False
    limitations: tuple[str, ...] = ()

    @field_validator("observed_at_utc", "valid_until_utc")
    @classmethod
    def validate_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @field_validator("evidence_refs")
    @classmethod
    def normalize_refs(
        cls,
        values: tuple[S5DEvidenceReference, ...],
    ) -> tuple[S5DEvidenceReference, ...]:
        locators = tuple(item.locator for item in values)
        if len(locators) != len(set(locators)):
            raise ValueError("S5D evidence reference locators must be unique")
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.locator,
                    item.content_sha256,
                    item.source_revision,
                ),
            )
        )

    @field_validator("limitations")
    @classmethod
    def normalize_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_text(values, label="S5D evidence limitations")

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.independently_attested and not self.provenance_complete:
            raise ValueError("independent S5D evidence requires complete provenance")
        if self.state is S5DEvidenceState.OPEN:
            if (
                self.evidence_class is not S5DEvidenceClass.NONE
                or self.evidence_refs
                or self.observed_at_utc is not None
                or self.valid_until_utc is not None
                or self.provenance_complete
                or self.independently_attested
            ):
                raise ValueError("OPEN S5D evidence cannot claim observations or provenance")
            if not self.limitations:
                raise ValueError("OPEN S5D evidence requires an explicit gap")
        else:
            if self.evidence_class is S5DEvidenceClass.NONE:
                raise ValueError("observed S5D evidence requires a concrete class")
            if not self.evidence_refs or self.observed_at_utc is None:
                raise ValueError("observed S5D evidence requires dated references")
            if (
                self.state in {S5DEvidenceState.PARTIAL, S5DEvidenceState.REJECTED}
                and not self.limitations
            ):
                raise ValueError("partial or rejected S5D evidence requires limitations")
        if (
            self.observed_at_utc is not None
            and self.valid_until_utc is not None
            and self.valid_until_utc < self.observed_at_utc
        ):
            raise ValueError("S5D evidence validity cannot end before observation")
        if self.state is S5DEvidenceState.VERIFIED:
            expected_class = _VERIFIED_CLASS[self.requirement]
            if self.evidence_class is not expected_class:
                raise ValueError("verified S5D requirement uses the wrong evidence class")
            if not self.provenance_complete:
                raise ValueError("verified S5D evidence requires complete provenance")
            if (
                self.requirement in _REQUIRES_INDEPENDENT_ATTESTATION
                and not self.independently_attested
            ):
                raise ValueError(
                    "verified S5D requirement requires independent attestation"
                )
        expected = _content_identity(
            self,
            identity_field="evidence_id",
            prefix="c011-s5d-evidence:sha256:",
        )
        if not self.evidence_id:
            object.__setattr__(self, "evidence_id", expected)
        elif self.evidence_id != expected:
            raise ValueError("S5D evidence ID does not match canonical content")
        return self


class S5DPromotionPolicy(C011ContractModel):
    """Frozen decision basis for one repository state; it grants no transition power."""

    policy_id: str = ""
    revision: Literal["1.0.0"] = "1.0.0"
    target_branch: str = Field(min_length=1, max_length=500)
    target_commit_oid: GitObjectId
    target_tree_oid: GitObjectId
    evaluated_at_utc: datetime
    max_evidence_age_days: int = Field(default=30, ge=1, le=365)
    requirements: tuple[S5DEvidenceRequirement, ...] = _REQUIREMENT_ORDER
    runtime_authority: Literal[False] = False
    canary_authority: Literal[False] = False
    active_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("evaluated_at_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.requirements != _REQUIREMENT_ORDER:
            raise ValueError("S5D policy requires the canonical evidence inventory")
        expected = _content_identity(
            self,
            identity_field="policy_id",
            prefix="c011-s5d-policy:sha256:",
        )
        if not self.policy_id:
            object.__setattr__(self, "policy_id", expected)
        elif self.policy_id != expected:
            raise ValueError("S5D policy ID does not match canonical content")
        return self


class S5DExternalEvidenceSnapshot(C011ContractModel):
    """Explicit current evidence inventory; every missing requirement is represented."""

    snapshot_id: str = ""
    target_branch: str = Field(min_length=1, max_length=500)
    target_commit_oid: GitObjectId
    target_tree_oid: GitObjectId
    evaluated_at_utc: datetime
    items: tuple[S5DEvidenceItem, ...] = Field(min_length=8, max_length=8)
    capability_status: Literal["QUEUED"] = "QUEUED"
    default_enabled: Literal[False] = False
    rollout_stage: Literal["BLOCKED"] = "BLOCKED"
    task_state_authority: Literal[False] = False
    root_context_adoption_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    transition_authority: Literal[False] = False

    @field_validator("evaluated_at_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if tuple(item.requirement for item in self.items) != _REQUIREMENT_ORDER:
            raise ValueError("S5D snapshot requires the canonical evidence inventory")
        if len({item.evidence_id for item in self.items}) != len(self.items):
            raise ValueError("S5D snapshot evidence IDs must be unique")
        if any(
            item.observed_at_utc is not None
            and item.observed_at_utc > self.evaluated_at_utc
            for item in self.items
        ):
            raise ValueError("S5D evidence cannot be observed after snapshot evaluation")
        expected = _content_identity(
            self,
            identity_field="snapshot_id",
            prefix="c011-s5d-snapshot:sha256:",
        )
        if not self.snapshot_id:
            object.__setattr__(self, "snapshot_id", expected)
        elif self.snapshot_id != expected:
            raise ValueError("S5D snapshot ID does not match canonical content")
        return self


class S5DPromotionDecision(C011ContractModel):
    """Evidence disposition only; even READY still requires a separate owner action."""

    decision_id: str = ""
    policy_id: str = Field(pattern=r"^c011-s5d-policy:sha256:[0-9a-f]{64}$")
    snapshot_id: str = Field(pattern=r"^c011-s5d-snapshot:sha256:[0-9a-f]{64}$")
    requested_transition: S5DRequestedTransition
    disposition: S5DPromotionDisposition
    satisfied_requirements: tuple[S5DEvidenceRequirement, ...] = ()
    partial_requirements: tuple[S5DEvidenceRequirement, ...] = ()
    open_requirements: tuple[S5DEvidenceRequirement, ...] = ()
    rejected_requirements: tuple[S5DEvidenceRequirement, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    owner_review_ready: bool = False
    capability_status_after: Literal["QUEUED"] = "QUEUED"
    rollout_stage_after: Literal["BLOCKED"] = "BLOCKED"
    transition_applied: Literal[False] = False
    provider_call_executed: Literal[False] = False
    runtime_authority: Literal[False] = False
    task_state_authority: Literal[False] = False
    root_context_adoption_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    canary_authority: Literal[False] = False
    active_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("blocked_reasons")
    @classmethod
    def normalize_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_text(values, label="S5D blocked reasons")

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        groups = (
            self.satisfied_requirements,
            self.partial_requirements,
            self.open_requirements,
            self.rejected_requirements,
        )
        flattened = tuple(item for group in groups for item in group)
        if len(flattened) != len(set(flattened)) or set(flattened) != set(
            _REQUIREMENT_ORDER
        ):
            raise ValueError("S5D decision must classify every requirement exactly once")
        if self.disposition is S5DPromotionDisposition.READY_FOR_OWNER_REVIEW:
            if (
                tuple(self.satisfied_requirements) != _REQUIREMENT_ORDER
                or self.partial_requirements
                or self.open_requirements
                or self.rejected_requirements
                or self.blocked_reasons
                or not self.owner_review_ready
            ):
                raise ValueError("S5D owner-review readiness requires all evidence")
        else:
            if self.owner_review_ready or not self.blocked_reasons:
                raise ValueError("blocked S5D decision requires reasons and no readiness")
            rejected = bool(self.rejected_requirements)
            if rejected != (
                self.disposition
                is S5DPromotionDisposition.BLOCKED_REJECTED_EVIDENCE
            ):
                raise ValueError("S5D rejected-evidence disposition mismatch")
        expected = _content_identity(
            self,
            identity_field="decision_id",
            prefix="c011-s5d-decision:sha256:",
        )
        if not self.decision_id:
            object.__setattr__(self, "decision_id", expected)
        elif self.decision_id != expected:
            raise ValueError("S5D decision ID does not match canonical content")
        return self


def evaluate_s5d_promotion(
    *,
    policy: S5DPromotionPolicy,
    snapshot: S5DExternalEvidenceSnapshot,
    requested_transition: S5DRequestedTransition,
) -> S5DPromotionDecision:
    """Classify current evidence without applying or authorizing a transition."""

    current_policy = S5DPromotionPolicy.model_validate(policy.model_dump(mode="json"))
    current_snapshot = S5DExternalEvidenceSnapshot.model_validate(
        snapshot.model_dump(mode="json")
    )
    satisfied: list[S5DEvidenceRequirement] = []
    partial: list[S5DEvidenceRequirement] = []
    opened: list[S5DEvidenceRequirement] = []
    rejected: list[S5DEvidenceRequirement] = []
    reasons: list[str] = []

    if current_snapshot.target_branch != current_policy.target_branch:
        reasons.append("snapshot target branch does not match the frozen policy")
    if current_snapshot.target_commit_oid != current_policy.target_commit_oid:
        reasons.append("snapshot target commit does not match the frozen policy")
    if current_snapshot.target_tree_oid != current_policy.target_tree_oid:
        reasons.append("snapshot target tree does not match the frozen policy")
    if current_snapshot.evaluated_at_utc != current_policy.evaluated_at_utc:
        reasons.append("snapshot evaluation time does not match the frozen policy")

    freshness_floor = current_policy.evaluated_at_utc - timedelta(
        days=current_policy.max_evidence_age_days
    )
    for item in current_snapshot.items:
        if item.state is S5DEvidenceState.REJECTED:
            rejected.append(item.requirement)
            reasons.append(f"{item.requirement.value} evidence is rejected")
        elif item.state is S5DEvidenceState.OPEN:
            opened.append(item.requirement)
            reasons.append(f"{item.requirement.value} evidence is open")
        elif item.state is S5DEvidenceState.PARTIAL:
            partial.append(item.requirement)
            reasons.append(f"{item.requirement.value} evidence is partial")
        elif (
            item.observed_at_utc is None
            or item.observed_at_utc < freshness_floor
            or (
                item.valid_until_utc is not None
                and item.valid_until_utc < current_policy.evaluated_at_utc
            )
        ):
            partial.append(item.requirement)
            reasons.append(f"{item.requirement.value} evidence is stale")
        else:
            satisfied.append(item.requirement)

    if rejected:
        disposition = S5DPromotionDisposition.BLOCKED_REJECTED_EVIDENCE
    elif reasons or len(satisfied) != len(_REQUIREMENT_ORDER):
        disposition = S5DPromotionDisposition.BLOCKED_INSUFFICIENT_EVIDENCE
    else:
        disposition = S5DPromotionDisposition.READY_FOR_OWNER_REVIEW

    return S5DPromotionDecision(
        policy_id=current_policy.policy_id,
        snapshot_id=current_snapshot.snapshot_id,
        requested_transition=requested_transition,
        disposition=disposition,
        satisfied_requirements=tuple(satisfied),
        partial_requirements=tuple(partial),
        open_requirements=tuple(opened),
        rejected_requirements=tuple(rejected),
        blocked_reasons=tuple(sorted(set(reasons))),
        owner_review_ready=(
            disposition is S5DPromotionDisposition.READY_FOR_OWNER_REVIEW
        ),
    )


__all__ = [
    "S5DEvidenceClass",
    "S5DEvidenceItem",
    "S5DEvidenceReference",
    "S5DEvidenceRequirement",
    "S5DEvidenceState",
    "S5DExternalEvidenceSnapshot",
    "S5DPromotionDecision",
    "S5DPromotionDisposition",
    "S5DPromotionPolicy",
    "S5DRequestedTransition",
    "evaluate_s5d_promotion",
]
