"""Structural and behavioral verifier for Luna Phase 8."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from luna.audit import AuditEventKind, AuditSession
from luna.continuity import (
    ContinuityService,
    ResumePolicy,
    ResumeStatus,
    SQLiteContinuityStore,
)
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.contracts.enums import PlanStepStatus, TaskPhase
from luna.contracts.plan import PlanStep

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    required_files = [
        ROOT / "src" / "luna" / "continuity" / "models.py",
        ROOT / "src" / "luna" / "continuity" / "store.py",
        ROOT / "src" / "luna" / "continuity" / "service.py",
    ]
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in required_files
        if not path.is_file()
    ]

    with TemporaryDirectory(prefix="luna-phase8-") as directory:
        root = Path(directory)
        task_id = uuid4()
        trace_id = uuid4()
        contract = TaskContract(
            task_id=task_id,
            objective="Verify restart-safe continuity.",
            required_conditions=("Checkpoint resumes safely.",),
            evidence_required=("checkpoint hash evidence",),
            scope=TaskScope(workspace_root=str(root)),
            risk_level=RiskLevel.LOW,
            owner="user",
        )
        state = TaskState(
            task_id=task_id,
            contract=contract,
            phase=TaskPhase.PLANNED,
            plan=(
                PlanStep(
                    sequence=1,
                    description="Continue.",
                    status=PlanStepStatus.PENDING,
                ),
            ),
            revision=4,
        )
        database = root / "runtime.sqlite3"
        audit = AuditSession(root / "audit")
        audit.record_task_contract(contract=contract, trace_id=trace_id)
        first_service = ContinuityService(
            SQLiteContinuityStore(database),
            audit,
        )
        stored = first_service.create_checkpoint(
            state=state,
            workspace_fingerprint="workspace-phase8",
            environment_fingerprint="environment-phase8",
            runtime_revision="phase8",
            next_step="Activate pending step.",
            trace_id=trace_id,
        )
        restarted_store = SQLiteContinuityStore(database)
        restarted = ContinuityService(restarted_store, audit)
        blocked = restarted.resume_latest(
            task_id=task_id,
            policy=ResumePolicy(
                runtime_revision="phase8-old",
                workspace_fingerprint="workspace-phase8",
                environment_fingerprint="environment-phase8",
            ),
            trace_id=trace_id,
        )
        ready = restarted.resume_latest(
            task_id=task_id,
            policy=ResumePolicy(
                runtime_revision="phase8",
                workspace_fingerprint="workspace-phase8",
                environment_fingerprint="environment-phase8",
            ),
            trace_id=trace_id,
        )
        second = restarted.resume_latest(
            task_id=task_id,
            policy=ResumePolicy(
                runtime_revision="phase8",
                workspace_fingerprint="workspace-phase8",
                environment_fingerprint="environment-phase8",
            ),
            trace_id=trace_id,
        )
        events = audit.events_for_task(task_id)
        kinds = {event.kind for event in events}
        integrity = restarted_store.verify_integrity()
        journal_mode = restarted_store.journal_mode()
        database_schema_version = restarted_store.schema_version()
        audit_integrity_valid = audit.verify_integrity().valid

    checks = {
        "required_files_present": not missing,
        "sqlite_wal_enabled": journal_mode == "wal",
        "schema_version_one": database_schema_version == 1,
        "checkpoint_digest_present": len(stored.payload_sha256) == 64,
        "mismatch_blocks_resume": blocked.status is ResumeStatus.BLOCKED,
        "matching_restart_resumes": ready.status is ResumeStatus.READY,
        "resumed_to_planned": (
            ready.resumed_state is not None
            and ready.resumed_state.phase is TaskPhase.PLANNED
        ),
        "double_resume_blocked": second.status is ResumeStatus.BLOCKED,
        "continuity_integrity_valid": integrity.valid,
        "checkpoint_audited": AuditEventKind.CHECKPOINT_CREATED in kinds,
        "resume_audited": AuditEventKind.RESUME_DECISION in kinds,
        "audit_integrity_valid": audit_integrity_valid,
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    print(
        json.dumps(
            {
                "phase": 8,
                "checks": checks,
                "missing_files": missing,
                "status": status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
