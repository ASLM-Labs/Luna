from __future__ import annotations

from uuid import uuid4

import pytest

from luna.modeling import (
    MessageRole,
    ModelBackendError,
    ModelBackendErrorCode,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
)
from luna.modeling.native import NativeModelBackend
from luna.neural import (
    LunaNeuralRuntime,
    NeuralFinishReason,
    NeuralGenerationResult,
    NeuralResourceBudget,
    NeuralResourcePolicy,
    NeuralResourceProfile,
    NeuralToolCall,
    NeuralUsage,
    NeuralWorkerState,
)


class ResultWorker:
    def __init__(self, *, tool_call: bool = False, mismatched: bool = False) -> None:
        self._state = NeuralWorkerState.STOPPED
        self._tool_call = tool_call
        self._mismatched = mismatched

    @property
    def worker_id(self) -> str:
        return "result-worker"

    @property
    def state(self) -> NeuralWorkerState:
        return self._state

    def start(self, *, budget: NeuralResourceBudget) -> None:
        assert budget.max_vram_mib == 4096
        self._state = NeuralWorkerState.READY

    def generate(self, request: ModelRequest) -> NeuralGenerationResult:
        request_id = uuid4() if self._mismatched else request.request_id
        if self._tool_call:
            return NeuralGenerationResult(
                request_id=request_id,
                tool_calls=(
                    NeuralToolCall(
                        call_id="call-native-1",
                        tool_name="compat.echo",
                        arguments={"message": "LUNA_TOOL_OK"},
                    ),
                ),
                finish_reason=NeuralFinishReason.TOOL_CALLS,
                usage=NeuralUsage(input_tokens=12, output_tokens=4),
            )
        return NeuralGenerationResult(
            request_id=request_id,
            text="native-ok",
            finish_reason=NeuralFinishReason.STOP,
            usage=NeuralUsage(input_tokens=5, output_tokens=2),
        )

    def stop(self) -> None:
        self._state = NeuralWorkerState.STOPPED


def _budget(*, inference_allowed: bool = True) -> NeuralResourceBudget:
    return NeuralResourceBudget(
        max_vram_mib=4096,
        max_gpu_utilization_percent=50,
        cpu_threads=4,
        max_system_ram_mib=8192,
        max_kv_cache_mib=1024,
        max_context_tokens=4096,
        batch_size=128,
        max_parallel_generations=1 if inference_allowed else 0,
        inference_allowed=inference_allowed,
        model_resident=True,
        background_inference=False,
    )


def _backend(worker: ResultWorker, *, inference_allowed: bool = True) -> NativeModelBackend:
    policy = NeuralResourcePolicy(
        profiles={NeuralResourceProfile.BALANCED: _budget(inference_allowed=inference_allowed)},
        active_profile=NeuralResourceProfile.BALANCED,
    )
    return NativeModelBackend(
        runtime=LunaNeuralRuntime(worker=worker, resource_policy=policy),
    )


def _request() -> ModelRequest:
    return ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="hello native"),),
        max_output_tokens=32,
    )


def test_native_backend_preserves_model_response_contract() -> None:
    backend = _backend(ResultWorker())
    request = _request()

    response = backend.generate(request)

    assert backend.backend_id == "luna-native"
    assert response.request_id == request.request_id
    assert response.backend_id == "luna-native"
    assert response.text == "native-ok"
    assert response.finish_reason is ModelFinishReason.STOP
    assert response.usage.input_tokens == 5
    assert response.usage.output_tokens == 2


def test_native_backend_normalizes_tool_call_without_execution_authority() -> None:
    backend = _backend(ResultWorker(tool_call=True))
    response = backend.generate(_request())

    assert response.finish_reason is ModelFinishReason.TOOL_CALLS
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.call_id == "call-native-1"
    assert call.tool_name == "compat.echo"
    assert call.arguments == {"message": "LUNA_TOOL_OK"}


def test_resource_denial_maps_to_provider_neutral_unavailable_error() -> None:
    backend = _backend(ResultWorker(), inference_allowed=False)

    with pytest.raises(ModelBackendError) as exc_info:
        backend.generate(_request())

    assert exc_info.value.code is ModelBackendErrorCode.UNAVAILABLE
    assert exc_info.value.retryable is True


def test_worker_protocol_mismatch_maps_to_protocol_error() -> None:
    backend = _backend(ResultWorker(mismatched=True))

    with pytest.raises(ModelBackendError) as exc_info:
        backend.generate(_request())

    assert exc_info.value.code is ModelBackendErrorCode.PROTOCOL_ERROR
    assert exc_info.value.retryable is False
