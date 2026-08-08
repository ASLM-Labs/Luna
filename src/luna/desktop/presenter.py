"""Presentation mapping from Phase 15 durable state to Phase 16 desktop cards."""

from __future__ import annotations

from collections.abc import Iterable

from luna.operations import (
    NotificationEvent,
    NotificationKind,
    NotificationStatus,
    QueueItem,
    QueueStatus,
    ResourceUsage,
    ScheduledJob,
)
from luna.runtime import RuntimeStopReason

from .models import (
    DesktopNotificationCard,
    DesktopResourceSummary,
    DesktopScheduleCard,
    DesktopTaskCard,
    DesktopTaskState,
    DesktopTone,
)


def _task_title(item: QueueItem) -> str:
    return item.payload.envelope.request.raw_request.strip()[:500]


def _terminal_card(item: QueueItem) -> DesktopTaskCard:
    outcome = item.outcome
    if outcome is None:
        if item.status is QueueStatus.CANCELLED:
            return DesktopTaskCard(
                item_id=item.item_id,
                task_id=item.payload.envelope.request.task_id,
                title=_task_title(item),
                state=DesktopTaskState.CANCELLED,
                tone=DesktopTone.NEUTRAL,
                state_label="İptal edildi",
                updated_at=item.updated_at,
            )
        raise ValueError("terminal desktop card requires a durable RuntimeOutcome or cancellation")

    verified_complete = (
        outcome.stop_reason is RuntimeStopReason.COMPLETED
        and outcome.completion_status is not None
        and outcome.completion_status.value == "VERIFIED_COMPLETE"
        and outcome.verification_report_id is not None
        and outcome.final_report_id is not None
    )
    if verified_complete:
        state = DesktopTaskState.VERIFIED_COMPLETE
        tone = DesktopTone.SUCCESS
        label = "Doğrulandı"
    elif outcome.stop_reason is RuntimeStopReason.CANCELLED:
        state = DesktopTaskState.CANCELLED
        tone = DesktopTone.NEUTRAL
        label = "İptal edildi"
    elif outcome.stop_reason in {
        RuntimeStopReason.SUSPENDED,
        RuntimeStopReason.RESOURCE_SUSPENDED,
        RuntimeStopReason.VERIFICATION_PENDING,
        RuntimeStopReason.UNVERIFIED,
        RuntimeStopReason.INCONCLUSIVE,
    }:
        state = DesktopTaskState.SUSPENDED
        tone = DesktopTone.WARNING
        label = "Devam için bekliyor"
    elif outcome.stop_reason in {
        RuntimeStopReason.BLOCKED,
        RuntimeStopReason.PERMISSION_DENIED,
        RuntimeStopReason.CONFLICTING_EVIDENCE,
        RuntimeStopReason.CONTEXT_INCOMPLETE,
        RuntimeStopReason.CLARIFICATION_REQUIRED,
    }:
        state = DesktopTaskState.BLOCKED
        tone = DesktopTone.WARNING
        label = "Dikkat gerekiyor"
    else:
        state = DesktopTaskState.FAILED
        tone = DesktopTone.DANGER
        label = "Başarısız"

    return DesktopTaskCard(
        item_id=item.item_id,
        task_id=outcome.task_id,
        title=_task_title(item),
        state=state,
        tone=tone,
        state_label=label,
        stop_reason=outcome.stop_reason.value,
        completion_status=(
            outcome.completion_status.value if outcome.completion_status is not None else None
        ),
        verification_report_id=outcome.verification_report_id,
        final_report_id=outcome.final_report_id,
        evidence_count=len(outcome.evidence_ids),
        observation_count=len(outcome.observation_ids),
        unresolved_uncertainty=outcome.unresolved_uncertainty,
        updated_at=item.updated_at,
    )


def task_card(item: QueueItem) -> DesktopTaskCard:
    """Map one durable queue item without inventing completion."""
    if item.status in {
        QueueStatus.COMPLETED,
        QueueStatus.SUSPENDED,
        QueueStatus.BLOCKED,
        QueueStatus.FAILED,
        QueueStatus.CANCELLED,
    }:
        return _terminal_card(item)

    mapping = {
        QueueStatus.QUEUED: (
            DesktopTaskState.QUEUED,
            DesktopTone.NEUTRAL,
            "Sırada",
        ),
        QueueStatus.LEASED: (
            DesktopTaskState.WORKING,
            DesktopTone.INFO,
            "Kaynak bekleniyor",
        ),
        QueueStatus.DISPATCHED: (
            DesktopTaskState.WORKING,
            DesktopTone.INFO,
            "Çalışıyor",
        ),
        QueueStatus.RECOVERY_REQUIRED: (
            DesktopTaskState.RECOVERY_REQUIRED,
            DesktopTone.WARNING,
            "Kurtarma gerekiyor",
        ),
    }
    state, tone, label = mapping[item.status]
    return DesktopTaskCard(
        item_id=item.item_id,
        task_id=item.payload.envelope.request.task_id,
        title=_task_title(item),
        state=state,
        tone=tone,
        state_label=label,
        updated_at=item.updated_at,
    )


def task_cards(items: Iterable[QueueItem]) -> tuple[DesktopTaskCard, ...]:
    """Newest-first user-facing task cards."""
    return tuple(
        task_card(item)
        for item in sorted(items, key=lambda item: item.updated_at, reverse=True)
    )


def notification_card(event: NotificationEvent) -> DesktopNotificationCard:
    """Render a local outbox event without adding transport claims."""
    tone = {
        NotificationKind.TASK_VERIFIED_COMPLETE: DesktopTone.SUCCESS,
        NotificationKind.TASK_REQUIRES_ATTENTION: DesktopTone.WARNING,
        NotificationKind.TASK_CANCELLED: DesktopTone.NEUTRAL,
    }[event.kind]
    return DesktopNotificationCard(
        notification_id=event.notification_id,
        task_id=event.task_id,
        kind=event.kind.value,
        message=event.message,
        tone=tone,
        acknowledged=event.status is NotificationStatus.ACKNOWLEDGED,
        external_delivery_allowed=event.external_delivery_allowed,
        created_at=event.created_at,
    )


def schedule_card(job: ScheduledJob) -> DesktopScheduleCard:
    """Render schedule state; scheduler eligibility remains non-authoritative."""
    return DesktopScheduleCard(
        schedule_id=job.schedule_id,
        title=job.envelope.request.raw_request.strip()[:500],
        kind=job.spec.kind.value,
        next_run_at=job.next_run_at,
        occurrence_count=job.occurrence_count,
        enabled=job.enabled,
    )


def resource_summary(usage: ResourceUsage) -> DesktopResourceSummary:
    """Render held capacity without treating capacity as permission."""
    return DesktopResourceSummary(
        worker_slots_held=usage.worker_slots,
        model_slots_held=usage.model_slots,
        network_slots_held=usage.network_slots,
    )
