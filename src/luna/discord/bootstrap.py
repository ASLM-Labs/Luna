"""Local construction helpers for the Phase 17 Discord gateway."""

from __future__ import annotations

from pathlib import Path

from luna.audit import AppendOnlyAuditLedger
from luna.operations import DurableTaskQueue, SQLiteOperationsStore

from .gateway import DiscordGateway
from .models import DiscordAuthorityConfig


def build_local_discord_gateway(
    *,
    config: DiscordAuthorityConfig,
    database_path: str | Path,
    audit_root: str | Path,
) -> DiscordGateway:
    """Build the transport-neutral gateway over Phase 15 durable operations + audit."""
    store = SQLiteOperationsStore(database_path)
    return DiscordGateway(
        config=config,
        queue=DurableTaskQueue(store),
        audit=AppendOnlyAuditLedger(audit_root),
    )
