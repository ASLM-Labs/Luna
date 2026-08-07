"""Deterministic recovery policy for Phase 12D failure categories."""

from __future__ import annotations

from luna.planning import RetryDecision, RetryReason
from luna.recovery.models import (
    FailureCategory,
    FailureRecord,
    RecoveryAction,
    RecoveryDecision,
)


class RecoveryPolicy:
    """Choose retry, replan, rollback, approval, suspension, or stop without guessing."""

    def decide(
        self,
        *,
        failure: FailureRecord,
        retry_decision: RetryDecision | None = None,
        mutation_active: bool = False,
    ) -> RecoveryDecision:
        category = failure.category

        if category is FailureCategory.INTEGRITY_FAILURE:
            return self._decision(
                failure,
                RecoveryAction.STOP,
                "integrity failure requires an immediate safe stop",
            )
        if category is FailureCategory.BUDGET_EXHAUSTED:
            return self._decision(
                failure,
                RecoveryAction.STOP,
                "hard runtime budget is exhausted; policy cannot self-extend it",
            )
        if category is FailureCategory.RESOURCE_UNAVAILABLE:
            return self._decision(
                failure,
                RecoveryAction.SUSPEND,
                "required runtime resource is unavailable; suspend instead of blind retry",
            )
        if category is FailureCategory.PERMISSION_OR_SCOPE_DENIED:
            return RecoveryDecision(
                failure_id=failure.failure_id,
                action=RecoveryAction.REQUEST_APPROVAL,
                reason="permission or scope denial requires explicit owner/runtime authority",
                owner_action_required=True,
            )
        if category is FailureCategory.STALE_STATE:
            return self._decision(
                failure,
                RecoveryAction.REINSPECT,
                "stale state requires a fresh observation before another action",
            )
        if category is FailureCategory.VERIFICATION_FAILURE:
            if mutation_active:
                return RecoveryDecision(
                    failure_id=failure.failure_id,
                    action=RecoveryAction.ROLLBACK,
                    reason="verification failed after mutation; restore the pre-change state",
                    rollback_required=True,
                )
            return self._decision(
                failure,
                RecoveryAction.REPLAN,
                "verification failed without an active mutation; revise the plan",
            )
        if category is FailureCategory.TRANSIENT_ENVIRONMENT:
            if (
                retry_decision is not None
                and retry_decision.allowed
                and retry_decision.reason is RetryReason.CHANGED_BASIS
            ):
                return RecoveryDecision(
                    failure_id=failure.failure_id,
                    action=RecoveryAction.RETRY,
                    reason="transient failure may retry only because the attempt basis changed",
                    retry_reason=retry_decision.reason,
                    changed_dimensions=retry_decision.changed_dimensions,
                )
            return self._decision(
                failure,
                RecoveryAction.REPLAN,
                "transient label alone does not authorize retry without a changed basis",
            )
        if category in {
            FailureCategory.INVALID_ACTION,
            FailureCategory.DETERMINISTIC_EXECUTION,
            FailureCategory.UNKNOWN_FAILURE,
        }:
            return self._decision(
                failure,
                RecoveryAction.REPLAN,
                "failure requires a revised action or plan rather than repeating the same call",
            )
        raise AssertionError(f"unmapped failure category: {category}")

    @staticmethod
    def _decision(
        failure: FailureRecord,
        action: RecoveryAction,
        reason: str,
    ) -> RecoveryDecision:
        return RecoveryDecision(
            failure_id=failure.failure_id,
            action=action,
            reason=reason,
        )
