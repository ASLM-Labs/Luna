"""Pure S5A provider/profile governance for bounded C-011 workers.

This module performs no provider call, process creation, filesystem access, network
access, runtime wiring, or capability promotion.  It only decides whether an exact
profile is eligible for a later shadow-only stage.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.modeling import ModelCompatibilityReport, ModelRolloutStage
from luna.neural import NeuralResourceBudget, NeuralResourceProfile
from luna.parallel_cognition.models import (
    AssignmentSemanticSpec,
    C011ContractModel,
    ParallelCognitionRole,
    Sha256,
    WorkerBudgetEnvelope,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class WorkerProviderKind(StrEnum):
    """Provider families admitted by the first truthful S5 control-plane slice."""

    LUNA_NATIVE_NR2B_SLICE1 = "LUNA_NATIVE_NR2B_SLICE1"


class ProviderProfileDisposition(StrEnum):
    """S5A can deny or prepare shadow evidence; it cannot authorize execution."""

    DENY = "DENY"
    SHADOW_ELIGIBLE = "SHADOW_ELIGIBLE"


class ProviderCapacity(C011ContractModel):
    """Upper bounds a provider profile can satisfy without expanding an assignment."""

    max_context_bytes: int = Field(ge=1)
    max_result_bytes: int = Field(ge=1)
    max_claims: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0, le=32768)
    max_runtime_ms: int = Field(ge=1)
    max_total_workers: int = Field(ge=1, le=3)
    max_concurrent_workers: int = Field(ge=1, le=3)

    @model_validator(mode="after")
    def validate_concurrency(self) -> Self:
        if self.max_concurrent_workers > self.max_total_workers:
            raise ValueError("provider concurrency cannot exceed its total worker ceiling")
        return self

    def contains(self, budget: WorkerBudgetEnvelope) -> bool:
        """Return whether the assignment remains inside every provider ceiling."""

        return bool(
            budget.max_context_bytes <= self.max_context_bytes
            and budget.max_result_bytes <= self.max_result_bytes
            and budget.max_claims <= self.max_claims
            and budget.max_tokens <= self.max_output_tokens
            and budget.max_runtime_ms <= self.max_runtime_ms
        )


class WorkerProviderProfile(C011ContractModel):
    """Content-addressed, secret-free description of one candidate worker profile."""

    profile_id: str = ""
    backend_id: str = Field(min_length=1, max_length=300)
    provider_kind: WorkerProviderKind
    model_identity: str = Field(min_length=1, max_length=500)
    model_artifact_sha256: Sha256
    driver_artifact_sha256: Sha256
    compatibility_fingerprint: Sha256
    compatibility_evidence_ref: str = Field(min_length=1, max_length=2000)
    resource_profile: NeuralResourceProfile
    resource_budget: NeuralResourceBudget
    capacity: ProviderCapacity
    allowed_roles: tuple[ParallelCognitionRole, ...] = Field(min_length=1, max_length=2)
    driver_protocol_version: Literal[1] = 1
    system_messages_supported: Literal[False] = False
    multi_turn_supported: Literal[False] = False
    tool_calls_supported: Literal[False] = False
    network_transport_required: Literal[False] = False
    credential_refs: tuple[()] = ()
    write_authority: Literal[False] = False
    network_authority: Literal[False] = False
    tool_authority: Literal[False] = False
    delegation_authority: Literal[False] = False
    memory_commit_authority: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("backend_id", "model_identity", "compatibility_evidence_ref")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("provider profile identifiers cannot be blank")
        return normalized

    @field_validator("allowed_roles")
    @classmethod
    def normalize_roles(
        cls, values: tuple[ParallelCognitionRole, ...]
    ) -> tuple[ParallelCognitionRole, ...]:
        if len(values) != len(set(values)):
            raise ValueError("provider profile roles must be unique")
        return tuple(sorted(values, key=lambda item: item.value))

    def _expected_profile_id(self) -> str:
        payload = self.model_dump(mode="json", exclude={"profile_id"})
        basis = {
            "contract_type": f"{type(self).__module__}.{type(self).__qualname__}",
            "schema_version": self.schema_version,
            "payload": payload,
        }
        digest = sha256(_canonical_json(basis).encode("utf-8")).hexdigest()
        return f"c011-provider-profile:sha256:{digest}"

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        budget = self.resource_budget
        if self.provider_kind is WorkerProviderKind.LUNA_NATIVE_NR2B_SLICE1:
            if (
                budget.max_vram_mib != 0
                or budget.max_gpu_utilization_percent != 0
                or budget.model_resident
                or budget.background_inference
            ):
                raise ValueError("NR-2B Slice 1 profile must remain CPU-only and ephemeral")
            if self.capacity.max_output_tokens > 256:
                raise ValueError("NR-2B Slice 1 profile cannot exceed 256 output tokens")
            if budget.max_parallel_generations > 1:
                raise ValueError("NR-2B Slice 1 profile supports one generation at a time")
        if self.capacity.max_concurrent_workers > budget.max_parallel_generations:
            raise ValueError("provider concurrency exceeds neural generation capacity")
        expected = self._expected_profile_id()
        if not self.profile_id:
            object.__setattr__(self, "profile_id", expected)
        elif self.profile_id != expected:
            raise ValueError("provider profile ID does not match canonical content")
        return self


class S5ProviderRoutingPolicy(C011ContractModel):
    """Injected S5A policy; no ambient setting can activate provider execution."""

    enabled: bool = False
    kill_switch_engaged: bool = True
    stage: ModelRolloutStage = ModelRolloutStage.BLOCKED
    approved_profile_id: str | None = Field(default=None, max_length=500)
    approved_compatibility_fingerprint: Sha256 | None = None
    max_total_workers: int = Field(default=0, ge=0, le=3)
    max_concurrent_workers: int = Field(default=0, ge=0, le=3)
    provider_execution_authority: Literal[False] = False
    root_context_adoption_authority: Literal[False] = False
    task_state_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("approved_profile_id")
    @classmethod
    def normalize_profile_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("approved profile ID cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.stage in {ModelRolloutStage.CANARY, ModelRolloutStage.ACTIVE}:
            raise ValueError("S5A cannot authorize CANARY or ACTIVE provider rollout")
        if self.max_concurrent_workers > self.max_total_workers:
            raise ValueError("routing concurrency cannot exceed its total worker ceiling")
        if self.enabled and not self.kill_switch_engaged:
            if self.stage is not ModelRolloutStage.SHADOW:
                raise ValueError("active S5A routing is limited to SHADOW eligibility")
            if self.approved_profile_id is None:
                raise ValueError("active S5A routing requires an approved profile")
            if self.approved_compatibility_fingerprint is None:
                raise ValueError("active S5A routing requires approved compatibility")
            if self.max_total_workers == 0 or self.max_concurrent_workers == 0:
                raise ValueError("active S5A routing requires positive worker ceilings")
        return self

    @property
    def active(self) -> bool:
        return self.enabled and not self.kill_switch_engaged


class ProviderProfileRequest(C011ContractModel):
    """Minimal exact assignment projection used for pure profile selection."""

    task_id: UUID
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    worker_role: ParallelCognitionRole
    budget: WorkerBudgetEnvelope

    @classmethod
    def from_assignment(cls, assignment: AssignmentSemanticSpec) -> ProviderProfileRequest:
        return cls(
            task_id=assignment.task_id,
            assignment_id=assignment.assignment_id,
            worker_role=assignment.worker_role,
            budget=assignment.budget,
        )


class ProviderProfileSelection(C011ContractModel):
    """Non-executable selection evidence for a later S5 driver stage."""

    disposition: ProviderProfileDisposition
    assignment_id: str = Field(pattern=r"^c011-assignment:sha256:[0-9a-f]{64}$")
    profile_id: str | None = Field(default=None, max_length=500)
    backend_id: str | None = Field(default=None, max_length=300)
    reasons: tuple[str, ...] = Field(min_length=1)
    provider_call_executed: Literal[False] = False
    provider_execution_authority: Literal[False] = False
    root_context_adoption_authority: Literal[False] = False
    task_state_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("reasons")
    @classmethod
    def normalize_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("profile selection reasons cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("profile selection reasons must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        has_binding = self.profile_id is not None and self.backend_id is not None
        if self.disposition is ProviderProfileDisposition.SHADOW_ELIGIBLE and not has_binding:
            raise ValueError("shadow-eligible selection requires a profile/backend binding")
        if self.disposition is ProviderProfileDisposition.DENY and (
            self.profile_id is None
        ) != (self.backend_id is None):
            raise ValueError("denied profile/backend binding must be complete or absent")
        return self


class ProviderProfileRegistry:
    """Immutable, I/O-free profile lookup and fail-closed selection boundary."""

    def __init__(self, profiles: Iterable[WorkerProviderProfile]) -> None:
        validated = tuple(
            WorkerProviderProfile.model_validate(profile.model_dump(mode="json"))
            for profile in profiles
        )
        profile_ids = tuple(profile.profile_id for profile in validated)
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("provider profile IDs must be unique")
        self._profiles = {profile.profile_id: profile for profile in validated}

    def profile(self, profile_id: str) -> WorkerProviderProfile | None:
        selected = self._profiles.get(profile_id)
        return None if selected is None else selected.model_copy(deep=True)

    def select(
        self,
        *,
        request: ProviderProfileRequest,
        policy: S5ProviderRoutingPolicy,
        compatibility: ModelCompatibilityReport,
        current_resource_budget: NeuralResourceBudget,
    ) -> ProviderProfileSelection:
        current_request = ProviderProfileRequest.model_validate(
            request.model_dump(mode="json")
        )
        current_policy = S5ProviderRoutingPolicy.model_validate(
            policy.model_dump(mode="json")
        )
        current_compatibility = ModelCompatibilityReport.model_validate(
            compatibility.model_dump(mode="json")
        )
        current_budget = NeuralResourceBudget.model_validate(
            current_resource_budget.model_dump(mode="json")
        )
        reasons: list[str] = []
        if not current_policy.enabled:
            reasons.append("provider routing policy is disabled")
        if current_policy.kill_switch_engaged:
            reasons.append("provider routing kill switch is engaged")
        if current_policy.stage is ModelRolloutStage.BLOCKED:
            reasons.append("provider rollout stage is BLOCKED")
        profile = (
            None
            if current_policy.approved_profile_id is None
            else self._profiles.get(current_policy.approved_profile_id)
        )
        if current_policy.approved_profile_id is None:
            reasons.append("no provider profile is approved")
        elif profile is None:
            reasons.append("approved provider profile is not registered")
        if profile is not None:
            actual_fingerprint = current_compatibility.fingerprint()
            if current_compatibility.backend_id != profile.backend_id:
                reasons.append("compatibility backend does not match the provider profile")
            if actual_fingerprint != profile.compatibility_fingerprint:
                reasons.append("current compatibility fingerprint does not match the profile")
            if (
                current_policy.approved_compatibility_fingerprint
                != profile.compatibility_fingerprint
            ):
                reasons.append("policy compatibility approval does not match the profile")
            if not current_compatibility.eligible_for_rollout:
                reasons.append("required provider compatibility cases are not all PASS")
            if current_budget != profile.resource_budget:
                reasons.append("current neural resource budget does not match the profile")
            if current_request.worker_role not in profile.allowed_roles:
                reasons.append("assignment role is not allowed by the provider profile")
            if not profile.capacity.contains(current_request.budget):
                reasons.append("assignment exceeds provider profile capacity")
            if current_policy.max_total_workers > profile.capacity.max_total_workers:
                reasons.append("routing total-worker ceiling exceeds provider capacity")
            if (
                current_policy.max_concurrent_workers
                > profile.capacity.max_concurrent_workers
            ):
                reasons.append("routing concurrency exceeds provider capacity")

        if reasons:
            return ProviderProfileSelection(
                disposition=ProviderProfileDisposition.DENY,
                assignment_id=current_request.assignment_id,
                profile_id=None if profile is None else profile.profile_id,
                backend_id=None if profile is None else profile.backend_id,
                reasons=tuple(reasons),
            )
        assert profile is not None
        return ProviderProfileSelection(
            disposition=ProviderProfileDisposition.SHADOW_ELIGIBLE,
            assignment_id=current_request.assignment_id,
            profile_id=profile.profile_id,
            backend_id=profile.backend_id,
            reasons=(
                "exact current profile is eligible for later shadow-only evidence collection",
            ),
        )


__all__ = [
    "ProviderCapacity",
    "ProviderProfileDisposition",
    "ProviderProfileRegistry",
    "ProviderProfileRequest",
    "ProviderProfileSelection",
    "S5ProviderRoutingPolicy",
    "WorkerProviderKind",
    "WorkerProviderProfile",
]
