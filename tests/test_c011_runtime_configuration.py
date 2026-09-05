from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from hashlib import sha256
from threading import Barrier, Lock
from typing import cast

import pytest
from pydantic import ValidationError

from luna.parallel_cognition import (
    BackendSafetyCapabilities,
    BoundedRealNativeAdapterPool,
    EqualComputeBudget,
    LocalNativeDriverResult,
    RealNativeAdapterPoolBinding,
    RealRuntimeArmContract,
    RealRuntimeAssetBinding,
    RealRuntimeConfigurationSet,
    RuntimeEffortProfile,
    RuntimeTopology,
    S4RuntimePolicy,
    S5BDriverIntegrityError,
    ShadowConfiguration,
    build_default_real_runtime_configuration_set,
    runtime_prompt_protocol_sha256,
)


def _digest(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _asset_binding(**updates: object) -> RealRuntimeAssetBinding:
    values: dict[str, object] = {
        "backend_id": "local-native:c011-runtime-contract",
        "provider_profile_id": "c011-provider-profile:sha256:" + _digest("profile"),
        "provider_binding_id": "c011-native-driver-binding:sha256:" + _digest("binding"),
        "model_identity": "candidate-model@sha256:" + _digest("model"),
        "model_artifact_sha256": _digest("model"),
        "bridge_artifact_sha256": _digest("bridge"),
        "driver_artifact_sha256": _digest("driver"),
        "runtime_bundle_sha256": _digest("runtime"),
        "environment_sha256": _digest("environment"),
        "sampling_sha256": _digest("sampling"),
    }
    values.update(updates)
    return RealRuntimeAssetBinding(**values)  # type: ignore[arg-type]


def _budget(**updates: object) -> EqualComputeBudget:
    values: dict[str, object] = {
        "max_total_tokens": 2048,
        "max_tool_calls": 0,
        "max_compute_units": 1000,
        "max_context_bytes": 32768,
        "max_wall_time_ms": 300000,
    }
    values.update(updates)
    return EqualComputeBudget(**values)  # type: ignore[arg-type]


def _configuration_set(
    *,
    parallel_workers: int = 2,
    asset_binding: RealRuntimeAssetBinding | None = None,
    budget: EqualComputeBudget | None = None,
) -> RealRuntimeConfigurationSet:
    return build_default_real_runtime_configuration_set(
        asset_binding=asset_binding or _asset_binding(),
        equal_compute_budget=budget or _budget(),
        parallel_workers=cast("object", parallel_workers),  # type: ignore[arg-type]
    )


def test_default_runtime_set_freezes_three_distinct_equal_compute_topologies() -> None:
    first = _configuration_set()
    second = _configuration_set()

    assert first == second
    assert tuple(arm.configuration for arm in first.arms) == tuple(ShadowConfiguration)
    assert tuple(arm.generation_count for arm in first.arms) == (1, 2, 3)
    assert tuple(arm.worker_count for arm in first.arms) == (0, 0, 2)
    assert tuple(arm.max_concurrent_generations for arm in first.arms) == (1, 1, 2)
    assert {arm.max_total_output_tokens for arm in first.arms} == {256}
    assert {arm.normalized_compute_units for arm in first.arms} == {1000}
    assert first.arms[0].effort_profile is RuntimeEffortProfile.STANDARD
    assert all(arm.effort_profile is RuntimeEffortProfile.ULTRA for arm in first.arms[1:])
    assert first.arms[-1].topology is RuntimeTopology.ROOT_WITH_READ_ONLY_PARALLEL_WORKERS


def test_three_worker_variant_preserves_equal_output_ceiling() -> None:
    configuration = _configuration_set(parallel_workers=3)
    parallel = configuration.arms[-1]

    assert configuration.adapter_pool_members == 3
    assert parallel.worker_count == 3
    assert parallel.max_output_tokens_per_root_generation == 64
    assert parallel.max_output_tokens_per_worker_generation == 64
    assert parallel.max_total_output_tokens == 256


def test_runtime_set_projects_exact_s5c_arm_identities() -> None:
    configuration = _configuration_set()
    shadow_arms = configuration.shadow_arms()

    assert tuple(arm.configuration for arm in shadow_arms) == tuple(ShadowConfiguration)
    assert tuple(arm.worker_count for arm in shadow_arms) == (0, 0, 2)
    assert tuple(arm.execution_configuration_sha256 for arm in shadow_arms) == tuple(
        arm.configuration_sha256 for arm in configuration.arms
    )
    assert {arm.provider_binding_id for arm in shadow_arms} == {
        configuration.asset_binding.provider_binding_id
    }
    assert {arm.model_identity for arm in shadow_arms} == {
        configuration.asset_binding.model_identity
    }


@pytest.mark.parametrize(
    ("configuration", "updates", "reason"),
    (
        (
            ShadowConfiguration.SOLO,
            {"worker_count": 1},
            "SOLO runtime topology",
        ),
        (
            ShadowConfiguration.ULTRA_SOLO,
            {"effort_profile": RuntimeEffortProfile.STANDARD},
            "ULTRA_SOLO runtime topology",
        ),
        (
            ShadowConfiguration.PARALLEL,
            {"worker_count": 1, "max_concurrent_generations": 1},
            "PARALLEL runtime topology",
        ),
        (
            ShadowConfiguration.PARALLEL,
            {"prompt_protocol_sha256": _digest("other")},
            "prompt protocol",
        ),
    ),
)
def test_noncanonical_arm_semantics_fail_closed(
    configuration: ShadowConfiguration,
    updates: dict[str, object],
    reason: str,
) -> None:
    arm = next(item for item in _configuration_set().arms if item.configuration is configuration)
    payload = arm.model_dump(mode="json")
    payload.update(updates)
    payload["configuration_id"] = ""

    with pytest.raises(ValidationError, match=reason):
        RealRuntimeArmContract.model_validate(payload)


def test_arm_and_set_content_identities_reject_tampering() -> None:
    configuration = _configuration_set()
    arm_payload = configuration.arms[0].model_dump(mode="json")
    arm_payload["configuration_id"] = "c011-real-runtime-arm:sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="configuration_id"):
        RealRuntimeArmContract.model_validate(arm_payload)

    set_payload = configuration.model_dump(mode="json")
    set_payload["configuration_set_id"] = "c011-real-runtime-set:sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="configuration_set_id"):
        RealRuntimeConfigurationSet.model_validate(set_payload)


def test_cross_arm_asset_compute_and_tool_drift_fail_closed() -> None:
    configuration = _configuration_set()
    arms = list(configuration.arms)
    changed = arms[1].model_dump(mode="json")
    changed.update(
        {
            "configuration_id": "",
            "asset_binding_id": "c011-real-runtime-assets:sha256:" + "1" * 64,
        }
    )
    arms[1] = RealRuntimeArmContract.model_validate(changed)
    payload = configuration.model_dump(mode="json")
    payload.update({"configuration_set_id": "", "arms": arms})
    with pytest.raises(ValidationError, match="share the exact asset"):
        RealRuntimeConfigurationSet.model_validate(payload)

    with pytest.raises(ValidationError, match="cannot grant tool calls"):
        _configuration_set(budget=_budget(max_tool_calls=1))


def test_runtime_contracts_are_authority_negative_and_final_only() -> None:
    configuration = _configuration_set()
    authority_values = (
        configuration.runtime_authority,
        configuration.task_state_authority,
        configuration.root_context_adoption_authority,
        configuration.completion_authority,
        configuration.user_facing_voice_authority,
        configuration.canary_authority,
        configuration.active_authority,
        configuration.promotion_authority,
    )

    assert not any(authority_values)
    assert configuration.default_enabled is False
    assert configuration.production_runtime_wiring is False
    assert all(arm.intermediate_payload_final_only for arm in configuration.arms)
    assert all(not arm.raw_analysis_persisted for arm in configuration.arms)
    assert all(not arm.worker_output_to_task_state for arm in configuration.arms)
    assert all(
        arm.prompt_protocol_sha256 == runtime_prompt_protocol_sha256(arm.configuration)
        for arm in configuration.arms
    )


@dataclass(slots=True)
class _FakeOneShotAdapter:
    lane: str
    barrier: Barrier | None = None
    backend_id: str = "local-native:c011-pool-test"
    profile_id: str = "c011-provider-profile:sha256:" + _digest("pool-profile")
    binding_id: str = "c011-native-driver-binding:sha256:" + _digest("pool-binding")
    safe: bool = True
    fail: bool = False
    calls: int = 0
    _consumed: bool = False
    _lock: Lock = field(default_factory=Lock)

    @property
    def safety_capabilities(self) -> BackendSafetyCapabilities:
        return BackendSafetyCapabilities(
            bounded_driver_calls=self.safe,
            cooperative_cancellation=self.safe,
            hard_termination=self.safe,
            isolated_ephemeral_scratch=self.safe,
            explicit_environment_only=self.safe,
            shell_disabled=self.safe,
        )

    @property
    def real_attempt_consumed(self) -> bool:
        return self._consumed

    def execute(self, **kwargs: object) -> LocalNativeDriverResult:
        del kwargs
        with self._lock:
            if self._consumed:
                raise AssertionError("fake one-shot adapter was replayed")
            self._consumed = True
            self.calls += 1
        if self.barrier is not None:
            self.barrier.wait(timeout=5)
        if self.fail:
            raise RuntimeError("bounded fake failure")
        return cast(LocalNativeDriverResult, self.lane)


def _pool_binding(**updates: object) -> RealNativeAdapterPoolBinding:
    values: dict[str, object] = {
        "member_binding_id": "c011-native-driver-binding:sha256:" + _digest("pool-binding"),
        "backend_id": "local-native:c011-pool-test",
        "profile_id": "c011-provider-profile:sha256:" + _digest("pool-profile"),
        "member_count": 2,
        "max_concurrent_members": 2,
    }
    values.update(updates)
    return RealNativeAdapterPoolBinding(**values)  # type: ignore[arg-type]


def test_pool_binding_is_content_addressed_and_capacity_is_exact() -> None:
    binding = _pool_binding()
    assert binding.pool_binding_id.startswith("c011-native-adapter-pool:sha256:")
    with pytest.raises(ValidationError, match="every bounded member"):
        _pool_binding(member_count=3)
    payload = binding.model_dump(mode="json")
    payload["pool_binding_id"] = "c011-native-adapter-pool:sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="pool_binding_id"):
        RealNativeAdapterPoolBinding.model_validate(payload)


@pytest.mark.parametrize("defect", ("duplicate", "identity", "unsafe", "consumed"))
def test_pool_rejects_nonindependent_or_untrusted_members(defect: str) -> None:
    first = _FakeOneShotAdapter("one")
    second = _FakeOneShotAdapter("two")
    members = [first, second]
    if defect == "duplicate":
        members[1] = first
    elif defect == "identity":
        second.backend_id = "other"
    elif defect == "unsafe":
        second.safe = False
    else:
        second._consumed = True

    with pytest.raises(S5BDriverIntegrityError):
        BoundedRealNativeAdapterPool(binding=_pool_binding(), adapters=members)


def test_pool_executes_two_distinct_members_concurrently_and_never_replays() -> None:
    barrier = Barrier(2)
    members = (
        _FakeOneShotAdapter("one", barrier=barrier),
        _FakeOneShotAdapter("two", barrier=barrier),
    )
    pool = BoundedRealNativeAdapterPool(
        binding=_pool_binding(),
        adapters=members,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda _: pool.execute(
                    request=cast("object", None),
                    context=cast("object", None),
                    policy=S4RuntimePolicy(),
                    cancellation_probe=lambda: False,
                ),
                range(2),
            )
        )

    assert set(cast(tuple[str, str], results)) == {"one", "two"}
    assert tuple(member.calls for member in members) == (1, 1)
    assert pool.real_attempts_consumed == 2
    assert pool.max_in_flight == 2
    assert pool.exhausted
    with pytest.raises(S5BDriverIntegrityError, match="replay is forbidden"):
        pool.execute(
            request=cast("object", None),
            context=cast("object", None),
            policy=S4RuntimePolicy(),
            cancellation_probe=lambda: False,
        )


def test_failed_pool_member_is_consumed_without_replay() -> None:
    members = (_FakeOneShotAdapter("one", fail=True), _FakeOneShotAdapter("two"))
    pool = BoundedRealNativeAdapterPool(binding=_pool_binding(), adapters=members)

    with pytest.raises(RuntimeError, match="bounded fake failure"):
        pool.execute(
            request=cast("object", None),
            context=cast("object", None),
            policy=S4RuntimePolicy(),
            cancellation_probe=lambda: False,
        )
    assert pool.real_attempts_consumed == 1
    assert members[0].calls == 1
