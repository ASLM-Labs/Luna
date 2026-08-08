"""Read-model controller for the Phase 16 local desktop shell."""

from __future__ import annotations

from pathlib import Path

from luna.operations import (
    NotificationOutbox,
    ResourceLeaseStatus,
    ResourceUsage,
    SQLiteOperationsStore,
)

from .gateway import DesktopCommandGateway
from .models import (
    DesktopComposerDraft,
    DesktopSection,
    DesktopShellSnapshot,
)
from .presenter import (
    notification_card,
    resource_summary,
    schedule_card,
    task_cards,
)


class DesktopShellController:
    """Owns UI refresh and command routing without becoming runtime authority."""

    def __init__(
        self,
        *,
        store: SQLiteOperationsStore,
        gateway: DesktopCommandGateway,
        notifications: NotificationOutbox,
        workspace_root: str | Path,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._notifications = notifications
        self._workspace_root = str(Path(workspace_root).expanduser().resolve())
        self._selected_section = DesktopSection.CHAT

    @property
    def workspace_root(self) -> str:
        return self._workspace_root

    def select_section(self, section: DesktopSection) -> None:
        self._selected_section = section

    def submit(self, draft: DesktopComposerDraft) -> str:
        """Queue a task and return the durable item ID for UI correlation."""
        item = self._gateway.submit(draft)
        return str(item.item_id)

    def cancel_queued(self, item_id: str) -> None:
        self._gateway.cancel_queued(item_id)

    def acknowledge_notification(self, notification_id: str) -> None:
        self._gateway.acknowledge_notification(notification_id)

    def snapshot(self) -> DesktopShellSnapshot:
        """Build a fresh immutable snapshot exclusively from durable state."""
        tasks = task_cards(self._store.list_queue_items())
        schedules = tuple(schedule_card(job) for job in self._store.list_schedules())
        notifications = tuple(
            notification_card(event) for event in self._notifications.pending()
        )

        held = ResourceUsage()
        for lease in self._store.list_resource_leases():
            if lease.status is ResourceLeaseStatus.RELEASED:
                continue
            held = ResourceUsage(
                worker_slots=held.worker_slots + lease.requirement.worker_slots,
                model_slots=held.model_slots + lease.requirement.model_slots,
                network_slots=held.network_slots + lease.requirement.network_slots,
            )

        return DesktopShellSnapshot(
            selected_section=self._selected_section,
            tasks=tasks,
            notifications=notifications,
            schedules=schedules,
            resources=resource_summary(held),
            workspace_root=self._workspace_root,
        )
