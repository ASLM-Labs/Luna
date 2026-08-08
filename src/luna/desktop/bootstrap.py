"""Local-session bootstrap for the Phase 16 desktop shell."""

from __future__ import annotations

from pathlib import Path

from luna.operations import DurableTaskQueue, NotificationOutbox, SQLiteOperationsStore
from luna.runtime import RuntimeActor

from .controller import DesktopShellController
from .gateway import DesktopCommandGateway


def build_local_desktop_controller(
    *,
    workspace_root: str | Path,
    database_path: str | Path,
    actor_id: str = "desktop-local-session",
) -> DesktopShellController:
    """Create a local desktop session; model output cannot invoke this trust bootstrap."""
    root = Path(workspace_root).expanduser().resolve()
    database = Path(database_path).expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)

    store = SQLiteOperationsStore(database)
    queue = DurableTaskQueue(store)
    notifications = NotificationOutbox(store)
    actor = RuntimeActor.verified_owner(actor_id)
    gateway = DesktopCommandGateway(
        queue=queue,
        notifications=notifications,
        actor=actor,
    )
    return DesktopShellController(
        store=store,
        gateway=gateway,
        notifications=notifications,
        workspace_root=root,
    )
