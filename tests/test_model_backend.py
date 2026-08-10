from __future__ import annotations

from uuid import uuid4

import pytest

from luna.modeling import (
    LocalOpenAICompatibleBackend,
    MessageRole,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelToolCall,
    ScriptedModelOutput,
    ScriptedTestBackend,
    ScriptedTurn,
)
from luna.tools import ToolArgumentRule, ToolArgumentType, ToolSpec


class FakeTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.last_payload: dict[str, object] | None = None

    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> dict[str, object]:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout_seconds == 5.0
        assert max_response_bytes == 100_000
        self.last_payload = payload
        return self.response


def make_request() -> ModelRequest:
    return ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="README dosyasını incele"),),
    )


def test_scripted_backend_is_deterministic_and_correlated() -> None:
    request = make_request()
    backend = ScriptedTestBackend(
        turns=(
            ScriptedTurn(
                expected_request_fingerprint=request.fingerprint(),
                output=ScriptedModelOutput(text="tamam"),
            ),
        )
    )

    response = backend.generate(request)

    assert response.request_id == request.request_id
    assert response.backend_id == "scripted-test"
    assert response.text == "tamam"
    assert backend.call_count == 1
    assert backend.remaining_turns == 0


def test_scripted_backend_rejects_unexpected_request() -> None:
    backend = ScriptedTestBackend(
        turns=(
            ScriptedTurn(
                expected_request_fingerprint="0" * 64,
                output=ScriptedModelOutput(text="unused"),
            ),
        )
    )

    with pytest.raises(ValueError, match="fingerprint"):
        backend.generate(make_request())


def test_local_adapter_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        LocalOpenAICompatibleBackend(
            endpoint="https://example.com/v1/chat/completions",
            model="test",
        )


def test_local_adapter_parses_tool_call_and_exports_schema() -> None:
    transport = FakeTransport(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "core.echo",
                                    "arguments": '{"message":"selam"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 4},
        }
    )
    backend = LocalOpenAICompatibleBackend(
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        model="local-test",
        transport=transport,
        timeout_seconds=5.0,
        max_response_bytes=100_000,
    )
    request = ModelRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="selam de"),),
        available_tools=(
            ToolSpec(
                name="core.echo",
                description="Echo",
                argument_schema={
                    "message": ToolArgumentRule(
                        argument_type=ToolArgumentType.STRING,
                        required=True,
                    )
                },
            ),
        ),
    )

    response = backend.generate(request)

    assert response.finish_reason is ModelFinishReason.TOOL_CALLS
    assert response.tool_calls == (
        ModelToolCall(
            call_id="call-1",
            tool_name="core.echo",
            arguments={"message": "selam"},
        ),
    )
    assert response.usage.input_tokens == 11
    assert transport.last_payload is not None
    tools = transport.last_payload["tools"]
    assert isinstance(tools, list)


def test_local_adapter_preserves_empty_length_as_incomplete_response() -> None:
    transport = FakeTransport(
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": None, "tool_calls": []},
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 64},
        }
    )
    backend = LocalOpenAICompatibleBackend(
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        model="local-test",
        transport=transport,
        timeout_seconds=5.0,
        max_response_bytes=100_000,
    )

    response = backend.generate(make_request())

    assert response.finish_reason is ModelFinishReason.LENGTH
    assert response.text == ""
    assert response.tool_calls == ()
    assert response.usage.output_tokens == 64
