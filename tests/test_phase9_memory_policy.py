from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from luna.audit import AuditEventKind, AuditSession
from luna.memory import (
    MemoryCandidate,
    MemoryDecisionStatus,
    MemoryPolicy,
    MemoryRejectionCode,
    MemoryScope,
    MemorySensitivity,
    MemorySourceKind,
    MemoryType,
    SQLiteMemoryStore,
    VerifiedMemoryService,
)


def _candidate(**updates: object) -> MemoryCandidate:
    payload: dict[str, object] = {
        "task_id": uuid4(),
        "memory_type": MemoryType.FACT,
        "statement": "The repository root is owner-selected.",
        "source_kind": MemorySourceKind.VERIFIED_OBSERVATION,
        "source_ref": "observation:repo-root",
        "confidence": 1.0,
        "scope": MemoryScope.REPOSITORY,
    }
    payload.update(updates)
    return MemoryCandidate.model_validate(payload)


def test_model_inference_cannot_be_committed_as_verified_fact(tmp_path: Path) -> None:
    service = VerifiedMemoryService(SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    candidate = _candidate(source_kind=MemorySourceKind.MODEL_INFERENCE)

    decision = service.commit_candidate(candidate=candidate, policy=MemoryPolicy())

    assert decision.status is MemoryDecisionStatus.REJECT
    assert MemoryRejectionCode.MODEL_INFERENCE_UNVERIFIED in decision.rejection_codes
    assert service.store.list_records() == ()


def test_one_off_preference_is_not_treated_as_persistent(tmp_path: Path) -> None:
    service = VerifiedMemoryService(SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    candidate = _candidate(
        memory_type=MemoryType.PREFERENCE,
        statement="Prefer compact output.",
        source_kind=MemorySourceKind.USER_STATEMENT,
        source_ref="conversation:one-mention",
        scope=MemoryScope.PRIVATE_USER,
        occurrence_count=1,
    )

    decision = service.commit_candidate(candidate=candidate, policy=MemoryPolicy())

    assert decision.status is MemoryDecisionStatus.REJECT
    assert MemoryRejectionCode.ONE_OFF_PREFERENCE in decision.rejection_codes


def test_repeated_or_explicit_preference_can_commit(tmp_path: Path) -> None:
    service = VerifiedMemoryService(SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    observed_at = datetime.now(UTC) - timedelta(minutes=3)
    candidate = _candidate(
        memory_type=MemoryType.PREFERENCE,
        statement="Keep validation windows open.",
        source_kind=MemorySourceKind.USER_CONFIRMATION,
        source_ref="conversation:confirmed-preference",
        observed_at=observed_at,
        scope=MemoryScope.PRIVATE_USER,
        occurrence_count=2,
    )

    decision = service.commit_candidate(candidate=candidate, policy=MemoryPolicy())

    assert decision.status is MemoryDecisionStatus.COMMIT
    assert decision.record is not None
    assert decision.record.source_ref == "conversation:confirmed-preference"
    assert decision.record.observed_at == observed_at
    assert decision.record.confidence == 1.0


def test_plaintext_secret_is_replaced_by_opaque_reference_everywhere(
    tmp_path: Path,
) -> None:
    secret = "github-token-very-secret-123456"
    task_id = uuid4()
    trace_id = uuid4()
    audit = AuditSession(tmp_path / "audit", explicit_secrets=(secret,))
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    service = VerifiedMemoryService(store, audit, explicit_secrets=(secret,))
    candidate = _candidate(
        task_id=task_id,
        memory_type=MemoryType.SECRET_REFERENCE,
        statement=f"api_key={secret}",
        source_kind=MemorySourceKind.SECRET_REFERENCE,
        source_ref="owner:secret-registration",
        scope=MemoryScope.PRIVATE_USER,
        sensitivity=MemorySensitivity.SECRET,
        explicit_persistence=True,
        secret_ref="secret://local/github-token",
    )

    decision = service.commit_candidate(
        candidate=candidate,
        policy=MemoryPolicy(),
        trace_id=trace_id,
    )

    assert decision.status is MemoryDecisionStatus.COMMIT
    assert decision.record is not None
    assert decision.record.statement == "[SECRET_REFERENCE]"
    assert decision.record.secret_ref == "secret://local/github-token"
    persisted = b"".join(
        path.read_bytes() for path in tmp_path.glob("memory.sqlite3*") if path.is_file()
    ) + audit.ledger.path.read_bytes()
    assert secret.encode("utf-8") not in persisted
    kinds = {event.kind for event in audit.events_for_task(task_id)}
    assert AuditEventKind.MEMORY_CANDIDATE in kinds
    assert AuditEventKind.MEMORY_DECISION in kinds
    assert AuditEventKind.MEMORY_COMMITTED in kinds
    assert audit.verify_integrity().valid


def test_plaintext_secret_in_non_secret_memory_is_rejected(tmp_path: Path) -> None:
    secret = "plain-secret-123456789"
    service = VerifiedMemoryService(
        SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        explicit_secrets=(secret,),
    )
    candidate = _candidate(statement=f"password={secret}")

    decision = service.commit_candidate(candidate=candidate, policy=MemoryPolicy())

    assert decision.status is MemoryDecisionStatus.REJECT
    assert MemoryRejectionCode.PLAINTEXT_SECRET in decision.rejection_codes


def test_secret_reference_cannot_embed_the_secret_value(tmp_path: Path) -> None:
    secret = "embedded-secret-value-123456"
    service = VerifiedMemoryService(
        SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        explicit_secrets=(secret,),
    )
    candidate = _candidate(
        memory_type=MemoryType.SECRET_REFERENCE,
        statement="Secret is registered externally.",
        source_kind=MemorySourceKind.SECRET_REFERENCE,
        source_ref="owner:secret-registration",
        scope=MemoryScope.PRIVATE_USER,
        sensitivity=MemorySensitivity.SECRET,
        explicit_persistence=True,
        secret_ref=f"secret://local/{secret}",
    )

    decision = service.commit_candidate(candidate=candidate, policy=MemoryPolicy())

    assert decision.status is MemoryDecisionStatus.REJECT
    assert MemoryRejectionCode.INVALID_SECRET_REFERENCE in decision.rejection_codes
    assert service.store.list_records() == ()
