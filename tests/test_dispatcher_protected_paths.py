from __future__ import annotations

from uuid import uuid4

from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.tools import (
    AutonomyLevel,
    ToolCapability,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    ToolSpec,
)
from luna.tools.registry import ToolExecutionContext, ToolExecutionOutput, ToolRegistry


class MisbehavingWriteTool:
    def execute(
        self,
        arguments: dict[str, str | int | float | bool | list[str] | None],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del arguments, context
        return ToolExecutionOutput(changed_files=("src/protected/secret.txt",))


def test_dispatcher_detects_protected_descendant_reported_by_handler() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="filesystem.synthetic_write",
            description="Synthetic write boundary test",
            risk_level=RiskLevel.MEDIUM,
            capabilities=(ToolCapability.WRITE,),
        ),
        MisbehavingWriteTool(),
    )
    contract = TaskContract(
        objective="Detect protected path mutations",
        required_conditions=("Protected path must remain unchanged",),
        evidence_required=("Observation",),
        scope=TaskScope(
            workspace_root=".",
            allowed_paths=("src",),
            protected_paths=("src/protected",),
            write_allowed=True,
        ),
    )
    outcome = ToolDispatcher(registry).dispatch(
        request=ToolRequest(
            task_id=contract.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.synthetic_write",
            expectation_id=uuid4(),
        ),
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("filesystem.synthetic_write",),
            autonomy_level=AutonomyLevel.BOUNDED,
            max_risk=RiskLevel.MEDIUM,
        ),
    )

    assert outcome.result.status is ToolResultStatus.FAILURE
    assert outcome.result.error_class == "ProtectedPathChanged"
    assert outcome.observation.protected_files_changed == ("src/protected/secret.txt",)
