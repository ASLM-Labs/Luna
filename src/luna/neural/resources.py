"""Luna-owned neural resource policy and non-escalation rules."""

from __future__ import annotations

from collections.abc import Mapping

from luna.neural.contracts import NeuralResourceBudget, NeuralResourceProfile


class NeuralResourcePolicy:
    """Own profile selection while keeping GPU/VRAM authority outside the worker."""

    def __init__(
        self,
        *,
        profiles: Mapping[NeuralResourceProfile, NeuralResourceBudget],
        active_profile: NeuralResourceProfile,
    ) -> None:
        if not profiles:
            raise ValueError("at least one neural resource profile is required")
        self._profiles = {key: value.model_copy(deep=True) for key, value in profiles.items()}
        if active_profile not in self._profiles:
            raise ValueError("active neural resource profile is not configured")
        self._active_profile = active_profile

    @property
    def active_profile(self) -> NeuralResourceProfile:
        return self._active_profile

    @property
    def current_budget(self) -> NeuralResourceBudget:
        """Return a copy so downstream workers cannot mutate policy-owned state."""
        return self._profiles[self._active_profile].model_copy(deep=True)

    def budget_for(self, profile: NeuralResourceProfile) -> NeuralResourceBudget:
        if profile not in self._profiles:
            raise KeyError(f"neural resource profile is not configured: {profile.value}")
        return self._profiles[profile].model_copy(deep=True)

    def transition(
        self,
        profile: NeuralResourceProfile,
        *,
        user_authorized: bool,
    ) -> NeuralResourceBudget:
        """Apply a profile change; automatic changes may reduce but never enlarge authority."""
        current = self.current_budget
        target = self.budget_for(profile)
        if not user_authorized and _expands_resource_authority(current=current, target=target):
            raise PermissionError("automatic neural resource escalation is forbidden")
        self._active_profile = profile
        return target.model_copy(deep=True)


def _expands_resource_authority(
    *,
    current: NeuralResourceBudget,
    target: NeuralResourceBudget,
) -> bool:
    numeric_pairs = (
        (current.max_vram_mib, target.max_vram_mib),
        (current.max_gpu_utilization_percent, target.max_gpu_utilization_percent),
        (current.cpu_threads, target.cpu_threads),
        (current.max_system_ram_mib, target.max_system_ram_mib),
        (current.max_kv_cache_mib, target.max_kv_cache_mib),
        (current.max_context_tokens, target.max_context_tokens),
        (current.batch_size, target.batch_size),
        (current.max_parallel_generations, target.max_parallel_generations),
        (current.idle_unload_seconds, target.idle_unload_seconds),
        (current.request_priority, target.request_priority),
    )
    if any(target_value > current_value for current_value, target_value in numeric_pairs):
        return True
    boolean_pairs = (
        (current.inference_allowed, target.inference_allowed),
        (current.model_resident, target.model_resident),
        (current.background_inference, target.background_inference),
    )
    return any(not current_value and target_value for current_value, target_value in boolean_pairs)
