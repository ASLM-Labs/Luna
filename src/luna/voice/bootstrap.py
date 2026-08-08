"""Local construction helpers for the Phase 18 Voice Gateway."""

from __future__ import annotations

from pathlib import Path

from luna.audit import AppendOnlyAuditLedger
from luna.operations import DurableTaskQueue, SQLiteOperationsStore

from .gateway import VoiceGateway
from .models import VoiceAuthorityConfig


def build_local_voice_gateway(
    *,
    config: VoiceAuthorityConfig,
    database_path: str | Path,
    audit_root: str | Path,
) -> VoiceGateway:
    """Build provider-neutral voice ingress over the durable queue and audit ledger."""
    store = SQLiteOperationsStore(database_path)
    return VoiceGateway(
        config=config,
        queue=DurableTaskQueue(store),
        audit=AppendOnlyAuditLedger(audit_root),
    )
