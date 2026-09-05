"""Process-local serialization for workspace mutation targets."""

from __future__ import annotations

from _thread import LockType
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from os.path import normcase
from threading import Lock

_REGISTRY_GUARD = Lock()


@dataclass(slots=True)
class _TargetLockEntry:
    """One process-local target lock plus active holders and waiters."""

    lock: LockType
    participants: int = 0


_TARGET_LOCKS: dict[tuple[str, str], _TargetLockEntry] = {}


class WorkspaceTargetSerializer:
    """Serialize Luna mutations to one target within this process."""

    def __init__(self, *, workspace_root_digest: str) -> None:
        self.workspace_root_digest = workspace_root_digest

    @contextmanager
    def hold(self, relative_path: str) -> Iterator[None]:
        """Hold the shared lock for one platform-canonical target identity."""

        key = (
            self.workspace_root_digest,
            normcase(relative_path),
        )

        with _REGISTRY_GUARD:
            entry = _TARGET_LOCKS.get(key)
            if entry is None:
                entry = _TargetLockEntry(lock=Lock())
                _TARGET_LOCKS[key] = entry
            entry.participants += 1

        try:
            with entry.lock:
                yield
        finally:
            with _REGISTRY_GUARD:
                entry.participants -= 1
                if (
                    entry.participants == 0
                    and _TARGET_LOCKS.get(key) is entry
                ):
                    del _TARGET_LOCKS[key]
