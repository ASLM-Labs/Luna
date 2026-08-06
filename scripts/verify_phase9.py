"""Structural and behavioral verifier for Luna Phase 9."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from luna.audit import AuditEventKind, AuditSession
from luna.memory import (
    MemoryCandidate,
    MemoryDecisionStatus,
    MemoryPolicy,
    MemoryQuery,
    MemoryRecordStatus,
    MemoryRejectionCode,
    MemoryScope,
    MemorySensitivity,
    MemorySourceKind,
    MemoryType,
    SQLiteMemoryStore,
    VerifiedMemoryService,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    required_files = [
        ROOT / "src" / "luna" / "memory" / "models.py",
        ROOT / "src" / "luna" / "memory" / "policy.py",
        ROOT / "src" / "luna" / "memory" / "store.py",
        ROOT / "src" / "luna" / "memory" / "service.py",
    ]
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in required_files
        if not path.is_file()
    ]

    secret = "phase9-verifier-secret-123456"
    with TemporaryDirectory(prefix="luna-phase9-") as directory:
        root = Path(directory)
        task_id = uuid4()
        trace_id = uuid4()
        audit = AuditSession(root / "audit", explicit_secrets=(secret,))
        store = SQLiteMemoryStore(root / "memory.sqlite3")
        service = VerifiedMemoryService(
            store,
            audit,
            explicit_secrets=(secret,),
        )
        policy = MemoryPolicy()

        verified_observed_at = datetime.now(UTC) - timedelta(minutes=5)
        verified = service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.PROJECT_DECISION,
                statement="Use the Documents Git repository as canonical workspace.",
                source_kind=MemorySourceKind.USER_CONFIRMATION,
                source_ref="conversation:canonical-repository",
                observed_at=verified_observed_at,
                confidence=1.0,
                scope=MemoryScope.PROJECT,
            ),
            policy=policy,
            trace_id=trace_id,
        )
        inference = service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.FACT,
                statement="The user probably wants all future output shortened.",
                source_kind=MemorySourceKind.MODEL_INFERENCE,
                source_ref="model:inference",
                confidence=0.95,
                scope=MemoryScope.PRIVATE_USER,
            ),
            policy=policy,
            trace_id=trace_id,
        )
        preference = service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.PREFERENCE,
                statement="Prefer compact output.",
                source_kind=MemorySourceKind.USER_STATEMENT,
                source_ref="conversation:single-mention",
                confidence=1.0,
                scope=MemoryScope.PRIVATE_USER,
            ),
            policy=policy,
            trace_id=trace_id,
        )
        secret_decision = service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.SECRET_REFERENCE,
                statement=f"api_key={secret}",
                source_kind=MemorySourceKind.SECRET_REFERENCE,
                source_ref="owner:secret-registration",
                confidence=1.0,
                scope=MemoryScope.PRIVATE_USER,
                sensitivity=MemorySensitivity.SECRET,
                explicit_persistence=True,
                secret_ref="secret://local/phase9-verifier",
            ),
            policy=policy,
            trace_id=trace_id,
        )
        old = service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.PROJECT_DECISION,
                statement="Use the desktop copy.",
                source_kind=MemorySourceKind.USER_CONFIRMATION,
                source_ref="conversation:old-workspace",
                confidence=1.0,
                scope=MemoryScope.REPOSITORY,
            ),
            policy=policy,
            trace_id=trace_id,
        )
        assert old.record is not None
        service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.PROJECT_DECISION,
                statement="Use the Documents repository.",
                source_kind=MemorySourceKind.USER_CONFIRMATION,
                source_ref="conversation:new-workspace",
                confidence=1.0,
                scope=MemoryScope.REPOSITORY,
                supersedes=old.record.memory_id,
            ),
            policy=policy,
            trace_id=trace_id,
        )
        retrieval = service.retrieve(
            query=MemoryQuery(scope=MemoryScope.REPOSITORY),
            task_id=task_id,
            trace_id=trace_id,
        )
        forgotten = service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.FACT,
                statement="This record exists only to verify user deletion.",
                source_kind=MemorySourceKind.USER_CONFIRMATION,
                source_ref="conversation:forget-verifier",
                confidence=1.0,
                scope=MemoryScope.PRIVATE_USER,
            ),
            policy=policy,
            trace_id=trace_id,
        )
        assert forgotten.record is not None
        service.forget(
            memory_id=forgotten.record.memory_id,
            task_id=task_id,
            trace_id=trace_id,
        )
        forgotten_absent = all(
            record.memory_id != forgotten.record.memory_id
            for record in store.list_records()
        )

        now = datetime.now(UTC)
        expiring = service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.RESEARCH_FACT,
                statement="A temporary maintenance window is active.",
                source_kind=MemorySourceKind.VERIFIED_OBSERVATION,
                source_ref="research:maintenance-window",
                confidence=0.95,
                scope=MemoryScope.RESEARCH,
                expires_at=now + timedelta(minutes=1),
            ),
            policy=policy,
            trace_id=trace_id,
        )
        assert expiring.record is not None
        expired_records, _ = store.retrieve(
            MemoryQuery(scope=MemoryScope.RESEARCH),
            now=now + timedelta(minutes=2),
        )

        integrity = store.verify_integrity()
        event_kinds = {
            event.kind for event in audit.events_for_task(task_id)
        }
        persisted = b"".join(
            path.read_bytes()
            for path in root.glob("memory.sqlite3*")
            if path.is_file()
        ) + audit.ledger.path.read_bytes()
        journal_mode = store.journal_mode()
        schema_version = store.schema_version()
        old_status = store.load(old.record.memory_id).status
        expired_status = store.load(expiring.record.memory_id).status
        audit_integrity = audit.verify_integrity().valid

    checks = {
        "required_files_present": not missing,
        "sqlite_wal_enabled": journal_mode == "wal",
        "schema_version_one": schema_version == 1,
        "verified_candidate_committed": (
            verified.status is MemoryDecisionStatus.COMMIT
        ),
        "model_inference_rejected": (
            MemoryRejectionCode.MODEL_INFERENCE_UNVERIFIED
            in inference.rejection_codes
        ),
        "one_off_preference_rejected": (
            MemoryRejectionCode.ONE_OFF_PREFERENCE in preference.rejection_codes
        ),
        "secret_reference_committed": (
            secret_decision.status is MemoryDecisionStatus.COMMIT
        ),
        "plaintext_secret_absent": secret.encode("utf-8") not in persisted,
        "retrieval_scope_isolated": (
            len(retrieval.records) == 1
            and retrieval.records[0].scope is MemoryScope.REPOSITORY
        ),
        "source_time_and_confidence_preserved": (
            verified.record is not None
            and verified.record.source_ref == "conversation:canonical-repository"
            and verified.record.observed_at == verified_observed_at
            and verified.record.confidence == 1.0
        ),
        "superseded_record_inactive": (
            old_status is MemoryRecordStatus.SUPERSEDED
        ),
        "user_forget_removes_record": forgotten_absent,
        "expiry_excludes_record": (
            not expired_records and expired_status is MemoryRecordStatus.EXPIRED
        ),
        "memory_integrity_valid": integrity.valid,
        "memory_candidate_audited": AuditEventKind.MEMORY_CANDIDATE in event_kinds,
        "memory_decision_audited": AuditEventKind.MEMORY_DECISION in event_kinds,
        "memory_commit_audited": AuditEventKind.MEMORY_COMMITTED in event_kinds,
        "memory_retrieval_audited": AuditEventKind.MEMORY_RETRIEVAL in event_kinds,
        "memory_forget_audited": AuditEventKind.MEMORY_FORGOTTEN in event_kinds,
        "audit_integrity_valid": audit_integrity,
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    print(
        json.dumps(
            {
                "phase": 9,
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
