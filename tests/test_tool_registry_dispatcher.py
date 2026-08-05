from __future__ import annotations

from uuid import uuid4

import pytest

from luna.contracts import ExpectedObservation, RiskLevel, TaskContract, TaskScope
from luna.contracts.enums import ObservationStatus
from luna.tools import (
    AutonomyLevel,
    ToolCapability,
    ToolDispatcher,
    ToolEventDecision,
    ToolOrigin,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    ToolSpec,
    build_phase4_registry,
)
from luna.tools.registry import ToolExecutionContext, ToolExecutionOutput, ToolRegistry


class ProcessLikeTool:
    def execute(
        self,
        arguments: dict[str, str | int | float | bool | list[str] | None],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del arguments, context
        return ToolExecutionOutput(stdout="executed")


def contract(*, write_allowed: bool = False, network_allowed: bool = False) -> TaskContract:
    task_id = uuid4()
    return TaskContract(
        task_id=task_id,
        objective="Phase 4 dispatcher test",
        required_conditions=("Request must be policy checked",),
        evidence_required=("ToolEvent",),
        scope=TaskScope(
            workspace_root=".",
            allowed_paths=("README.md",),
            write_allowed=write_allowed,
            network_allowed=network_allowed,
        ),
        risk_level=RiskLevel.LOW,
    )


def test_duplicate_registration_is_rejected() -> None:
    registry = ToolRegistry()
    spec = ToolSpec(name="core.test", description="test")
    handler = ProcessLikeTool()
    registry.register(spec, handler)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec, handler)


def test_unregistered_tool_returns_blocked_result_event_and_observation() -> None:
    task = contract()
    outcome = ToolDispatcher(ToolRegistry()).dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="unknown.tool",
        ),
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("unknown.tool",)),
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert outcome.event.decision is ToolEventDecision.BLOCKED
    assert outcome.observation.status is ObservationStatus.BLOCKED
    assert outcome.result.error_class == "UnregisteredTool"


def test_empty_allowlist_denies_registered_tool() -> None:
    task = contract()
    outcome = ToolDispatcher(build_phase4_registry()).dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="core.echo",
            arguments={"message": "hello"},
        ),
        task_contract=task,
        policy=ToolPolicy(),
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert "not explicitly allowed" in outcome.event.reason


def test_argument_schema_rejects_unknown_fields() -> None:
    task = contract()
    outcome = ToolDispatcher(build_phase4_registry()).dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="core.echo",
            arguments={"message": "hello", "secret": "no"},
        ),
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("core.echo",)),
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert outcome.result.error_class == "ToolArgumentError"


def test_echo_executes_only_with_explicit_permission() -> None:
    task = contract()
    outcome = ToolDispatcher(build_phase4_registry()).dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="core.echo",
            arguments={"message": "hello"},
            origin=ToolOrigin.MODEL,
        ),
        task_contract=task,
        policy=ToolPolicy(
            allowed_tools=("core.echo",),
            max_risk=RiskLevel.LOW,
        ),
    )

    assert outcome.result.status is ToolResultStatus.SUCCESS
    assert outcome.result.stdout_excerpt == "hello"
    assert outcome.event.decision is ToolEventDecision.EXECUTED
    assert outcome.observation.stdout_ref == f"sha256:{outcome.result.stdout_digest}"


def test_high_impact_tool_requires_expected_observation() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="process.verify",
            description="Synthetic process tool",
            risk_level=RiskLevel.MEDIUM,
            capabilities=(ToolCapability.PROCESS,),
        ),
        ProcessLikeTool(),
    )
    task = contract()
    dispatcher = ToolDispatcher(registry)
    policy = ToolPolicy(
        allowed_tools=("process.verify",),
        autonomy_level=AutonomyLevel.BOUNDED,
        max_risk=RiskLevel.MEDIUM,
    )

    blocked = dispatcher.dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="process.verify",
        ),
        task_contract=task,
        policy=policy,
    )
    expectation = ExpectedObservation(
        summary="Process returns success",
        expected_status=ObservationStatus.SUCCESS,
        failure_signals=("non_zero_exit",),
        verification_method="Inspect exit code",
        high_impact=True,
    )
    allowed = dispatcher.dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="process.verify",
            expectation_id=expectation.expectation_id,
        ),
        task_contract=task,
        policy=policy,
    )

    assert blocked.result.status is ToolResultStatus.BLOCKED
    assert allowed.result.status is ToolResultStatus.SUCCESS


def test_timeout_budget_is_checked_before_execution() -> None:
    task = contract()
    outcome = ToolDispatcher(build_phase4_registry()).dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="core.echo",
            arguments={"message": "hello"},
            timeout_ms=20000,
        ),
        task_contract=task,
        policy=ToolPolicy(
            allowed_tools=("core.echo",),
            max_timeout_ms=1000,
        ),
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert "timeout" in outcome.event.reason


def test_output_is_bounded_and_hash_preserves_full_value() -> None:
    task = contract()
    outcome = ToolDispatcher(build_phase4_registry()).dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="core.echo",
            arguments={"message": "hello"},
            max_output_chars=3,
        ),
        task_contract=task,
        policy=ToolPolicy(
            allowed_tools=("core.echo",),
            max_output_chars=3,
        ),
    )

    assert outcome.result.status is ToolResultStatus.SUCCESS
    assert outcome.result.stdout_excerpt == "hel"
    assert outcome.result.output_chars == 5
    assert outcome.result.truncated
    assert len(outcome.result.stdout_digest) == 64
