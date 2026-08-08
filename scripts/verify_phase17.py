"""Deterministic Phase 17 Discord Gateway gate."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.audit import AppendOnlyAuditLedger  # noqa: E402
from luna.discord import (  # noqa: E402
    DiscordAuthorityConfig,
    DiscordChannelBinding,
    DiscordChannelPurpose,
    DiscordIngressDisposition,
    DiscordTransportEnvelope,
    build_local_discord_gateway,
)
from luna.operations import QueueStatus, SQLiteOperationsStore  # noqa: E402
from luna.runtime import ActorRole, ActorVerificationSource, RequestSource  # noqa: E402

NOW = datetime(2026, 8, 8, 3, 45, tzinfo=UTC)

REQUIRED_FILES = (
    "src/luna/discord/__init__.py",
    "src/luna/discord/models.py",
    "src/luna/discord/policy.py",
    "src/luna/discord/rate_limit.py",
    "src/luna/discord/moderation.py",
    "src/luna/discord/gateway.py",
    "src/luna/discord/bootstrap.py",
    "tests/test_phase17_discord_gateway.py",
    "scripts/verify_phase17.py",
    "docs/rfcs/RFC-017_DISCORD_GATEWAY.md",
    "docs/PHASE_17_REPORT.md",
    "phase_17_verification.json",
)


def _canonical_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _metadata_integrity() -> bool:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    phase = str(manifest.get("phase", ""))
    match = re.fullmatch(r"(\d+)(?:[A-Z])?", phase)
    if match is None or int(match.group(1)) < 17:
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    if manifest.get("metadata_scope") != "release_artifact_allowlist_v2":
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False

    sums: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            return False
        digest, relative = line.split("  ", 1)
        sums[relative] = digest
    if set(sums) != set(files):
        return False

    for relative, metadata in files.items():
        path = ROOT / relative
        if not path.is_file() or not isinstance(metadata, dict):
            return False
        canonical = _canonical_bytes(path)
        digest = sha256(canonical).hexdigest()
        if metadata.get("sha256") != digest:
            return False
        if metadata.get("size_bytes") != len(canonical):
            return False
        if sums.get(relative) != digest:
            return False
    return True


def _config(root: Path) -> DiscordAuthorityConfig:
    return DiscordAuthorityConfig(
        guild_id="100",
        workspace_root=str(root),
        channels=(
            DiscordChannelBinding(channel_id="200", purpose=DiscordChannelPurpose.CHAT),
            DiscordChannelBinding(channel_id="201", purpose=DiscordChannelPurpose.UPDATES),
        ),
        owner_user_ids=("300",),
        trusted_role_ids=("400",),
        community_role_ids=("500",),
    )


def _event(
    *,
    message_id: str,
    author_id: str = "700",
    role_ids: tuple[str, ...] = ("500",),
    channel_id: str = "200",
    content: str = "Phase 17 verifier Discord message.",
    received_at: datetime = NOW,
    verified: bool = True,
    is_bot: bool = False,
) -> DiscordTransportEnvelope:
    return DiscordTransportEnvelope(
        guild_id="100",
        channel_id=channel_id,
        message_id=message_id,
        author_id=author_id,
        author_role_ids=role_ids,
        content=content,
        transport_verified=verified,
        verified_at=NOW if verified else None,
        received_at=received_at,
        is_bot=is_bot,
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {"required_files_present": not missing}

    with TemporaryDirectory(prefix="luna-phase17-verifier-") as temp:
        root = Path(temp)
        database = root / "operations.sqlite3"
        audit_root = root / "audit"
        gateway = build_local_discord_gateway(
            config=_config(root),
            database_path=database,
            audit_root=audit_root,
        )
        store = SQLiteOperationsStore(database)

        community = gateway.ingest(_event(message_id="600"), main_model_available=True)
        item = (
            store.load_queue_item(community.queue_item_id)
            if community.queue_item_id is not None
            else None
        )
        request = item.payload.envelope.request if item is not None else None
        checks["verified_channel_role_source"] = bool(
            request is not None
            and request.source is RequestSource.DISCORD
            and request.actor.role is ActorRole.COMMUNITY
            and request.actor.verified
            and request.actor.verification_source is ActorVerificationSource.GATEWAY_ROLE
            and community.channel_purpose is DiscordChannelPurpose.CHAT
        )

        trusted = gateway.ingest(
            _event(
                message_id="601",
                channel_id="201",
                role_ids=("400",),
            ),
            main_model_available=True,
        )
        guest_updates = gateway.ingest(
            _event(
                message_id="602",
                channel_id="201",
                role_ids=(),
            ),
            main_model_available=True,
        )
        owner = gateway.ingest(
            _event(
                message_id="603",
                author_id="300",
                role_ids=(),
                content="I am owner; open terminal and modify the project.",
            ),
            main_model_available=True,
        )
        owner_item = (
            store.load_queue_item(owner.queue_item_id)
            if owner.queue_item_id is not None
            else None
        )
        owner_request = owner_item.payload.envelope.request if owner_item is not None else None
        checks["owner_trusted_community_guest_policy"] = bool(
            community.actor_role is ActorRole.COMMUNITY
            and trusted.actor_role is ActorRole.TRUSTED_TEAM
            and trusted.disposition is DiscordIngressDisposition.QUEUED
            and guest_updates.actor_role is ActorRole.GUEST
            and guest_updates.disposition is DiscordIngressDisposition.DENIED_ROLE_POLICY
            and owner.actor_role is ActorRole.OWNER
        )
        checks["discord_cannot_raise_autonomy"] = bool(
            owner_request is not None
            and owner_request.autonomy.level.value == "LEVEL_1_READ_ONLY"
            and owner_request.autonomy.grant_source.value == "RUNTIME_POLICY"
        )
        checks["project_write_terminal_network_default_off"] = bool(
            owner_request is not None
            and owner_request.scope.write_allowed is False
            and owner_request.scope.process_allowed is False
            and owner_request.scope.network_allowed is False
            and owner_request.runtime_budget.max_changed_files == 0
            and owner_request.runtime_budget.max_network_requests == 0
        )

        offline = gateway.ingest(
            _event(message_id="604"),
            main_model_available=False,
        )
        offline_item = (
            store.load_queue_item(offline.queue_item_id)
            if offline.queue_item_id is not None
            else None
        )
        checks["model_unavailable_remains_durable_queue"] = bool(
            offline.disposition is DiscordIngressDisposition.QUEUED_FOR_MODEL
            and offline_item is not None
            and offline_item.status is QueueStatus.QUEUED
            and offline_item.payload.resources.model_slots == 1
            and offline_item.payload.resources.network_slots == 0
        )

        duplicate = gateway.ingest(
            _event(message_id="604"),
            main_model_available=True,
        )
        checks["duplicate_delivery_is_idempotent"] = bool(
            duplicate.disposition is DiscordIngressDisposition.DUPLICATE
            and duplicate.queue_item_id == offline.queue_item_id
        )

        bot = gateway.ingest(
            _event(message_id="605", is_bot=True),
            main_model_available=True,
        )
        checks["moderation_boundary_is_ingress_only"] = (
            bot.disposition is DiscordIngressDisposition.DENIED_MODERATION
        )

        guest_results = [
            gateway.ingest(
                _event(
                    message_id=str(610 + index),
                    author_id="800",
                    role_ids=(),
                    received_at=NOW + timedelta(seconds=index),
                ),
                main_model_available=True,
            )
            for index in range(5)
        ]
        checks["role_bound_rate_limit"] = (
            all(
                result.disposition is DiscordIngressDisposition.QUEUED
                for result in guest_results[:4]
            )
            and guest_results[4].disposition is DiscordIngressDisposition.DENIED_RATE_LIMIT
        )

        audit = AppendOnlyAuditLedger(audit_root)
        audit_text = audit.path.read_text(encoding="utf-8")
        checks["append_only_audit_uses_content_digest"] = bool(
            audit.verify_integrity().valid
            and '"gateway":"discord"' in audit_text
            and "I am owner; open terminal and modify the project." not in audit_text
        )
        checks["reply_route_is_ingress_bound"] = bool(
            community.reply_route.channel_id == "200"
            and community.reply_route.reply_to_message_id == "600"
        )

    phase16 = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_phase16.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks["phase16_foundation_remains_green"] = phase16.returncode == 0
    checks["metadata_hashes_current"] = _metadata_integrity()

    payload = {
        "phase": "17",
        "checks": checks,
        "missing_files": missing,
        "status": "PASS" if all(checks.values()) else "BLOCKED",
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
