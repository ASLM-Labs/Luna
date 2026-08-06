from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from luna.autonomy import (
    AutonomyLevel,
    AutonomyPolicy,
    FreeResearchContract,
)
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.tools import (
    ToolArgumentRule,
    ToolArgumentType,
    ToolCapability,
    ToolDispatcher,
    ToolExecutionContext,
    ToolExecutionOutput,
    ToolOrigin,
    ToolPolicy,
    ToolRegistry,
    ToolRequest,
    ToolSpec,
)
from luna.tools.policy import evaluate_tool_policy


class _NetworkFixture:
    def execute(
        self,
        arguments: dict[str, str | int | float | bool | list[str] | None],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del arguments, context
        return ToolExecutionOutput(stdout="ok")


def _contract(
    task_id: UUID,
    root: Path,
    *,
    write: bool = False,
    network: bool = False,
) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Verify runtime autonomy enforcement.",
        required_conditions=("Policy decision is deterministic.",),
        evidence_required=("policy decision",),
        scope=TaskScope(
            workspace_root=str(root),
            allowed_paths=("out.txt",) if write else (),
            write_allowed=write,
            network_allowed=network,
        ),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def _spec(
    name: str,
    *,
    capability: ToolCapability | None = None,
    risk: RiskLevel = RiskLevel.LOW,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Phase 10 autonomy fixture.",
        risk_level=risk,
        capabilities=() if capability is None else (capability,),
        argument_schema={
            "url": ToolArgumentRule(
                argument_type=ToolArgumentType.STRING,
                required=capability is ToolCapability.NETWORK,
            )
        }
        if capability is ToolCapability.NETWORK
        else {},
    )


def _request(task_id: UUID, tool_name: str, *, url: str | None = None) -> ToolRequest:
    return ToolRequest(
        task_id=task_id,
        trace_id=uuid4(),
        tool_name=tool_name,
        arguments={} if url is None else {"url": url},
        expectation_id=uuid4(),
        origin=ToolOrigin.MODEL,
    )


def test_autonomy_levels_keep_backward_aliases() -> None:
    assert AutonomyLevel.OBSERVE_ONLY is AutonomyLevel.LEVEL_1_READ_ONLY
    assert AutonomyLevel.BOUNDED is AutonomyLevel.LEVEL_2_CONTROLLED
    assert AutonomyLevel.OWNER_APPROVED is AutonomyLevel.LEVEL_3_TASK
    assert [item.number for item in AutonomyLevel] == [0, 1, 2, 3, 4]
    assert AutonomyLevel("BOUNDED") is AutonomyLevel.LEVEL_2_CONTROLLED


def test_level_zero_blocks_even_model_origin_no_effect_tool(tmp_path: Path) -> None:
    task_id = uuid4()
    decision = evaluate_tool_policy(
        spec=_spec("fixture.echo"),
        request=_request(task_id, "fixture.echo"),
        task_contract=_contract(task_id, tmp_path),
        policy=ToolPolicy(
            allowed_tools=("fixture.echo",),
            autonomy_level=AutonomyLevel.LEVEL_0_ADVISORY,
        ),
    )

    assert decision.allowed is False
    assert "Level 0" in decision.reason


def test_level_one_blocks_write_and_level_two_allows_scoped_write(tmp_path: Path) -> None:
    task_id = uuid4()
    spec = _spec("fixture.write", capability=ToolCapability.WRITE)
    request = _request(task_id, spec.name)
    contract = _contract(task_id, tmp_path, write=True)

    denied = evaluate_tool_policy(
        spec=spec,
        request=request,
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=(spec.name,),
            autonomy_level=AutonomyLevel.LEVEL_1_READ_ONLY,
        ),
    )
    allowed = evaluate_tool_policy(
        spec=spec,
        request=request,
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=(spec.name,),
            autonomy_level=AutonomyLevel.LEVEL_2_CONTROLLED,
            max_risk=RiskLevel.MEDIUM,
        ),
    )

    assert denied.allowed is False
    assert allowed.allowed is True


def test_level_two_blocks_network_capability(tmp_path: Path) -> None:
    task_id = uuid4()
    spec = _spec("fixture.network", capability=ToolCapability.NETWORK)
    decision = evaluate_tool_policy(
        spec=spec,
        request=_request(task_id, spec.name),
        task_contract=_contract(task_id, tmp_path, network=True),
        policy=ToolPolicy(
            allowed_tools=(spec.name,),
            autonomy_level=AutonomyLevel.LEVEL_2_CONTROLLED,
            max_risk=RiskLevel.MEDIUM,
        ),
    )

    assert decision.allowed is False
    assert "Level 2" in decision.reason


def test_level_four_requires_separate_active_domain_scoped_contract(tmp_path: Path) -> None:
    task_id = uuid4()
    now = datetime.now(UTC)
    spec = _spec("research.fetch", capability=ToolCapability.NETWORK)
    contract = FreeResearchContract(
        task_id=task_id,
        purpose="Research the official project documentation.",
        allowed_tools=(spec.name,),
        allowed_domains=("example.com",),
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=10),
    )
    policy = ToolPolicy(
        allowed_tools=(spec.name,),
        autonomy_level=AutonomyLevel.LEVEL_4_FREE_RESEARCH,
        free_research_contract=contract,
    )
    task_contract = _contract(task_id, tmp_path, network=True)

    allowed = evaluate_tool_policy(
        spec=spec,
        request=_request(task_id, spec.name, url="https://docs.example.com/page"),
        task_contract=task_contract,
        policy=policy,
    )
    denied = evaluate_tool_policy(
        spec=spec,
        request=_request(task_id, spec.name, url="https://outside.test/page"),
        task_contract=task_contract,
        policy=policy,
    )

    assert allowed.allowed is True
    assert "free_research_contract:PASS" in allowed.checks
    assert denied.allowed is False
    assert "domain allowlist" in denied.reason


def test_level_four_without_contract_is_rejected() -> None:
    with pytest.raises(ValidationError, match="FREE_RESEARCH"):
        ToolPolicy(autonomy_level=AutonomyLevel.LEVEL_4_FREE_RESEARCH)


def test_model_cannot_be_an_autonomy_grant_source() -> None:
    with pytest.raises(ValidationError):
        AutonomyPolicy(
            task_id=uuid4(),
            level=AutonomyLevel.LEVEL_0_ADVISORY,
            grant_source="MODEL",
        )


def test_dispatcher_consumes_free_research_request_budget(tmp_path: Path) -> None:
    task_id = uuid4()
    now = datetime.now(UTC)
    spec = _spec("research.fetch", capability=ToolCapability.NETWORK)
    registry = ToolRegistry()
    registry.register(spec, _NetworkFixture())
    dispatcher = ToolDispatcher(registry)
    research = FreeResearchContract(
        task_id=task_id,
        purpose="Verify runtime request accounting.",
        allowed_tools=(spec.name,),
        allowed_domains=("example.com",),
        max_requests=1,
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=5),
    )
    policy = ToolPolicy(
        allowed_tools=(spec.name,),
        autonomy_level=AutonomyLevel.LEVEL_4_FREE_RESEARCH,
        free_research_contract=research,
    )
    contract = _contract(task_id, tmp_path, network=True)

    first = dispatcher.dispatch(
        request=_request(task_id, spec.name, url="https://example.com/one"),
        task_contract=contract,
        policy=policy,
    )
    second = dispatcher.dispatch(
        request=_request(task_id, spec.name, url="https://example.com/two"),
        task_contract=contract,
        policy=policy,
    )

    assert first.result.status.value == "SUCCESS"
    assert second.result.status.value == "BLOCKED"
    assert "request budget is exhausted" in second.result.stderr_excerpt


def test_forged_request_timestamp_cannot_bypass_expired_research_contract(
    tmp_path: Path,
) -> None:
    task_id = uuid4()
    now = datetime.now(UTC)
    spec = _spec("research.fetch", capability=ToolCapability.NETWORK)
    issued_at = now - timedelta(minutes=10)
    expires_at = now - timedelta(minutes=5)
    research = FreeResearchContract(
        task_id=task_id,
        purpose="Verify runtime clock ownership.",
        allowed_tools=(spec.name,),
        allowed_domains=("example.com",),
        issued_at=issued_at,
        expires_at=expires_at,
    )
    decision = evaluate_tool_policy(
        spec=spec,
        request=ToolRequest(
            task_id=task_id,
            trace_id=uuid4(),
            tool_name=spec.name,
            arguments={"url": "https://example.com/page"},
            expectation_id=uuid4(),
            requested_at=issued_at + timedelta(seconds=1),
        ),
        task_contract=_contract(task_id, tmp_path, network=True),
        policy=ToolPolicy(
            allowed_tools=(spec.name,),
            autonomy_level=AutonomyLevel.LEVEL_4_FREE_RESEARCH,
            free_research_contract=research,
        ),
    )

    assert decision.allowed is False
    assert "expired" in decision.reason
