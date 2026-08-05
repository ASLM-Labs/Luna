from __future__ import annotations

from uuid import uuid4

from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.modeling import (
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelToolCall,
    ScriptedModelOutput,
    ScriptedTestBackend,
    ScriptedTurn,
)
from luna.modeling.contracts import MessageRole
from luna.modeling.tool_bridge import model_call_to_request
from luna.tools import ToolDispatcher, ToolPolicy, ToolResultStatus, build_phase4_registry


def test_model_tool_proposal_cannot_bypass_dispatcher_permission() -> None:
    task = TaskContract(
        objective="Test model/tool trust boundary",
        required_conditions=("Unapproved tool must not execute",),
        evidence_required=("Blocked ToolEvent",),
        scope=TaskScope(workspace_root="."),
        risk_level=RiskLevel.LOW,
    )
    request = ModelRequest(
        task_id=task.task_id,
        trace_id=uuid4(),
        messages=(ModelMessage(role=MessageRole.USER, content="Run echo"),),
    )
    backend = ScriptedTestBackend(
        turns=(
            ScriptedTurn(
                output=ScriptedModelOutput(
                    tool_calls=(
                        ModelToolCall(
                            call_id="call-1",
                            tool_name="core.echo",
                            arguments={"message": "should not run"},
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )

    response = backend.generate(request)
    tool_request = model_call_to_request(
        call=response.tool_calls[0],
        task_id=task.task_id,
        trace_id=request.trace_id,
    )
    outcome = ToolDispatcher(build_phase4_registry()).dispatch(
        request=tool_request,
        task_contract=task,
        policy=ToolPolicy(),
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert "not explicitly allowed" in outcome.event.reason
