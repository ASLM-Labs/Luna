"""Fail-closed real equal-compute execution-readiness contracts.

The preflight evaluates supplied evidence only. It cannot call a provider, execute a
model, change rollout state, or turn an owner authorization into runtime authority.
"""

from __future__ import annotations

import json
from datetime import datetime
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


class RealEqualComputePrerequisite(StrEnum):
    CURRENT_ASSET_BINDING = "CURRENT_ASSET_BINDING"
    MEASURED_TOKEN_ACCOUNTING = "MEASURED_TOKEN_ACCOUNTING"
    SOLO_RUNTIME_CONTRACT = "SOLO_RUNTIME_CONTRACT"
    ULTRA_SOLO_RUNTIME_CONTRACT = "ULTRA_SOLO_RUNTIME_CONTRACT"
    PARALLEL_RUNTIME_CONTRACT = "PARALLEL_RUNTIME_CONTRACT"
    REPRESENTATIVE_FROZEN_SUITE = "REPRESENTATIVE_FROZEN_SUITE"
    INDEPENDENT_EVALUATOR_ATTESTATION = "INDEPENDENT_EVALUATOR_ATTESTATION"
    CONTAMINATION_PROVENANCE_ATTESTATION = "CONTAMINATION_PROVENANCE_ATTESTATION"
    HARDWARE_RESOURCE_ATTESTATION = "HARDWARE_RESOURCE_ATTESTATION"
    SAFETY_CONTAINMENT_ATTESTATION = "SAFETY_CONTAINMENT_ATTESTATION"
    EXTERNAL_LEDGER_ANCHOR = "EXTERNAL_LEDGER_ANCHOR"


_PREREQUISITE_ORDER = tuple(RealEqualComputePrerequisite)


class RealEqualComputeEvidenceState(StrEnum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    OPEN = "OPEN"
    REJECTED = "REJECTED"


class RealEqualComputeEvidenceClass(StrEnum):
    NONE = "NONE"
    REPOSITORY_SOURCE = "REPOSITORY_SOURCE"
    REPOSITORY_RECEIPT = "REPOSITORY_RECEIPT"
    REAL_PROVIDER_MEASUREMENT = "REAL_PROVIDER_MEASUREMENT"
    EXTERNAL_ATTESTATION = "EXTERNAL_ATTESTATION"


class RealEqualComputePreflightDisposition(StrEnum):
    BLOCKED_PREREQUISITES = "BLOCKED_PREREQUISITES"
    BLOCKED_REJECTED_BASIS = "BLOCKED_REJECTED_BASIS"
    READY_FOR_AUTHORIZED_EXECUTION = "READY_FOR_AUTHORIZED_EXECUTION"


_VERIFIED_CLASS = {
    RealEqualComputePrerequisite.CURRENT_ASSET_BINDING: (
        RealEqualComputeEvidenceClass.REAL_PROVIDER_MEASUREMENT
    ),
    RealEqualComputePrerequisite.MEASURED_TOKEN_ACCOUNTING: (
        RealEqualComputeEvidenceClass.REAL_PROVIDER_MEASUREMENT
    ),
    RealEqualComputePrerequisite.SOLO_RUNTIME_CONTRACT: (
        RealEqualComputeEvidenceClass.REPOSITORY_SOURCE
    ),
    RealEqualComputePrerequisite.ULTRA_SOLO_RUNTIME_CONTRACT: (
        RealEqualComputeEvidenceClass.REPOSITORY_SOURCE
    ),
    RealEqualComputePrerequisite.PARALLEL_RUNTIME_CONTRACT: (
        RealEqualComputeEvidenceClass.REPOSITORY_SOURCE
    ),
    RealEqualComputePrerequisite.REPRESENTATIVE_FROZEN_SUITE: (
        RealEqualComputeEvidenceClass.REPOSITORY_RECEIPT
    ),
    RealEqualComputePrerequisite.INDEPENDENT_EVALUATOR_ATTESTATION: (
        RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION
    ),
    RealEqualComputePrerequisite.CONTAMINATION_PROVENANCE_ATTESTATION: (
        RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION
    ),
    RealEqualComputePrerequisite.HARDWARE_RESOURCE_ATTESTATION: (
        RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION
    ),
    RealEqualComputePrerequisite.SAFETY_CONTAINMENT_ATTESTATION: (
        RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION
    ),
    RealEqualComputePrerequisite.EXTERNAL_LEDGER_ANCHOR: (
        RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION
    ),
}
_EXTERNAL_REQUIREMENTS = frozenset(
    {
        RealEqualComputePrerequisite.INDEPENDENT_EVALUATOR_ATTESTATION,
        RealEqualComputePrerequisite.CONTAMINATION_PROVENANCE_ATTESTATION,
        RealEqualComputePrerequisite.HARDWARE_RESOURCE_ATTESTATION,
        RealEqualComputePrerequisite.SAFETY_CONTAINMENT_ATTESTATION,
        RealEqualComputePrerequisite.EXTERNAL_LEDGER_ANCHOR,
    }
)


class RealEqualComputeEvidenceReference(C011ContractModel):
    locator: str = Field(min_length=1, max_length=2000)
    content_sha256: Sha256
    source_revision: str = Field(min_length=1, max_length=500)


class RealEqualComputePrerequisiteEvidence(C011ContractModel):
    evidence_id: str = ""
    prerequisite: RealEqualComputePrerequisite
    state: RealEqualComputeEvidenceState
    evidence_class: RealEqualComputeEvidenceClass
    evidence_refs: tuple[RealEqualComputeEvidenceReference, ...] = Field(
        default=(), max_length=32
    )
    observed_at_utc: datetime | None = None
    provenance_complete: bool = False
    independently_attested: bool = False
    limitations: tuple[str, ...] = ()

    @field_validator("observed_at_utc")
    @classmethod
    def validate_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @field_validator("evidence_refs")
    @classmethod
    def normalize_refs(
        cls,
        values: tuple[RealEqualComputeEvidenceReference, ...],
    ) -> tuple[RealEqualComputeEvidenceReference, ...]:
        locators = tuple(item.locator for item in values)
        if len(locators) != len(set(locators)):
            raise ValueError("real equal-compute evidence locators must be unique")
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
        return _unique_text(values, label="real equal-compute evidence limitations")

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.independently_attested and not self.provenance_complete:
            raise ValueError("independent evidence requires complete provenance")
        if self.state is RealEqualComputeEvidenceState.OPEN:
            if (
                self.evidence_class is not RealEqualComputeEvidenceClass.NONE
                or self.evidence_refs
                or self.observed_at_utc is not None
                or self.provenance_complete
                or self.independently_attested
            ):
                raise ValueError("OPEN prerequisite cannot claim observations")
            if not self.limitations:
                raise ValueError("OPEN prerequisite requires an explicit gap")
        else:
            if self.evidence_class is RealEqualComputeEvidenceClass.NONE:
                raise ValueError("observed prerequisite requires an evidence class")
            if not self.evidence_refs or self.observed_at_utc is None:
                raise ValueError("observed prerequisite requires dated references")
            if (
                self.state
                in {
                    RealEqualComputeEvidenceState.PARTIAL,
                    RealEqualComputeEvidenceState.REJECTED,
                }
                and not self.limitations
            ):
                raise ValueError("partial or rejected prerequisite requires limitations")
        if self.state is RealEqualComputeEvidenceState.VERIFIED:
            if self.evidence_class is not _VERIFIED_CLASS[self.prerequisite]:
                raise ValueError("verified prerequisite uses the wrong evidence class")
            if not self.provenance_complete:
                raise ValueError("verified prerequisite requires complete provenance")
            if (
                self.prerequisite in _EXTERNAL_REQUIREMENTS
                and not self.independently_attested
            ):
                raise ValueError("verified external prerequisite requires attestation")
        expected = _content_identity(
            self,
            identity_field="evidence_id",
            prefix="c011-real-equal-compute-evidence:sha256:",
        )
        if not self.evidence_id:
            object.__setattr__(self, "evidence_id", expected)
        elif self.evidence_id != expected:
            raise ValueError("real equal-compute evidence ID does not match content")
        return self


class RealEqualComputePreflightPolicy(C011ContractModel):
    policy_id: str = ""
    revision: Literal["1.0.0"] = "1.0.0"
    target_branch: str = Field(min_length=1, max_length=500)
    target_commit_oid: GitObjectId
    target_tree_oid: GitObjectId
    evaluated_at_utc: datetime
    prerequisites: tuple[RealEqualComputePrerequisite, ...] = _PREREQUISITE_ORDER
    required_configurations: tuple[Literal["SOLO", "ULTRA_SOLO", "PARALLEL"], ...] = (
        "SOLO",
        "ULTRA_SOLO",
        "PARALLEL",
    )
    minimum_parallel_workers: Literal[2] = 2
    measured_token_accounting_required: Literal[True] = True
    owner_authorization_scope: Literal[
        "BOUNDED_REAL_EQUAL_COMPUTE_EVIDENCE_TEST"
    ] = "BOUNDED_REAL_EQUAL_COMPUTE_EVIDENCE_TEST"
    authorization_grants_runtime_authority: Literal[False] = False
    runtime_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("evaluated_at_utc")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.prerequisites != _PREREQUISITE_ORDER:
            raise ValueError("preflight policy requires the canonical prerequisite inventory")
        if self.required_configurations != ("SOLO", "ULTRA_SOLO", "PARALLEL"):
            raise ValueError("preflight policy requires the canonical configuration order")
        expected = _content_identity(
            self,
            identity_field="policy_id",
            prefix="c011-real-equal-compute-policy:sha256:",
        )
        if not self.policy_id:
            object.__setattr__(self, "policy_id", expected)
        elif self.policy_id != expected:
            raise ValueError("real equal-compute policy ID does not match content")
        return self


class RealEqualComputePreflightSnapshot(C011ContractModel):
    snapshot_id: str = ""
    target_branch: str = Field(min_length=1, max_length=500)
    target_commit_oid: GitObjectId
    target_tree_oid: GitObjectId
    evaluated_at_utc: datetime
    items: tuple[RealEqualComputePrerequisiteEvidence, ...] = Field(
        min_length=11, max_length=11
    )
    capability_status: Literal["QUEUED"] = "QUEUED"
    default_enabled: Literal[False] = False
    rollout_stage: Literal["BLOCKED"] = "BLOCKED"
    provider_call_executed: Literal[False] = False
    real_model_execution_completed: Literal[False] = False
    transition_authority: Literal[False] = False

    @field_validator("evaluated_at_utc")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if tuple(item.prerequisite for item in self.items) != _PREREQUISITE_ORDER:
            raise ValueError("snapshot requires the canonical prerequisite inventory")
        if len({item.evidence_id for item in self.items}) != len(self.items):
            raise ValueError("snapshot evidence IDs must be unique")
        if any(
            item.observed_at_utc is not None
            and item.observed_at_utc > self.evaluated_at_utc
            for item in self.items
        ):
            raise ValueError("evidence cannot postdate the preflight snapshot")
        expected = _content_identity(
            self,
            identity_field="snapshot_id",
            prefix="c011-real-equal-compute-snapshot:sha256:",
        )
        if not self.snapshot_id:
            object.__setattr__(self, "snapshot_id", expected)
        elif self.snapshot_id != expected:
            raise ValueError("real equal-compute snapshot ID does not match content")
        return self


class RealEqualComputePreflightDecision(C011ContractModel):
    decision_id: str = ""
    policy_id: str = Field(
        pattern=r"^c011-real-equal-compute-policy:sha256:[0-9a-f]{64}$"
    )
    snapshot_id: str = Field(
        pattern=r"^c011-real-equal-compute-snapshot:sha256:[0-9a-f]{64}$"
    )
    disposition: RealEqualComputePreflightDisposition
    verified_prerequisites: tuple[RealEqualComputePrerequisite, ...] = ()
    partial_prerequisites: tuple[RealEqualComputePrerequisite, ...] = ()
    open_prerequisites: tuple[RealEqualComputePrerequisite, ...] = ()
    rejected_prerequisites: tuple[RealEqualComputePrerequisite, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    preflight_ready: bool = False
    owner_authorization_recorded: Literal[True] = True
    execution_attempted: Literal[False] = False
    provider_call_executed: Literal[False] = False
    real_model_execution_completed: Literal[False] = False
    capability_status_after: Literal["QUEUED"] = "QUEUED"
    rollout_stage_after: Literal["BLOCKED"] = "BLOCKED"
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
        return _unique_text(values, label="preflight blocked reasons")

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        groups = (
            self.verified_prerequisites,
            self.partial_prerequisites,
            self.open_prerequisites,
            self.rejected_prerequisites,
        )
        flattened = tuple(item for group in groups for item in group)
        if len(flattened) != len(set(flattened)) or set(flattened) != set(
            _PREREQUISITE_ORDER
        ):
            raise ValueError("decision must classify every prerequisite exactly once")
        if (
            self.disposition
            is RealEqualComputePreflightDisposition.READY_FOR_AUTHORIZED_EXECUTION
        ):
            if (
                self.verified_prerequisites != _PREREQUISITE_ORDER
                or self.partial_prerequisites
                or self.open_prerequisites
                or self.rejected_prerequisites
                or self.blocked_reasons
                or not self.preflight_ready
            ):
                raise ValueError("execution readiness requires every prerequisite")
        else:
            if self.preflight_ready or not self.blocked_reasons:
                raise ValueError("blocked preflight requires reasons and no readiness")
            rejected = bool(self.rejected_prerequisites)
            if rejected != (
                self.disposition
                is RealEqualComputePreflightDisposition.BLOCKED_REJECTED_BASIS
            ):
                raise ValueError("rejected prerequisite disposition mismatch")
        expected = _content_identity(
            self,
            identity_field="decision_id",
            prefix="c011-real-equal-compute-decision:sha256:",
        )
        if not self.decision_id:
            object.__setattr__(self, "decision_id", expected)
        elif self.decision_id != expected:
            raise ValueError("real equal-compute decision ID does not match content")
        return self


def evaluate_real_equal_compute_preflight(
    *,
    policy: RealEqualComputePreflightPolicy,
    snapshot: RealEqualComputePreflightSnapshot,
) -> RealEqualComputePreflightDecision:
    """Classify execution readiness without attempting or authorizing execution."""

    current_policy = RealEqualComputePreflightPolicy.model_validate(
        policy.model_dump(mode="json")
    )
    current_snapshot = RealEqualComputePreflightSnapshot.model_validate(
        snapshot.model_dump(mode="json")
    )
    verified: list[RealEqualComputePrerequisite] = []
    partial: list[RealEqualComputePrerequisite] = []
    opened: list[RealEqualComputePrerequisite] = []
    rejected: list[RealEqualComputePrerequisite] = []
    reasons: list[str] = []

    if current_snapshot.target_branch != current_policy.target_branch:
        reasons.append("snapshot target branch does not match the frozen policy")
    if current_snapshot.target_commit_oid != current_policy.target_commit_oid:
        reasons.append("snapshot target commit does not match the frozen policy")
    if current_snapshot.target_tree_oid != current_policy.target_tree_oid:
        reasons.append("snapshot target tree does not match the frozen policy")
    if current_snapshot.evaluated_at_utc != current_policy.evaluated_at_utc:
        reasons.append("snapshot evaluation time does not match the frozen policy")

    for item in current_snapshot.items:
        if item.state is RealEqualComputeEvidenceState.REJECTED:
            rejected.append(item.prerequisite)
            reasons.append(f"{item.prerequisite.value} basis is rejected")
        elif item.state is RealEqualComputeEvidenceState.OPEN:
            opened.append(item.prerequisite)
            reasons.append(f"{item.prerequisite.value} prerequisite is open")
        elif item.state is RealEqualComputeEvidenceState.PARTIAL:
            partial.append(item.prerequisite)
            reasons.append(f"{item.prerequisite.value} prerequisite is partial")
        else:
            verified.append(item.prerequisite)

    if rejected:
        disposition = RealEqualComputePreflightDisposition.BLOCKED_REJECTED_BASIS
    elif reasons or len(verified) != len(_PREREQUISITE_ORDER):
        disposition = RealEqualComputePreflightDisposition.BLOCKED_PREREQUISITES
    else:
        disposition = RealEqualComputePreflightDisposition.READY_FOR_AUTHORIZED_EXECUTION

    return RealEqualComputePreflightDecision(
        policy_id=current_policy.policy_id,
        snapshot_id=current_snapshot.snapshot_id,
        disposition=disposition,
        verified_prerequisites=tuple(verified),
        partial_prerequisites=tuple(partial),
        open_prerequisites=tuple(opened),
        rejected_prerequisites=tuple(rejected),
        blocked_reasons=tuple(sorted(set(reasons))),
        preflight_ready=(
            disposition
            is RealEqualComputePreflightDisposition.READY_FOR_AUTHORIZED_EXECUTION
        ),
    )


__all__ = [
    "RealEqualComputeEvidenceClass",
    "RealEqualComputeEvidenceReference",
    "RealEqualComputeEvidenceState",
    "RealEqualComputePreflightDecision",
    "RealEqualComputePreflightDisposition",
    "RealEqualComputePreflightPolicy",
    "RealEqualComputePreflightSnapshot",
    "RealEqualComputePrerequisite",
    "RealEqualComputePrerequisiteEvidence",
    "evaluate_real_equal_compute_preflight",
]
