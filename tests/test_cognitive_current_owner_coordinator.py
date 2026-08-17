"""G2-C thin current-owner coordinator contract tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import luna.continuity as continuity_package
from luna.continuity import (
    CognitiveCurrentOwnerCoordinator,
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolution,
    CognitiveOwnerResolutionStatus,
    build_cognitive_rehydration_manifest,
    build_identity_owner_binding,
    build_memory_owner_binding,
    build_session_owner_binding,
    build_verification_evidence_owner_binding,
)
from luna.contracts.enums import EvidenceResult, EvidenceSourceKind
from luna.contracts.evidence import Evidence
from luna.identity import (
    IdentityIntegrityError,
    IdentityProfile,
    IdentityProfileService,
    SQLiteIdentityStore,
    UserProfile,
)
from luna.memory.models import (
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemorySourceKind,
    MemoryType,
)
from luna.memory.service import VerifiedMemoryService
from luna.memory.store import MemoryIntegrityError, SQLiteMemoryStore
from luna.sessions import WorkingSession, WorkingSessionService
from luna.sessions.store import SessionIntegrityError, SQLiteSessionStore
from luna.verification import (
    EvidenceStoreError,
    SQLiteEvidenceStore,
    VerifiedEvidenceRegistry,
)


def _profile() -> IdentityProfile:
    return IdentityProfile(
        user_profile=UserProfile(
            user_id="g2-c-owner",
            display_name="G2-C Owner",
            preferred_address="Owner",
        )
    )


def _memory() -> MemoryRecord:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryRecord(
        candidate_id=uuid4(),
        task_id=uuid4(),
        memory_type=MemoryType.FACT,
        statement="Verified G2-C fact.",
        source_kind=MemorySourceKind.USER_CONFIRMATION,
        source_ref="g2-c:test",
        observed_at=now,
        created_at=now,
        last_verified_at=now,
        confidence=1.0,
        scope=MemoryScope.PROJECT,
        sensitivity=MemorySensitivity.PRIVATE,
    )


def _evidence(task_id: UUID) -> Evidence:
    return Evidence(
        task_id=task_id,
        requirement_id="g2-c-current-owner",
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:g2-c",
        result=EvidenceResult.PASS,
        environment_fingerprint="env-g2-c",
        revision="g2-c",
        reproducible=True,
        confidence=1.0,
    )


@dataclass
class _Harness:
    profile: IdentityProfile
    identity: IdentityProfileService
    memory_store: SQLiteMemoryStore
    memory: VerifiedMemoryService
    session: WorkingSessionService
    evidence_store: SQLiteEvidenceStore
    evidence: VerifiedEvidenceRegistry
    coordinator: CognitiveCurrentOwnerCoordinator


def _harness(
    tmp_path: Path,
    *,
    initialize_identity: bool = True,
) -> _Harness:
    profile = _profile()

    identity = IdentityProfileService(
        SQLiteIdentityStore(
            tmp_path / "identity.sqlite3"
        )
    )

    if initialize_identity:
        identity.initialize(profile)

    memory_store = SQLiteMemoryStore(
        tmp_path / "memory.sqlite3"
    )
    memory = VerifiedMemoryService(memory_store)

    session = WorkingSessionService(
        SQLiteSessionStore(
            tmp_path / "sessions.sqlite3"
        )
    )

    evidence_store = SQLiteEvidenceStore(
        tmp_path / "evidence.sqlite3"
    )
    evidence = VerifiedEvidenceRegistry(
        evidence_store
    )

    coordinator = CognitiveCurrentOwnerCoordinator(
        identity_provider=identity,
        memory_provider=memory,
        session_provider=session,
        evidence_provider=evidence,
    )

    return _Harness(
        profile=profile,
        identity=identity,
        memory_store=memory_store,
        memory=memory,
        session=session,
        evidence_store=evidence_store,
        evidence=evidence,
        coordinator=coordinator,
    )


def _manifest(
    *,
    task_id: UUID,
    bindings: tuple[CognitiveOwnerBinding, ...],
):
    return build_cognitive_rehydration_manifest(
        task_id=task_id,
        checkpoint_id=uuid4(),
        task_revision=7,
        task_state_sha256="1" * 64,
        bindings=bindings,
    )


def _resolution(
    values: tuple[CognitiveOwnerResolution, ...],
    owner_kind: CognitiveOwnerKind,
) -> CognitiveOwnerResolution:
    matches = tuple(
        item
        for item in values
        if item.historical_binding.owner_kind is owner_kind
    )

    assert len(matches) == 1

    return matches[0]


def test_coordinator_is_publicly_exported() -> None:
    assert (
        continuity_package.CognitiveCurrentOwnerCoordinator
        is CognitiveCurrentOwnerCoordinator
    )


def test_current_owner_capture_resolves_all_canonical_owners(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    task_id = uuid4()

    memory = _memory()
    harness.memory_store.save(memory)

    session = harness.session.open_session(
        owner_ref="owner://g2-c"
    )

    evidence = _evidence(task_id)
    harness.evidence_store.save(evidence)

    manifest = _manifest(
        task_id=task_id,
        bindings=(
            build_session_owner_binding(
                session=session,
                entries=(),
            ),
            build_memory_owner_binding(memory),
            build_verification_evidence_owner_binding(
                task_id=task_id,
                evidence=(evidence,),
            ),
            build_identity_owner_binding(
                harness.profile
            ),
        ),
    )

    resolutions = harness.coordinator.resolve_manifest(
        manifest
    )

    assert tuple(
        item.historical_binding
        for item in resolutions
    ) == manifest.bindings

    assert all(
        item.status
        is CognitiveOwnerResolutionStatus.MATCHED
        for item in resolutions
    )


def test_uninitialized_identity_resolves_missing_without_historical_fallback(
    tmp_path: Path,
) -> None:
    harness = _harness(
        tmp_path,
        initialize_identity=False,
    )

    manifest = _manifest(
        task_id=uuid4(),
        bindings=(
            build_identity_owner_binding(
                harness.profile
            ),
        ),
    )

    resolution = harness.coordinator.resolve_manifest(
        manifest
    )[0]

    assert (
        resolution.status
        is CognitiveOwnerResolutionStatus.MISSING
    )
    assert resolution.current_binding is None


def test_missing_memory_and_session_resolve_missing(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    task_id = uuid4()

    memory = _memory()
    session = WorkingSession(
        owner_ref="owner://historical"
    )

    manifest = _manifest(
        task_id=task_id,
        bindings=(
            build_identity_owner_binding(
                harness.profile
            ),
            build_memory_owner_binding(memory),
            build_session_owner_binding(
                session=session,
                entries=(),
            ),
        ),
    )

    resolutions = harness.coordinator.resolve_manifest(
        manifest
    )

    memory_resolution = _resolution(
        resolutions,
        CognitiveOwnerKind.VERIFIED_MEMORY,
    )
    session_resolution = _resolution(
        resolutions,
        CognitiveOwnerKind.WORKING_SESSION,
    )

    assert (
        memory_resolution.status
        is CognitiveOwnerResolutionStatus.MISSING
    )
    assert memory_resolution.current_binding is None

    assert (
        session_resolution.status
        is CognitiveOwnerResolutionStatus.MISSING
    )
    assert session_resolution.current_binding is None


def test_empty_evidence_set_is_current_owner_state_not_missing(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    task_id = uuid4()

    manifest = _manifest(
        task_id=task_id,
        bindings=(
            build_identity_owner_binding(
                harness.profile
            ),
            build_verification_evidence_owner_binding(
                task_id=task_id,
                evidence=(),
            ),
        ),
    )

    resolutions = harness.coordinator.resolve_manifest(
        manifest
    )

    evidence_resolution = _resolution(
        resolutions,
        CognitiveOwnerKind.VERIFICATION_EVIDENCE,
    )

    assert (
        evidence_resolution.status
        is CognitiveOwnerResolutionStatus.MATCHED
    )
    assert evidence_resolution.current_binding is not None


def test_native_store_failures_resolve_unavailable_without_reusing_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path)
    task_id = uuid4()

    memory = _memory()
    session = WorkingSession(
        owner_ref="owner://historical"
    )

    manifest = _manifest(
        task_id=task_id,
        bindings=(
            build_identity_owner_binding(
                harness.profile
            ),
            build_memory_owner_binding(memory),
            build_session_owner_binding(
                session=session,
                entries=(),
            ),
            build_verification_evidence_owner_binding(
                task_id=task_id,
                evidence=(),
            ),
        ),
    )

    def identity_unavailable() -> IdentityProfile:
        raise IdentityIntegrityError(
            "synthetic identity unavailable"
        )

    def memory_unavailable(
        _memory_id: UUID,
    ) -> MemoryRecord:
        raise MemoryIntegrityError(
            "synthetic memory unavailable"
        )

    def session_unavailable(
        _session_id: UUID,
    ):
        raise SessionIntegrityError(
            "synthetic session unavailable"
        )

    def evidence_unavailable(
        _task_id: UUID,
    ) -> tuple[Evidence, ...]:
        raise EvidenceStoreError(
            "synthetic evidence unavailable"
        )

    monkeypatch.setattr(
        harness.identity,
        "current_identity",
        identity_unavailable,
    )
    monkeypatch.setattr(
        harness.memory,
        "current_memory",
        memory_unavailable,
    )
    monkeypatch.setattr(
        harness.session,
        "current_session",
        session_unavailable,
    )
    monkeypatch.setattr(
        harness.evidence,
        "current_evidence",
        evidence_unavailable,
    )

    resolutions = harness.coordinator.resolve_manifest(
        manifest
    )

    assert all(
        item.status
        is CognitiveOwnerResolutionStatus.UNAVAILABLE
        for item in resolutions
    )

    assert all(
        item.current_binding is None
        for item in resolutions
    )


def test_cross_task_evidence_binding_is_rejected_before_current_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path)

    manifest_task = uuid4()
    historical_task = uuid4()

    manifest = _manifest(
        task_id=manifest_task,
        bindings=(
            build_identity_owner_binding(
                harness.profile
            ),
            build_verification_evidence_owner_binding(
                task_id=historical_task,
                evidence=(),
            ),
        ),
    )

    called = False

    def forbidden(
        _task_id: UUID,
    ) -> tuple[Evidence, ...]:
        nonlocal called
        called = True
        raise AssertionError(
            "cross-task evidence must fail before provider read"
        )

    monkeypatch.setattr(
        harness.evidence,
        "current_evidence",
        forbidden,
    )

    with pytest.raises(
        ValueError,
        match="manifest task identity",
    ):
        harness.coordinator.resolve_manifest(
            manifest
        )

    assert called is False


def test_noncanonical_owner_source_ref_is_rejected(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    malformed_memory = CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
        source_ref="memory://historical-not-canonical",
        content_sha256="2" * 64,
    )

    manifest = _manifest(
        task_id=uuid4(),
        bindings=(
            build_identity_owner_binding(
                harness.profile
            ),
            malformed_memory,
        ),
    )

    with pytest.raises(
        ValueError,
        match="non-canonical source_ref",
    ):
        harness.coordinator.resolve_manifest(
            manifest
        )
