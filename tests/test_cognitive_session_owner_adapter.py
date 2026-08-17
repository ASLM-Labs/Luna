from __future__ import annotations

import pytest

from luna.continuity import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolutionReason,
    CognitiveOwnerResolutionStatus,
    build_session_owner_binding,
    resolve_session_owner_binding,
)
from luna.sessions.models import SessionEntry, SessionEntryRole, WorkingSession
from luna.sessions.service import WorkingSessionService
from luna.sessions.store import SQLiteSessionStore


def _service(
    tmp_path,
) -> tuple[SQLiteSessionStore, WorkingSessionService, WorkingSession]:
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    service = WorkingSessionService(store)
    session = service.open_session(owner_ref="owner://fixture")
    return store, service, session


def _current(
    store: SQLiteSessionStore,
    session_id,
) -> tuple[WorkingSession, tuple[SessionEntry, ...]]:
    return store.load_session(session_id), store.list_entries(session_id)


def test_session_binding_uses_session_identity_and_full_chain_digest(tmp_path) -> None:
    store, service, session = _service(tmp_path)
    service.append_visible_message(
        session_id=session.session_id,
        owner_ref=session.owner_ref,
        role=SessionEntryRole.USER,
        content="First visible message.",
    )
    current_session, entries = _current(store, session.session_id)

    first = build_session_owner_binding(session=current_session, entries=entries)
    repeated = build_session_owner_binding(session=current_session, entries=entries)

    assert first == repeated
    assert first.owner_kind is CognitiveOwnerKind.WORKING_SESSION
    assert first.source_ref == f"session://{session.session_id}"
    assert len(first.content_sha256) == 64
    assert first.runtime_authority is False
    assert first.execution_authority is False
    assert first.completion_authority is False


def test_session_binding_rejects_entry_from_another_session() -> None:
    session = WorkingSession(owner_ref="owner://fixture")
    foreign = WorkingSession(owner_ref="owner://other")
    entry = SessionEntry(
        session_id=foreign.session_id,
        sequence=1,
        role=SessionEntryRole.USER,
        content="Foreign entry.",
    )

    with pytest.raises(ValueError, match="belong to the selected session"):
        build_session_owner_binding(session=session, entries=(entry,))


def test_session_binding_requires_full_contiguous_sequence() -> None:
    session = WorkingSession(owner_ref="owner://fixture")
    entry = SessionEntry(
        session_id=session.session_id,
        sequence=2,
        role=SessionEntryRole.USER,
        content="Sequence gap.",
    )

    with pytest.raises(ValueError, match="full contiguous sequence"):
        build_session_owner_binding(session=session, entries=(entry,))


def test_same_session_owner_state_matches(tmp_path) -> None:
    store, _, session = _service(tmp_path)
    current_session, entries = _current(store, session.session_id)
    historical = build_session_owner_binding(session=current_session, entries=entries)

    resolution = resolve_session_owner_binding(
        historical_binding=historical,
        current_session=current_session,
        current_entries=entries,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.MATCHED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.SNAPSHOT_MATCH


def test_appended_message_changes_same_session_owner_digest(tmp_path) -> None:
    store, service, session = _service(tmp_path)
    initial_session, initial_entries = _current(store, session.session_id)
    historical = build_session_owner_binding(
        session=initial_session,
        entries=initial_entries,
    )

    service.append_visible_message(
        session_id=session.session_id,
        owner_ref=session.owner_ref,
        role=SessionEntryRole.USER,
        content="New current turn.",
    )
    current_session, current_entries = _current(store, session.session_id)
    resolution = resolve_session_owner_binding(
        historical_binding=historical,
        current_session=current_session,
        current_entries=current_entries,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.CONTENT_CHANGED
    assert resolution.current_binding is not None
    assert resolution.current_binding.source_ref == historical.source_ref


def test_close_changes_same_session_owner_digest(tmp_path) -> None:
    store, service, session = _service(tmp_path)
    service.append_visible_message(
        session_id=session.session_id,
        owner_ref=session.owner_ref,
        role=SessionEntryRole.ASSISTANT,
        content="Visible response.",
    )
    open_session, entries = _current(store, session.session_id)
    historical = build_session_owner_binding(session=open_session, entries=entries)

    service.close_session(session_id=session.session_id, owner_ref=session.owner_ref)
    closed_session, closed_entries = _current(store, session.session_id)
    resolution = resolve_session_owner_binding(
        historical_binding=historical,
        current_session=closed_session,
        current_entries=closed_entries,
    )

    assert closed_entries == entries
    assert resolution.status is CognitiveOwnerResolutionStatus.CHANGED
    assert resolution.reason_code is CognitiveOwnerResolutionReason.CONTENT_CHANGED


def test_bounded_snapshots_do_not_define_session_owner_digest(tmp_path) -> None:
    store, service, session = _service(tmp_path)
    for index in range(3):
        service.append_visible_message(
            session_id=session.session_id,
            owner_ref=session.owner_ref,
            role=SessionEntryRole.USER,
            content=f"Message {index}.",
        )
    current_session, entries = _current(store, session.session_id)
    before = build_session_owner_binding(session=current_session, entries=entries)

    one_entry = service.snapshot(
        session_id=session.session_id,
        owner_ref=session.owner_ref,
        max_entries=1,
    )
    two_entries = service.snapshot(
        session_id=session.session_id,
        owner_ref=session.owner_ref,
        max_entries=2,
    )
    current_session, entries = _current(store, session.session_id)
    after = build_session_owner_binding(session=current_session, entries=entries)

    assert len(one_entry.entries) == 1
    assert len(two_entries.entries) == 2
    assert before == after


def test_missing_session_owner_resolves_missing() -> None:
    session = WorkingSession(owner_ref="owner://fixture")
    historical = build_session_owner_binding(session=session, entries=())

    resolution = resolve_session_owner_binding(
        historical_binding=historical,
        current_session=None,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.MISSING
    assert resolution.reason_code is CognitiveOwnerResolutionReason.OWNER_MISSING


def test_unavailable_session_owner_is_not_misclassified_missing() -> None:
    session = WorkingSession(owner_ref="owner://fixture")
    historical = build_session_owner_binding(session=session, entries=())

    resolution = resolve_session_owner_binding(
        historical_binding=historical,
        current_session=None,
        current_unavailable=True,
    )

    assert resolution.status is CognitiveOwnerResolutionStatus.UNAVAILABLE
    assert resolution.reason_code is CognitiveOwnerResolutionReason.OWNER_UNAVAILABLE


def test_session_adapter_rejects_different_session_as_same_owner() -> None:
    historical_session = WorkingSession(owner_ref="owner://fixture")
    current_session = WorkingSession(owner_ref="owner://fixture")

    with pytest.raises(ValueError, match="does not match historical session identity"):
        resolve_session_owner_binding(
            historical_binding=build_session_owner_binding(
                session=historical_session,
                entries=(),
            ),
            current_session=current_session,
            current_entries=(),
        )


def test_session_adapter_rejects_non_session_historical_binding() -> None:
    historical = CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.VERIFIED_MEMORY,
        source_ref="memory://record/fixture",
        content_sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="not a working-session binding"):
        resolve_session_owner_binding(
            historical_binding=historical,
            current_session=WorkingSession(owner_ref="owner://fixture"),
        )


def test_session_adapter_rejects_session_and_unavailable_together() -> None:
    session = WorkingSession(owner_ref="owner://fixture")

    with pytest.raises(ValueError, match="cannot also be marked unavailable"):
        resolve_session_owner_binding(
            historical_binding=build_session_owner_binding(session=session, entries=()),
            current_session=session,
            current_entries=(),
            current_unavailable=True,
        )


def test_missing_session_owner_cannot_carry_current_entries() -> None:
    session = WorkingSession(owner_ref="owner://fixture")
    entry = SessionEntry(
        session_id=session.session_id,
        sequence=1,
        role=SessionEntryRole.SUMMARY,
        content="Current entry without current session.",
    )

    with pytest.raises(ValueError, match="cannot carry current entries"):
        resolve_session_owner_binding(
            historical_binding=build_session_owner_binding(session=session, entries=()),
            current_session=None,
            current_entries=(entry,),
        )
