"""Convert model tool proposals into ordinary untrusted ToolRequests."""

from __future__ import annotations

from uuid import UUID

from luna.modeling.contracts import ModelToolCall
from luna.tools.models import ToolOrigin, ToolRequest


def model_call_to_request(
    *,
    call: ModelToolCall,
    task_id: UUID,
    trace_id: UUID,
    working_directory: str | None = None,
    expectation_id: UUID | None = None,
) -> ToolRequest:
    """Preserve arguments while granting no permission or risk override."""
    return ToolRequest(
        task_id=task_id,
        trace_id=trace_id,
        tool_name=call.tool_name,
        arguments=call.arguments,
        working_directory=working_directory,
        expectation_id=expectation_id,
        origin=ToolOrigin.MODEL,
    )
