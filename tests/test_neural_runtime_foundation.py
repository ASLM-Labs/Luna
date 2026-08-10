from __future__ import annotations

from uuid import uuid4

import pytest

from luna.modeling import MessageRole, ModelMessage, ModelRequest
from luna.neural import (
    LunaNeuralRuntime,
    NeuralFinishReason,
    NeuralGenerationResult,
    NeuralResourceBudget,
    NeuralResourcePolicy,
    NeuralResourceProfile,
    NeuralRuntimeError,
    NeuralRuntimeErrorCode,
    NeuralUsage,
    NeuralWorkerState,
)


class FakeWorker:
    def __init__(self) -> None:
        self._state = NeuralWorkerState.STOPPED
        self.starts = 0
        self.stops = 0
        self.budgets: list[NeuralResourceBudget] = []
        self.request_id_override = None

    @property
    def worker_id(self) -> str:
        return "fake-neural-worker"

    @property
    def state(self) -> NeuralWorkerState:
        return self._state

    def start(self, *, budget: NeuralResourceBudget) -> None:
        self.starts += 1
        self.budgets.append(budget.model_copy(deep=True))
        self._state = NeuralWorkerState.READY

    def generate(self, request: ModelRequest) -> NeuralGenerationResult:
        return NeuralGenerationResult(
            request_id=self.request_id_override or request.request_id,
            text="ok",
            finish_reason=NeuralFinishReason.STOP,
            usage=NeuralUsage(input_tokens=7, output_tokens=2),
        )

    def stop(self) -> None:
        self.stops += 1
        self._state = NeuralWorkerState.STOPPED


def _budget(
    *,
    vram: int,
    gpu: int,
    threads: int,
    resident: bool,
    inference: bool = True,
) -> NeuralResourceBudget:
    return NeuralResourceBudget(
        max_vram_mib=vram,
        max_gpu_utilization_percent=gpu,
        cpu_threads=threads,
        max_system_ram_mib=8192,
        max_kv_cache_mib=1024,
        max_context_tokens=4096,
        batch_size=256,
        max_parallel_generations=1 if inference else 0,
        idle_unload_seconds=60 if resident else 0,
        request_priority=50,
        inference_allowed=inference,
        model_resident=resident,
        background_inference=False,
    )


def _profiles() -> dict[NeuralResourceProfile, NeuralResourceBudget]:
    return {
        NeuralResourceProfile.USER_PRIORITY: _budget(
            vram=2048,
            gpu=10,
            threads=2,
            resident=False,
            inference=False,
        ),
        NeuralResourceProfile.BALANCED: _budget(
            vram=8192,
            gpu=65,
            threads=8,
            resident=True,
        ),
        NeuralResourceProfile.PERFORMANCE: _budget(
            vram=11000,
            gpu=90,
            threads=12,
            resident=True,
        ),
    }


def _request() -> ModelRequest:
    return ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="hello"),),
        max_output_tokens=32,
    )


def test_automatic_resource_escalation_is_blocked_but_user_escalation_is_allowed() -> None:
    policy = NeuralResourcePolicy(
        profiles=_profiles(),
        active_profile=NeuralResourceProfile.BALANCED,
    )

    with pytest.raises(PermissionError, match="escalation"):
        policy.transition(
            NeuralResourceProfile.PERFORMANCE,
            user_authorized=False,
        )

    policy.transition(
        NeuralResourceProfile.PERFORMANCE,
        user_authorized=True,
    )
    assert policy.active_profile is NeuralResourceProfile.PERFORMANCE


def test_automatic_resource_reduction_is_allowed() -> None:
    policy = NeuralResourcePolicy(
        profiles=_profiles(),
        active_profile=NeuralResourceProfile.BALANCED,
    )

    policy.transition(
        NeuralResourceProfile.USER_PRIORITY,
        user_authorized=False,
    )
    assert policy.active_profile is NeuralResourceProfile.USER_PRIORITY
    assert policy.current_budget.inference_allowed is False


def test_resource_policy_returns_copies_not_mutable_authority() -> None:
    policy = NeuralResourcePolicy(
        profiles=_profiles(),
        active_profile=NeuralResourceProfile.BALANCED,
    )
    observed = policy.current_budget
    observed.max_vram_mib = 1

    assert policy.current_budget.max_vram_mib == 8192


def test_runtime_lazy_starts_and_keeps_resident_worker() -> None:
    worker = FakeWorker()
    policy = NeuralResourcePolicy(
        profiles=_profiles(),
        active_profile=NeuralResourceProfile.BALANCED,
    )
    runtime = LunaNeuralRuntime(worker=worker, resource_policy=policy)

    first = runtime.generate(_request())
    second = runtime.generate(_request())

    assert first.text == "ok"
    assert second.text == "ok"
    assert worker.starts == 1
    assert worker.stops == 0
    assert worker.state is NeuralWorkerState.READY
    runtime.shutdown()
    assert worker.stops == 1


def test_ephemeral_profile_releases_worker_after_request() -> None:
    profiles = _profiles()
    profiles[NeuralResourceProfile.DESKTOP] = _budget(
        vram=6144,
        gpu=40,
        threads=4,
        resident=False,
    )
    worker = FakeWorker()
    runtime = LunaNeuralRuntime(
        worker=worker,
        resource_policy=NeuralResourcePolicy(
            profiles=profiles,
            active_profile=NeuralResourceProfile.DESKTOP,
        ),
    )

    runtime.generate(_request())

    assert worker.starts == 1
    assert worker.stops == 1
    assert worker.state is NeuralWorkerState.STOPPED


def test_inference_denied_profile_does_not_start_worker() -> None:
    worker = FakeWorker()
    runtime = LunaNeuralRuntime(
        worker=worker,
        resource_policy=NeuralResourcePolicy(
            profiles=_profiles(),
            active_profile=NeuralResourceProfile.USER_PRIORITY,
        ),
    )

    with pytest.raises(NeuralRuntimeError) as exc_info:
        runtime.generate(_request())

    assert exc_info.value.code is NeuralRuntimeErrorCode.RESOURCE_DENIED
    assert worker.starts == 0


def test_request_id_mismatch_is_protocol_failure() -> None:
    worker = FakeWorker()
    worker.request_id_override = uuid4()
    runtime = LunaNeuralRuntime(
        worker=worker,
        resource_policy=NeuralResourcePolicy(
            profiles=_profiles(),
            active_profile=NeuralResourceProfile.BALANCED,
        ),
    )

    with pytest.raises(NeuralRuntimeError) as exc_info:
        runtime.generate(_request())

    assert exc_info.value.code is NeuralRuntimeErrorCode.WORKER_PROTOCOL


def test_runtime_profile_reduction_releases_resident_worker() -> None:
    worker = FakeWorker()
    runtime = LunaNeuralRuntime(
        worker=worker,
        resource_policy=NeuralResourcePolicy(
            profiles=_profiles(),
            active_profile=NeuralResourceProfile.BALANCED,
        ),
    )
    runtime.generate(_request())
    assert worker.state is NeuralWorkerState.READY

    runtime.transition_profile(
        NeuralResourceProfile.USER_PRIORITY,
        user_authorized=False,
    )

    assert runtime.active_profile is NeuralResourceProfile.USER_PRIORITY
    assert worker.state is NeuralWorkerState.STOPPED
    assert worker.stops == 1
