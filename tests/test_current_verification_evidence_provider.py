"""G2-E exact current verification-evidence provider contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import luna.verification as verification_package
from luna.contracts.enums import EvidenceResult, EvidenceSourceKind
from luna.contracts.evidence import Evidence
from luna.verification import (
    CurrentVerificationEvidenceProvider,
    EvidenceStoreError,
    SQLiteEvidenceStore,
    VerifiedEvidenceRegistry,
)


def _evidence(
    task_id: UUID,
    *,
    revision: str,
    result: EvidenceResult = EvidenceResult.PASS,
) -> Evidence:
    return Evidence(
        task_id=task_id,
        requirement_id="tests-pass",
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref=f"verification:{revision}",
        result=result,
        environment_fingerprint="env-g2-e",
        revision=revision,
        reproducible=True,
        confidence=1.0,
    )


def _registry(
    tmp_path: Path,
) -> tuple[SQLiteEvidenceStore, VerifiedEvidenceRegistry]:
    store = SQLiteEvidenceStore(tmp_path / "evidence.sqlite3")
    return store, VerifiedEvidenceRegistry(store)


def test_current_evidence_provider_is_publicly_exported() -> None:
    assert (
        verification_package.CurrentVerificationEvidenceProvider
        is CurrentVerificationEvidenceProvider
    )


def test_current_evidence_returns_complete_durable_set(
    tmp_path: Path,
) -> None:
    store, registry = _registry(tmp_path)
    task_id = uuid4()

    old = _evidence(
        task_id,
        revision="old-revision",
        result=EvidenceResult.FAIL,
    )
    new = _evidence(
        task_id,
        revision="new-revision",
        result=EvidenceResult.PASS,
    )

    store.save(old)
    store.save(new)

    provider: CurrentVerificationEvidenceProvider = registry

    assert provider.current_evidence(task_id) == (old, new)


def test_current_evidence_empty_set_is_present_not_missing(
    tmp_path: Path,
) -> None:
    _, registry = _registry(tmp_path)

    assert registry.current_evidence(uuid4()) == ()


def test_current_evidence_does_not_use_integrity_boolean_as_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, registry = _registry(tmp_path)
    task_id = uuid4()
    expected = _evidence(task_id, revision="current")
    store.save(expected)

    def forbidden() -> bool:
        raise AssertionError(
            "current owner read must not collapse availability into verify_integrity()"
        )

    monkeypatch.setattr(store, "verify_integrity", forbidden)

    assert registry.current_evidence(task_id) == (expected,)


def test_current_evidence_propagates_record_integrity_failure(
    tmp_path: Path,
) -> None:
    store, registry = _registry(tmp_path)
    task_id = uuid4()
    evidence = _evidence(task_id, revision="current")
    store.save(evidence)

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            UPDATE evidence_records
            SET payload_sha256 = ?
            WHERE evidence_id = ?
            """,
            ("0" * 64, str(evidence.evidence_id)),
        )

    with pytest.raises(
        EvidenceStoreError,
        match="evidence payload digest mismatch",
    ):
        registry.current_evidence(task_id)


def test_current_evidence_propagates_store_unavailability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, registry = _registry(tmp_path)
    task_id = uuid4()

    def unavailable(_: UUID) -> tuple[Evidence, ...]:
        raise sqlite3.OperationalError("synthetic evidence store unavailable")

    monkeypatch.setattr(store, "list_for_task", unavailable)

    with pytest.raises(
        sqlite3.OperationalError,
        match="synthetic evidence store unavailable",
    ):
        registry.current_evidence(task_id)
