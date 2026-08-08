"""Deterministic Phase 18 Voice Gateway gate."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.audit import AppendOnlyAuditLedger  # noqa: E402
from luna.operations import QueueStatus, SQLiteOperationsStore  # noqa: E402
from luna.runtime import ActorRole, ActorVerificationSource, RequestSource  # noqa: E402
from luna.voice import (  # noqa: E402
    ScriptedSpeechToTextAdapter,
    UnboundTextToSpeechAdapter,
    VoiceActionClass,
    VoiceAuthorityConfig,
    VoiceCaptureMode,
    VoiceConfirmationEvent,
    VoiceIngressDisposition,
    VoiceTranscriptPacket,
    VoiceUtteranceKind,
    build_local_voice_gateway,
)

NOW = datetime(2026, 8, 8, 6, 30, tzinfo=UTC)

REQUIRED_FILES = (
    "src/luna/voice/__init__.py",
    "src/luna/voice/models.py",
    "src/luna/voice/adapters.py",
    "src/luna/voice/session.py",
    "src/luna/voice/confirmation.py",
    "src/luna/voice/gateway.py",
    "src/luna/voice/bootstrap.py",
    "tests/test_phase18_voice_gateway.py",
    "scripts/verify_phase18.py",
    "docs/rfcs/RFC-018_VOICE_GATEWAY.md",
    "docs/PHASE_18_REPORT.md",
    "phase_18_verification.json",
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
    if match is None or int(match.group(1)) < 18:
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
        if not isinstance(relative, str) or not isinstance(metadata, dict):
            return False
        path = ROOT / relative
        if not path.is_file():
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


def _packet(*, session_id, action_class: VoiceActionClass, text: str) -> VoiceTranscriptPacket:
    return VoiceTranscriptPacket(
        session_id=session_id,
        speaker_id="owner-speaker",
        text=text,
        confidence=0.99,
        capture_mode=VoiceCaptureMode.PUSH_TO_TALK,
        utterance_kind=(
            VoiceUtteranceKind.CHAT
            if action_class is VoiceActionClass.CONVERSATION
            else VoiceUtteranceKind.COMMAND
        ),
        action_class=action_class,
        transport_verified=True,
        received_at=NOW,
    )


def _confirm(packet: VoiceTranscriptPacket, index: int) -> VoiceConfirmationEvent:
    return VoiceConfirmationEvent(
        session_id=packet.session_id,
        utterance_id=packet.utterance_id,
        speaker_id=packet.speaker_id,
        transcript_sha256=packet.text_sha256,
        confirmation_index=index,
        confirmed=True,
        transport_verified=True,
        occurred_at=NOW,
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {"required_files_present": not missing}

    stt = ScriptedSpeechToTextAdapter(text="Merhaba Luna", confidence=0.95)
    scripted = stt.transcribe(
        b"fixture-audio",
        session_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000018"),
        speaker_id="owner-speaker",
        capture_mode=VoiceCaptureMode.WAKE_WORD,
        utterance_kind=VoiceUtteranceKind.CHAT,
        action_class=VoiceActionClass.CONVERSATION,
        now=NOW,
    )
    tts = UnboundTextToSpeechAdapter().plan("Merhaba")
    checks["stt_tts_adapters_provider_neutral"] = bool(
        scripted.transport_verified
        and scripted.text == "Merhaba Luna"
        and tts.provider_bound is False
        and tts.voice_profile_id is None
    )

    with TemporaryDirectory(prefix="luna-phase18-verifier-") as temp:
        root = Path(temp)
        database = root / "operations.sqlite3"
        audit_root = root / "audit"
        gateway = build_local_voice_gateway(
            config=VoiceAuthorityConfig(
                workspace_root=str(root),
                owner_actor_id="owner-local",
                allowed_speaker_ids=("owner-speaker",),
            ),
            database_path=database,
            audit_root=audit_root,
        )
        store = SQLiteOperationsStore(database)
        session = gateway.open_owner_session(
            speaker_id="owner-speaker",
            local_session_verified=True,
            speaker_verified=True,
            now=NOW,
        )

        low = _packet(
            session_id=session.session_id,
            action_class=VoiceActionClass.READ_ONLY_COMMAND,
            text="README durumunu oku.",
        )
        low_pending = gateway.ingest(low, main_model_available=True)
        low_queued = gateway.confirm(_confirm(low, 1), main_model_available=True)
        low_item = (
            store.load_queue_item(low_queued.queue_item_id)
            if low_queued.queue_item_id is not None
            else None
        )
        low_request = low_item.payload.envelope.request if low_item is not None else None
        checks["verified_speaker_session_identity"] = bool(
            low_request is not None
            and low_request.source is RequestSource.VOICE
            and low_request.actor.role is ActorRole.OWNER
            and low_request.actor.verified
            and low_request.actor.verification_source is ActorVerificationSource.LOCAL_SESSION
        )
        checks["low_risk_direct_confirmation"] = bool(
            low_pending.disposition is VoiceIngressDisposition.DIRECT_CONFIRMATION_REQUIRED
            and low_queued.disposition is VoiceIngressDisposition.QUEUED
            and low_item is not None
            and low_item.status is QueueStatus.QUEUED
        )
        low_view = gateway.sessions.transcript_view(session.session_id)
        checks["transcript_view_confirmation_visible"] = bool(
            low_view
            and low_view[0].text == low.text
            and low_view[0].required_confirmations == 1
            and low_view[0].confirmation_count == 1
        )

        high = _packet(
            session_id=session.session_id,
            action_class=VoiceActionClass.HIGH_IMPACT,
            text="Projeyi değiştir, terminal aç ve deploy et.",
        )
        high_pending = gateway.ingest(high, main_model_available=True)
        first = gateway.confirm(_confirm(high, 1), main_model_available=True)
        before_second_count = len(store.list_queue_items())
        high_queued = gateway.confirm(_confirm(high, 2), main_model_available=True)
        high_item = (
            store.load_queue_item(high_queued.queue_item_id)
            if high_queued.queue_item_id is not None
            else None
        )
        high_request = high_item.payload.envelope.request if high_item is not None else None
        checks["high_risk_double_confirmation"] = bool(
            high_pending.disposition is VoiceIngressDisposition.DOUBLE_CONFIRMATION_REQUIRED
            and first.disposition is VoiceIngressDisposition.CONFIRMATION_PROGRESS
            and before_second_count == 1
            and high_queued.disposition
            is VoiceIngressDisposition.QUEUED_FOR_APPROVAL_REVIEW
        )
        checks["spoken_text_cannot_grant_authority"] = bool(
            high_request is not None
            and high_request.autonomy.level.value == "LEVEL_1_READ_ONLY"
            and high_request.scope.write_allowed is False
            and high_request.scope.process_allowed is False
            and high_request.scope.network_allowed is False
            and high_request.runtime_budget.max_changed_files == 0
            and high_request.runtime_budget.max_network_requests == 0
        )
        checks["high_impact_requires_non_voice_approval_review"] = bool(
            high_queued.disposition is VoiceIngressDisposition.QUEUED_FOR_APPROVAL_REVIEW
            and high_request is not None
            and any("non-voice" in value for value in high_request.required_conditions)
        )

        chat = _packet(
            session_id=session.session_id,
            action_class=VoiceActionClass.CONVERSATION,
            text="Bunu ana model uygun olduğunda yanıtla.",
        )
        offline = gateway.ingest(chat, main_model_available=False)
        offline_item = (
            store.load_queue_item(offline.queue_item_id)
            if offline.queue_item_id is not None
            else None
        )
        checks["model_unavailable_remains_durable_queue"] = bool(
            offline.disposition is VoiceIngressDisposition.QUEUED_FOR_MODEL
            and offline_item is not None
            and offline_item.status is QueueStatus.QUEUED
        )

        pending_cancel = _packet(
            session_id=session.session_id,
            action_class=VoiceActionClass.READ_ONLY_COMMAND,
            text="Durumu tekrar oku.",
        )
        gateway.ingest(pending_cancel, main_model_available=True)
        interrupted = gateway.interrupt(session.session_id, now=NOW)
        checks["interruption_cancel_predispatch_safe"] = bool(
            interrupted.disposition is VoiceIngressDisposition.INTERRUPTED
            and offline.queue_item_id is not None
            and store.load_queue_item(offline.queue_item_id).status is QueueStatus.CANCELLED
            and gateway.confirm(
                _confirm(pending_cancel, 1),
                main_model_available=True,
            ).disposition
            is VoiceIngressDisposition.DENIED_CONFIRMATION
        )

        audit = AppendOnlyAuditLedger(audit_root)
        audit_text = audit.path.read_text(encoding="utf-8")
        checks["append_only_audit_uses_transcript_digest"] = bool(
            audit.verify_integrity().valid
            and '"gateway":"voice"' in audit_text
            and high.text not in audit_text
            and low.text not in audit_text
        )

    phase17 = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_phase17.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks["phase17_foundation_remains_green"] = phase17.returncode == 0
    checks["metadata_hashes_current"] = _metadata_integrity()

    payload = {
        "phase": "18",
        "checks": checks,
        "missing_files": missing,
        "status": "PASS" if all(checks.values()) else "BLOCKED",
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
