"""Working-session service and non-authoritative context projection."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from luna.audit.redaction import SecretRedactor
from luna.context import (
    ContextAuthorityRole,
    ContextInterpretation,
    ContextLayer,
    ContextSource,
    ContextSourceKind,
    LayeredContextCandidate,
)
from luna.sessions.models import (
    SessionEntry,
    SessionEntryRole,
    SessionSnapshot,
    WorkingSession,
)
from luna.sessions.store import SessionOwnershipError, SQLiteSessionStore


class CurrentSessionProvider(Protocol):
    """Read one exact current durable working-session owner state."""

    def current_session(
        self,
        session_id: UUID,
    ) -> tuple[WorkingSession, tuple[SessionEntry, ...]]:
        """Return the exact session plus its complete ordered entry chain."""
        ...


class WorkingSessionService:
    """Own durable visible conversation history without owning runtime authority."""

    def __init__(
        self,
        store: SQLiteSessionStore,
        *,
        explicit_secrets: tuple[str, ...] = (),
    ) -> None:
        self.store = store
        self._redactor = SecretRedactor(explicit_secrets)

    def current_session(
        self,
        session_id: UUID,
    ) -> tuple[WorkingSession, tuple[SessionEntry, ...]]:
        """Return one complete current durable session state without projection."""
        return self.store.load_session_state(session_id)

    def open_session(self, *, owner_ref: str, label: str | None = None) -> WorkingSession:
        """Create one explicit durable session identity."""
        return self.store.create_session(WorkingSession(owner_ref=owner_ref, label=label))

    def append_visible_message(
        self,
        *,
        session_id: UUID,
        owner_ref: str,
        role: SessionEntryRole,
        content: str,
        source_task_id: UUID | None = None,
    ) -> SessionEntry:
        """Persist caller-supplied visible conversation text after redaction."""
        redacted = self._redactor.redact_text(content)
        return self.store.append_entry(
            session_id=session_id,
            owner_ref=owner_ref,
            role=role,
            content=redacted.text,
            source_task_id=source_task_id,
            redactions_applied=redacted.redactions_applied,
        )

    def close_session(self, *, session_id: UUID, owner_ref: str) -> WorkingSession:
        """Close a session; closed history stays readable but becomes append-immutable."""
        return self.store.close_session(session_id=session_id, owner_ref=owner_ref)

    def snapshot(
        self,
        *,
        session_id: UUID,
        owner_ref: str,
        max_entries: int = 8,
        max_chars: int = 12_000,
    ) -> SessionSnapshot:
        """Return the newest bounded entries while preserving chronological order."""
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        if max_chars < 1:
            raise ValueError("max_chars must be at least 1")
        session = self.store.load_session(session_id)
        if session.owner_ref != owner_ref:
            raise SessionOwnershipError("working session owner binding mismatch")
        entries = self.store.list_entries(session_id)

        retained_reversed: list[SessionEntry] = []
        chars_used = 0
        for entry in reversed(entries):
            if len(retained_reversed) >= max_entries:
                break
            if chars_used + len(entry.content) > max_chars:
                break
            retained_reversed.append(entry)
            chars_used += len(entry.content)
        retained = tuple(reversed(retained_reversed))
        return SessionSnapshot(
            session=session,
            entries=retained,
            truncated_entries=len(entries) - len(retained),
            chars_used=chars_used,
        )

    def project_context(
        self,
        *,
        session_id: UUID,
        owner_ref: str,
        max_entries: int = 8,
        max_chars: int = 12_000,
    ) -> tuple[LayeredContextCandidate, ...]:
        """Project session history only as unverified RUNTIME_CONTINUITY DATA_ONLY."""
        snapshot = self.snapshot(
            session_id=session_id,
            owner_ref=owner_ref,
            max_entries=max_entries,
            max_chars=max_chars,
        )
        projected: list[LayeredContextCandidate] = []
        for entry in snapshot.entries:
            text = f"[{entry.role.value}] {entry.content}"
            source = ContextSource.from_text(
                kind=ContextSourceKind.DOCUMENT,
                locator=f"session://{session_id}/entry/{entry.sequence}",
                text=text,
                verified=False,
                observed_at=entry.created_at,
                metadata={
                    "authority_role": ContextAuthorityRole.CONVERSATION.value,
                    "session_id": str(session_id),
                    "session_sequence": entry.sequence,
                    "session_role": entry.role.value,
                },
            )
            projected.append(
                LayeredContextCandidate(
                    layer=ContextLayer.RUNTIME_CONTINUITY,
                    source=source,
                    priority=40,
                    required=False,
                    interpretation=ContextInterpretation.DATA_ONLY,
                )
            )
        return tuple(projected)
