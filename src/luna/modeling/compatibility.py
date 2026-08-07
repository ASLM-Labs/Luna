"""Real-model compatibility probe contracts for Phase 13."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.modeling.backend import ModelBackend
from luna.modeling.contracts import (
    MessageRole,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
)
from luna.modeling.errors import ModelBackendError
from luna.tools.models import ToolArgumentRule, ToolArgumentType, ToolSpec


class ModelCompatibilityCapability(StrEnum):
    TEXT_RESPONSE = "TEXT_RESPONSE"
    SINGLE_TOOL_CALL = "SINGLE_TOOL_CALL"
    JSON_TOOL_ARGUMENTS = "JSON_TOOL_ARGUMENTS"
    USAGE_ACCOUNTING = "USAGE_ACCOUNTING"


class ModelCompatibilityStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class ModelCompatibilityCaseResult(LunaContractModel):
    case_id: str = Field(min_length=1, max_length=120)
    capability: ModelCompatibilityCapability
    status: ModelCompatibilityStatus
    required: bool
    detail: str = Field(min_length=1, max_length=500)
    backend_error_code: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_error(self) -> ModelCompatibilityCaseResult:
        if self.status is ModelCompatibilityStatus.ERROR and self.backend_error_code is None:
            raise ValueError("ERROR compatibility result requires backend_error_code")
        if (
            self.status is not ModelCompatibilityStatus.ERROR
            and self.backend_error_code is not None
        ):
            raise ValueError("backend_error_code is valid only for ERROR results")
        return self


class ModelCompatibilityReport(LunaContractModel):
    report_id: UUID = Field(default_factory=uuid4)
    backend_id: str = Field(min_length=1, max_length=300)
    results: tuple[ModelCompatibilityCaseResult, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_results(self) -> ModelCompatibilityReport:
        ids = tuple(item.case_id for item in self.results)
        if len(ids) != len(set(ids)):
            raise ValueError("compatibility case IDs must be unique")
        return self

    @property
    def required_passed(self) -> bool:
        return all(
            item.status is ModelCompatibilityStatus.PASS
            for item in self.results
            if item.required
        )

    @property
    def eligible_for_rollout(self) -> bool:
        return self.required_passed

    def fingerprint(self) -> str:
        payload = {
            "backend_id": self.backend_id,
            "results": [
                {
                    "case_id": item.case_id,
                    "capability": item.capability.value,
                    "status": item.status.value,
                    "required": item.required,
                    "detail": item.detail,
                    "backend_error_code": item.backend_error_code,
                }
                for item in self.results
            ],
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode()).hexdigest()


class ModelCompatibilityProbe:
    """Small live probe; it grants no rollout authority."""

    _TOOL_NAME = "compat.echo"
    _TOOL_VALUE = "LUNA_TOOL_OK"

    @staticmethod
    def _base_ids() -> tuple[UUID, UUID]:
        return uuid4(), uuid4()

    def run(self, backend: ModelBackend) -> ModelCompatibilityReport:
        task_id, trace_id = self._base_ids()
        results: list[ModelCompatibilityCaseResult] = []

        text_request = ModelRequest(
            task_id=task_id,
            trace_id=trace_id,
            messages=(
                ModelMessage(
                    role=MessageRole.USER,
                    content="Reply with a short non-empty acknowledgement and do not call a tool.",
                ),
            ),
            temperature=0.0,
            max_output_tokens=64,
        )
        text_response: ModelResponse | None = None
        try:
            text_response = backend.generate(text_request)
            text_ok = (
                text_response.request_id == text_request.request_id
                and bool(text_response.text.strip())
                and not text_response.tool_calls
                and text_response.finish_reason in {
                    ModelFinishReason.STOP,
                    ModelFinishReason.LENGTH,
                }
            )
            results.append(
                ModelCompatibilityCaseResult(
                    case_id="P13-C01-text-response",
                    capability=ModelCompatibilityCapability.TEXT_RESPONSE,
                    status=(
                        ModelCompatibilityStatus.PASS
                        if text_ok
                        else ModelCompatibilityStatus.FAIL
                    ),
                    required=True,
                    detail=(
                        "provider-neutral text response contract satisfied"
                        if text_ok
                        else "text response did not satisfy correlation/content/tool constraints"
                    ),
                )
            )
        except ModelBackendError as exc:
            results.append(
                ModelCompatibilityCaseResult(
                    case_id="P13-C01-text-response",
                    capability=ModelCompatibilityCapability.TEXT_RESPONSE,
                    status=ModelCompatibilityStatus.ERROR,
                    required=True,
                    detail=exc.safe_reason,
                    backend_error_code=exc.code.value,
                )
            )

        tool_spec = ToolSpec(
            name=self._TOOL_NAME,
            description="Compatibility probe echo tool. Do not execute it.",
            argument_schema={
                "message": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                    min_length=1,
                    max_length=64,
                )
            },
        )
        tool_request = ModelRequest(
            task_id=task_id,
            trace_id=trace_id,
            messages=(
                ModelMessage(
                    role=MessageRole.USER,
                    content=(
                        "Call exactly the compat.echo tool once with JSON argument "
                        '{"message":"LUNA_TOOL_OK"}.'
                    ),
                ),
            ),
            available_tools=(tool_spec,),
            temperature=0.0,
            max_output_tokens=128,
        )
        tool_response: ModelResponse | None = None
        try:
            tool_response = backend.generate(tool_request)
            single_call_ok = (
                tool_response.request_id == tool_request.request_id
                and tool_response.finish_reason is ModelFinishReason.TOOL_CALLS
                and len(tool_response.tool_calls) == 1
                and tool_response.tool_calls[0].tool_name == self._TOOL_NAME
            )
            results.append(
                ModelCompatibilityCaseResult(
                    case_id="P13-C02-single-tool-call",
                    capability=ModelCompatibilityCapability.SINGLE_TOOL_CALL,
                    status=(
                        ModelCompatibilityStatus.PASS
                        if single_call_ok
                        else ModelCompatibilityStatus.FAIL
                    ),
                    required=True,
                    detail=(
                        "single provider tool call contract satisfied"
                        if single_call_ok
                        else "model did not return exactly one correlated compat.echo tool call"
                    ),
                )
            )

            args_ok = (
                single_call_ok
                and tool_response.tool_calls[0].arguments
                == {"message": self._TOOL_VALUE}
            )
            results.append(
                ModelCompatibilityCaseResult(
                    case_id="P13-C03-json-tool-arguments",
                    capability=ModelCompatibilityCapability.JSON_TOOL_ARGUMENTS,
                    status=(
                        ModelCompatibilityStatus.PASS
                        if args_ok
                        else ModelCompatibilityStatus.FAIL
                    ),
                    required=True,
                    detail=(
                        "JSON tool arguments round-tripped without coercion"
                        if args_ok
                        else "tool arguments were missing, malformed, or changed"
                    ),
                )
            )
        except ModelBackendError as exc:
            for case_id, capability in (
                ("P13-C02-single-tool-call", ModelCompatibilityCapability.SINGLE_TOOL_CALL),
                ("P13-C03-json-tool-arguments", ModelCompatibilityCapability.JSON_TOOL_ARGUMENTS),
            ):
                results.append(
                    ModelCompatibilityCaseResult(
                        case_id=case_id,
                        capability=capability,
                        status=ModelCompatibilityStatus.ERROR,
                        required=True,
                        detail=exc.safe_reason,
                        backend_error_code=exc.code.value,
                    )
                )

        usage_seen = False
        for response in (text_response, tool_response):
            if response is not None and (
                response.usage.input_tokens > 0 or response.usage.output_tokens > 0
            ):
                usage_seen = True
                break
        results.append(
            ModelCompatibilityCaseResult(
                case_id="P13-C04-usage-accounting",
                capability=ModelCompatibilityCapability.USAGE_ACCOUNTING,
                status=(
                    ModelCompatibilityStatus.PASS
                    if usage_seen
                    else ModelCompatibilityStatus.FAIL
                ),
                required=False,
                detail=(
                    "provider reported token usage"
                    if usage_seen
                    else "provider omitted token usage; optional capability unavailable"
                ),
            )
        )

        return ModelCompatibilityReport(
            backend_id=backend.backend_id,
            results=tuple(results),
        )
