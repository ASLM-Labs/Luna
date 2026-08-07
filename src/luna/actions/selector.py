"""Deterministic two-stage tool selection for untrusted action proposals."""

from __future__ import annotations

from dataclasses import dataclass

from luna.actions.models import (
    ActionDenial,
    ActionDenialCode,
    ActionDenialStage,
    ActionKind,
    ActionProposal,
    ActionTargetKind,
    ToolFamily,
    ToolRoute,
)
from luna.tools.models import ToolSpec
from luna.tools.registry import ToolRegistry

_FAMILY_BY_KIND = {
    ActionKind.READ: ToolFamily.FILESYSTEM,
    ActionKind.WRITE: ToolFamily.FILESYSTEM,
    ActionKind.ROLLBACK: ToolFamily.WORKSPACE,
    ActionKind.PROCESS: ToolFamily.PROCESS,
    ActionKind.UTILITY: ToolFamily.CORE,
}


@dataclass(frozen=True, slots=True)
class FamilySelection:
    """Stage-one result."""

    family: ToolFamily
    checks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConcreteToolSelection:
    """Stage-two result."""

    family: ToolFamily
    spec: ToolSpec
    checks: tuple[str, ...]


class ToolSelector:
    """Select a tool family then one concrete registered ToolSpec without executing it."""

    def __init__(self, registry: ToolRegistry, routes: tuple[ToolRoute, ...]) -> None:
        self._registry = registry
        self._routes = routes
        route_names = tuple(route.tool_name for route in routes)
        if len(route_names) != len(set(route_names)):
            raise ValueError("tool routes must reference unique tool names")
        missing = tuple(name for name in route_names if registry.get(name) is None)
        if missing:
            raise ValueError("tool routes reference unregistered tools: " + ", ".join(missing))

    def select_family(self, proposal: ActionProposal) -> FamilySelection:
        """Stage one: map semantic action kind to one runtime-owned family."""
        family = _FAMILY_BY_KIND.get(proposal.kind)
        if family is None:
            raise AssertionError(f"unmapped action kind: {proposal.kind}")
        return FamilySelection(
            family=family,
            checks=(
                "action_kind:PASS",
                f"tool_family:{family.value}:PASS",
            ),
        )

    def select_tool(
        self,
        proposal: ActionProposal,
        family_selection: FamilySelection,
    ) -> ConcreteToolSelection | ActionDenial:
        """Stage two: select exactly one compatible registered route or deny."""
        family = family_selection.family
        checks = list(family_selection.checks)
        routes = tuple(
            route
            for route in self._routes
            if route.family is family
            and proposal.kind in route.action_kinds
            and proposal.target_kind in route.target_kinds
        )
        if not routes:
            return self._denial(
                proposal=proposal,
                family=family,
                code=ActionDenialCode.NO_MATCHING_TOOL,
                reason="no runtime-owned route matches the action family and target",
                checks=(*checks, "route_match:FAIL"),
            )
        checks.append("route_match:PASS")

        required = set(proposal.required_capabilities)
        compatible = tuple(
            route
            for route in routes
            if (
                (registered := self._registry.get(route.tool_name)) is not None
                and required.issubset(set(registered.spec.capabilities))
            )
        )
        if not compatible:
            return self._denial(
                proposal=proposal,
                family=family,
                code=ActionDenialCode.NO_MATCHING_TOOL,
                reason="matching routes do not satisfy required tool capabilities",
                checks=(*checks, "capability_match:FAIL"),
            )
        checks.append("capability_match:PASS")

        if proposal.preferred_tool_name is not None:
            registered = self._registry.get(proposal.preferred_tool_name)
            if registered is None:
                return self._denial(
                    proposal=proposal,
                    family=family,
                    code=ActionDenialCode.UNKNOWN_PREFERRED_TOOL,
                    reason="preferred tool is not registered",
                    checks=(*checks, "preferred_tool_registered:FAIL"),
                    tool_name=proposal.preferred_tool_name,
                )
            chosen = next(
                (route for route in compatible if route.tool_name == proposal.preferred_tool_name),
                None,
            )
            if chosen is None:
                return self._denial(
                    proposal=proposal,
                    family=family,
                    code=ActionDenialCode.PREFERRED_TOOL_MISMATCH,
                    reason="preferred tool is registered but incompatible with the action route",
                    checks=(*checks, "preferred_tool_route:FAIL"),
                    tool_name=proposal.preferred_tool_name,
                )
            checks.append("preferred_tool_route:PASS")
            return ConcreteToolSelection(
                family=family,
                spec=registered.spec,
                checks=tuple(checks),
            )

        if len(compatible) != 1:
            return self._denial(
                proposal=proposal,
                family=family,
                code=ActionDenialCode.AMBIGUOUS_TOOL,
                reason=(
                    "multiple compatible tools exist; proposal must name one "
                    "registered preference"
                ),
                checks=(*checks, "single_candidate:FAIL"),
            )

        registered = self._registry.get(compatible[0].tool_name)
        if registered is None:
            raise AssertionError("validated route disappeared from immutable registry")
        checks.append("single_candidate:PASS")
        return ConcreteToolSelection(
            family=family,
            spec=registered.spec,
            checks=tuple(checks),
        )

    @staticmethod
    def _denial(
        *,
        proposal: ActionProposal,
        family: ToolFamily,
        code: ActionDenialCode,
        reason: str,
        checks: tuple[str, ...],
        tool_name: str | None = None,
    ) -> ActionDenial:
        return ActionDenial(
            proposal_id=proposal.proposal_id,
            task_id=proposal.task_id,
            trace_id=proposal.trace_id,
            stage=ActionDenialStage.TOOL_SELECTION,
            code=code,
            reason=reason,
            checks=checks,
            selected_family=family,
            selected_tool_name=tool_name,
        )


def build_phase12c_routes() -> tuple[ToolRoute, ...]:
    """Return runtime-owned routes for the built-in Phase 5 registry."""
    return (
        ToolRoute(
            tool_name="core.echo",
            family=ToolFamily.CORE,
            action_kinds=(ActionKind.UTILITY,),
            target_kinds=(ActionTargetKind.NONE,),
        ),
        ToolRoute(
            tool_name="filesystem.read_text",
            family=ToolFamily.FILESYSTEM,
            action_kinds=(ActionKind.READ,),
            target_kinds=(ActionTargetKind.FILE,),
        ),
        ToolRoute(
            tool_name="filesystem.list_directory",
            family=ToolFamily.FILESYSTEM,
            action_kinds=(ActionKind.READ,),
            target_kinds=(ActionTargetKind.DIRECTORY,),
        ),
        ToolRoute(
            tool_name="filesystem.write_text",
            family=ToolFamily.FILESYSTEM,
            action_kinds=(ActionKind.WRITE,),
            target_kinds=(ActionTargetKind.FILE,),
        ),
        ToolRoute(
            tool_name="filesystem.replace_text",
            family=ToolFamily.FILESYSTEM,
            action_kinds=(ActionKind.WRITE,),
            target_kinds=(ActionTargetKind.FILE,),
        ),
        ToolRoute(
            tool_name="workspace.rollback",
            family=ToolFamily.WORKSPACE,
            action_kinds=(ActionKind.ROLLBACK,),
            target_kinds=(ActionTargetKind.SNAPSHOT,),
        ),
        ToolRoute(
            tool_name="process.run_argv",
            family=ToolFamily.PROCESS,
            action_kinds=(ActionKind.PROCESS,),
            target_kinds=(ActionTargetKind.PROCESS,),
        ),
    )
