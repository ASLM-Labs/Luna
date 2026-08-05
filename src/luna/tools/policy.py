"""Deterministic dispatcher policy; security decisions are runtime-owned."""

from __future__ import annotations

from dataclasses import dataclass

from luna.contracts.enums import RiskLevel
from luna.contracts.task import TaskContract
from luna.tools.models import (
    AutonomyLevel,
    ToolCapability,
    ToolPolicy,
    ToolRequest,
    ToolSpec,
)
from luna.tools.paths import WorkspacePathError, canonical_workspace_path


_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    checks: tuple[str, ...]
    reason: str
    timeout_ms: int
    max_output_chars: int
    working_directory: str | None


def _denied(checks: list[str], check: str, reason: str) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        checks=tuple([*checks, f"{check}:FAIL"]),
        reason=reason,
        timeout_ms=0,
        max_output_chars=0,
        working_directory=None,
    )


def evaluate_tool_policy(
    *,
    spec: ToolSpec,
    request: ToolRequest,
    task_contract: TaskContract,
    policy: ToolPolicy,
) -> PolicyDecision:
    """Run every pre-execution policy check in a fixed order."""
    checks: list[str] = []

    if request.task_id != task_contract.task_id:
        return _denied(checks, "task_id", "task_id does not match contract")
    checks.append("task_id:PASS")

    if spec.name not in policy.allowed_tools:
        return _denied(checks, "tool_permission", "tool is not explicitly allowed")
    checks.append("tool_permission:PASS")

    if _RISK_ORDER[spec.risk_level] > _RISK_ORDER[policy.max_risk]:
        return _denied(checks, "risk_budget", "tool risk exceeds policy")
    checks.append("risk_budget:PASS")

    capabilities = set(spec.capabilities)
    high_impact_capabilities = {
        ToolCapability.WRITE,
        ToolCapability.NETWORK,
        ToolCapability.PROCESS,
    }
    if capabilities & high_impact_capabilities and request.expectation_id is None:
        return _denied(
            checks,
            "expected_observation",
            "high-impact tool request requires expectation_id",
        )
    checks.append("expected_observation:PASS")

    if (
        policy.autonomy_level is AutonomyLevel.OBSERVE_ONLY
        and capabilities - {ToolCapability.READ}
    ):
        return _denied(
            checks,
            "autonomy",
            "autonomy level permits read-only tools",
        )
    if spec.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} and (
        policy.autonomy_level is not AutonomyLevel.OWNER_APPROVED
        or spec.name not in policy.owner_approved_tools
    ):
        return _denied(
            checks,
            "owner_approval",
            "high-risk tool lacks explicit owner approval",
        )
    checks.append("autonomy:PASS")

    if ToolCapability.WRITE in capabilities and not task_contract.scope.write_allowed:
        return _denied(checks, "write_scope", "task scope does not allow writes")
    checks.append("write_scope:PASS")

    if ToolCapability.NETWORK in capabilities and not task_contract.scope.network_allowed:
        return _denied(checks, "network_scope", "task scope does not allow network")
    checks.append("network_scope:PASS")

    timeout_ms = request.timeout_ms or spec.default_timeout_ms
    timeout_ceiling = min(spec.max_timeout_ms, policy.max_timeout_ms)
    if timeout_ms > timeout_ceiling:
        return _denied(checks, "timeout_budget", "requested timeout exceeds budget")
    checks.append("timeout_budget:PASS")

    max_output_chars = request.max_output_chars or min(
        spec.max_output_chars,
        policy.max_output_chars,
    )
    output_ceiling = min(spec.max_output_chars, policy.max_output_chars)
    if max_output_chars > output_ceiling:
        return _denied(checks, "output_budget", "requested output exceeds budget")
    checks.append("output_budget:PASS")

    working_directory: str | None = None
    if spec.requires_working_directory and request.working_directory is None:
        return _denied(
            checks,
            "working_directory",
            "tool requires a working directory",
        )
    if request.working_directory is not None:
        try:
            working_directory = str(
                canonical_workspace_path(
                    task_contract.scope.workspace_root,
                    request.working_directory,
                )
            )
        except WorkspacePathError as exc:
            return _denied(checks, "working_directory", str(exc))
    checks.append("working_directory:PASS")

    return PolicyDecision(
        allowed=True,
        checks=tuple(checks),
        reason="all dispatcher policy checks passed",
        timeout_ms=timeout_ms,
        max_output_chars=max_output_chars,
        working_directory=working_directory,
    )
