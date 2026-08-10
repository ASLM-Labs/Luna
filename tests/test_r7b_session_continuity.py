from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.context import (
    CONTEXT_LAYER_ORDER,
    ContextAuthorityRole,
    ContextInterpretation,
    ContextLayer,
    LayeredContextComposer,
)
from luna.sessions import (
    SessionClosedError,
    SessionEntry,
    SessionEntryRole,
    SessionIntegrityError,
    SessionOwnershipError,
    SessionStatus,
    SQLiteSessionStore,
    WorkingSessionService,
)

OWNER = "owner:r7b-test"
OTHER_OWNER = "owner:other"


def _service(root: Path, *, explicit_secrets: tuple[str, ...] = ()) -> WorkingSessionService:
    return WorkingSessionService(
        SQLiteSessionStore(root / "session.sqlite3"),
        explicit_secrets=explicit_secrets,
    )


def test_session_survives_service_restart_and_preserves_cross_task_order(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = service.open_session(owner_ref=OWNER, label="R7-B working session")
    first_task = uuid4()
    second_task = uuid4()

    first = service.append_visible_message(
        session_id=session.session_id,
        owner_ref=OWNER,
        role=SessionEntryRole.USER,
        content="First visible request.",
        source_task_id=first_task,
    )
    second = service.append_visible_message(
        session_id=session.session_id,
        owner_ref=OWNER,
        role=SessionEntryRole.ASSISTANT,
        content="First visible answer.",
        source_task_id=first_task,
    )

    restarted = _service(tmp_path)
    third = restarted.append_visible_message(
        session_id=session.session_id,
        owner_ref=OWNER,
        role=SessionEntryRole.USER,
        content="Continue this in a new task.",
        source_task_id=second_task,
    )
    snapshot = restarted.snapshot(session_id=session.session_id, owner_ref=OWNER)

    assert snapshot.session.session_id == session.session_id
    assert tuple(entry.sequence for entry in snapshot.entries) == (1, 2, 3)
    assert tuple(entry.entry_id for entry in snapshot.entries) == (
        first.entry_id,
        second.entry_id,
        third.entry_id,
    )
    assert snapshot.entries[-1].source_task_id == second_task


def test_owner_binding_prevents_cross_session_contamination(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.open_session(owner_ref=OWNER)
    second = service.open_session(owner_ref=OTHER_OWNER)
    service.append_visible_message(
        session_id=first.session_id,
        owner_ref=OWNER,
        role=SessionEntryRole.USER,
        content="Only the first owner may see this.",
    )

    with pytest.raises(SessionOwnershipError):
        service.snapshot(session_id=first.session_id, owner_ref=OTHER_OWNER)
    with pytest.raises(SessionOwnershipError):
        service.append_visible_message(
            session_id=first.session_id,
            owner_ref=OTHER_OWNER,
            role=SessionEntryRole.USER,
            content="Must not append.",
        )

    assert service.snapshot(session_id=second.session_id, owner_ref=OTHER_OWNER).entries == ()


def test_closed_session_rejects_new_entries_but_remains_readable(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = service.open_session(owner_ref=OWNER)
    service.append_visible_message(
        session_id=session.session_id,
        owner_ref=OWNER,
        role=SessionEntryRole.USER,
        content="Persist before close.",
    )

    closed = service.close_session(session_id=session.session_id, owner_ref=OWNER)
    assert closed.status is SessionStatus.CLOSED
    assert closed.closed_at is not None

    with pytest.raises(SessionClosedError):
        service.append_visible_message(
            session_id=session.session_id,
            owner_ref=OWNER,
            role=SessionEntryRole.ASSISTANT,
            content="Must not append after close.",
        )
    assert len(service.snapshot(session_id=session.session_id, owner_ref=OWNER).entries) == 1


def test_secret_text_is_redacted_before_sqlite_persistence(tmp_path: Path) -> None:
    secret = "owner-secret-value"
    service = _service(tmp_path, explicit_secrets=(secret,))
    session = service.open_session(owner_ref=OWNER)
    entry = service.append_visible_message(
        session_id=session.session_id,
        owner_ref=OWNER,
        role=SessionEntryRole.USER,
        content=f"Use token={secret} and remember {secret} in this visible message.",
    )

    assert secret not in entry.content
    assert entry.redactions_applied
    database_bytes = (tmp_path / "session.sqlite3").read_bytes()
    assert secret.encode("utf-8") not in database_bytes


def test_projection_is_runtime_continuity_data_only_unverified_conversation(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    session = service.open_session(owner_ref=OWNER)
    service.append_visible_message(
        session_id=session.session_id,
        owner_ref=OWNER,
        role=SessionEntryRole.USER,
        content="Earlier conversation context, not current reality.",
    )

    candidates = service.project_context(session_id=session.session_id, owner_ref=OWNER)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.layer is ContextLayer.RUNTIME_CONTINUITY
    assert candidate.interpretation is ContextInterpretation.DATA_ONLY
    assert candidate.required is False
    assert candidate.source.verified is False
    assert candidate.source.metadata["authority_role"] == ContextAuthorityRole.CONVERSATION.value
    assert str(candidate.source.locator).startswith(f"session://{session.session_id}/entry/")

    bundle = LayeredContextComposer().compose(task_id=uuid4(), candidates=candidates)
    assert tuple(section.layer for section in bundle.sections) == CONTEXT_LAYER_ORDER
    entry = next(
        entry
        for section in bundle.sections
        if section.layer is ContextLayer.RUNTIME_CONTINUITY
        for entry in section.entries
    )
    assert entry.interpretation is ContextInterpretation.DATA_ONLY
    assert entry.source.verified is False


def test_bounded_snapshot_keeps_newest_entries_in_chronological_order(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = service.open_session(owner_ref=OWNER)
    for index in range(1, 6):
        service.append_visible_message(
            session_id=session.session_id,
            owner_ref=OWNER,
            role=SessionEntryRole.SUMMARY,
            content=f"entry-{index}",
        )

    snapshot = service.snapshot(
        session_id=session.session_id,
        owner_ref=OWNER,
        max_entries=3,
        max_chars=100,
    )
    assert tuple(entry.content for entry in snapshot.entries) == ("entry-3", "entry-4", "entry-5")
    assert snapshot.truncated_entries == 2

    char_bounded = service.snapshot(
        session_id=session.session_id,
        owner_ref=OWNER,
        max_entries=5,
        max_chars=len("entry-4") + len("entry-5"),
    )
    assert tuple(entry.content for entry in char_bounded.entries) == ("entry-4", "entry-5")
    assert char_bounded.truncated_entries == 3


def test_session_contract_has_no_authority_verification_or_hidden_reasoning_fields() -> None:
    session_id = uuid4()
    base = {
        "session_id": session_id,
        "sequence": 1,
        "role": SessionEntryRole.ASSISTANT,
        "content": "Visible answer only.",
    }
    for forbidden in (
        "verified",
        "tool_policy",
        "approval_id",
        "checkpoint_id",
        "evidence_id",
        "hidden_reasoning",
        "provider_reasoning",
    ):
        payload = dict(base)
        payload[forbidden] = "forbidden"
        with pytest.raises(ValidationError):
            SessionEntry.model_validate(payload)


def test_store_detects_persisted_entry_tampering(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = service.open_session(owner_ref=OWNER)
    entry = service.append_visible_message(
        session_id=session.session_id,
        owner_ref=OWNER,
        role=SessionEntryRole.USER,
        content="Integrity protected visible message.",
    )

    database = tmp_path / "session.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE session_entries SET payload_json = ? WHERE entry_id = ?",
            ("{}", str(entry.entry_id)),
        )
        connection.commit()

    with pytest.raises(SessionIntegrityError):
        service.snapshot(session_id=session.session_id, owner_ref=OWNER)


def test_explicit_session_id_is_required_for_reuse(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.open_session(owner_ref=OWNER)
    second = service.open_session(owner_ref=OWNER)
    service.append_visible_message(
        session_id=first.session_id,
        owner_ref=OWNER,
        role=SessionEntryRole.USER,
        content="First session only.",
    )

    assert first.session_id != second.session_id
    assert service.snapshot(session_id=second.session_id, owner_ref=OWNER).entries == ()
    assert service.snapshot(session_id=first.session_id, owner_ref=OWNER).entries[0].content == (
        "First session only."
    )
