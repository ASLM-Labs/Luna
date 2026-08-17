"""Canonical IdentityProfile lifecycle and read-only current-owner boundary."""

from __future__ import annotations

from typing import Protocol

from luna.identity.models import IdentityProfile
from luna.identity.store import SQLiteIdentityStore


class CurrentIdentityProvider(Protocol):
    """Read-only boundary exposing the canonical current Luna identity."""

    def current_identity(self) -> IdentityProfile:
        """Return canonical current identity state without granting authority."""
        ...


class IdentityProfileService:
    """Own explicit identity bootstrap while exposing read-only current state."""

    def __init__(self, store: SQLiteIdentityStore) -> None:
        self._store = store

    def initialize(self, profile: IdentityProfile) -> IdentityProfile:
        """Explicitly establish the initial durable canonical identity."""
        return self._store.initialize(profile)

    def current_identity(self) -> IdentityProfile:
        """Return the exact durable canonical current identity."""
        return self._store.load_current()
