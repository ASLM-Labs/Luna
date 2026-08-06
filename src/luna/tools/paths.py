"""Canonical workspace path checks shared by tool policy and built-ins."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


class WorkspacePathError(ValueError):
    """Raised when a requested path escapes or violates workspace scope."""


def canonical_workspace_path(workspace_root: str, relative_path: str) -> Path:
    """Resolve a relative path and reject traversal, absolute paths, and symlink escape."""
    normalized = relative_path.replace("\\", "/").strip()
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute() or ".." in pure.parts:
        raise WorkspacePathError("workspace path must be relative and cannot contain '..'")

    root = Path(workspace_root).expanduser().resolve()
    candidate = (root / Path(*pure.parts)).resolve()
    root_key = os.path.normcase(str(root))
    candidate_key = os.path.normcase(str(candidate))
    try:
        common = os.path.commonpath((root_key, candidate_key))
    except ValueError as exc:
        raise WorkspacePathError("workspace path is on a different volume") from exc
    if common != root_key:
        raise WorkspacePathError("workspace path escapes the declared root")
    return candidate


def normalize_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute() or ".." in pure.parts:
        raise WorkspacePathError("scope path must be relative and cannot contain '..'")
    return pure.as_posix()


def path_is_allowed(relative_path: str, allowed_paths: tuple[str, ...]) -> bool:
    """Allow an exact path or a descendant of an explicitly allowed directory."""
    candidate = PurePosixPath(normalize_relative_path(relative_path))
    candidate_parts = tuple(part.casefold() for part in candidate.parts)
    for allowed in allowed_paths:
        allowed_path = PurePosixPath(normalize_relative_path(allowed))
        allowed_parts = tuple(part.casefold() for part in allowed_path.parts)
        if candidate_parts[: len(allowed_parts)] == allowed_parts:
            return True
    return False


def ensure_no_symlink_components(workspace_root: str, relative_path: str) -> None:
    """Reject existing symlink components before any read or write target is used."""
    normalized = normalize_relative_path(relative_path)
    root = Path(workspace_root).expanduser().resolve()
    current = root
    for part in PurePosixPath(normalized).parts:
        current = current / part
        if current.is_symlink():
            raise WorkspacePathError("workspace path contains a symlink component")
