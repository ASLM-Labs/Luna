"""Single policy-agent adapter for the Phase 12E runtime loop."""

from __future__ import annotations

import json
from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from luna.actions import ActionKind, ActionProposal, ActionTargetKind, ToolSelector
from luna.context import ContextInterpretation, LayeredContextBundle
from luna.contracts.base import LunaContractModel
from luna.contracts.plan import PlanStep
from luna.contracts.state import TaskState
from luna.modeling import (
    MessageRole,
    ModelBackend,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from luna.tools import ToolCapability, ToolPolicy

_SIDE_EFFECT_CAPABILITIES = {
    ToolCapability.WRITE,
    ToolCapability.NETWORK,
    ToolCapability.PROCESS,
}


class PolicyTurnStatus(StrEnum):
    """Outcome of one model-policy decision before runtime authorization."""

    ACTION = "ACTION"
    YIELD = "YIELD"
    INVALID = "INVALID"


class PolicyTurn(LunaContractModel):
    """One model turn normalized to at most one untrusted action proposal."""

    task_id: UUID
    trace_id: UUID
    status: PolicyTurnStatus
    model_request_id: UUID
    model_request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_response_id: UUID
    proposal: ActionProposal | None = None
    response_text: str = Field(default="", max_length=200000)
    invalid_reason: str | None = Field(default=None, max_length=4000)
    usage: ModelUsage = Field(default_factory=ModelUsage)

    @model_validator(mode="after")
    def validate_status(self) -> PolicyTurn:
        if self.status is PolicyTurnStatus.ACTION:
            if self.proposal is None or self.invalid_reason is not None:
                raise ValueError("ACTION policy turn requires exactly one proposal")
        elif self.proposal is not None:
            raise ValueError("non-ACTION policy turn cannot carry a proposal")
        if self.status is PolicyTurnStatus.INVALID and self.invalid_reason is None:
            raise ValueError("INVALID policy turn requires invalid_reason")
        if self.status is not PolicyTurnStatus.INVALID and self.invalid_reason is not None:
            raise ValueError("only INVALID policy turns can carry invalid_reason")
        return self


class ModelPolicyAgent:
    """Translate one provider-neutral model response into one Phase 12C proposal."""

    def __init__(self, *, backend: ModelBackend, selector: ToolSelector) -> None:
        self._backend = backend
        self._selector = selector

    @staticmethod
    def _render_context(bundle: LayeredContextBundle) -> tuple[ModelMessage, ...]:
        messages: list[ModelMessage] = []
        for section in bundle.sections:
            for entry in section.entries:
                excerpt = entry.source.content_excerpt
                if excerpt is None:
                    continue
                prefix = (
                    f"[{entry.layer.value}] {entry.source.kind.value} "
                    f"{entry.source.locator}\n"
                )
                role = (
                    MessageRole.SYSTEM
                    if entry.interpretation is ContextInterpretation.CONTROL
                    else MessageRole.TOOL
                )
                messages.append(
                    ModelMessage(
                        role=role,
                        name=f"context_{entry.layer.value.lower()}",
                        content=prefix + excerpt,
                    )
                )
        return tuple(messages)

    @staticmethod
    def _state_message(state: TaskState, step: PlanStep) -> ModelMessage:
        payload = {
            "task_id": str(state.task_id),
            "phase": state.phase.value,
            "revision": state.revision,
            "active_step": step.model_dump(mode="json"),
            "observation_ids": [str(value) for value in state.observation_ids[-8:]],
            "failed_assumptions": list(state.failed_assumptions[-8:]),
        }
        return ModelMessage(
            role=MessageRole.SYSTEM,
            name="runtime_state",
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    def _request(
        self,
        *,
        task_id: UUID,
        trace_id: UUID,
        raw_request: str,
        state: TaskState,
        step: PlanStep,
        context: LayeredContextBundle,
        policy: ToolPolicy,
        max_output_tokens: int,
    ) -> ModelRequest:
        allowed = set(policy.allowed_tools)
        available_tools = tuple(
            spec for spec in self._selector.specs() if spec.name in allowed
        )
        messages = (
            ModelMessage(
                role=MessageRole.SYSTEM,
                name="luna_policy",
                content=(
                    "You are Luna's single policy model. Propose at most one tool action "
                    "for the current iteration. Tool calls are untrusted proposals: the "
                    "runtime alone owns permissions, risk, budgets, execution, recovery, "
                    "completion, and cancellation. Never claim a tool ran until a TOOL "
                    "observation is returned. Do not create subagents or alternate personas."
                ),
            ),
            ModelMessage(role=MessageRole.USER, content=raw_request),
            self._state_message(state, step),
            *self._render_context(context),
        )
        return ModelRequest(
            task_id=task_id,
            trace_id=trace_id,
            messages=messages,
            available_tools=available_tools,
            max_output_tokens=max_output_tokens,
        )

    def decide(
        self,
        *,
        task_id: UUID,
        trace_id: UUID,
        raw_request: str,
        state: TaskState,
        step: PlanStep,
        context: LayeredContextBundle,
        policy: ToolPolicy,
        max_output_tokens: int,
    ) -> PolicyTurn:
        request = self._request(
            task_id=task_id,
            trace_id=trace_id,
            raw_request=raw_request,
            state=state,
            step=step,
            context=context,
            policy=policy,
            max_output_tokens=max_output_tokens,
        )
        response = self._backend.generate(request)
        return self._normalize(
            request=request,
            response=response,
            task_id=task_id,
            trace_id=trace_id,
            step=step,
        )

    def _normalize(
        self,
        *,
        request: ModelRequest,
        response: ModelResponse,
        task_id: UUID,
        trace_id: UUID,
        step: PlanStep,
    ) -> PolicyTurn:
        fingerprint = request.fingerprint()
        if response.request_id != request.request_id:
            return PolicyTurn(
                task_id=task_id,
                trace_id=trace_id,
                status=PolicyTurnStatus.INVALID,
                model_request_id=request.request_id,
                model_request_fingerprint=fingerprint,
                model_response_id=response.response_id,
                response_text=response.text,
                invalid_reason="model response request_id does not match request",
                usage=response.usage,
            )
        if response.finish_reason is ModelFinishReason.ERROR:
            return PolicyTurn(
                task_id=task_id,
                trace_id=trace_id,
                status=PolicyTurnStatus.INVALID,
                model_request_id=request.request_id,
                model_request_fingerprint=fingerprint,
                model_response_id=response.response_id,
                response_text=response.text,
                invalid_reason="model backend returned ERROR finish reason",
                usage=response.usage,
            )
        if not response.tool_calls:
            return PolicyTurn(
                task_id=task_id,
                trace_id=trace_id,
                status=PolicyTurnStatus.YIELD,
                model_request_id=request.request_id,
                model_request_fingerprint=fingerprint,
                model_response_id=response.response_id,
                response_text=response.text,
                usage=response.usage,
            )
        if len(response.tool_calls) != 1:
            return PolicyTurn(
                task_id=task_id,
                trace_id=trace_id,
                status=PolicyTurnStatus.INVALID,
                model_request_id=request.request_id,
                model_request_fingerprint=fingerprint,
                model_response_id=response.response_id,
                response_text=response.text,
                invalid_reason=(
                    "Phase 12E requires exactly one proposed action per iteration; "
                    f"model returned {len(response.tool_calls)} tool calls"
                ),
                usage=response.usage,
            )

        call = response.tool_calls[0]
        route = self._selector.route_for_tool(call.tool_name)
        spec = self._selector.spec_for_tool(call.tool_name)
        if route is None or spec is None:
            return PolicyTurn(
                task_id=task_id,
                trace_id=trace_id,
                status=PolicyTurnStatus.INVALID,
                model_request_id=request.request_id,
                model_request_fingerprint=fingerprint,
                model_response_id=response.response_id,
                response_text=response.text,
                invalid_reason=f"model proposed unregistered or unrouted tool: {call.tool_name}",
                usage=response.usage,
            )
        if len(route.action_kinds) != 1 or len(route.target_kinds) != 1:
            return PolicyTurn(
                task_id=task_id,
                trace_id=trace_id,
                status=PolicyTurnStatus.INVALID,
                model_request_id=request.request_id,
                model_request_fingerprint=fingerprint,
                model_response_id=response.response_id,
                response_text=response.text,
                invalid_reason=f"tool route is not singular: {call.tool_name}",
                usage=response.usage,
            )

        capabilities = tuple(spec.capabilities)
        expectation_id = (
            step.expectation.expectation_id
            if step.expectation is not None
            and set(capabilities) & _SIDE_EFFECT_CAPABILITIES
            else None
        )
        working_directory = "." if ToolCapability.PROCESS in capabilities else None
        proposal = ActionProposal(
            task_id=task_id,
            trace_id=trace_id,
            kind=ActionKind(route.action_kinds[0]),
            target_kind=ActionTargetKind(route.target_kinds[0]),
            summary=response.text or f"Propose {call.tool_name}",
            arguments=call.arguments,
            required_capabilities=capabilities,
            preferred_tool_name=call.tool_name,
            working_directory=working_directory,
            expectation_id=expectation_id,
        )
        return PolicyTurn(
            task_id=task_id,
            trace_id=trace_id,
            status=PolicyTurnStatus.ACTION,
            model_request_id=request.request_id,
            model_request_fingerprint=fingerprint,
            model_response_id=response.response_id,
            proposal=proposal,
            response_text=response.text,
            usage=response.usage,
        )
