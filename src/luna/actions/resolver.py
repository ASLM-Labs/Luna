"""Pre-execution action resolution with structured denial and no hidden fallback."""

from __future__ import annotations

from luna.actions.models import (
    ActionDenial,
    ActionDenialCode,
    ActionDenialStage,
    ActionProposal,
    ActionResolution,
    ActionResolutionStatus,
)
from luna.actions.selector import ToolSelector
from luna.contracts.task import TaskContract
from luna.tools.arguments import ToolArgumentError, validate_tool_arguments
from luna.tools.models import ToolPolicy, ToolRequest
from luna.tools.policy import evaluate_tool_policy


class ActionResolver:
    """Resolve one proposal into a non-executed ToolRequest or structured denial."""

    def __init__(self, selector: ToolSelector) -> None:
        self._selector = selector

    @property
    def selector(self) -> ToolSelector:
        """Expose the read-only selector boundary to the Phase 12E policy adapter."""
        return self._selector

    def resolve(
        self,
        *,
        proposal: ActionProposal,
        task_contract: TaskContract,
        policy: ToolPolicy,
    ) -> ActionResolution:
        """Resolve exactly once; a denied tool is never substituted automatically."""
        family = self._selector.select_family(proposal)
        selected = self._selector.select_tool(proposal, family)
        if isinstance(selected, ActionDenial):
            return self._denied(proposal, selected)

        try:
            validate_tool_arguments(selected.spec, proposal.arguments)
        except ToolArgumentError as exc:
            denial = ActionDenial(
                proposal_id=proposal.proposal_id,
                task_id=proposal.task_id,
                trace_id=proposal.trace_id,
                stage=ActionDenialStage.ARGUMENT_VALIDATION,
                code=ActionDenialCode.INVALID_ARGUMENTS,
                reason=str(exc),
                checks=(*selected.checks, "argument_schema:FAIL"),
                selected_family=selected.family,
                selected_tool_name=selected.spec.name,
            )
            return self._denied(proposal, denial)

        request = ToolRequest(
            task_id=proposal.task_id,
            trace_id=proposal.trace_id,
            tool_name=selected.spec.name,
            arguments=proposal.arguments,
            working_directory=proposal.working_directory,
            timeout_ms=proposal.timeout_ms,
            max_output_chars=proposal.max_output_chars,
            expectation_id=proposal.expectation_id,
            origin=proposal.origin,
        )
        decision = evaluate_tool_policy(
            spec=selected.spec,
            request=request,
            task_contract=task_contract,
            policy=policy,
        )
        if not decision.allowed:
            denial = ActionDenial(
                proposal_id=proposal.proposal_id,
                task_id=proposal.task_id,
                trace_id=proposal.trace_id,
                stage=ActionDenialStage.POLICY_PREFLIGHT,
                code=ActionDenialCode.POLICY_DENIED,
                reason=decision.reason,
                checks=(*selected.checks, *decision.checks),
                selected_family=selected.family,
                selected_tool_name=selected.spec.name,
            )
            return self._denied(proposal, denial)

        return ActionResolution(
            status=ActionResolutionStatus.PREPARED,
            proposal=proposal,
            selected_family=selected.family,
            selected_tool=selected.spec,
            request_id=request.request_id,
            policy_checks=(*selected.checks, "argument_schema:PASS", *decision.checks),
        )

    @staticmethod
    def to_tool_request(resolution: ActionResolution) -> ToolRequest:
        """Rebuild the prepared request; dispatcher remains the execution authority."""
        if resolution.status is not ActionResolutionStatus.PREPARED:
            raise ValueError("denied action cannot become a ToolRequest")
        proposal = resolution.proposal
        selected_tool = resolution.selected_tool
        if selected_tool is None or resolution.request_id is None:
            raise ValueError("prepared resolution is incomplete")
        return ToolRequest(
            request_id=resolution.request_id,
            task_id=proposal.task_id,
            trace_id=proposal.trace_id,
            tool_name=selected_tool.name,
            arguments=proposal.arguments,
            working_directory=proposal.working_directory,
            timeout_ms=proposal.timeout_ms,
            max_output_chars=proposal.max_output_chars,
            expectation_id=proposal.expectation_id,
            origin=proposal.origin,
        )

    @staticmethod
    def _denied(proposal: ActionProposal, denial: ActionDenial) -> ActionResolution:
        return ActionResolution(
            status=ActionResolutionStatus.DENIED,
            proposal=proposal,
            selected_family=denial.selected_family,
            denial=denial,
            observation=denial.to_observation(),
        )
