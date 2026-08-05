"""Deterministic backend for acceptance tests without model access."""

from __future__ import annotations

from collections import deque

from pydantic import Field

from luna.contracts.base import LunaContractModel
from luna.modeling.contracts import (
    ModelFinishReason,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    ModelUsage,
)


class ScriptedModelOutput(LunaContractModel):
    text: str = Field(default="", max_length=200000)
    tool_calls: tuple[ModelToolCall, ...] = ()
    finish_reason: ModelFinishReason = ModelFinishReason.STOP
    usage: ModelUsage = Field(default_factory=ModelUsage)


class ScriptedTurn(LunaContractModel):
    expected_request_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    output: ScriptedModelOutput


class ScriptedTestBackend:
    """FIFO scripted backend with optional exact request matching."""

    def __init__(self, turns: tuple[ScriptedTurn, ...], backend_id: str = "scripted-test") -> None:
        self._turns = deque(turns)
        self._backend_id = backend_id
        self._call_count = 0

    @property
    def backend_id(self) -> str:
        return self._backend_id

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def remaining_turns(self) -> int:
        return len(self._turns)

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not self._turns:
            raise RuntimeError("scripted backend has no remaining turns")
        turn = self._turns.popleft()
        fingerprint = request.fingerprint()
        if (
            turn.expected_request_fingerprint is not None
            and turn.expected_request_fingerprint != fingerprint
        ):
            raise ValueError("model request did not match scripted fingerprint")
        self._call_count += 1
        return ModelResponse(
            request_id=request.request_id,
            backend_id=self.backend_id,
            text=turn.output.text,
            tool_calls=turn.output.tool_calls,
            finish_reason=turn.output.finish_reason,
            usage=turn.output.usage,
        )
