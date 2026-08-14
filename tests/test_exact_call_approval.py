from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.tools import (
    AutonomyLevel,
    ExactCallApproval,
    ToolArgumentRule,
    ToolArgumentType,
    ToolCapability,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    ToolSpec,
)
from luna.tools.models import ToolArgumentValue
from luna.tools.registry import ToolExecutionContext, ToolExecutionOutput, ToolRegistry


@dataclass
class _CountingHandler:
    calls: int = 0

    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del context
        self.calls += 1
        return ToolExecutionOutput(stdout=str(arguments))


def _dispatcher(
    *,
    risk_level: RiskLevel = RiskLevel.HIGH,
) -> tuple[ToolDispatcher, _CountingHandler]:
    handler = _CountingHandler()
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="control.high_risk_read",
            description="Synthetic high-risk read used only for exact-call approval tests.",
            risk_level=risk_level,
            capabilities=(ToolCapability.READ,),
            argument_schema={
                "alpha": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                ),
                "beta": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                ),
            },
        ),
        handler,
    )
    return ToolDispatcher(registry), handler


def _contract(task_id=None) -> TaskContract:
    return TaskContract(
        task_id=task_id or uuid4(),
        objective="Verify exact-call approval binding.",
        required_conditions=("Only the approved call may execute.",),
        evidence_required=("ToolEvent policy checks",),
        scope=TaskScope(workspace_root="."),
        risk_level=RiskLevel.HIGH,
    )


def _request(contract: TaskContract, *, alpha: str = "one", beta: str = "two") -> ToolRequest:
    return ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="control.high_risk_read",
        arguments={"alpha": alpha, "beta": beta},
    )


def _policy(*approvals: ExactCallApproval) -> ToolPolicy:
    return ToolPolicy(
        allowed_tools=("control.high_risk_read",),
        owner_approved_tools=("control.high_risk_read",),
        exact_call_approvals=approvals,
        autonomy_level=AutonomyLevel.LEVEL_3_TASK,
        max_risk=RiskLevel.HIGH,
    )


def test_exact_call_fingerprint_is_stable_across_argument_order() -> None:
    contract = _contract()
    first = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="control.high_risk_read",
        arguments={"alpha": "one", "beta": "two"},
        working_directory="folder\\child",
    )
    second = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="control.high_risk_read",
        arguments={"beta": "two", "alpha": "one"},
        working_directory="folder/child",
    )

    assert first.exact_call_fingerprint() == second.exact_call_fingerprint()


def test_tool_level_owner_approval_alone_does_not_authorize_high_risk_call() -> None:
    dispatcher, handler = _dispatcher()
    contract = _contract()
    request = _request(contract)
    basis = "a" * 64

    outcome = dispatcher.dispatch(
        request=request,
        task_contract=contract,
        policy=_policy(),
        approval_basis_fingerprint=basis,
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert handler.calls == 0
    assert "exact call is not owner-approved" in outcome.event.reason
    assert request.exact_call_fingerprint() in outcome.event.reason
    assert basis in outcome.event.reason


def test_owner_gated_medium_risk_tool_also_requires_exact_call_approval() -> None:
    dispatcher, handler = _dispatcher(risk_level=RiskLevel.MEDIUM)
    contract = _contract()
    request = _request(contract)
    basis = "f" * 64
    policy = ToolPolicy(
        allowed_tools=("control.high_risk_read",),
        owner_approved_tools=("control.high_risk_read",),
        autonomy_level=AutonomyLevel.LEVEL_2_CONTROLLED,
        max_risk=RiskLevel.MEDIUM,
    )

    outcome = dispatcher.dispatch(
        request=request,
        task_contract=contract,
        policy=policy,
        approval_basis_fingerprint=basis,
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert handler.calls == 0
    assert "exact call is not owner-approved" in outcome.event.reason


def test_exact_call_approval_authorizes_only_matching_call_and_basis() -> None:
    dispatcher, handler = _dispatcher()
    contract = _contract()
    request = _request(contract)
    basis = "b" * 64
    approval = ExactCallApproval.bind(
        request,
        basis_fingerprint=basis,
        approved_by="owner:test",
        evidence_ref="approval:test:exact-call",
    )
    policy = _policy(approval)

    approved = dispatcher.dispatch(
        request=request,
        task_contract=contract,
        policy=policy,
        approval_basis_fingerprint=basis,
    )
    changed_arguments = dispatcher.dispatch(
        request=_request(contract, beta="changed"),
        task_contract=contract,
        policy=policy,
        approval_basis_fingerprint=basis,
    )
    changed_basis = dispatcher.dispatch(
        request=request.model_copy(update={"request_id": uuid4()}),
        task_contract=contract,
        policy=policy,
        approval_basis_fingerprint="c" * 64,
    )

    assert approved.result.status is ToolResultStatus.SUCCESS
    assert "exact_call_approval:PASS" in approved.event.policy_checks
    assert (
        f"exact_call_fingerprint:{request.exact_call_fingerprint()}"
        in approved.event.policy_checks
    )
    assert f"exact_call_approval_basis:{basis}" in approved.event.policy_checks
    assert f"exact_call_approval_id:{approval.approval_id}" in approved.event.policy_checks
    assert "exact_call_approved_by:owner:test" in approved.event.policy_checks
    assert (
        "exact_call_approval_evidence:approval:test:exact-call"
        in approved.event.policy_checks
    )
    assert changed_arguments.result.status is ToolResultStatus.BLOCKED
    assert "not owner-approved" in changed_arguments.event.reason
    assert changed_basis.result.status is ToolResultStatus.BLOCKED
    assert "basis no longer matches" in changed_basis.event.reason
    assert handler.calls == 1


def test_exact_call_approval_is_task_bound() -> None:
    dispatcher, handler = _dispatcher()
    approved_contract = _contract()
    approved_request = _request(approved_contract)
    basis = "d" * 64
    approval = ExactCallApproval.bind(
        approved_request,
        basis_fingerprint=basis,
        approved_by="owner:test",
        evidence_ref="approval:test:task-bound",
    )
    other_contract = _contract()
    other_request = _request(other_contract)

    outcome = dispatcher.dispatch(
        request=other_request,
        task_contract=other_contract,
        policy=_policy(approval),
        approval_basis_fingerprint=basis,
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert handler.calls == 0


def test_high_risk_dispatch_requires_runtime_owned_approval_basis() -> None:
    dispatcher, handler = _dispatcher()
    contract = _contract()
    request = _request(contract)
    approval = ExactCallApproval.bind(
        request,
        basis_fingerprint="e" * 64,
        approved_by="owner:test",
        evidence_ref="approval:test:basis-required",
    )

    outcome = dispatcher.dispatch(
        request=request,
        task_contract=contract,
        policy=_policy(approval),
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert handler.calls == 0
    assert "basis=missing" in outcome.event.reason
