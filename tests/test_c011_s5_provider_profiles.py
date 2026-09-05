from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from luna.modeling import (
    ModelCompatibilityCapability,
    ModelCompatibilityCaseResult,
    ModelCompatibilityReport,
    ModelCompatibilityStatus,
    ModelRolloutStage,
)
from luna.neural import NeuralResourceBudget, NeuralResourceProfile
from luna.parallel_cognition import (
    ParallelCognitionRole,
    ProviderCapacity,
    ProviderProfileDisposition,
    ProviderProfileRegistry,
    ProviderProfileRequest,
    S5ProviderRoutingPolicy,
    WorkerBudgetEnvelope,
    WorkerProviderKind,
    WorkerProviderProfile,
)

_TASK_ID = UUID("58a6fb62-5740-40f1-9b0f-b48d273a3847")
_ASSIGNMENT_ID = f"c011-assignment:sha256:{'c' * 64}"


def _compatibility(
    *, backend_id: str = "luna-native-s5", passing: bool = True
) -> ModelCompatibilityReport:
    results = tuple(
        ModelCompatibilityCaseResult(
            case_id=f"S5A-{index:02d}-{capability.value.lower()}",
            capability=capability,
            status=(
                ModelCompatibilityStatus.PASS
                if passing or index > 1
                else ModelCompatibilityStatus.FAIL
            ),
            required=True,
            detail="deterministic S5A compatibility evidence",
        )
        for index, capability in enumerate(ModelCompatibilityCapability, start=1)
    )
    return ModelCompatibilityReport(
        report_id=UUID("f63be18c-5e27-4646-8be3-b042e78ff16c"),
        backend_id=backend_id,
        results=results,
        created_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )


def _resource_budget(**overrides: object) -> NeuralResourceBudget:
    values: dict[str, object] = {
        "max_vram_mib": 0,
        "max_gpu_utilization_percent": 0,
        "cpu_threads": 8,
        "max_system_ram_mib": 32768,
        "max_kv_cache_mib": 0,
        "max_context_tokens": 8192,
        "batch_size": 128,
        "max_parallel_generations": 1,
        "idle_unload_seconds": 0,
        "request_priority": 50,
        "inference_allowed": True,
        "model_resident": False,
        "background_inference": False,
    }
    values.update(overrides)
    return NeuralResourceBudget.model_validate(values)


def _capacity(**overrides: object) -> ProviderCapacity:
    values: dict[str, object] = {
        "max_context_bytes": 65536,
        "max_result_bytes": 32768,
        "max_claims": 8,
        "max_output_tokens": 256,
        "max_runtime_ms": 30000,
        "max_total_workers": 1,
        "max_concurrent_workers": 1,
    }
    values.update(overrides)
    return ProviderCapacity.model_validate(values)


def _profile(
    compatibility: ModelCompatibilityReport,
    *,
    resource_budget: NeuralResourceBudget | None = None,
    capacity: ProviderCapacity | None = None,
    allowed_roles: tuple[ParallelCognitionRole, ...] = (
        ParallelCognitionRole.PARALLEL,
    ),
) -> WorkerProviderProfile:
    return WorkerProviderProfile(
        backend_id=compatibility.backend_id,
        provider_kind=WorkerProviderKind.LUNA_NATIVE_NR2B_SLICE1,
        model_identity="fixture-native-model",
        model_artifact_sha256="a" * 64,
        driver_artifact_sha256="b" * 64,
        compatibility_fingerprint=compatibility.fingerprint(),
        compatibility_evidence_ref="docs/NEURAL_RUNTIME_NR2B_REAL_PROOF_RECEIPT.json",
        resource_profile=NeuralResourceProfile.DESKTOP,
        resource_budget=resource_budget or _resource_budget(),
        capacity=capacity or _capacity(),
        allowed_roles=allowed_roles,
    )


def _request(
    *,
    worker_role: ParallelCognitionRole = ParallelCognitionRole.PARALLEL,
    **budget_overrides: object,
) -> ProviderProfileRequest:
    budget_values: dict[str, object] = {
        "max_context_bytes": 32768,
        "max_result_bytes": 16384,
        "max_claims": 4,
        "max_tokens": 128,
        "max_runtime_ms": 15000,
        "deadline_at": datetime.now(UTC) + timedelta(minutes=5),
    }
    budget_values.update(budget_overrides)
    return ProviderProfileRequest(
        task_id=_TASK_ID,
        assignment_id=_ASSIGNMENT_ID,
        worker_role=worker_role,
        budget=WorkerBudgetEnvelope.model_validate(budget_values),
    )


def _active_policy(profile: WorkerProviderProfile, **overrides: object) -> S5ProviderRoutingPolicy:
    values: dict[str, object] = {
        "enabled": True,
        "kill_switch_engaged": False,
        "stage": ModelRolloutStage.SHADOW,
        "approved_profile_id": profile.profile_id,
        "approved_compatibility_fingerprint": profile.compatibility_fingerprint,
        "max_total_workers": 1,
        "max_concurrent_workers": 1,
    }
    values.update(overrides)
    return S5ProviderRoutingPolicy.model_validate(values)


def test_profile_is_content_addressed_normalized_and_tamper_evident() -> None:
    compatibility = _compatibility()
    profile = _profile(
        compatibility,
        allowed_roles=(
            ParallelCognitionRole.PARALLEL,
            ParallelCognitionRole.INDEPENDENT_REVIEWER,
        ),
    )

    assert profile.profile_id.startswith("c011-provider-profile:sha256:")
    assert profile.allowed_roles == (
        ParallelCognitionRole.INDEPENDENT_REVIEWER,
        ParallelCognitionRole.PARALLEL,
    )
    assert WorkerProviderProfile.model_validate(profile.model_dump(mode="json")) == profile

    tampered = profile.model_dump(mode="json")
    tampered["model_identity"] = "different-model"
    with pytest.raises(ValidationError, match="canonical content"):
        WorkerProviderProfile.model_validate(tampered)


@pytest.mark.parametrize(
    ("budget_overrides", "capacity_overrides", "match"),
    [
        ({"max_vram_mib": 1}, {}, "CPU-only"),
        ({"model_resident": True}, {}, "CPU-only"),
        ({"max_parallel_generations": 2}, {}, "one generation"),
        ({}, {"max_output_tokens": 257}, "256 output tokens"),
    ],
)
def test_nr2b_slice1_profile_rejects_unproven_resource_expansion(
    budget_overrides: dict[str, object],
    capacity_overrides: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        _profile(
            _compatibility(),
            resource_budget=_resource_budget(**budget_overrides),
            capacity=_capacity(**capacity_overrides),
        )


def test_registry_revalidates_profiles_rejects_duplicates_and_returns_copies() -> None:
    profile = _profile(_compatibility())
    with pytest.raises(ValueError, match="unique"):
        ProviderProfileRegistry((profile, profile))

    registry = ProviderProfileRegistry((profile,))
    selected = registry.profile(profile.profile_id)
    assert selected == profile
    assert selected is not profile
    assert registry.profile("c011-provider-profile:sha256:" + "0" * 64) is None


def test_default_and_kill_switch_policies_fail_closed_without_execution_authority() -> None:
    compatibility = _compatibility()
    profile = _profile(compatibility)
    registry = ProviderProfileRegistry((profile,))

    default_denial = registry.select(
        request=_request(),
        policy=S5ProviderRoutingPolicy(),
        compatibility=compatibility,
        current_resource_budget=profile.resource_budget,
    )
    killed_denial = registry.select(
        request=_request(),
        policy=_active_policy(profile, kill_switch_engaged=True),
        compatibility=compatibility,
        current_resource_budget=profile.resource_budget,
    )

    assert default_denial.disposition is ProviderProfileDisposition.DENY
    assert any("disabled" in reason for reason in default_denial.reasons)
    assert killed_denial.disposition is ProviderProfileDisposition.DENY
    assert any("kill switch" in reason for reason in killed_denial.reasons)
    for decision in (default_denial, killed_denial):
        assert not decision.provider_call_executed
        assert not decision.provider_execution_authority
        assert not decision.root_context_adoption_authority
        assert not decision.task_state_authority
        assert not decision.completion_authority
        assert not decision.user_facing_voice_authority
        assert not decision.promotion_authority


@pytest.mark.parametrize(
    ("compatibility", "policy_overrides", "reason"),
    [
        (_compatibility(backend_id="other-backend"), {}, "backend"),
        (_compatibility(passing=False), {}, "fingerprint"),
        (
            _compatibility(),
            {"approved_compatibility_fingerprint": "d" * 64},
            "policy compatibility",
        ),
    ],
)
def test_registry_denies_stale_or_mismatched_compatibility(
    compatibility: ModelCompatibilityReport,
    policy_overrides: dict[str, object],
    reason: str,
) -> None:
    approved_compatibility = _compatibility()
    profile = _profile(approved_compatibility)
    selection = ProviderProfileRegistry((profile,)).select(
        request=_request(),
        policy=_active_policy(profile, **policy_overrides),
        compatibility=compatibility,
        current_resource_budget=profile.resource_budget,
    )

    assert selection.disposition is ProviderProfileDisposition.DENY
    assert any(reason in item for item in selection.reasons)


@pytest.mark.parametrize(
    ("candidate_request", "resource_budget", "policy_overrides", "reason"),
    [
        (_request(), _resource_budget(cpu_threads=7), {}, "resource budget"),
        (
            _request(worker_role=ParallelCognitionRole.INDEPENDENT_REVIEWER),
            _resource_budget(),
            {},
            "role",
        ),
        (_request(max_tokens=257), _resource_budget(), {}, "capacity"),
        (_request(), _resource_budget(), {"max_total_workers": 2}, "total-worker"),
    ],
)
def test_registry_denies_assignment_resource_or_policy_expansion(
    candidate_request: ProviderProfileRequest,
    resource_budget: NeuralResourceBudget,
    policy_overrides: dict[str, object],
    reason: str,
) -> None:
    compatibility = _compatibility()
    profile = _profile(compatibility)
    selection = ProviderProfileRegistry((profile,)).select(
        request=candidate_request,
        policy=_active_policy(profile, **policy_overrides),
        compatibility=compatibility,
        current_resource_budget=resource_budget,
    )

    assert selection.disposition is ProviderProfileDisposition.DENY
    assert any(reason in item for item in selection.reasons)


def test_exact_profile_is_only_shadow_eligible_and_grants_no_authority() -> None:
    compatibility = _compatibility()
    profile = _profile(compatibility)
    selection = ProviderProfileRegistry((profile,)).select(
        request=_request(),
        policy=_active_policy(profile),
        compatibility=compatibility,
        current_resource_budget=profile.resource_budget,
    )

    assert selection.disposition is ProviderProfileDisposition.SHADOW_ELIGIBLE
    assert selection.profile_id == profile.profile_id
    assert selection.backend_id == profile.backend_id
    assert not selection.provider_call_executed
    assert not selection.provider_execution_authority
    assert not selection.root_context_adoption_authority
    assert not selection.task_state_authority
    assert not selection.completion_authority
    assert not selection.user_facing_voice_authority
    assert not selection.promotion_authority


@pytest.mark.parametrize("stage", [ModelRolloutStage.CANARY, ModelRolloutStage.ACTIVE])
def test_s5a_policy_rejects_authoritative_rollout_stages(stage: ModelRolloutStage) -> None:
    with pytest.raises(ValidationError, match="CANARY or ACTIVE"):
        S5ProviderRoutingPolicy(stage=stage)
