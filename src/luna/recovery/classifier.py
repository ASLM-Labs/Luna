"""Deterministic Phase 12D failure classification from structured runtime evidence."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from luna.actions import ActionDenial, ActionDenialCode
from luna.contracts.enums import ObservationStatus
from luna.contracts.observation import Observation
from luna.recovery.models import FailureCategory, FailureRecord, FailureSource
from luna.tools import ToolResult, ToolResultStatus

_INVALID_ACTION_CODES = {
    ActionDenialCode.MULTIPLE_SIDE_EFFECTS,
    ActionDenialCode.INVALID_FAMILY,
    ActionDenialCode.NO_MATCHING_TOOL,
    ActionDenialCode.AMBIGUOUS_TOOL,
    ActionDenialCode.UNKNOWN_PREFERRED_TOOL,
    ActionDenialCode.PREFERRED_TOOL_MISMATCH,
    ActionDenialCode.INVALID_ARGUMENTS,
}

_DEFAULT_TRANSIENT_ERROR_CLASSES = (
    "ConnectionError",
    "ResourceBusyError",
    "TemporaryError",
    "TimeoutError",
)


class FailureClassifier:
    """Classify only structured signals; arbitrary model prose cannot declare transience."""

    def __init__(
        self,
        *,
        transient_error_classes: Iterable[str] = _DEFAULT_TRANSIENT_ERROR_CLASSES,
    ) -> None:
        cleaned = tuple(
            sorted(
                {
                    value.strip()
                    for value in transient_error_classes
                    if value.strip()
                }
            )
        )
        if not cleaned:
            raise ValueError("transient error class allowlist must not be empty")
        self._transient_error_classes = frozenset(cleaned)

    def from_action_denial(self, denial: ActionDenial) -> FailureRecord:
        """Convert Phase 12C structured denial into one stable failure category."""
        if denial.code in _INVALID_ACTION_CODES:
            return FailureRecord(
                task_id=denial.task_id,
                trace_id=denial.trace_id,
                source=FailureSource.ACTION_DENIAL,
                category=FailureCategory.INVALID_ACTION,
                reason=denial.reason,
                source_ref=str(denial.denial_id),
            )
        if denial.code is ActionDenialCode.POLICY_DENIED:
            return FailureRecord(
                task_id=denial.task_id,
                trace_id=denial.trace_id,
                source=FailureSource.ACTION_DENIAL,
                category=FailureCategory.PERMISSION_OR_SCOPE_DENIED,
                reason=denial.reason,
                source_ref=str(denial.denial_id),
                owner_action_required=True,
            )
        raise AssertionError(f"unmapped action denial code: {denial.code}")

    def from_tool_result(
        self,
        *,
        task_id: UUID,
        trace_id: UUID,
        result: ToolResult,
    ) -> FailureRecord:
        """Classify a failed or blocked ToolResult without interpreting free-form stderr."""
        if result.status is ToolResultStatus.SUCCESS:
            raise ValueError("successful ToolResult is not a failure")

        error_class = result.error_class
        if result.status is ToolResultStatus.BLOCKED:
            return FailureRecord(
                task_id=task_id,
                trace_id=trace_id,
                source=FailureSource.TOOL_RESULT,
                category=FailureCategory.PERMISSION_OR_SCOPE_DENIED,
                reason="tool dispatcher blocked the request",
                source_ref=str(result.result_id),
                error_class=error_class,
                owner_action_required=True,
            )

        if error_class in self._transient_error_classes:
            return FailureRecord(
                task_id=task_id,
                trace_id=trace_id,
                source=FailureSource.TOOL_RESULT,
                category=FailureCategory.TRANSIENT_ENVIRONMENT,
                reason="tool failed with a runtime-approved transient error class",
                source_ref=str(result.result_id),
                error_class=error_class,
                retryable=True,
                requires_changed_basis=True,
            )

        return FailureRecord(
            task_id=task_id,
            trace_id=trace_id,
            source=FailureSource.TOOL_RESULT,
            category=FailureCategory.DETERMINISTIC_EXECUTION,
            reason="tool failed without an approved transient classification",
            source_ref=str(result.result_id),
            error_class=error_class,
        )

    @staticmethod
    def from_observation(
        *,
        task_id: UUID,
        observation: Observation,
    ) -> FailureRecord:
        """Classify a normalized observation when richer tool evidence is unavailable."""
        if observation.status is ObservationStatus.SUCCESS:
            raise ValueError("successful observation is not a failure")
        return FailureRecord(
            task_id=task_id,
            trace_id=observation.trace_id,
            source=FailureSource.OBSERVATION,
            category=FailureCategory.UNKNOWN_FAILURE,
            reason=(
                "normalized observation reports a non-success outcome without "
                "a richer structured cause"
            ),
            source_ref=str(observation.observation_id),
        )

    @staticmethod
    def stale_state(*, task_id: UUID, trace_id: UUID, reason: str) -> FailureRecord:
        return FailureRecord(
            task_id=task_id,
            trace_id=trace_id,
            source=FailureSource.WORKSPACE,
            category=FailureCategory.STALE_STATE,
            reason=reason,
        )

    @staticmethod
    def verification_failure(
        *,
        task_id: UUID,
        trace_id: UUID,
        reason: str,
    ) -> FailureRecord:
        return FailureRecord(
            task_id=task_id,
            trace_id=trace_id,
            source=FailureSource.VERIFICATION,
            category=FailureCategory.VERIFICATION_FAILURE,
            reason=reason,
            rollback_recommended=True,
        )

    @staticmethod
    def integrity_failure(
        *,
        task_id: UUID,
        trace_id: UUID,
        reason: str,
    ) -> FailureRecord:
        return FailureRecord(
            task_id=task_id,
            trace_id=trace_id,
            source=FailureSource.RUNTIME,
            category=FailureCategory.INTEGRITY_FAILURE,
            reason=reason,
            integrity_critical=True,
        )

    @staticmethod
    def budget_exhausted(
        *,
        task_id: UUID,
        trace_id: UUID,
        reason: str,
    ) -> FailureRecord:
        return FailureRecord(
            task_id=task_id,
            trace_id=trace_id,
            source=FailureSource.RUNTIME,
            category=FailureCategory.BUDGET_EXHAUSTED,
            reason=reason,
        )

    @staticmethod
    def resource_unavailable(
        *,
        task_id: UUID,
        trace_id: UUID,
        reason: str,
    ) -> FailureRecord:
        return FailureRecord(
            task_id=task_id,
            trace_id=trace_id,
            source=FailureSource.RUNTIME,
            category=FailureCategory.RESOURCE_UNAVAILABLE,
            reason=reason,
        )
