from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from luna.continuity import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolutionReason,
    CognitiveOwnerResolutionStatus,
    build_verification_evidence_owner_binding,
    resolve_verification_evidence_owner_binding,
)
from luna.contracts.enums import EvidenceResult, EvidenceSourceKind
from luna.contracts.evidence import Evidence
from luna.verification import SQLiteEvidenceStore


def _evidence(
    task_id: UUID,
    *,
    evidence_id: UUID | None = None,
    requirement_id: str = "tests-pass",
    source_ref: str = "verification:test",
    result: EvidenceResult = EvidenceResult.PASS,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id or uuid4(),
        task_id=task_id,
        requirement_id=requirement_id,
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref=source_ref,
        result=result,
        environment_fingerprint="env-cognitive-verification-evidence",
        revision="rev-cognitive-verification-evidence",
        reproducible=True,
        confidence=1.0,
    )


def test_owner_taxonomy_keeps_only_current_durable_verification_owner() -> None:
    assert tuple(item.value for item in CognitiveOwnerKind) == (
        "IDENTITY_PROFILE",
        "VERIFIED_MEMORY",
        "WORKING_SESSION",
        "VERIFICATION_EVIDENCE",
    )


def test_empty_task_evidence_set_is_a_deterministic_owner_snapshot() -> None:
    task_id = uuid4()

    first = build_verification_evidence_owner_binding(task_id=task_id, evidence=())
    repeated = build_verification_evidence_owner_binding(task_id=task_id, evidence=())

    assert repeated == first
    assert first.owner_kind is CognitiveOwnerKind.VERIFICATION_EVIDENCE
    assert first.source_ref == f"verification://task/{task_id}/evidence"
    assert len(first.content_sha256) == 64
    assert first.runtime_authority is False
    assert first.execution_authority is False
    assert first.completion_authority is False


def test_evidence_owner_digest_is_independent_of_input_order() -> None:
    task_id = uuid4()
    first = _evidence(task_id)
    second = _evidence(task_id, requirement_id="lint-pass")

    forward = build_verification_evidence_owner_binding(
        task_id=task_id,
        evidence=(first, second),
    )
    reverse = build_verification_evidence_owner_binding(
        task_id=task_id,
        evidence=(second, first),
    )

    assert reverse == forward


def test_evidence_owner_rejects_cross_task_record() -> None:
    task_id = uuid4()

    with pytest.raises(ValueError, match="must belong to the task"):
        build_verification_evidence_owner_binding(
            task_id=task_id,
            evidence=(_evidence(uuid4()),),
        )


def test_evidence_owner_rejects_duplicate_evidence_identity() -> None:
    task_id = uuid4()
    evidence_id = uuid4()
    first = _evidence(task_id, evidence_id=evidence_id)
    duplicate = first.model_copy(update={"requirement_id": "different-requirement"})

    with pytest.raises(ValueError, match="unique evidence IDs"):
        build_verification_evidence_owner_binding(
            task_id=task_id,
            evidence=(first, duplicate),
        )


def test_same_evidence_set_matches() -> None:
    task_id = uuid4()
    evidence = (_evidence(task_id),)
    historical = build_verification_evidence_owner_binding(
        task_id=task_id,
        evidence=evidence,
    )

    resolution = resolve_verification_evidence_owner_binding(
        historical_binding=historical,
        task_id=task_id,
        current_evidence=evidence,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.MATCHED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.SNAPSHOT_MATCH


def test_added_evidence_changes_same_task_owner_snapshot() -> None:
    task_id = uuid4()
    first = _evidence(task_id)
    historical = build_verification_evidence_owner_binding(
        task_id=task_id,
        evidence=(first,),
    )

    resolution = resolve_verification_evidence_owner_binding(
        historical_binding=historical,
        task_id=task_id,
        current_evidence=(first, _evidence(task_id, requirement_id="ruff-pass")),
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.CONTENT_CHANGED
    assert resolution.current_binding is not None
    assert resolution.current_binding.source_ref == historical.source_ref


def test_store_insertion_order_does_not_change_owner_digest(tmp_path: Path) -> None:
    task_id = uuid4()
    first = _evidence(task_id)
    second = _evidence(task_id, requirement_id="mypy-pass")
    forward_store = SQLiteEvidenceStore(tmp_path / "forward.sqlite3")
    reverse_store = SQLiteEvidenceStore(tmp_path / "reverse.sqlite3")

    forward_store.save(first)
    forward_store.save(second)
    reverse_store.save(second)
    reverse_store.save(first)

    forward = build_verification_evidence_owner_binding(
        task_id=task_id,
        evidence=forward_store.list_for_task(task_id),
    )
    reverse = build_verification_evidence_owner_binding(
        task_id=task_id,
        evidence=reverse_store.list_for_task(task_id),
    )

    assert reverse == forward


def test_store_restart_preserves_exact_owner_binding(tmp_path: Path) -> None:
    task_id = uuid4()
    path = tmp_path / "evidence.sqlite3"
    store = SQLiteEvidenceStore(path)
    store.save(_evidence(task_id))
    historical = build_verification_evidence_owner_binding(
        task_id=task_id,
        evidence=store.list_for_task(task_id),
    )

    restarted = SQLiteEvidenceStore(path)
    current = build_verification_evidence_owner_binding(
        task_id=task_id,
        evidence=restarted.list_for_task(task_id),
    )

    assert current == historical
    assert restarted.verify_integrity() is True


def test_empty_store_task_is_not_misclassified_missing(tmp_path: Path) -> None:
    task_id = uuid4()
    store = SQLiteEvidenceStore(tmp_path / "evidence.sqlite3")
    historical = build_verification_evidence_owner_binding(task_id=task_id, evidence=())

    resolution = resolve_verification_evidence_owner_binding(
        historical_binding=historical,
        task_id=task_id,
        current_evidence=store.list_for_task(task_id),
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.MATCHED


def test_missing_evidence_owner_resolves_missing() -> None:
    task_id = uuid4()
    historical = build_verification_evidence_owner_binding(task_id=task_id, evidence=())

    resolution = resolve_verification_evidence_owner_binding(
        historical_binding=historical,
        task_id=task_id,
        current_evidence=None,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.MISSING
    assert resolution.reason_code is CognitiveOwnerResolutionReason.OWNER_MISSING


def test_unavailable_evidence_owner_is_not_misclassified_missing() -> None:
    task_id = uuid4()
    historical = build_verification_evidence_owner_binding(task_id=task_id, evidence=())

    resolution = resolve_verification_evidence_owner_binding(
        historical_binding=historical,
        task_id=task_id,
        current_evidence=None,
        current_unavailable=True,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.UNAVAILABLE
    assert resolution.reason_code is CognitiveOwnerResolutionReason.OWNER_UNAVAILABLE


def test_evidence_adapter_rejects_cross_task_substitution() -> None:
    historical_task_id = uuid4()
    historical = build_verification_evidence_owner_binding(
        task_id=historical_task_id,
        evidence=(),
    )
    current_task_id = uuid4()

    with pytest.raises(ValueError, match="historical task identity"):
        resolve_verification_evidence_owner_binding(
            historical_binding=historical,
            task_id=current_task_id,
            current_evidence=(),
        )


def test_evidence_adapter_rejects_non_evidence_historical_binding() -> None:
    historical = CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
        source_ref="memory://fixture",
        content_sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="not a verification-evidence binding"):
        resolve_verification_evidence_owner_binding(
            historical_binding=historical,
            task_id=uuid4(),
            current_evidence=(),
        )


def test_evidence_adapter_rejects_available_and_unavailable_together() -> None:
    task_id = uuid4()
    historical = build_verification_evidence_owner_binding(task_id=task_id, evidence=())

    with pytest.raises(ValueError, match="cannot also be marked unavailable"):
        resolve_verification_evidence_owner_binding(
            historical_binding=historical,
            task_id=task_id,
            current_evidence=(),
            current_unavailable=True,
        )
