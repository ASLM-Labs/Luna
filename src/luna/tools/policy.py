"""Deterministic dispatcher policy; security decisions are runtime-owned."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from luna.autonomy import AutonomyLevel
from luna.contracts.base import utc_now
from luna.contracts.enums import RiskLevel
from luna.contracts.task import TaskContract
from luna.tools.models import (
    ToolCapability,
    ToolPolicy,
    ToolRequest,
    ToolSpec,
)
from luna.tools.paths import (
    WorkspacePathError,
    canonical_workspace_path,
    path_is_allowed,
)

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
    now: datetime | None = None,
) -> PolicyDecision:
    """Run every pre-execution policy check in a fixed order."""
    checks: list[str] = []
    current_time = now or utc_now()

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

    autonomy = policy.autonomy_policy_for(request.task_id)
    if autonomy.level is AutonomyLevel.LEVEL_0_ADVISORY:
        return _denied(checks, "autonomy", "Level 0 does not permit tool execution")
    if (
        autonomy.level is AutonomyLevel.LEVEL_1_READ_ONLY
        and capabilities - {ToolCapability.READ}
    ):
        return _denied(checks, "autonomy", "Level 1 permits read-only tools")
    if (
        autonomy.level is AutonomyLevel.LEVEL_2_CONTROLLED
        and ToolCapability.NETWORK in capabilities
    ):
        return _denied(
            checks,
            "autonomy",
            "Level 2 blocks network capability",
        )
    if autonomy.level is AutonomyLevel.LEVEL_4_FREE_RESEARCH:
        contract = autonomy.free_research_contract
        if contract is None:
            return _denied(
                checks,
                "free_research_contract",
                "Level 4 requires a FREE_RESEARCH contract",
            )
        if not autonomy.research_budget_available():
            return _denied(
                checks,
                "free_research_budget",
                "FREE_RESEARCH request budget is exhausted",
            )
        if not autonomy.research_window_active(current_time):
            return _denied(
                checks,
                "free_research_window",
                "FREE_RESEARCH authorization is expired or outside its session window",
            )
        if spec.name not in contract.allowed_tools:
            return _denied(
                checks,
                "free_research_tool",
                "tool is outside the FREE_RESEARCH contract",
            )
        if ToolCapability.WRITE in capabilities:
            return _denied(
                checks,
                "free_research_write",
                "FREE_RESEARCH does not authorize workspace writes",
            )
        if ToolCapability.NETWORK in capabilities:
            target = next(
                (
                    value
                    for key, value in request.arguments.items()
                    if key in {"url", "uri", "endpoint", "host", "domain"}
                    and isinstance(value, str)
                ),
                None,
            )
            if target is None or not contract.allows_domain(target):
                return _denied(
                    checks,
                    "free_research_domain",
                    "network target is outside the FREE_RESEARCH domain allowlist",
                )
        checks.append("free_research_contract:PASS")
    if spec.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} and (
        autonomy.level not in {
            AutonomyLevel.LEVEL_3_TASK,
            AutonomyLevel.LEVEL_4_FREE_RESEARCH,
        }
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

    if ToolCapability.PROCESS in capabilities and not task_contract.scope.process_allowed:
        return _denied(checks, "process_scope", "task scope does not allow processes")
    checks.append("process_scope:PASS")

    if "path" in spec.argument_schema:
        path_value = request.arguments.get("path")
        if not isinstance(path_value, str):
            return _denied(checks, "path_scope", "tool path argument is not a string")
        try:
            canonical_workspace_path(task_contract.scope.workspace_root, path_value)
            allowed = path_is_allowed(path_value, task_contract.scope.allowed_paths)
        except WorkspacePathError as exc:
            return _denied(checks, "path_scope", str(exc))
        if not allowed:
            return _denied(checks, "path_scope", "tool path is outside allowed_paths")
    checks.append("path_scope:PASS")

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

    if ToolCapability.PROCESS in capabilities and "argv" in spec.argument_schema:
        argv_value = request.arguments.get("argv")
        if not isinstance(argv_value, list) or not all(
            isinstance(item, str) for item in argv_value
        ):
            return _denied(checks, "process_approval", "process argv is not valid")
        requested_argv = tuple(argv_value)
        matched_approval = None
        for approval in policy.process_approvals:
            try:
                approved_cwd = str(
                    canonical_workspace_path(
                        task_contract.scope.workspace_root,
                        approval.working_directory,
                    )
                )
            except WorkspacePathError:
                continue
            if approval.argv == requested_argv and approved_cwd == working_directory:
                matched_approval = approval
                break
        if matched_approval is None:
            return _denied(
                checks,
                "process_approval",
                "exact argv and working directory were not owner-approved",
            )
        if (
            matched_approval.may_write_workspace
            and not task_contract.scope.write_allowed
        ):
            return _denied(
                checks,
                "process_write_scope",
                "approved process may write the workspace but task scope does not allow writes",
            )
        checks.append("process_write_scope:PASS")
    checks.append("process_approval:PASS")

    return PolicyDecision(
        allowed=True,
        checks=tuple(checks),
        reason="all dispatcher policy checks passed",
        timeout_ms=timeout_ms,
        max_output_chars=max_output_chars,
        working_directory=working_directory,
    )
