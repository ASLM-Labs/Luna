"""Provider-neutral contracts for Luna-owned neural runtime control."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from luna.contracts.base import LunaContractModel
from luna.tools.models import ToolArgumentValue


class NeuralResourceProfile(StrEnum):
    """Named resource-policy profiles selected by Luna or the user."""

    IDLE = "IDLE"
    DESKTOP = "DESKTOP"
    BALANCED = "BALANCED"
    PERFORMANCE = "PERFORMANCE"
    USER_PRIORITY = "USER_PRIORITY"
    DEDICATED = "DEDICATED"


class NeuralWorkerState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    READY = "READY"
    FAILED = "FAILED"


class NeuralFinishReason(StrEnum):
    STOP = "STOP"
    TOOL_CALLS = "TOOL_CALLS"
    LENGTH = "LENGTH"
    ERROR = "ERROR"


class NeuralRuntimeErrorCode(StrEnum):
    RESOURCE_DENIED = "RESOURCE_DENIED"
    WORKER_UNAVAILABLE = "WORKER_UNAVAILABLE"
    WORKER_PROTOCOL = "WORKER_PROTOCOL"
    WORKER_FAILURE = "WORKER_FAILURE"


class NeuralResourceBudget(LunaContractModel):
    """Upper bounds owned by Luna; the neural worker cannot enlarge them."""

    max_vram_mib: int = Field(ge=0)
    max_gpu_utilization_percent: int = Field(ge=0, le=100)
    cpu_threads: int = Field(ge=1, le=1024)
    max_system_ram_mib: int = Field(ge=0)
    max_kv_cache_mib: int = Field(ge=0)
    max_context_tokens: int = Field(ge=1, le=1_048_576)
    batch_size: int = Field(ge=1, le=65_536)
    max_parallel_generations: int = Field(ge=0, le=128)
    idle_unload_seconds: int = Field(default=0, ge=0, le=86_400)
    request_priority: int = Field(default=50, ge=0, le=100)
    inference_allowed: bool = True
    model_resident: bool = False
    background_inference: bool = False


class NeuralToolCall(LunaContractModel):
    """Normalized neural proposal; it carries no tool-execution authority."""

    call_id: str = Field(min_length=1, max_length=300)
    tool_name: str = Field(min_length=1, max_length=120)
    arguments: dict[str, ToolArgumentValue] = Field(default_factory=dict)


class NeuralUsage(LunaContractModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class NeuralGenerationResult(LunaContractModel):
    request_id: UUID
    text: str = Field(default="", max_length=200000)
    tool_calls: tuple[NeuralToolCall, ...] = ()
    finish_reason: NeuralFinishReason
    usage: NeuralUsage = Field(default_factory=NeuralUsage)

    @model_validator(mode="after")
    def validate_result(self) -> NeuralGenerationResult:
        if (
            not self.text
            and not self.tool_calls
            and self.finish_reason not in {NeuralFinishReason.ERROR, NeuralFinishReason.LENGTH}
        ):
            raise ValueError(
                "neural result must contain text, tool calls, or an error/incomplete finish"
            )
        if self.finish_reason is NeuralFinishReason.TOOL_CALLS and not self.tool_calls:
            raise ValueError("TOOL_CALLS finish requires at least one neural tool call")
        call_ids = tuple(call.call_id for call in self.tool_calls)
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("neural tool call IDs must be unique")
        return self
