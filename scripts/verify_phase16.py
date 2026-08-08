"""Deterministic Phase 16 Desktop Product Shell gate."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.contracts import CompletionStatus, TaskPhase, TaskState  # noqa: E402
from luna.contracts.task import TaskContract  # noqa: E402
from luna.desktop import (  # noqa: E402
    THEME_TOKENS,
    DesktopAccessMode,
    DesktopApproval,
    DesktopComposerDraft,
    DesktopTaskState,
    build_local_desktop_controller,
    task_card,
)
from luna.operations import QueueStatus, SQLiteOperationsStore  # noqa: E402
from luna.runtime import (  # noqa: E402
    RuntimeOutcome,
    RuntimeStopReason,
    RuntimeUsage,
    build_task_fingerprint,
)

NOW = datetime(2026, 8, 8, 2, 30, tzinfo=UTC)

REQUIRED_FILES = (
    "src/luna/desktop/__init__.py",
    "src/luna/desktop/models.py",
    "src/luna/desktop/presenter.py",
    "src/luna/desktop/gateway.py",
    "src/luna/desktop/controller.py",
    "src/luna/desktop/bootstrap.py",
    "src/luna/desktop/theme.py",
    "src/luna/desktop/tk_shell.py",
    "tests/test_phase16_desktop_product_shell.py",
    "scripts/verify_phase16.py",
    "docs/rfcs/RFC-016_DESKTOP_PRODUCT_SHELL.md",
    "docs/PHASE_16_REPORT.md",
    "phase_16_verification.json",
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
    if match is None or int(match.group(1)) < 16:
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


def _completed_outcome(item) -> RuntimeOutcome:
    request = item.payload.envelope.request
    contract = TaskContract(
        task_id=request.task_id,
        objective="Complete the Phase 16 verifier fixture.",
        required_conditions=("The runtime must truthfully report the task outcome.",),
        evidence_required=("runtime observations",),
        scope=request.scope,
        owner=request.actor.actor_id,
    )
    state = TaskState(
        task_id=request.task_id,
        contract=contract,
        phase=TaskPhase.CLOSED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
    )
    return RuntimeOutcome(
        request_id=request.request_id,
        task_id=request.task_id,
        trace_id=request.trace_id,
        task_fingerprint=build_task_fingerprint(request).digest,
        state=state,
        stop_reason=RuntimeStopReason.COMPLETED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
        verification_report_id=uuid4(),
        final_report_id=uuid4(),
        usage=RuntimeUsage(budget=request.runtime_budget),
        started_at=NOW,
        finished_at=NOW,
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {
        "required_files_present": not missing,
        "light_first_theme_locked": (
            THEME_TOKENS["canvas"] == "#FFFFFF"
            and THEME_TOKENS["text"] == "#171717"
            and THEME_TOKENS["surface"] == "#F5F6F8"
            and THEME_TOKENS["blue"] == "#2563EB"
        ),
    }

    with TemporaryDirectory(prefix="luna-phase16-verifier-") as temp:
        root = Path(temp)
        database = root / "operations.sqlite3"
        controller = build_local_desktop_controller(
            workspace_root=root,
            database_path=database,
            actor_id="phase16-verifier",
        )

        item_id = controller.submit(
            DesktopComposerDraft(
                text="Inspect the Phase 16 verifier workspace.",
                workspace_root=str(root),
            )
        )
        store = SQLiteOperationsStore(database)
        item = store.load_queue_item(UUID(item_id))
        request = item.payload.envelope.request

        checks["desktop_default_is_read_only"] = (
            request.source.value == "DESKTOP"
            and request.scope.write_allowed is False
            and request.scope.network_allowed is False
            and request.autonomy.level.value == "LEVEL_1_READ_ONLY"
            and request.runtime_budget.max_changed_files == 0
        )
        checks["desktop_routes_through_durable_queue"] = item.status is QueueStatus.QUEUED
        checks["desktop_snapshot_does_not_invent_completion"] = (
            controller.snapshot().tasks[0].state is DesktopTaskState.QUEUED
            and controller.snapshot().tasks[0].completion_status is None
        )

        try:
            DesktopComposerDraft(
                text="Write without approval.",
                workspace_root=str(root),
                access_mode=DesktopAccessMode.CONTROLLED_WRITE,
            )
        except ValueError:
            checks["desktop_write_requires_explicit_approval"] = True
        else:
            checks["desktop_write_requires_explicit_approval"] = False

        approved = DesktopComposerDraft(
            text="Update README within the approved path.",
            workspace_root=str(root),
            access_mode=DesktopAccessMode.CONTROLLED_WRITE,
            approval=DesktopApproval(
                approved=True,
                workspace_root=str(root),
                allowed_paths=("README.md",),
                max_changed_files=1,
                max_added_lines=20,
                max_deleted_lines=10,
            ),
        )
        approved_id = controller.submit(approved)
        approved_item = store.load_queue_item(UUID(approved_id))
        approved_request = approved_item.payload.envelope.request
        checks["desktop_write_budget_is_bounded_and_network_closed"] = (
            approved_request.scope.write_allowed
            and approved_request.scope.allowed_paths == ("README.md",)
            and not approved_request.scope.network_allowed
            and approved_request.runtime_budget.max_changed_files == 1
            and approved_request.runtime_budget.max_network_requests == 0
        )

        outcome = _completed_outcome(item)
        card = task_card(
            item.model_copy(
                update={
                    "status": QueueStatus.COMPLETED,
                    "outcome": outcome,
                    "dispatch_id": uuid4(),
                    "dispatch_started_at": NOW,
                    "updated_at": NOW,
                }
            )
        )
        checks["desktop_verified_label_is_runtime_evidence_bound"] = (
            card.state is DesktopTaskState.VERIFIED_COMPLETE
            and card.verification_report_id == outcome.verification_report_id
            and card.final_report_id == outcome.final_report_id
        )
        checks["desktop_notifications_remain_local_only"] = all(
            not event.external_delivery_allowed
            for event in controller.snapshot().notifications
        )
        checks["desktop_schedule_read_model_is_non_authoritative"] = (
            store.list_schedules() == ()
        )

    phase15 = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_phase15.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks["phase15_foundation_remains_green"] = phase15.returncode == 0
    checks["metadata_hashes_current"] = _metadata_integrity()

    payload = {
        "phase": "16",
        "checks": checks,
        "missing_files": missing,
        "status": "PASS" if all(checks.values()) else "BLOCKED",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
