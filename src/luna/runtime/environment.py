"""Deterministic runtime/environment fingerprints used by Phase 12E checkpoints."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from luna.continuity import ResumePolicy
from luna.contracts.task import TaskContract
from luna.tools.paths import canonical_workspace_path


class RuntimeFingerprintError(RuntimeError):
    """Raised when a continuity fingerprint cannot be computed safely."""


class RuntimeFingerprintProvider(Protocol):
    """Supply fresh fingerprints at every durable checkpoint/resume boundary."""

    @property
    def runtime_revision(self) -> str:
        """Return the runtime build/revision used for continuity compatibility."""
        ...

    def workspace_fingerprint(
        self,
        *,
        task_contract: TaskContract,
        workspace_root: str | None = None,
    ) -> str:
        """Return a deterministic fingerprint for the effective workspace."""
        ...

    def environment_fingerprint(self) -> str:
        """Return a deterministic fingerprint for the current Python/runtime environment."""
        ...

    def resume_policy(
        self,
        *,
        task_contract: TaskContract,
        workspace_root: str | None = None,
    ) -> ResumePolicy:
        """Build the exact policy consumed by ContinuityService.resume_latest."""
        ...


class DeterministicFingerprintProvider:
    """Hash Git state when available, otherwise hash task-scoped filesystem content."""

    def __init__(
        self,
        *,
        runtime_revision: str = "luna-0.1-phase12e",
        git_executable: str = "git",
        max_fallback_files: int = 10_000,
        max_fallback_bytes: int = 100_000_000,
    ) -> None:
        if not runtime_revision.strip():
            raise ValueError("runtime_revision cannot be blank")
        self._runtime_revision = runtime_revision.strip()
        self._git = git_executable
        self._max_fallback_files = max_fallback_files
        self._max_fallback_bytes = max_fallback_bytes

    @property
    def runtime_revision(self) -> str:
        return self._runtime_revision

    @staticmethod
    def _run(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            shell=False,
        )

    def _git_fingerprint(self, root: Path) -> str | None:
        if shutil.which(self._git) is None:
            return None
        top = self._run(
            [self._git, "-C", str(root), "rev-parse", "--show-toplevel"]
        )
        if top.returncode != 0:
            return None
        try:
            top_path = Path(top.stdout.decode("utf-8").strip()).resolve()
        except UnicodeDecodeError:
            return None
        if top_path != root:
            return None

        commands = (
            [self._git, "-C", str(root), "rev-parse", "HEAD"],
            [self._git, "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            [self._git, "-C", str(root), "diff", "--binary", "HEAD", "--"],
            [self._git, "-C", str(root), "diff", "--binary", "--cached", "HEAD", "--"],
            [self._git, "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
        )
        outputs: list[bytes] = []
        for command in commands:
            result = self._run(command)
            if result.returncode != 0:
                raise RuntimeFingerprintError(
                    "Git workspace fingerprint command failed: "
                    + result.stderr.decode("utf-8", errors="replace").strip()
                )
            outputs.append(result.stdout)

        digest = sha256()
        digest.update(b"luna-workspace-git-v1\0")
        digest.update(str(root).encode("utf-8"))
        for output in outputs[:4]:
            digest.update(b"\0")
            digest.update(output)

        untracked = tuple(
            value.decode("utf-8", errors="surrogateescape")
            for value in outputs[4].split(b"\0")
            if value
        )
        for relative in sorted(untracked):
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise RuntimeFingerprintError(
                    "untracked fingerprint path escaped workspace"
                ) from exc
            digest.update(b"\0UNTRACKED\0")
            digest.update(relative.encode("utf-8", errors="surrogateescape"))
            if target.is_file() and not target.is_symlink():
                digest.update(target.read_bytes())
            elif target.is_symlink():
                digest.update(b"SYMLINK:")
                digest.update(os.readlink(target).encode("utf-8", errors="surrogateescape"))
            else:
                digest.update(b"NON_FILE")
        return digest.hexdigest()

    def _fallback_fingerprint(self, contract: TaskContract, root: Path) -> str:
        digest = sha256()
        digest.update(b"luna-workspace-scoped-v1\0")
        digest.update(str(root).encode("utf-8"))
        paths = tuple(
            dict.fromkeys((*contract.scope.allowed_paths, *contract.scope.protected_paths))
        )
        if not paths:
            digest.update(b"\0NO_SCOPED_PATHS")
            return digest.hexdigest()

        file_count = 0
        byte_count = 0
        for relative in sorted(paths):
            target = canonical_workspace_path(str(root), relative)
            digest.update(b"\0PATH\0")
            digest.update(relative.encode("utf-8"))
            if not target.exists():
                digest.update(b"\0MISSING")
                continue
            candidates = (target,) if target.is_file() else tuple(
                path
                for path in sorted(target.rglob("*"))
                if ".git" not in path.parts and ".luna" not in path.parts
            )
            for item in candidates:
                if item.is_dir():
                    continue
                file_count += 1
                if file_count > self._max_fallback_files:
                    raise RuntimeFingerprintError("workspace fingerprint file limit exceeded")
                rel = item.relative_to(root).as_posix()
                digest.update(b"\0FILE\0")
                digest.update(rel.encode("utf-8"))
                if item.is_symlink():
                    digest.update(b"SYMLINK:")
                    digest.update(os.readlink(item).encode("utf-8", errors="surrogateescape"))
                    continue
                data = item.read_bytes()
                byte_count += len(data)
                if byte_count > self._max_fallback_bytes:
                    raise RuntimeFingerprintError("workspace fingerprint byte limit exceeded")
                digest.update(data)
        return digest.hexdigest()

    def workspace_fingerprint(
        self,
        *,
        task_contract: TaskContract,
        workspace_root: str | None = None,
    ) -> str:
        root = Path(workspace_root or task_contract.scope.workspace_root).resolve()
        if not root.exists() or not root.is_dir():
            raise RuntimeFingerprintError("workspace root is unavailable")
        git_digest = self._git_fingerprint(root)
        return git_digest or self._fallback_fingerprint(task_contract, root)

    def environment_fingerprint(self) -> str:
        payload = "\n".join(
            (
                "luna-environment-v1",
                platform.system(),
                platform.release(),
                platform.machine(),
                platform.python_implementation(),
                platform.python_version(),
                sys.executable,
            )
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def resume_policy(
        self,
        *,
        task_contract: TaskContract,
        workspace_root: str | None = None,
    ) -> ResumePolicy:
        return ResumePolicy(
            runtime_revision=self.runtime_revision,
            workspace_fingerprint=self.workspace_fingerprint(
                task_contract=task_contract,
                workspace_root=workspace_root,
            ),
            environment_fingerprint=self.environment_fingerprint(),
        )
