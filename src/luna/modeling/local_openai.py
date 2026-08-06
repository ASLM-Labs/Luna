"""Loopback-only adapter for local OpenAI-compatible model servers."""

from __future__ import annotations

import json
from typing import Protocol, cast
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from luna.modeling.contracts import (
    MessageRole,
    ModelFinishReason,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    ModelUsage,
)
from luna.tools.models import ToolArgumentRule, ToolArgumentType, ToolArgumentValue, ToolSpec


class JsonTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> dict[str, object]:
        """POST JSON and return one decoded object."""
        ...


class UrllibJsonTransport:
    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> dict[str, object]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(max_response_bytes + 1)
        if len(raw) > max_response_bytes:
            raise ValueError("local model response exceeded byte limit")
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("local model response must be a JSON object")
        return cast(dict[str, object], decoded)


def _validate_loopback_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("local model endpoint must use http or https")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("local model adapter accepts loopback endpoints only")
    if not parsed.path:
        raise ValueError("local model endpoint requires an API path")
    return endpoint.rstrip("/")


def _json_schema(rule: ToolArgumentRule) -> dict[str, object]:
    mapping = {
        ToolArgumentType.STRING: "string",
        ToolArgumentType.INTEGER: "integer",
        ToolArgumentType.NUMBER: "number",
        ToolArgumentType.BOOLEAN: "boolean",
        ToolArgumentType.STRING_LIST: "array",
    }
    schema: dict[str, object] = {"type": mapping[rule.argument_type]}
    if rule.description:
        schema["description"] = rule.description
    if rule.argument_type is ToolArgumentType.STRING_LIST:
        schema["items"] = {"type": "string"}
    if rule.min_length is not None:
        key = "minItems" if rule.argument_type is ToolArgumentType.STRING_LIST else "minLength"
        schema[key] = rule.min_length
    if rule.max_length is not None:
        key = "maxItems" if rule.argument_type is ToolArgumentType.STRING_LIST else "maxLength"
        schema[key] = rule.max_length
    if rule.minimum is not None:
        schema["minimum"] = rule.minimum
    if rule.maximum is not None:
        schema["maximum"] = rule.maximum
    if rule.choices:
        schema["enum"] = list(rule.choices)
    return schema


def _tool_payload(spec: ToolSpec) -> dict[str, object]:
    required = [name for name, rule in spec.argument_schema.items() if rule.required]
    parameters: dict[str, object] = {
        "type": "object",
        "properties": {
            name: _json_schema(rule)
            for name, rule in spec.argument_schema.items()
        },
        "additionalProperties": False,
    }
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": parameters,
        },
    }


def _role(role: MessageRole) -> str:
    return role.value.casefold()


def _as_dict(value: object, description: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(description)
    return cast(dict[str, object], value)


def _as_list(value: object, description: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(description)
    return cast(list[object], value)


def _parse_arguments(value: object) -> dict[str, ToolArgumentValue]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        raise ValueError("tool call arguments must be a JSON object")
    result: dict[str, ToolArgumentValue] = {}
    for key, item in parsed.items():
        if not isinstance(key, str):
            raise ValueError("tool argument names must be strings")
        if item is None or isinstance(item, (str, int, float, bool)):
            result[key] = item
        elif isinstance(item, list) and all(isinstance(part, str) for part in item):
            result[key] = cast(list[str], item)
        else:
            raise ValueError("unsupported tool argument value")
    return result


class LocalOpenAICompatibleBackend:
    """Local adapter; it never treats model text as runtime evidence."""

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        transport: JsonTransport | None = None,
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        if not model.strip():
            raise ValueError("local model name must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes < 1024:
            raise ValueError("max_response_bytes is too small")
        self._endpoint = _validate_loopback_endpoint(endpoint)
        self._model = model.strip()
        self._transport = transport or UrllibJsonTransport()
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    @property
    def backend_id(self) -> str:
        return f"local-openai-compatible:{self._model}"

    def generate(self, request: ModelRequest) -> ModelResponse:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": _role(message.role),
                    "content": message.content,
                    **({"name": message.name} if message.name is not None else {}),
                }
                for message in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if request.available_tools:
            payload["tools"] = [_tool_payload(spec) for spec in request.available_tools]
            payload["tool_choice"] = "auto"

        raw = self._transport.post_json(
            url=self._endpoint,
            payload=payload,
            timeout_seconds=self._timeout_seconds,
            max_response_bytes=self._max_response_bytes,
        )
        choices = _as_list(raw.get("choices"), "local model response requires choices")
        if not choices:
            raise ValueError("local model response returned no choices")
        choice = _as_dict(choices[0], "local model choice must be an object")
        message = _as_dict(choice.get("message"), "local model choice requires message")
        text_value = message.get("content")
        text = text_value if isinstance(text_value, str) else ""

        tool_calls: list[ModelToolCall] = []
        raw_calls = message.get("tool_calls", [])
        for raw_call in _as_list(raw_calls, "tool_calls must be a list"):
            call = _as_dict(raw_call, "tool call must be an object")
            function = _as_dict(call.get("function"), "tool call requires function")
            call_id = call.get("id")
            name = function.get("name")
            if not isinstance(call_id, str) or not isinstance(name, str):
                raise ValueError("tool call id and name must be strings")
            tool_calls.append(
                ModelToolCall(
                    call_id=call_id,
                    tool_name=name,
                    arguments=_parse_arguments(function.get("arguments", {})),
                )
            )

        raw_finish = choice.get("finish_reason")
        finish_map = {
            "stop": ModelFinishReason.STOP,
            "tool_calls": ModelFinishReason.TOOL_CALLS,
            "length": ModelFinishReason.LENGTH,
        }
        finish_reason = (
            finish_map.get(raw_finish, ModelFinishReason.ERROR)
            if isinstance(raw_finish, str)
            else ModelFinishReason.ERROR
        )

        usage_raw = raw.get("usage", {})
        usage_dict = _as_dict(usage_raw, "usage must be an object")
        input_tokens = usage_dict.get("prompt_tokens", 0)
        output_tokens = usage_dict.get("completion_tokens", 0)
        usage = ModelUsage(
            input_tokens=input_tokens if isinstance(input_tokens, int) else 0,
            output_tokens=output_tokens if isinstance(output_tokens, int) else 0,
        )
        return ModelResponse(
            request_id=request.request_id,
            backend_id=self.backend_id,
            text=text,
            tool_calls=tuple(tool_calls),
            finish_reason=finish_reason,
            usage=usage,
        )
