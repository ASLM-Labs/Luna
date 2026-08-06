"""Provider-neutral model request and response contracts."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.tools.models import ToolArgumentValue, ToolSpec


class MessageRole(StrEnum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"


class ModelFinishReason(StrEnum):
    STOP = "STOP"
    TOOL_CALLS = "TOOL_CALLS"
    LENGTH = "LENGTH"
    ERROR = "ERROR"


class ModelMessage(LunaContractModel):
    role: MessageRole
    content: str = Field(min_length=1, max_length=200000)
    name: str | None = Field(default=None, max_length=120)


class ModelToolCall(LunaContractModel):
    """Untrusted model proposal; ToolDispatcher still owns authorization."""

    call_id: str = Field(min_length=1, max_length=300)
    tool_name: str = Field(min_length=1, max_length=120)
    arguments: dict[str, ToolArgumentValue] = Field(default_factory=dict)


class ModelUsage(LunaContractModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ModelRequest(LunaContractModel):
    request_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    trace_id: UUID
    messages: tuple[ModelMessage, ...] = Field(min_length=1)
    available_tools: tuple[ToolSpec, ...] = ()
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=2048, ge=1, le=32768)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_tools(self) -> ModelRequest:
        names = tuple(spec.name for spec in self.available_tools)
        if len(names) != len(set(names)):
            raise ValueError("available model tools must be unique")
        return self

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"request_id", "created_at"})
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()


class ModelResponse(LunaContractModel):
    response_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    backend_id: str = Field(min_length=1, max_length=300)
    text: str = Field(default="", max_length=200000)
    tool_calls: tuple[ModelToolCall, ...] = ()
    finish_reason: ModelFinishReason
    usage: ModelUsage = Field(default_factory=ModelUsage)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_response(self) -> ModelResponse:
        if (
            not self.text
            and not self.tool_calls
            and self.finish_reason is not ModelFinishReason.ERROR
        ):
            raise ValueError("model response must contain text, tool calls, or an error finish")
        if self.finish_reason is ModelFinishReason.TOOL_CALLS and not self.tool_calls:
            raise ValueError("TOOL_CALLS finish requires at least one tool call")
        call_ids = tuple(call.call_id for call in self.tool_calls)
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("model tool call IDs must be unique")
        return self
