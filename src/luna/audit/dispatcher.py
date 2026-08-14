"""Audited composition around the controlled ToolDispatcher."""

from __future__ import annotations

from luna.audit.session import AuditSession
from luna.contracts.task import TaskContract
from luna.tools.dispatcher import ToolDispatcher
from luna.tools.lifecycle import CancellationProbe
from luna.tools.models import DispatchOutcome, ToolPolicy, ToolRequest
from luna.tools.registry import ToolRegistry


class AuditedToolDispatcher:
    """Record request before execution and all observable results after execution."""

    def __init__(self, registry: ToolRegistry, audit: AuditSession) -> None:
        self._audit = audit
        self._dispatcher = ToolDispatcher(registry, output_capture=audit)

    def dispatch(
        self,
        *,
        request: ToolRequest,
        task_contract: TaskContract,
        policy: ToolPolicy,
        cancellation_probe: CancellationProbe | None = None,
    ) -> DispatchOutcome:
        self._audit.record_tool_request(request)
        outcome = self._dispatcher.dispatch(
            request=request,
            task_contract=task_contract,
            policy=policy,
            cancellation_probe=cancellation_probe,
        )
        self._audit.record_dispatch_outcome(outcome)
        return outcome
