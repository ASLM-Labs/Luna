"""Content-addressed real-runtime configurations for C-011 evidence runs.

The contracts in this module define the exact meaning of SOLO, ULTRA_SOLO and
PARALLEL for later equal-compute evidence. They do not execute a model, select
production routing, adopt output, or grant rollout authority.
"""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from luna.parallel_cognition.models import C011ContractModel, Sha256
from luna.parallel_cognition.shadow_evaluation import (
    EqualComputeBudget,
    ShadowArmSpec,
    ShadowConfiguration,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class _ContentAddressedRuntimeContract(C011ContractModel):
    _identity_field: ClassVar[str]
    _identity_prefix: ClassVar[str]

    @model_validator(mode="after")
    def validate_content_identity(self) -> Self:
        payload = self.model_dump(mode="json", exclude={self._identity_field})
        basis = {
            "contract_type": f"{type(self).__module__}.{type(self).__qualname__}",
            "schema_version": self.schema_version,
            "payload": payload,
        }
        expected = (
            self._identity_prefix + sha256(_canonical_json(basis).encode("utf-8")).hexdigest()
        )
        supplied = getattr(self, self._identity_field)
        if not supplied:
            object.__setattr__(self, self._identity_field, expected)
        elif supplied != expected:
            raise ValueError(f"{self._identity_field} does not match canonical contract content")
        return self


class RuntimeEffortProfile(StrEnum):
    """Root-owned effort semantics; worker topology remains a separate axis."""

    STANDARD = "STANDARD"
    ULTRA = "ULTRA"


class RuntimeTopology(StrEnum):
    ROOT_ONLY = "ROOT_ONLY"
    ROOT_WITH_READ_ONLY_PARALLEL_WORKERS = "ROOT_WITH_READ_ONLY_PARALLEL_WORKERS"


_PROMPT_PROTOCOLS = {
    ShadowConfiguration.SOLO: (
        "c011-runtime-v1: one root final-only pass over the frozen case context"
    ),
    ShadowConfiguration.ULTRA_SOLO: (
        "c011-runtime-v1: one root final-only draft followed by one root-only "
        "verification and finalization pass"
    ),
    ShadowConfiguration.PARALLEL: (
        "c011-runtime-v1: independent read-only worker passes execute concurrently; "
        "one root-only pass verifies and synthesizes their final-only drafts"
    ),
}


def runtime_prompt_protocol_sha256(configuration: ShadowConfiguration) -> str:
    """Return the canonical public protocol digest for one runtime arm."""

    return sha256(_PROMPT_PROTOCOLS[configuration].encode("utf-8")).hexdigest()


class RealRuntimeAssetBinding(_ContentAddressedRuntimeContract):
    """Exact common provider and artifact identity shared by every compared arm."""

    asset_binding_id: str = ""
    backend_id: str = Field(min_length=1, max_length=300)
    provider_profile_id: str = Field(pattern=r"^c011-provider-profile:sha256:[0-9a-f]{64}$")
    provider_binding_id: str = Field(pattern=r"^c011-native-driver-binding:sha256:[0-9a-f]{64}$")
    model_identity: str = Field(min_length=1, max_length=500)
    model_artifact_sha256: Sha256
    bridge_artifact_sha256: Sha256
    driver_artifact_sha256: Sha256
    runtime_bundle_sha256: Sha256
    environment_sha256: Sha256
    sampling_sha256: Sha256
    bridge_abi_version: Literal[2] = 2
    usage_source: Literal["ENGINE_NATIVE_COUNTERS"] = "ENGINE_NATIVE_COUNTERS"
    cpu_only: Literal[True] = True
    ephemeral_model_lifecycle: Literal[True] = True
    tool_authority: Literal[False] = False
    network_authority: Literal[False] = False
    write_authority: Literal[False] = False
    state_mutation_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    _identity_field = "asset_binding_id"
    _identity_prefix = "c011-real-runtime-assets:sha256:"

    @field_validator("backend_id", "model_identity")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("runtime asset identifiers cannot be blank")
        return normalized


class RealRuntimeArmContract(_ContentAddressedRuntimeContract):
    """One executable topology definition under a shared evidence-only budget."""

    configuration_id: str = ""
    configuration: ShadowConfiguration
    effort_profile: RuntimeEffortProfile
    topology: RuntimeTopology
    asset_binding_id: str = Field(pattern=r"^c011-real-runtime-assets:sha256:[0-9a-f]{64}$")
    prompt_protocol_sha256: Sha256
    root_generation_count: int = Field(ge=1, le=2)
    worker_count: int = Field(ge=0, le=3)
    worker_generations_per_worker: int = Field(ge=0, le=1)
    max_concurrent_generations: int = Field(ge=1, le=3)
    max_output_tokens_per_root_generation: int = Field(ge=1, le=256)
    max_output_tokens_per_worker_generation: int = Field(ge=0, le=256)
    max_total_output_tokens: int = Field(ge=1, le=1024)
    normalized_compute_units: int = Field(ge=1)
    seed: int = Field(default=0, ge=0)
    measured_usage_required: Literal[True] = True
    intermediate_payload_final_only: Literal[True] = True
    raw_analysis_persisted: Literal[False] = False
    worker_output_to_task_state: Literal[False] = False
    execution_authority: Literal[False] = False
    task_state_authority: Literal[False] = False
    root_context_adoption_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    _identity_field = "configuration_id"
    _identity_prefix = "c011-real-runtime-arm:sha256:"

    @property
    def generation_count(self) -> int:
        return self.root_generation_count + (self.worker_count * self.worker_generations_per_worker)

    @property
    def configuration_sha256(self) -> str:
        return self.configuration_id.rsplit(":", maxsplit=1)[-1]

    @model_validator(mode="after")
    def validate_topology(self) -> Self:
        expected_protocol = runtime_prompt_protocol_sha256(self.configuration)
        if self.prompt_protocol_sha256 != expected_protocol:
            raise ValueError("runtime arm prompt protocol does not match its configuration")

        if self.configuration is ShadowConfiguration.SOLO:
            expected = (
                self.effort_profile is RuntimeEffortProfile.STANDARD
                and self.topology is RuntimeTopology.ROOT_ONLY
                and self.root_generation_count == 1
                and self.worker_count == 0
                and self.worker_generations_per_worker == 0
                and self.max_concurrent_generations == 1
                and self.max_output_tokens_per_worker_generation == 0
            )
            if not expected:
                raise ValueError("SOLO runtime topology is not canonical")
        elif self.configuration is ShadowConfiguration.ULTRA_SOLO:
            expected = (
                self.effort_profile is RuntimeEffortProfile.ULTRA
                and self.topology is RuntimeTopology.ROOT_ONLY
                and self.root_generation_count == 2
                and self.worker_count == 0
                and self.worker_generations_per_worker == 0
                and self.max_concurrent_generations == 1
                and self.max_output_tokens_per_worker_generation == 0
            )
            if not expected:
                raise ValueError("ULTRA_SOLO runtime topology is not canonical")
        else:
            expected = (
                self.effort_profile is RuntimeEffortProfile.ULTRA
                and self.topology is RuntimeTopology.ROOT_WITH_READ_ONLY_PARALLEL_WORKERS
                and self.root_generation_count == 1
                and 2 <= self.worker_count <= 3
                and self.worker_generations_per_worker == 1
                and self.max_concurrent_generations == self.worker_count
                and self.max_output_tokens_per_worker_generation > 0
            )
            if not expected:
                raise ValueError("PARALLEL runtime topology is not canonical")

        computed_output_ceiling = (
            self.root_generation_count * self.max_output_tokens_per_root_generation
            + self.worker_count
            * self.worker_generations_per_worker
            * self.max_output_tokens_per_worker_generation
        )
        if computed_output_ceiling != self.max_total_output_tokens:
            raise ValueError("runtime arm output-token ceiling does not match its calls")
        return self


class RealRuntimeConfigurationSet(_ContentAddressedRuntimeContract):
    """Canonical three-arm contract set for a bounded equal-compute evidence run."""

    configuration_set_id: str = ""
    revision: Literal["1.0.0"] = "1.0.0"
    asset_binding: RealRuntimeAssetBinding
    equal_compute_budget: EqualComputeBudget
    adapter_pool_members: int = Field(ge=2, le=3)
    arms: tuple[RealRuntimeArmContract, ...] = Field(min_length=3, max_length=3)
    capability_status: Literal["QUEUED"] = "QUEUED"
    default_enabled: Literal[False] = False
    rollout_stage: Literal["BLOCKED"] = "BLOCKED"
    evidence_only: Literal[True] = True
    production_runtime_wiring: Literal[False] = False
    runtime_authority: Literal[False] = False
    task_state_authority: Literal[False] = False
    root_context_adoption_authority: Literal[False] = False
    completion_authority: Literal[False] = False
    user_facing_voice_authority: Literal[False] = False
    canary_authority: Literal[False] = False
    active_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    _identity_field = "configuration_set_id"
    _identity_prefix = "c011-real-runtime-set:sha256:"

    @model_validator(mode="after")
    def validate_configuration_set(self) -> Self:
        expected_order = tuple(ShadowConfiguration)
        if tuple(arm.configuration for arm in self.arms) != expected_order:
            raise ValueError("runtime set requires canonical SOLO/ULTRA_SOLO/PARALLEL order")
        if any(arm.asset_binding_id != self.asset_binding.asset_binding_id for arm in self.arms):
            raise ValueError("runtime arms must share the exact asset binding")
        if len({arm.configuration_id for arm in self.arms}) != len(self.arms):
            raise ValueError("runtime arm identities must be unique")
        if len({arm.prompt_protocol_sha256 for arm in self.arms}) != len(self.arms):
            raise ValueError("runtime arm prompt protocols must be distinct")
        if len({arm.max_total_output_tokens for arm in self.arms}) != 1:
            raise ValueError("runtime arms must share one output-token ceiling")
        if len({arm.normalized_compute_units for arm in self.arms}) != 1:
            raise ValueError("runtime arms must share normalized compute units")
        if self.arms[0].normalized_compute_units != self.equal_compute_budget.max_compute_units:
            raise ValueError("runtime compute units must match the shared budget")
        if self.arms[0].max_total_output_tokens > self.equal_compute_budget.max_total_tokens:
            raise ValueError("runtime output ceiling exceeds the shared token budget")
        if self.equal_compute_budget.max_tool_calls != 0:
            raise ValueError("C-011 real runtime evidence cannot grant tool calls")
        parallel = self.arms[-1]
        if parallel.worker_count != self.adapter_pool_members:
            raise ValueError("parallel worker count must match the bounded adapter pool")
        return self

    def shadow_arms(self) -> tuple[ShadowArmSpec, ...]:
        """Project exact runtime identities into the accepted S5C arm schema."""

        assets = self.asset_binding
        return tuple(
            ShadowArmSpec(
                configuration=arm.configuration,
                execution_configuration_sha256=arm.configuration_sha256,
                backend_id=assets.backend_id,
                provider_profile_id=assets.provider_profile_id,
                provider_binding_id=assets.provider_binding_id,
                model_identity=assets.model_identity,
                driver_sha256=assets.driver_artifact_sha256,
                runtime_sha256=assets.runtime_bundle_sha256,
                environment_sha256=assets.environment_sha256,
                sampling_sha256=assets.sampling_sha256,
                seed=arm.seed,
                worker_count=arm.worker_count,
            )
            for arm in self.arms
        )


def build_default_real_runtime_configuration_set(
    *,
    asset_binding: RealRuntimeAssetBinding,
    equal_compute_budget: EqualComputeBudget,
    parallel_workers: Literal[2, 3] = 2,
) -> RealRuntimeConfigurationSet:
    """Build the frozen v1 topology with an equal 256-output-token arm ceiling."""

    normalized_compute = equal_compute_budget.max_compute_units
    parallel_root_tokens = 128 if parallel_workers == 2 else 64
    arms = (
        RealRuntimeArmContract(
            configuration=ShadowConfiguration.SOLO,
            effort_profile=RuntimeEffortProfile.STANDARD,
            topology=RuntimeTopology.ROOT_ONLY,
            prompt_protocol_sha256=runtime_prompt_protocol_sha256(ShadowConfiguration.SOLO),
            root_generation_count=1,
            worker_count=0,
            worker_generations_per_worker=0,
            max_concurrent_generations=1,
            max_output_tokens_per_root_generation=256,
            max_output_tokens_per_worker_generation=0,
            max_total_output_tokens=256,
            asset_binding_id=asset_binding.asset_binding_id,
            normalized_compute_units=normalized_compute,
        ),
        RealRuntimeArmContract(
            configuration=ShadowConfiguration.ULTRA_SOLO,
            effort_profile=RuntimeEffortProfile.ULTRA,
            topology=RuntimeTopology.ROOT_ONLY,
            prompt_protocol_sha256=runtime_prompt_protocol_sha256(ShadowConfiguration.ULTRA_SOLO),
            root_generation_count=2,
            worker_count=0,
            worker_generations_per_worker=0,
            max_concurrent_generations=1,
            max_output_tokens_per_root_generation=128,
            max_output_tokens_per_worker_generation=0,
            max_total_output_tokens=256,
            asset_binding_id=asset_binding.asset_binding_id,
            normalized_compute_units=normalized_compute,
        ),
        RealRuntimeArmContract(
            configuration=ShadowConfiguration.PARALLEL,
            effort_profile=RuntimeEffortProfile.ULTRA,
            topology=RuntimeTopology.ROOT_WITH_READ_ONLY_PARALLEL_WORKERS,
            prompt_protocol_sha256=runtime_prompt_protocol_sha256(ShadowConfiguration.PARALLEL),
            root_generation_count=1,
            worker_count=parallel_workers,
            worker_generations_per_worker=1,
            max_concurrent_generations=parallel_workers,
            max_output_tokens_per_root_generation=parallel_root_tokens,
            max_output_tokens_per_worker_generation=64,
            max_total_output_tokens=256,
            asset_binding_id=asset_binding.asset_binding_id,
            normalized_compute_units=normalized_compute,
        ),
    )
    return RealRuntimeConfigurationSet(
        asset_binding=asset_binding,
        equal_compute_budget=equal_compute_budget,
        adapter_pool_members=parallel_workers,
        arms=arms,
    )


__all__ = [
    "RealRuntimeArmContract",
    "RealRuntimeAssetBinding",
    "RealRuntimeConfigurationSet",
    "RuntimeEffortProfile",
    "RuntimeTopology",
    "build_default_real_runtime_configuration_set",
    "runtime_prompt_protocol_sha256",
]
