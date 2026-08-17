"""Thin current-owner capture and historical/current snapshot resolution."""

from __future__ import annotations

import sqlite3
from uuid import UUID

from luna.continuity.cognitive import (
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolution,
    CognitiveOwnerResolutionStatus,
    CognitiveRehydrationManifest,
    build_cognitive_owner_resolution,
)
from luna.continuity.identity_adapter import resolve_identity_owner_binding
from luna.continuity.memory_adapter import resolve_memory_owner_binding
from luna.continuity.session_adapter import resolve_session_owner_binding
from luna.continuity.verification_evidence_adapter import (
    resolve_verification_evidence_owner_binding,
)
from luna.identity.service import CurrentIdentityProvider
from luna.identity.store import (
    IdentityNotInitializedError,
    IdentityStoreError,
)
from luna.memory.service import CurrentMemoryProvider
from luna.memory.store import MemoryNotFoundError, MemoryStoreError
from luna.sessions.service import CurrentSessionProvider
from luna.sessions.store import SessionNotFoundError, SessionStoreError
from luna.verification.evidence_store import (
    CurrentVerificationEvidenceProvider,
    EvidenceStoreError,
)

_IDENTITY_SOURCE_PREFIX = "identity://luna/profile/"
_MEMORY_SOURCE_PREFIX = "memory://record/"
_SESSION_SOURCE_PREFIX = "session://"
_EVIDENCE_SOURCE_PREFIX = "verification://task/"
_EVIDENCE_SOURCE_SUFFIX = "/evidence"


def _canonical_uuid_source_ref(
    source_ref: str,
    *,
    prefix: str,
    owner_label: str,
) -> UUID:
    """Parse one adapter-owned canonical UUID source ref."""

    if not source_ref.startswith(prefix):
        raise ValueError(
            f"{owner_label} historical binding has non-canonical source_ref"
        )

    raw = source_ref[len(prefix) :]

    try:
        owner_id = UUID(raw)
    except ValueError as exc:
        raise ValueError(
            f"{owner_label} historical binding has invalid canonical UUID"
        ) from exc

    if source_ref != f"{prefix}{owner_id}":
        raise ValueError(
            f"{owner_label} historical binding source_ref is not canonical"
        )

    return owner_id


class CognitiveCurrentOwnerCoordinator:
    """Resolve historical owner bindings only from canonical current providers."""

    def __init__(
        self,
        *,
        identity_provider: CurrentIdentityProvider,
        memory_provider: CurrentMemoryProvider,
        session_provider: CurrentSessionProvider,
        evidence_provider: CurrentVerificationEvidenceProvider,
    ) -> None:
        self._identity_provider = identity_provider
        self._memory_provider = memory_provider
        self._session_provider = session_provider
        self._evidence_provider = evidence_provider

    def resolve_manifest(
        self,
        manifest: CognitiveRehydrationManifest,
    ) -> tuple[CognitiveOwnerResolution, ...]:
        """Resolve every historical binding against current canonical owner state."""

        return tuple(
            self._resolve_binding(
                manifest=manifest,
                historical_binding=binding,
            )
            for binding in manifest.bindings
        )

    def _resolve_binding(
        self,
        *,
        manifest: CognitiveRehydrationManifest,
        historical_binding: CognitiveOwnerBinding,
    ) -> CognitiveOwnerResolution:
        owner_kind = historical_binding.owner_kind

        if owner_kind is CognitiveOwnerKind.IDENTITY_PROFILE:
            return self._resolve_identity(
                historical_binding=historical_binding
            )

        if owner_kind is CognitiveOwnerKind.VERIFIED_MEMORY:
            return self._resolve_memory(
                historical_binding=historical_binding
            )

        if owner_kind is CognitiveOwnerKind.WORKING_SESSION:
            return self._resolve_session(
                historical_binding=historical_binding
            )

        if owner_kind is CognitiveOwnerKind.VERIFICATION_EVIDENCE:
            return self._resolve_evidence(
                manifest=manifest,
                historical_binding=historical_binding,
            )

        raise ValueError(
            f"unsupported cognitive owner kind: {owner_kind}"
        )

    def _resolve_identity(
        self,
        *,
        historical_binding: CognitiveOwnerBinding,
    ) -> CognitiveOwnerResolution:
        _canonical_uuid_source_ref(
            historical_binding.source_ref,
            prefix=_IDENTITY_SOURCE_PREFIX,
            owner_label="identity",
        )

        try:
            current = self._identity_provider.current_identity()
        except IdentityNotInitializedError:
            return build_cognitive_owner_resolution(
                historical_binding=historical_binding,
                absence_status=CognitiveOwnerResolutionStatus.MISSING,
            )
        except (IdentityStoreError, sqlite3.DatabaseError):
            return build_cognitive_owner_resolution(
                historical_binding=historical_binding,
                absence_status=CognitiveOwnerResolutionStatus.UNAVAILABLE,
            )

        return resolve_identity_owner_binding(
            historical_binding=historical_binding,
            current_identity=current,
        )

    def _resolve_memory(
        self,
        *,
        historical_binding: CognitiveOwnerBinding,
    ) -> CognitiveOwnerResolution:
        memory_id = _canonical_uuid_source_ref(
            historical_binding.source_ref,
            prefix=_MEMORY_SOURCE_PREFIX,
            owner_label="memory",
        )

        try:
            current = self._memory_provider.current_memory(
                memory_id
            )
        except MemoryNotFoundError:
            return resolve_memory_owner_binding(
                historical_binding=historical_binding,
                current_record=None,
            )
        except (MemoryStoreError, sqlite3.DatabaseError):
            return resolve_memory_owner_binding(
                historical_binding=historical_binding,
                current_record=None,
                current_unavailable=True,
            )

        return resolve_memory_owner_binding(
            historical_binding=historical_binding,
            current_record=current,
        )

    def _resolve_session(
        self,
        *,
        historical_binding: CognitiveOwnerBinding,
    ) -> CognitiveOwnerResolution:
        session_id = _canonical_uuid_source_ref(
            historical_binding.source_ref,
            prefix=_SESSION_SOURCE_PREFIX,
            owner_label="session",
        )

        try:
            current_session, current_entries = (
                self._session_provider.current_session(
                    session_id
                )
            )
        except SessionNotFoundError:
            return resolve_session_owner_binding(
                historical_binding=historical_binding,
                current_session=None,
            )
        except (SessionStoreError, sqlite3.DatabaseError):
            return resolve_session_owner_binding(
                historical_binding=historical_binding,
                current_session=None,
                current_unavailable=True,
            )

        return resolve_session_owner_binding(
            historical_binding=historical_binding,
            current_session=current_session,
            current_entries=current_entries,
        )

    def _resolve_evidence(
        self,
        *,
        manifest: CognitiveRehydrationManifest,
        historical_binding: CognitiveOwnerBinding,
    ) -> CognitiveOwnerResolution:
        expected_source_ref = (
            f"{_EVIDENCE_SOURCE_PREFIX}"
            f"{manifest.task_id}"
            f"{_EVIDENCE_SOURCE_SUFFIX}"
        )

        if historical_binding.source_ref != expected_source_ref:
            raise ValueError(
                "historical verification evidence binding "
                "does not match manifest task identity"
            )

        try:
            current = self._evidence_provider.current_evidence(
                manifest.task_id
            )
        except (EvidenceStoreError, sqlite3.DatabaseError):
            return resolve_verification_evidence_owner_binding(
                historical_binding=historical_binding,
                task_id=manifest.task_id,
                current_evidence=None,
                current_unavailable=True,
            )

        return resolve_verification_evidence_owner_binding(
            historical_binding=historical_binding,
            task_id=manifest.task_id,
            current_evidence=current,
        )
