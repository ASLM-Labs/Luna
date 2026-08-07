"""Hard minimal-change and scope-creep policy for Phase 12D."""

from __future__ import annotations

from luna.contracts.task import TaskScope
from luna.recovery.models import (
    ChangeEstimate,
    MinimalChangeDecision,
    MinimalChangeDenialCode,
)
from luna.runtime import RuntimeBudget
from luna.tools.paths import path_is_allowed


def _deny(
    checks: list[str],
    check: str,
    reason: str,
    code: MinimalChangeDenialCode,
) -> MinimalChangeDecision:
    return MinimalChangeDecision(
        allowed=False,
        checks=tuple([*checks, f"{check}:FAIL"]),
        reason=reason,
        denial_code=code,
    )


class MinimalChangePolicy:
    """Enforce explicit path and line budgets before and after workspace mutation."""

    def evaluate_declared(
        self,
        *,
        estimate: ChangeEstimate,
        scope: TaskScope,
        budget: RuntimeBudget,
    ) -> MinimalChangeDecision:
        checks: list[str] = []

        if not scope.write_allowed:
            return _deny(
                checks,
                "write_scope",
                "task scope does not permit workspace writes",
                MinimalChangeDenialCode.WRITE_NOT_ALLOWED,
            )
        checks.append("write_scope:PASS")

        outside = tuple(
            path
            for path in estimate.touched_paths
            if not path_is_allowed(path, scope.allowed_paths)
        )
        if outside:
            return _deny(
                checks,
                "allowed_paths",
                "declared change contains a path outside allowed_paths",
                MinimalChangeDenialCode.OUTSIDE_ALLOWED_PATHS,
            )
        checks.append("allowed_paths:PASS")

        protected = tuple(
            path
            for path in estimate.touched_paths
            if scope.protected_paths and path_is_allowed(path, scope.protected_paths)
        )
        if protected:
            return _deny(
                checks,
                "protected_paths",
                "declared change touches a protected path",
                MinimalChangeDenialCode.PROTECTED_PATH,
            )
        checks.append("protected_paths:PASS")

        if estimate.changed_files > budget.max_changed_files:
            return _deny(
                checks,
                "file_budget",
                "declared changed-file count exceeds runtime budget",
                MinimalChangeDenialCode.FILE_BUDGET_EXCEEDED,
            )
        checks.append("file_budget:PASS")

        if estimate.added_lines > budget.max_added_lines:
            return _deny(
                checks,
                "added_line_budget",
                "declared added-line count exceeds runtime budget",
                MinimalChangeDenialCode.ADDED_LINE_BUDGET_EXCEEDED,
            )
        checks.append("added_line_budget:PASS")

        if estimate.deleted_lines > budget.max_deleted_lines:
            return _deny(
                checks,
                "deleted_line_budget",
                "declared deleted-line count exceeds runtime budget",
                MinimalChangeDenialCode.DELETED_LINE_BUDGET_EXCEEDED,
            )
        checks.append("deleted_line_budget:PASS")

        if not estimate.has_effect:
            return _deny(
                checks,
                "meaningful_effect",
                "declared mutation has no line-level effect",
                MinimalChangeDenialCode.NO_EFFECT,
            )
        checks.append("meaningful_effect:PASS")

        return MinimalChangeDecision(
            allowed=True,
            checks=tuple(checks),
            reason="declared change stays inside scope and hard runtime budgets",
        )

    def evaluate_observed(
        self,
        *,
        approved: ChangeEstimate,
        observed: ChangeEstimate,
        scope: TaskScope,
        budget: RuntimeBudget,
    ) -> MinimalChangeDecision:
        base = self.evaluate_declared(estimate=observed, scope=scope, budget=budget)
        if not base.allowed:
            return base

        checks = list(base.checks)
        approved_paths = set(approved.touched_paths)
        observed_paths = set(observed.touched_paths)
        if not observed_paths.issubset(approved_paths):
            return _deny(
                checks,
                "declared_scope",
                "observed mutation expanded beyond the approved path set",
                MinimalChangeDenialCode.UNDECLARED_SCOPE_GROWTH,
            )
        checks.append("declared_scope:PASS")

        if (
            observed.added_lines > approved.added_lines
            or observed.deleted_lines > approved.deleted_lines
        ):
            return _deny(
                checks,
                "declared_line_budget",
                "observed mutation exceeded the approved line-change estimate",
                MinimalChangeDenialCode.UNDECLARED_LINE_GROWTH,
            )
        checks.append("declared_line_budget:PASS")

        return MinimalChangeDecision(
            allowed=True,
            checks=tuple(checks),
            reason="observed mutation stays within approved scope and declared change size",
        )
