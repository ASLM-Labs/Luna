"""Single policy-agent adapter for the Phase 12E runtime loop."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from pydantic import Field, model_validator

from luna.actions import (
    ActionKind,
    ActionProposal,
    ActionTargetKind,
    InformationAwareToolAdvisor,
    ToolSelector,
)
from luna.context import (
    ContextInterpretation,
    ContextLayer,
    ContextSourceKind,
    LayeredContextBundle,
)
from luna.context.layered import LayeredContextEntry
from luna.context.window import (
    ModelWindowProjection,
    ModelWindowProjectionStatus,
    ModelWindowProjector,
    estimate_model_messages_tokens,
    estimate_tool_specs_tokens,
    render_context_entry,
)
from luna.contracts.base import LunaContractModel
from luna.contracts.enums import ObservationStatus
from luna.contracts.observation import Observation
from luna.contracts.plan import PlanStep
from luna.contracts.specification import ConstraintKind
from luna.contracts.state import TaskState
from luna.intent.judgment import IntentConstraintJudge
from luna.intent.resolver import DeterministicIntentResolver
from luna.modeling import (
    MessageRole,
    ModelBackend,
    ModelBackendError,
    ModelBackendErrorCode,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from luna.planning import (
    DecisionCompression,
    DecisionControlAdvisor,
    InformationGainPlan,
    InformationNeedKind,
    LocalJudgmentBuilder,
)
from luna.retrieval import (
    InformationRetrievalStrategist,
    InformationRetrievalStrategy,
    KnowledgeRequestProfile,
    KnowledgeSource,
    KnowledgeUncertainty,
    ObservedRetrievalStrategyLedger,
    RetrievalDecision,
)
from luna.tools import (
    ToolCapability,
    ToolPolicy,
    ToolSpec,
    ToolVisibilityProjection,
)
from luna.verification import VerificationStrategySelector

_SIDE_EFFECT_CAPABILITIES = {
    ToolCapability.WRITE,
    ToolCapability.NETWORK,
    ToolCapability.PROCESS,
}


class PolicyTurnStatus(StrEnum):
    """Outcome of one model-policy decision before runtime authorization."""

    ACTION = "ACTION"
    YIELD = "YIELD"
    INCOMPLETE = "INCOMPLETE"
    INVALID = "INVALID"
    BACKEND_FAILURE = "BACKEND_FAILURE"


class PolicyTurn(LunaContractModel):
    """One model turn normalized to at most one untrusted action proposal."""

    task_id: UUID
    trace_id: UUID
    status: PolicyTurnStatus
    model_request_id: UUID
    model_request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_response_id: UUID | None = None
    proposal: ActionProposal | None = None
    retrieval_strategy_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    retrieval_source: KnowledgeSource | None = None
    response_text: str = Field(default="", max_length=200000)
    invalid_reason: str | None = Field(default=None, max_length=4000)
    backend_error_code: ModelBackendErrorCode | None = None
    backend_error_backend_id: str | None = Field(default=None, max_length=300)
    backend_retryable: bool = False
    backend_retry_after_seconds: float | None = Field(default=None, ge=0.0)
    usage: ModelUsage = Field(default_factory=ModelUsage)

    @model_validator(mode="after")
    def validate_status(self) -> PolicyTurn:
        if self.status is PolicyTurnStatus.ACTION:
            if self.proposal is None or self.invalid_reason is not None:
                raise ValueError("ACTION policy turn requires exactly one proposal")
        elif self.proposal is not None:
            raise ValueError("non-ACTION policy turn cannot carry a proposal")

        retrieval_bound = self.retrieval_strategy_fingerprint is not None
        if retrieval_bound != (self.retrieval_source is not None):
            raise ValueError("retrieval strategy fingerprint and source must be bound together")
        if retrieval_bound and self.status is not PolicyTurnStatus.ACTION:
            raise ValueError("only ACTION turns may carry a retrieval attempt binding")

        if self.status is PolicyTurnStatus.BACKEND_FAILURE:
            if (
                self.invalid_reason is None
                or self.backend_error_code is None
                or self.backend_error_backend_id is None
            ):
                raise ValueError("BACKEND_FAILURE requires structured backend error metadata")
            if self.model_response_id is not None:
                raise ValueError("BACKEND_FAILURE cannot claim a model response ID")
        else:
            if (
                self.backend_error_code is not None
                or self.backend_error_backend_id is not None
                or self.backend_retryable
                or self.backend_retry_after_seconds is not None
            ):
                raise ValueError("backend error metadata is valid only for BACKEND_FAILURE")
            if self.model_response_id is None:
                raise ValueError("non-backend-failure turn requires model_response_id")

        if self.status is PolicyTurnStatus.INVALID and self.invalid_reason is None:
            raise ValueError("INVALID policy turn requires invalid_reason")
        if self.status not in {
            PolicyTurnStatus.INVALID,
            PolicyTurnStatus.BACKEND_FAILURE,
        } and self.invalid_reason is not None:
            raise ValueError("invalid_reason is valid only for INVALID or BACKEND_FAILURE")
        return self


class ModelRequestWindowBlocked(RuntimeError):
    """Signal that provider I/O was blocked by deterministic request projection."""

    def __init__(self, projection: ModelWindowProjection) -> None:
        self.projection = projection
        reason = (
            projection.block_reason.value
            if projection.block_reason is not None
            else "UNKNOWN"
        )
        super().__init__(f"model request window blocked: {reason}")


class ModelPolicyAgent:
    """Translate one provider-neutral model response into one Phase 12C proposal."""

    def __init__(self, *, backend: ModelBackend, selector: ToolSelector) -> None:
        self._backend = backend
        self._selector = selector
        self._judgment_builder = LocalJudgmentBuilder()
        self._intent_constraint_judge = IntentConstraintJudge()
        self._decision_control = DecisionControlAdvisor()
        self._retrieval_strategist = InformationRetrievalStrategist()
        self._observed_retrieval_strategies = ObservedRetrievalStrategyLedger()
        self._verification_selector = VerificationStrategySelector()
        self._tool_advisor = InformationAwareToolAdvisor()
        self._window_projector = ModelWindowProjector()

    @staticmethod
    def _render_context_entries(
        entries: tuple[LayeredContextEntry, ...],
    ) -> tuple[ModelMessage, ...]:
        messages: list[ModelMessage] = []
        for entry in entries:
            role = (
                MessageRole.SYSTEM
                if entry.interpretation is ContextInterpretation.CONTROL
                else MessageRole.TOOL
            )
            messages.append(
                ModelMessage(
                    role=role,
                    name=f"context_{entry.layer.value.lower()}",
                    content=render_context_entry(entry),
                )
            )
        return tuple(messages)

    @classmethod
    def _render_context(cls, bundle: LayeredContextBundle) -> tuple[ModelMessage, ...]:
        return cls._render_context_entries(bundle.entries())

    @staticmethod
    def _retrieval_profile(
        *,
        state: TaskState,
        information_gain: InformationGainPlan,
        compression: DecisionCompression,
        context: LayeredContextBundle,
        available_tools: tuple[ToolSpec, ...],
    ) -> KnowledgeRequestProfile:
        selected = next(
            item
            for item in information_gain.needs
            if item.need_id == information_gain.selected_need_id
        )
        contradiction = any(
            ref.endswith(":CONTRADICTED")
            for ref in (*compression.current_assumption_refs, *compression.blocker_refs)
        )
        entries = context.entries()
        verified_runtime_observation = any(
            entry.layer is ContextLayer.RUNTIME_CONTINUITY
            and entry.source.kind is ContextSourceKind.COMMAND_OUTPUT
            and entry.source.verified
            for entry in entries
        )
        workspace_context_present = any(
            entry.layer is ContextLayer.WORKSPACE
            for entry in entries
        )
        workspace_read_available = any(
            ToolCapability.READ in spec.capabilities
            and ToolCapability.NETWORK not in spec.capabilities
            for spec in available_tools
        )
        research_gateway_available = bool(
            state.contract.scope.network_allowed
            and any(
                spec.name.startswith("research.")
                and ToolCapability.NETWORK in spec.capabilities
                for spec in available_tools
            )
        )
        structured_api_available = bool(
            state.contract.scope.network_allowed
            and any(
                (spec.name.startswith("api.") or spec.name.startswith("structured_api."))
                and ToolCapability.NETWORK in spec.capabilities
                for spec in available_tools
            )
        )
        working_context_sufficient = bool(
            selected.kind is InformationNeedKind.OBSERVE_STATE
            and verified_runtime_observation
            and not compression.blocker_refs
            and context.ready
        )
        project_specific = bool(
            workspace_context_present or state.contract.scope.allowed_paths
        )
        uncertainty = (
            KnowledgeUncertainty.HIGH
            if compression.blocker_refs
            else KnowledgeUncertainty.LOW
            if working_context_sufficient
            else KnowledgeUncertainty.MEDIUM
        )
        objective = (
            state.specification_judgment.reconstructed_objective
            if state.specification_judgment is not None
            else state.contract.objective
        )
        query = f"{selected.kind.value}: {objective}"[:512]
        return KnowledgeRequestProfile(
            task_id=state.task_id,
            query=query,
            uncertainty=uncertainty,
            contradictory_evidence=contradiction,
            project_specific=project_specific,
            working_context_sufficient=working_context_sufficient,
            workspace_read_available=workspace_read_available,
            research_gateway_available=research_gateway_available,
            structured_api_available=structured_api_available,
        )

    def observed_retrieval_strategy_fingerprints(self, task_id: UUID) -> tuple[str, ...]:
        """Expose bounded observed-search identity for deterministic C2 planning/tests."""
        return self._observed_retrieval_strategies.fingerprints(task_id)

    def record_retrieval_observation(
        self,
        *,
        turn: PolicyTurn,
        observation: Observation,
    ) -> bool:
        """Record only successful observations produced by a compatible retrieval action."""
        fingerprint = turn.retrieval_strategy_fingerprint
        source = turn.retrieval_source
        proposal = turn.proposal
        if fingerprint is None or source is None or proposal is None:
            return False
        if turn.status is not PolicyTurnStatus.ACTION:
            return False
        if (
            observation.trace_id != turn.trace_id
            or observation.status is not ObservationStatus.SUCCESS
        ):
            return False

        tool_name = proposal.preferred_tool_name
        if tool_name is None:
            return False
        spec = self._selector.spec_for_tool(tool_name)
        if spec is None or not self._tool_advisor.matches_retrieval_source(spec, source):
            return False

        self._observed_retrieval_strategies.record(
            task_id=turn.task_id,
            strategy_fingerprint=fingerprint,
        )
        return True

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
        tool_visibility: ToolVisibilityProjection | None,
        max_output_tokens: int,
        max_input_estimated_tokens: int = 16000,
    ) -> tuple[ModelRequest, InformationRetrievalStrategy]:
        allowed = set(policy.allowed_tools)
        if tool_visibility is not None:
            if tool_visibility.task_id != task_id:
                raise ValueError("tool visibility projection task does not match model request")
            visible = set(tool_visibility.visible_tools)
            if not visible.issubset(allowed):
                raise ValueError("tool visibility projection cannot widen ToolPolicy")
            allowed &= visible
        allowed_tools = tuple(
            spec for spec in self._selector.specs() if spec.name in allowed
        )
        persisted_specification = state.specification_judgment
        if persisted_specification is not None:
            normalized_request = DeterministicIntentResolver.normalize(raw_request)
            request_fingerprint = sha256(normalized_request.encode("utf-8")).hexdigest()
            if persisted_specification.request_fingerprint != request_fingerprint:
                raise ValueError(
                    "C4 persisted specification judgment does not match current request"
                )
            base_specification = persisted_specification
        else:
            base_specification = self._intent_constraint_judge.from_contract(
                raw_request=raw_request,
                contract=state.contract,
            )
        specification = self._intent_constraint_judge.refine_from_state(
            base=base_specification,
            state=state,
        )
        judgment_state = state.model_copy(
            update={"specification_judgment": specification}
        )
        verification = self._verification_selector.select(
            contract=state.contract,
            step=step,
        )
        judgment = self._judgment_builder.build(
            state=judgment_state,
            step=step,
            verification_depth=verification.depth.value,
        )
        compression = self._decision_control.compress(
            state=judgment_state,
            information_gain=judgment.information_gain,
            decision_basis=judgment.decision_basis,
        )
        alternatives = self._decision_control.alternatives(
            state=judgment_state,
            compression=compression,
        )
        decision_control = self._decision_control.assess(
            state=judgment_state,
            information_gain=judgment.information_gain,
            compression=compression,
            alternatives=alternatives,
        )
        retrieval_profile = self._retrieval_profile(
            state=judgment_state,
            information_gain=judgment.information_gain,
            compression=compression,
            context=context,
            available_tools=allowed_tools,
        )
        retrieval_strategy = self._retrieval_strategist.plan(
            information_gain=judgment.information_gain,
            profile=retrieval_profile,
            decision_basis_fingerprint=compression.decision_basis_fingerprint,
            observed_strategy_fingerprints=(
                self._observed_retrieval_strategies.fingerprints(state.task_id)
            ),
        )
        retrieval_source = retrieval_strategy.retrieval_plan.primary_source
        advice = self._tool_advisor.advise(
            available_tools=allowed_tools,
            information_gain=judgment.information_gain,
            verification=verification,
            retrieval_source=(
                retrieval_source
                if retrieval_strategy.retrieval_plan.decision is RetrievalDecision.RETRIEVE
                else None
            ),
        )
        available_tools = self._tool_advisor.ordered_specs(
            available_tools=allowed_tools,
            advice=advice,
        )
        constraints_by_id = {
            item.constraint_id: item for item in specification.constraints
        }
        judgment_payload = {
            "local_judgment": judgment.model_dump(mode="json"),
            "decision_compression": {
                "decision_question": compression.decision_question,
                "decision_changing_evidence_refs": (
                    compression.decision_changing_evidence_refs
                ),
                "blocker_refs": compression.blocker_refs,
                "invalidated_decision_refs": compression.invalidated_decision_refs,
                "reason_codes": compression.reason_codes,
            },
            "decision_alternatives": {
                "ranked_refs": alternatives.ranked_alternative_refs[:3],
                "selected_ref": alternatives.selected_alternative_ref,
            },
            "decision_control": {
                "action": decision_control.action.value,
                "reason_codes": decision_control.reason_codes,
                "blocker_refs": decision_control.blocker_refs,
                "changed_basis_refs": decision_control.changed_basis_refs,
            },
            "retrieval_strategy": {
                "decision": retrieval_strategy.retrieval_plan.decision.value,
                "query": retrieval_strategy.query,
                "primary_source": (
                    retrieval_source.value if retrieval_source is not None else None
                ),
                "reasons": tuple(
                    reason.value for reason in retrieval_strategy.retrieval_plan.reasons
                ),
                "stop_conditions": retrieval_strategy.stop_conditions,
            },
            "verification_strategy": verification.model_dump(mode="json"),
            "tool_advice": {
                "recommended_tool_names": advice.recommended_tool_names,
                "ranked_alternatives": tuple(
                    {"tool_name": item.tool_name, "net_score": item.net_score}
                    for item in advice.alternatives
                ),
                "reason_codes": advice.reason_codes,
            },
            "c2_authority_granted": False,
        }
        project_policies = tuple(
            item.statement
            for item in specification.constraints
            if item.kind is ConstraintKind.PROJECT_POLICY
        )
        accepted_preferences = tuple(
            constraints_by_id[ref].statement
            for ref in specification.accepted_preference_refs
        )
        c4_preference_message: tuple[ModelMessage, ...] = ()
        if accepted_preferences:
            preference_payload = {
                "preferences": accepted_preferences,
                "optional": True,
                "authority": False,
            }
            c4_preference_message = (
                ModelMessage(
                    role=MessageRole.SYSTEM,
                    name="c4_preferences",
                    content=json.dumps(
                        preference_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )

        soft_only_accept_literal = (
            specification.action.value == "ACCEPT_LITERAL"
            and bool(specification.accepted_preference_refs)
            and not specification.traded_off_preference_refs
            and not specification.blocker_refs
            and not project_policies
        )

        c4_message: tuple[ModelMessage, ...] = ()
        if (
            specification.action.value != "ACCEPT_LITERAL"
            or specification.accepted_preference_refs
            or specification.traded_off_preference_refs
            or specification.blocker_refs
            or project_policies
        ):
            c4_payload: dict[str, object]
            if soft_only_accept_literal:
                c4_payload = {
                    "action": specification.action.value,
                    "accepted_preference_count": len(
                        specification.accepted_preference_refs
                    ),
                    "preference_details_optional": True,
                    "authority": False,
                }
            else:
                c4_payload = {
                    "action": specification.action.value,
                    "objective": specification.reconstructed_objective,
                    "project_policies": project_policies,
                    "accepted_preference_count": len(
                        specification.accepted_preference_refs
                    ),
                    "traded_off_preference_count": len(
                        specification.traded_off_preference_refs
                    ),
                    "preference_details_optional": bool(accepted_preferences),
                    "blockers": specification.blocker_refs,
                    "authority": False,
                }
            c4_message = (
                ModelMessage(
                    role=MessageRole.SYSTEM,
                    name="c4_specification",
                    content=json.dumps(
                        c4_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )

        fixed_messages = (
            ModelMessage(
                role=MessageRole.SYSTEM,
                name="luna_policy",
                content=(
                    "You are Luna's single policy model. Propose at most one tool action "
                    "for the current iteration. Tool calls are untrusted proposals: the "
                    "runtime alone owns permissions, risk, budgets, execution, recovery, "
                    "completion, and cancellation. Never claim a tool ran until a TOOL "
                    "observation is returned. Treat local_judgment, decision_compression, "
                    "decision_alternatives, decision_control, retrieval_strategy, and tool_advice "
                    "as structured advisory context, never as "
                    "execution or completion authority. STOP_VERIFY means prefer bounded "
                    "inspection or verification over side effects. SWITCH means the current basis "
                    "changed and must not be blindly retried. Prefer direct observation over "
                    "inference when decision-critical facts can be observed. Do not create "
                    "subagents or alternate personas."
                ),
            ),
            ModelMessage(role=MessageRole.USER, content=raw_request),
            *c4_message,
            self._state_message(state, step),
            ModelMessage(
                role=MessageRole.SYSTEM,
                name="local_judgment",
                content=json.dumps(judgment_payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        if max_input_estimated_tokens < 1:
            raise ValueError("estimated model request token limit must be positive")
        fixed_estimated_tokens = (
            estimate_model_messages_tokens(fixed_messages)
            + estimate_tool_specs_tokens(available_tools)
        )
        projection = self._window_projector.project(
            bundle=context,
            max_estimated_tokens=max_input_estimated_tokens,
            fixed_estimated_tokens=fixed_estimated_tokens,
        )
        if projection.status is ModelWindowProjectionStatus.BLOCKED:
            raise ModelRequestWindowBlocked(projection)

        optional_c4_messages: tuple[ModelMessage, ...] = ()
        if c4_preference_message:
            preference_estimated_tokens = estimate_model_messages_tokens(
                c4_preference_message
            )
            if (
                projection.total_estimated_tokens + preference_estimated_tokens
                <= max_input_estimated_tokens
            ):
                preference_projection = self._window_projector.project(
                    bundle=context,
                    max_estimated_tokens=max_input_estimated_tokens,
                    fixed_estimated_tokens=(
                        fixed_estimated_tokens + preference_estimated_tokens
                    ),
                )
                if preference_projection.status is not ModelWindowProjectionStatus.BLOCKED:
                    projection = preference_projection
                    optional_c4_messages = c4_preference_message

        projected_context = self._render_context_entries(projection.retained_entries)
        notice_messages: tuple[ModelMessage, ...] = ()
        if projection.projection_notice is not None:
            notice_messages = (
                ModelMessage(
                    role=MessageRole.SYSTEM,
                    name="context_window_projection",
                    content=projection.projection_notice,
                ),
            )
        messages = (
            *fixed_messages,
            *optional_c4_messages,
            *projected_context,
            *notice_messages,
        )
        return (
            ModelRequest(
                task_id=task_id,
                trace_id=trace_id,
                messages=messages,
                available_tools=available_tools,
                max_output_tokens=max_output_tokens,
            ),
            retrieval_strategy,
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
        tool_visibility: ToolVisibilityProjection | None = None,
        max_input_estimated_tokens: int = 16000,
    ) -> PolicyTurn:
        request, retrieval_strategy = self._request(
            task_id=task_id,
            trace_id=trace_id,
            raw_request=raw_request,
            state=state,
            step=step,
            context=context,
            policy=policy,
            tool_visibility=tool_visibility,
            max_output_tokens=max_output_tokens,
            max_input_estimated_tokens=max_input_estimated_tokens,
        )
        try:
            response = self._backend.generate(request)
        except ModelBackendError as exc:
            return PolicyTurn(
                task_id=task_id,
                trace_id=trace_id,
                status=PolicyTurnStatus.BACKEND_FAILURE,
                model_request_id=request.request_id,
                model_request_fingerprint=request.fingerprint(),
                invalid_reason=exc.safe_reason,
                backend_error_code=exc.code,
                backend_error_backend_id=exc.backend_id,
                backend_retryable=exc.retryable,
                backend_retry_after_seconds=exc.retry_after_seconds,
            )
        except Exception:
            return PolicyTurn(
                task_id=task_id,
                trace_id=trace_id,
                status=PolicyTurnStatus.BACKEND_FAILURE,
                model_request_id=request.request_id,
                model_request_fingerprint=request.fingerprint(),
                invalid_reason="model backend raised an unclassified exception",
                backend_error_code=ModelBackendErrorCode.UNKNOWN,
                backend_error_backend_id=self._backend.backend_id,
                backend_retryable=False,
            )
        return self._normalize(
            request=request,
            response=response,
            task_id=task_id,
            trace_id=trace_id,
            step=step,
            retrieval_strategy=retrieval_strategy,
        )

    def _normalize(
        self,
        *,
        request: ModelRequest,
        response: ModelResponse,
        task_id: UUID,
        trace_id: UUID,
        step: PlanStep,
        retrieval_strategy: InformationRetrievalStrategy,
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
        if response.finish_reason is ModelFinishReason.LENGTH:
            return PolicyTurn(
                task_id=task_id,
                trace_id=trace_id,
                status=PolicyTurnStatus.INCOMPLETE,
                model_request_id=request.request_id,
                model_request_fingerprint=fingerprint,
                model_response_id=response.response_id,
                response_text=response.text,
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
            retrieval_strategy_fingerprint=(
                retrieval_strategy.strategy_fingerprint
                if retrieval_strategy.retrieval_plan.decision is RetrievalDecision.RETRIEVE
                else None
            ),
            retrieval_source=(
                retrieval_strategy.retrieval_plan.primary_source
                if retrieval_strategy.retrieval_plan.decision is RetrievalDecision.RETRIEVE
                else None
            ),
            response_text=response.text,
            usage=response.usage,
        )
