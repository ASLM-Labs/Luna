"""Blind-retry prevention based on explicit attempt conditions."""

from __future__ import annotations

from collections.abc import Iterable

from luna.contracts.enums import ObservationStatus
from luna.planning.models import (
    AttemptBasis,
    AttemptRecord,
    RetryDecision,
    RetryReason,
)


class RetryGuard:
    """Allow retries only when the action or its observable basis changes."""

    @staticmethod
    def _changed_dimensions(previous: AttemptBasis, current: AttemptBasis) -> tuple[str, ...]:
        changed: list[str] = []
        if previous.context_fingerprint != current.context_fingerprint:
            changed.append("context")
        if previous.evidence_refs != current.evidence_refs:
            changed.append("evidence")
        if previous.assumption_revision != current.assumption_revision:
            changed.append("assumption")
        if previous.execution_strategy != current.execution_strategy:
            changed.append("execution_strategy")
        if previous.verification_strategy != current.verification_strategy:
            changed.append("verification_strategy")
        if previous.scope_fingerprint != current.scope_fingerprint:
            changed.append("scope")
        return tuple(changed)

    def evaluate(
        self,
        candidate: AttemptBasis,
        history: Iterable[AttemptRecord],
    ) -> RetryDecision:
        same_action = [
            attempt
            for attempt in history
            if attempt.basis.action_key == candidate.action_key
        ]
        if not same_action:
            return RetryDecision(
                allowed=True,
                reason=RetryReason.FRESH_ACTION,
            )

        same_action.sort(key=lambda attempt: attempt.recorded_at)
        latest = same_action[-1]
        exact_match = next(
            (
                attempt
                for attempt in reversed(same_action)
                if attempt.basis.fingerprint() == candidate.fingerprint()
            ),
            None,
        )
        if exact_match is not None:
            if exact_match.outcome is ObservationStatus.SUCCESS:
                return RetryDecision(
                    allowed=False,
                    reason=RetryReason.ALREADY_SUCCEEDED,
                    matching_attempt_id=exact_match.attempt_id,
                )
            return RetryDecision(
                allowed=False,
                reason=RetryReason.BLIND_RETRY_BLOCKED,
                matching_attempt_id=exact_match.attempt_id,
            )

        changed = self._changed_dimensions(latest.basis, candidate)
        if not changed:
            return RetryDecision(
                allowed=False,
                reason=RetryReason.BLIND_RETRY_BLOCKED,
                matching_attempt_id=latest.attempt_id,
            )
        return RetryDecision(
            allowed=True,
            reason=RetryReason.CHANGED_BASIS,
            matching_attempt_id=latest.attempt_id,
            changed_dimensions=changed,
        )
