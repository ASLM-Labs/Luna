"""ModelBackend adapter for the Luna-owned neural runtime."""

from __future__ import annotations

from luna.modeling.contracts import (
    ModelFinishReason,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    ModelUsage,
)
from luna.modeling.errors import ModelBackendError, ModelBackendErrorCode
from luna.neural.contracts import NeuralFinishReason, NeuralRuntimeErrorCode
from luna.neural.runtime import LunaNeuralRuntime, NeuralRuntimeError

_FINISH_MAP = {
    NeuralFinishReason.STOP: ModelFinishReason.STOP,
    NeuralFinishReason.TOOL_CALLS: ModelFinishReason.TOOL_CALLS,
    NeuralFinishReason.LENGTH: ModelFinishReason.LENGTH,
    NeuralFinishReason.ERROR: ModelFinishReason.ERROR,
}

_ERROR_MAP = {
    NeuralRuntimeErrorCode.RESOURCE_DENIED: ModelBackendErrorCode.UNAVAILABLE,
    NeuralRuntimeErrorCode.WORKER_UNAVAILABLE: ModelBackendErrorCode.UNAVAILABLE,
    NeuralRuntimeErrorCode.WORKER_FAILURE: ModelBackendErrorCode.UNAVAILABLE,
    NeuralRuntimeErrorCode.WORKER_PROTOCOL: ModelBackendErrorCode.PROTOCOL_ERROR,
}


class NativeModelBackend:
    """Expose Luna Neural Runtime through the existing provider-neutral model contract."""

    def __init__(
        self,
        *,
        runtime: LunaNeuralRuntime,
        backend_id: str = "luna-native",
    ) -> None:
        if not backend_id.strip():
            raise ValueError("backend_id must not be blank")
        self._runtime = runtime
        self._backend_id = backend_id.strip()

    @property
    def backend_id(self) -> str:
        return self._backend_id

    def generate(self, request: ModelRequest) -> ModelResponse:
        try:
            result = self._runtime.generate(request)
        except NeuralRuntimeError as exc:
            raise ModelBackendError(
                code=_ERROR_MAP[exc.code],
                backend_id=self.backend_id,
                safe_reason=exc.safe_reason,
                retryable=exc.retryable,
            ) from exc

        return ModelResponse(
            request_id=request.request_id,
            backend_id=self.backend_id,
            text=result.text,
            tool_calls=tuple(
                ModelToolCall(
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                )
                for call in result.tool_calls
            ),
            finish_reason=_FINISH_MAP[result.finish_reason],
            usage=ModelUsage(
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
            ),
        )
