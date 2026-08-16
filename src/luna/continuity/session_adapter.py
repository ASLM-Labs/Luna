"""Working-session adapter for cognitive owner binding and snapshot resolution."""

from __future__ import annotations

import json
from collections.abc import Iterable
from hashlib import sha256

from luna.continuity.cognitive import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolution,
    CognitiveOwnerResolutionStatus,
    build_cognitive_owner_resolution,
)
from luna.sessions.models import SessionEntry, WorkingSession, model_digest

_SESSION_SOURCE_PREFIX = "session://"
_SESSION_OWNER_DIGEST_VERSION = 1


def _canonical_session_entries(
    *,
    session: WorkingSession,
    entries: Iterable[SessionEntry],
) -> tuple[SessionEntry, ...]:
    entries_tuple = tuple(entries)
    if any(entry.session_id != session.session_id for entry in entries_tuple):
        raise ValueError("session owner entries must belong to the selected session")

    sequences = tuple(entry.sequence for entry in entries_tuple)
    if sequences != tuple(range(1, len(entries_tuple) + 1)):
        raise ValueError("session owner entries must be the full contiguous sequence")

    entry_ids = tuple(entry.entry_id for entry in entries_tuple)
    if len(entry_ids) != len(set(entry_ids)):
        raise ValueError("session owner entries must have unique entry IDs")

    return entries_tuple


def _session_owner_digest(
    *,
    session: WorkingSession,
    entries: Iterable[SessionEntry],
) -> str:
    entries_tuple = _canonical_session_entries(session=session, entries=entries)
    payload = {
        "semantics_version": _SESSION_OWNER_DIGEST_VERSION,
        "session_sha256": model_digest(session),
        "entry_sha256": [model_digest(entry) for entry in entries_tuple],
    }
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(rendered.encode("utf-8")).hexdigest()


def build_session_owner_binding(
    *,
    session: WorkingSession,
    entries: Iterable[SessionEntry],
) -> CognitiveOwnerBinding:
    """Bind one canonical session plus its full ordered entry chain."""

    return CognitiveOwnerBinding(
        owner_kind=CognitiveOwnerKind.WORKING_SESSION,
        source_ref=f"{_SESSION_SOURCE_PREFIX}{session.session_id}",
        content_sha256=_session_owner_digest(session=session, entries=entries),
    )


def resolve_session_owner_binding(
    *,
    historical_binding: CognitiveOwnerBinding,
    current_session: WorkingSession | None,
    current_entries: Iterable[SessionEntry] = (),
    current_unavailable: bool = False,
) -> CognitiveOwnerResolution:
    """Compare one historical session binding with its exact current owner state."""

    if historical_binding.owner_kind is not CognitiveOwnerKind.WORKING_SESSION:
        raise ValueError("historical binding is not a working-session binding")

    entries_tuple = tuple(current_entries)
    if current_session is None:
        if entries_tuple:
            raise ValueError("missing session owner cannot carry current entries")
        absence_status = (
            CognitiveOwnerResolutionStatus.UNAVAILABLE
            if current_unavailable
            else CognitiveOwnerResolutionStatus.MISSING
        )
        return build_cognitive_owner_resolution(
            historical_binding=historical_binding,
            absence_status=absence_status,
        )

    if current_unavailable:
        raise ValueError("available working session cannot also be marked unavailable")

    current_binding = build_session_owner_binding(
        session=current_session,
        entries=entries_tuple,
    )
    if current_binding.source_ref != historical_binding.source_ref:
        raise ValueError(
            "current working session does not match historical session identity"
        )

    return build_cognitive_owner_resolution(
        historical_binding=historical_binding,
        current_binding=current_binding,
    )
