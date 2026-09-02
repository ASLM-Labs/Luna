from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.actions import (
    ActionDenialCode,
    ActionDenialStage,
    ActionKind,
    ActionProposal,
    ActionProposalBatch,
    ActionResolutionStatus,
    ActionResolver,
    ActionTargetKind,
    ToolFamily,
    ToolRoute,
    ToolSelector,
    build_phase12c_routes,
)
from luna.autonomy import AutonomyLevel
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.contracts.enums import ObservationStatus
from luna.tools import (
    ToolCapability,
    ToolDispatcher,
    ToolPolicy,
    ToolSpec,
    build_phase5_registry,
)
from luna.tools.registry import (
    RegisteredTool,
    ToolExecutionContext,
    ToolExecutionOutput,
    ToolRegistry,
)


def _task(
    *,
    write_allowed: bool = False,
    process_allowed: bool = False,
) -> TaskContract:
    return TaskContract(
        objective="Resolve one action without bypassing runtime authority",
        required_conditions=("Selection is deterministic",),
        evidence_required=("Structured action resolution",),
        scope=TaskScope(
            workspace_root=".",
            allowed_paths=("README.md",),
            write_allowed=write_allowed,
            process_allowed=process_allowed,
        ),
        risk_level=RiskLevel.LOW,
    )


def _resolver() -> ActionResolver:
    registry = build_phase5_registry()
    return ActionResolver(ToolSelector(registry, build_phase12c_routes()))


def _read_proposal(task: TaskContract, *, target: ActionTargetKind) -> ActionProposal:
    path = "README.md" if target is ActionTargetKind.FILE else "."
    return ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.READ,
        target_kind=target,
        summary="Inspect observed workspace content",
        arguments={"path": path},
        required_capabilities=(ToolCapability.READ,),
    )


def test_read_action_requires_read_capability() -> None:
    task = _task()
    with pytest.raises(ValidationError, match="requires capabilities"):
        ActionProposal(
            task_id=task.task_id,
            trace_id=uuid4(),
            kind=ActionKind.READ,
            target_kind=ActionTargetKind.FILE,
            summary="Read a file",
            arguments={"path": "README.md"},
        )


def test_read_action_cannot_request_side_effect_capability() -> None:
    task = _task()
    with pytest.raises(ValidationError, match="side-effect"):
        ActionProposal(
            task_id=task.task_id,
            trace_id=uuid4(),
            kind=ActionKind.READ,
            target_kind=ActionTargetKind.FILE,
            summary="Pretend read with write authority",
            arguments={"path": "README.md"},
            required_capabilities=(ToolCapability.READ, ToolCapability.WRITE),
        )


def test_model_cannot_supply_or_lower_risk_level_in_action_proposal() -> None:
    task = _task()
    with pytest.raises(ValidationError):
        ActionProposal.model_validate(
            {
                "task_id": task.task_id,
                "trace_id": uuid4(),
                "kind": "READ",
                "target_kind": "FILE",
                "summary": "Read a file",
                "arguments": {"path": "README.md"},
                "required_capabilities": ["READ"],
                "risk_level": "LOW",
            }
        )


def test_batch_allows_multiple_read_only_proposals() -> None:
    task = _task()
    trace_id = uuid4()
    proposals = (
        ActionProposal(
            task_id=task.task_id,
            trace_id=trace_id,
            kind=ActionKind.READ,
            target_kind=ActionTargetKind.FILE,
            summary="Read file",
            arguments={"path": "README.md"},
            required_capabilities=(ToolCapability.READ,),
        ),
        ActionProposal(
            task_id=task.task_id,
            trace_id=trace_id,
            kind=ActionKind.READ,
            target_kind=ActionTargetKind.DIRECTORY,
            summary="List directory",
            arguments={"path": "."},
            required_capabilities=(ToolCapability.READ,),
        ),
    )
    batch = ActionProposalBatch(task_id=task.task_id, trace_id=trace_id, proposals=proposals)
    assert len(batch.proposals) == 2


def test_batch_blocks_multiple_side_effect_proposals() -> None:
    task = _task(write_allowed=True, process_allowed=True)
    trace_id = uuid4()
    write = ActionProposal(
        task_id=task.task_id,
        trace_id=trace_id,
        kind=ActionKind.WRITE,
        target_kind=ActionTargetKind.FILE,
        summary="Write file",
        arguments={"path": "README.md", "content": "x", "create_if_missing": False},
        required_capabilities=(ToolCapability.WRITE,),
        preferred_tool_name="filesystem.write_text",
        expectation_id=uuid4(),
    )
    process = ActionProposal(
        task_id=task.task_id,
        trace_id=trace_id,
        kind=ActionKind.PROCESS,
        target_kind=ActionTargetKind.PROCESS,
        summary="Run process",
        arguments={"argv": ["python", "--version"]},
        required_capabilities=(ToolCapability.PROCESS,),
        preferred_tool_name="process.run_argv",
        working_directory=".",
        expectation_id=uuid4(),
    )
    with pytest.raises(ValidationError, match="at most one side-effect"):
        ActionProposalBatch(
            task_id=task.task_id,
            trace_id=trace_id,
            proposals=(write, process),
        )


def test_stage_one_selects_runtime_owned_family() -> None:
    task = _task()
    selector = ToolSelector(build_phase5_registry(), build_phase12c_routes())
    family = selector.select_family(_read_proposal(task, target=ActionTargetKind.FILE))
    assert family.family is ToolFamily.FILESYSTEM
    assert "tool_family:FILESYSTEM:PASS" in family.checks


def test_stage_two_selects_unique_registered_file_reader() -> None:
    task = _task()
    registry = build_phase5_registry()
    selector = ToolSelector(registry, build_phase12c_routes())
    proposal = _read_proposal(task, target=ActionTargetKind.FILE)
    selected = selector.select_tool(proposal, selector.select_family(proposal))
    assert not hasattr(selected, "code")
    assert selected.spec.name == "filesystem.read_text"  # type: ignore[union-attr]


def test_rollback_alias_is_explicit_only_and_safe_undo_is_default() -> None:
    task = _task(write_allowed=True)
    selector = ToolSelector(
        build_phase5_registry(),
        build_phase12c_routes(),
    )

    proposal = ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.ROLLBACK,
        target_kind=ActionTargetKind.SNAPSHOT,
        summary="Conditionally undo one snapshot.",
        arguments={
            "snapshot_id": str(uuid4()),
        },
        required_capabilities=(
            ToolCapability.WRITE,
        ),
        expectation_id=uuid4(),
    )

    selected = selector.select_tool(
        proposal,
        selector.select_family(
            proposal
        ),
    )

    assert not hasattr(
        selected,
        "code",
    )
    assert (
        selected.spec.name  # type: ignore[union-attr]
        == "workspace.safe_undo"
    )

    legacy = proposal.model_copy(
        update={
            "preferred_tool_name":
                "workspace.rollback",
        }
    )

    legacy_selected = selector.select_tool(
        legacy,
        selector.select_family(
            legacy
        ),
    )

    assert not hasattr(
        legacy_selected,
        "code",
    )
    assert (
        legacy_selected.spec.name  # type: ignore[union-attr]
        == "workspace.rollback"
    )

    canonical_route = (
        selector.route_for_tool(
            "workspace.safe_undo"
        )
    )
    legacy_route = (
        selector.route_for_tool(
            "workspace.rollback"
        )
    )

    assert canonical_route is not None
    assert legacy_route is not None
    assert (
        canonical_route.default_for_shape
        is True
    )
    assert (
        legacy_route.default_for_shape
        is False
    )


def test_unknown_preferred_tool_is_structured_denial() -> None:
    task = _task()
    registry = build_phase5_registry()
    selector = ToolSelector(registry, build_phase12c_routes())
    proposal = ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.READ,
        target_kind=ActionTargetKind.FILE,
        summary="Read with invented tool",
        arguments={"path": "README.md"},
        required_capabilities=(ToolCapability.READ,),
        preferred_tool_name="filesystem.magic_reader",
    )
    selected = selector.select_tool(proposal, selector.select_family(proposal))
    assert selected.code is ActionDenialCode.UNKNOWN_PREFERRED_TOOL  # type: ignore[union-attr]
    assert selected.stage is ActionDenialStage.TOOL_SELECTION  # type: ignore[union-attr]


def test_ambiguous_write_requires_explicit_registered_preference() -> None:
    task = _task(write_allowed=True)
    proposal = ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.WRITE,
        target_kind=ActionTargetKind.FILE,
        summary="Modify a file",
        arguments={"path": "README.md"},
        required_capabilities=(ToolCapability.WRITE,),
        expectation_id=uuid4(),
    )
    selector = ToolSelector(build_phase5_registry(), build_phase12c_routes())
    selected = selector.select_tool(proposal, selector.select_family(proposal))
    assert selected.code is ActionDenialCode.AMBIGUOUS_TOOL  # type: ignore[union-attr]


def test_invalid_arguments_become_structured_denial_before_dispatch() -> None:
    task = _task()
    proposal = ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.READ,
        target_kind=ActionTargetKind.FILE,
        summary="Read without required path",
        arguments={},
        required_capabilities=(ToolCapability.READ,),
    )
    resolution = _resolver().resolve(
        proposal=proposal,
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("filesystem.read_text",)),
    )
    assert resolution.status is ActionResolutionStatus.DENIED
    assert resolution.denial is not None
    assert resolution.denial.code is ActionDenialCode.INVALID_ARGUMENTS
    assert resolution.observation is not None
    assert resolution.observation.status is ObservationStatus.BLOCKED


def test_permission_denial_does_not_fallback_to_another_write_tool() -> None:
    task = _task(write_allowed=True)
    proposal = ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.WRITE,
        target_kind=ActionTargetKind.FILE,
        summary="Create exact file",
        arguments={
            "path": "README.md",
            "content": "phase12c",
            "create_if_missing": False,
        },
        required_capabilities=(ToolCapability.WRITE,),
        preferred_tool_name="filesystem.write_text",
        expectation_id=uuid4(),
    )
    resolution = _resolver().resolve(
        proposal=proposal,
        task_contract=task,
        policy=ToolPolicy(
            allowed_tools=("filesystem.replace_text",),
            autonomy_level=AutonomyLevel.LEVEL_2_CONTROLLED,
            max_risk=RiskLevel.MEDIUM,
        ),
    )
    assert resolution.status is ActionResolutionStatus.DENIED
    assert resolution.denial is not None
    assert resolution.denial.code is ActionDenialCode.POLICY_DENIED
    assert resolution.denial.selected_tool_name == "filesystem.write_text"
    assert "not explicitly allowed" in resolution.denial.reason


def test_high_impact_action_requires_expected_observation_in_preflight() -> None:
    task = _task(write_allowed=True)
    proposal = ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.WRITE,
        target_kind=ActionTargetKind.FILE,
        summary="Write without expectation",
        arguments={
            "path": "README.md",
            "content": "phase12c",
            "create_if_missing": False,
        },
        required_capabilities=(ToolCapability.WRITE,),
        preferred_tool_name="filesystem.write_text",
    )
    resolution = _resolver().resolve(
        proposal=proposal,
        task_contract=task,
        policy=ToolPolicy(
            allowed_tools=("filesystem.write_text",),
            autonomy_level=AutonomyLevel.LEVEL_2_CONTROLLED,
            max_risk=RiskLevel.MEDIUM,
        ),
    )
    assert resolution.status is ActionResolutionStatus.DENIED
    assert resolution.denial is not None
    assert resolution.denial.code is ActionDenialCode.POLICY_DENIED
    assert "expectation_id" in resolution.denial.reason


def test_read_action_prepares_request_without_executing() -> None:
    task = _task()
    proposal = _read_proposal(task, target=ActionTargetKind.FILE)
    resolution = _resolver().resolve(
        proposal=proposal,
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("filesystem.read_text",)),
    )
    assert resolution.status is ActionResolutionStatus.PREPARED
    assert resolution.selected_tool is not None
    assert resolution.selected_tool.name == "filesystem.read_text"
    request = ActionResolver.to_tool_request(resolution)
    assert request.request_id == resolution.request_id
    assert request.tool_name == "filesystem.read_text"


def test_denied_resolution_cannot_become_tool_request() -> None:
    task = _task()
    proposal = ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.READ,
        target_kind=ActionTargetKind.FILE,
        summary="Invent a reader",
        arguments={"path": "README.md"},
        required_capabilities=(ToolCapability.READ,),
        preferred_tool_name="filesystem.unknown",
    )
    resolution = _resolver().resolve(
        proposal=proposal,
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("filesystem.read_text",)),
    )
    with pytest.raises(ValueError, match="denied action"):
        ActionResolver.to_tool_request(resolution)


class CountingTool:
    def __init__(self) -> None:
        self.calls = 0

    def execute(
        self,
        arguments: dict[str, str | int | float | bool | list[str] | None],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del arguments, context
        self.calls += 1
        return ToolExecutionOutput(stdout="executed")


class RemovingSnapshotRegistry(ToolRegistry):
    """Deterministically remove one tool after selection captures its snapshot."""

    def __init__(self, tool_name: str) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._remove_on_snapshot = False

    def arm_removal(self) -> None:
        self._remove_on_snapshot = True

    def snapshot(self) -> tuple[RegisteredTool, ...]:
        registrations = super().snapshot()
        if self._remove_on_snapshot:
            self._remove_on_snapshot = False
            self.unregister(self._tool_name)
        return registrations


def test_tool_removal_during_selection_returns_structured_denial() -> None:
    task = _task()
    registry = RemovingSnapshotRegistry("core.count")
    registry.register(
        ToolSpec(name="core.count", description="Count explicit executions."),
        CountingTool(),
    )
    selector = ToolSelector(
        registry,
        (
            ToolRoute(
                tool_name="core.count",
                family=ToolFamily.CORE,
                action_kinds=(ActionKind.UTILITY,),
                target_kinds=(ActionTargetKind.NONE,),
            ),
        ),
    )
    proposal = ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.UTILITY,
        summary="Select a tool that becomes unavailable.",
    )
    registry.arm_removal()

    selected = selector.select_tool(proposal, selector.select_family(proposal))

    assert selected.code is ActionDenialCode.NO_MATCHING_TOOL  # type: ignore[union-attr]
    assert selected.stage is ActionDenialStage.TOOL_SELECTION  # type: ignore[union-attr]
    assert "selected_tool_available:FAIL" in selected.checks  # type: ignore[union-attr]
    assert registry.get("core.count") is None


def test_resolver_never_executes_handler_dispatcher_is_separate_authority() -> None:
    task = _task()
    handler = CountingTool()
    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="core.count", description="Count explicit executions."),
        handler,
    )
    selector = ToolSelector(
        registry,
        (
            ToolRoute(
                tool_name="core.count",
                family=ToolFamily.CORE,
                action_kinds=(ActionKind.UTILITY,),
                target_kinds=(ActionTargetKind.NONE,),
            ),
        ),
    )
    proposal = ActionProposal(
        task_id=task.task_id,
        trace_id=uuid4(),
        kind=ActionKind.UTILITY,
        summary="Prepare utility action",
        preferred_tool_name="core.count",
    )
    resolution = ActionResolver(selector).resolve(
        proposal=proposal,
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("core.count",)),
    )
    assert resolution.status is ActionResolutionStatus.PREPARED
    assert handler.calls == 0

    request = ActionResolver.to_tool_request(resolution)
    outcome = ToolDispatcher(registry).dispatch(
        request=request,
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("core.count",)),
    )
    assert outcome.result.status.value == "SUCCESS"
    assert handler.calls == 1


def test_routes_cannot_reference_unregistered_tools() -> None:
    with pytest.raises(ValueError, match="unregistered"):
        ToolSelector(
            ToolRegistry(),
            (
                ToolRoute(
                    tool_name="core.missing",
                    family=ToolFamily.CORE,
                    action_kinds=(ActionKind.UTILITY,),
                    target_kinds=(ActionTargetKind.NONE,),
                ),
            ),
        )
