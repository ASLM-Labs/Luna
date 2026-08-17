"""G2-S exact current-session provider contract tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

import luna.sessions as sessions_package
from luna.sessions import (
    CurrentSessionProvider,
    SessionEntryRole,
    SessionStatus,
    WorkingSessionService,
)
from luna.sessions.store import (
    SessionIntegrityError,
    SessionNotFoundError,
    SQLiteSessionStore,
)


def _service(
    tmp_path: Path,
) -> tuple[SQLiteSessionStore, WorkingSessionService]:
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    return store, WorkingSessionService(store)


def test_current_session_provider_is_publicly_exported() -> None:
    assert (
        sessions_package.CurrentSessionProvider
        is CurrentSessionProvider
    )


def test_current_session_returns_complete_ordered_owner_state(
    tmp_path: Path,
) -> None:
    _, service = _service(tmp_path)
    session = service.open_session(owner_ref="owner://g2-s")

    expected = (
        service.append_visible_message(
            session_id=session.session_id,
            owner_ref=session.owner_ref,
            role=SessionEntryRole.USER,
            content="First visible message.",
        ),
        service.append_visible_message(
            session_id=session.session_id,
            owner_ref=session.owner_ref,
            role=SessionEntryRole.ASSISTANT,
            content="Second visible message.",
        ),
        service.append_visible_message(
            session_id=session.session_id,
            owner_ref=session.owner_ref,
            role=SessionEntryRole.SUMMARY,
            content="Third visible message.",
        ),
    )

    provider: CurrentSessionProvider = service
    current, entries = provider.current_session(session.session_id)

    assert current == session
    assert entries == expected
    assert tuple(entry.sequence for entry in entries) == (1, 2, 3)


def test_current_session_does_not_compose_non_atomic_public_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service = _service(tmp_path)
    session = service.open_session(owner_ref="owner://g2-s")
    service.append_visible_message(
        session_id=session.session_id,
        owner_ref=session.owner_ref,
        role=SessionEntryRole.USER,
        content="Exact state.",
    )

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "current owner read must use atomic load_session_state"
        )

    monkeypatch.setattr(store, "load_session", unexpected)
    monkeypatch.setattr(store, "list_entries", unexpected)

    current, entries = service.current_session(session.session_id)

    assert current.session_id == session.session_id
    assert len(entries) == 1


def test_current_session_preserves_closed_state_and_history(
    tmp_path: Path,
) -> None:
    _, service = _service(tmp_path)
    session = service.open_session(owner_ref="owner://g2-s")
    entry = service.append_visible_message(
        session_id=session.session_id,
        owner_ref=session.owner_ref,
        role=SessionEntryRole.USER,
        content="Persist after close.",
    )

    closed = service.close_session(
        session_id=session.session_id,
        owner_ref=session.owner_ref,
    )

    current, entries = service.current_session(session.session_id)

    assert closed.status is SessionStatus.CLOSED
    assert current == closed
    assert entries == (entry,)


def test_current_session_propagates_missing_session(
    tmp_path: Path,
) -> None:
    _, service = _service(tmp_path)
    missing_id = uuid4()

    with pytest.raises(
        SessionNotFoundError,
        match=str(missing_id),
    ):
        service.current_session(missing_id)


def test_current_session_propagates_session_integrity_failure(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path)
    session = service.open_session(owner_ref="owner://g2-s")

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            UPDATE working_sessions
            SET payload_sha256 = ?
            WHERE session_id = ?
            """,
            ("0" * 64, str(session.session_id)),
        )

    with pytest.raises(
        SessionIntegrityError,
        match="working session digest mismatch",
    ):
        service.current_session(session.session_id)


def test_current_session_propagates_entry_integrity_failure(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path)
    session = service.open_session(owner_ref="owner://g2-s")
    entry = service.append_visible_message(
        session_id=session.session_id,
        owner_ref=session.owner_ref,
        role=SessionEntryRole.USER,
        content="Integrity-bound entry.",
    )

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            UPDATE session_entries
            SET payload_sha256 = ?
            WHERE entry_id = ?
            """,
            ("0" * 64, str(entry.entry_id)),
        )

    with pytest.raises(
        SessionIntegrityError,
        match="session entry digest mismatch",
    ):
        service.current_session(session.session_id)


def test_load_session_state_is_read_only(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path)
    session = service.open_session(owner_ref="owner://g2-s")
    service.append_visible_message(
        session_id=session.session_id,
        owner_ref=session.owner_ref,
        role=SessionEntryRole.USER,
        content="Read-only state.",
    )

    before = store.path.read_bytes()

    first = service.current_session(session.session_id)
    second = service.current_session(session.session_id)

    after = store.path.read_bytes()

    assert first == second
    assert before == after
