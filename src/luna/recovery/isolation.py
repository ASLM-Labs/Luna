"""Risk-based workspace isolation policy for Phase 12D."""

from __future__ import annotations

from luna.contracts.enums import RiskLevel
from luna.contracts.task import TaskContract
from luna.recovery.models import ChangeEstimate, IsolationDecision, IsolationMode

_WORKTREE_RISKS = {RiskLevel.HIGH, RiskLevel.CRITICAL}


class WorkspaceIsolationPolicy:
    """Select isolation strength without creating snapshots or worktrees itself."""

    def plan(
        self,
        *,
        task_contract: TaskContract,
        change: ChangeEstimate | None,
        worktree_available: bool,
    ) -> IsolationDecision:
        if change is None:
            return IsolationDecision(
                allowed=True,
                mode=IsolationMode.NONE,
                risk_level=task_contract.risk_level,
                checks=("workspace_mutation:NONE",),
                reason="no workspace mutation is proposed",
            )

        checks = ["workspace_mutation:PRESENT"]
        if not task_contract.scope.write_allowed:
            return IsolationDecision(
                allowed=False,
                mode=IsolationMode.NONE,
                risk_level=task_contract.risk_level,
                checks=(*checks, "write_scope:FAIL"),
                reason="workspace isolation cannot authorize a task with write disabled",
            )
        checks.append("write_scope:PASS")

        if task_contract.risk_level in _WORKTREE_RISKS and not worktree_available:
            return IsolationDecision(
                allowed=False,
                mode=IsolationMode.WORKTREE,
                risk_level=task_contract.risk_level,
                checks=(*checks, "worktree_available:FAIL"),
                reason="high-risk workspace mutation requires worktree isolation",
                worktree_required=True,
                clean_workspace_required=True,
            )

        if task_contract.risk_level in _WORKTREE_RISKS:
            return IsolationDecision(
                allowed=True,
                mode=IsolationMode.WORKTREE,
                risk_level=task_contract.risk_level,
                checks=(*checks, "worktree_available:PASS"),
                reason="high-risk workspace mutation requires isolated worktree execution",
                worktree_required=True,
                clean_workspace_required=True,
            )

        return IsolationDecision(
            allowed=True,
            mode=IsolationMode.SNAPSHOT,
            risk_level=task_contract.risk_level,
            checks=(*checks, "snapshot_required:PASS"),
            reason="low/medium-risk mutation uses snapshot-first workspace protection",
            snapshot_required=True,
        )
