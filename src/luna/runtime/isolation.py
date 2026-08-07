"""Runtime-owned workspace isolation execution for Phase 12E."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import UUID

from luna.contracts.task import TaskContract
from luna.recovery import IsolationDecision, IsolationMode
from luna.tools.paths import WorkspacePathError, canonical_workspace_path


class WorkspaceIsolationError(RuntimeError):
    """Raised when required workspace isolation cannot be established safely."""


@dataclass(frozen=True, slots=True)
class IsolationLease:
    """Effective workspace root for one isolated action."""

    mode: IsolationMode
    workspace_root: str
    cleanup_required: bool = False


class WorkspaceIsolationManager(Protocol):
    """Execution boundary consumed by the policy loop after isolation policy."""

    def worktree_available(self, task_contract: TaskContract) -> bool:
        """Return whether a required linked worktree can be safely created or reused."""
        ...

    def acquire(
        self,
        *,
        task_contract: TaskContract,
        decision: IsolationDecision,
        task_id: UUID,
    ) -> IsolationLease:
        """Acquire the isolation mode selected by runtime policy."""
        ...

    def align_text_baseline(
        self,
        *,
        source_workspace_root: str,
        isolated_workspace_root: str,
        relative_path: str,
    ) -> None:
        """Preserve the source worktree's exact text bytes inside isolation."""
        ...

    def cleanup(self, *, task_contract: TaskContract, task_id: UUID) -> None:
        """Remove a task-owned linked worktree when cancellation/rollback requires it."""
        ...


class GitWorktreeIsolationManager:
    """Use a deterministic detached Git worktree for HIGH/CRITICAL mutations."""

    def __init__(
        self,
        *,
        git_executable: str = "git",
        worktree_base_root: str | None = None,
    ) -> None:
        self._git = git_executable
        if worktree_base_root is None:
            worktree_base_root = str(Path(tempfile.gettempdir()) / "luna-worktrees")
        self._worktree_base_root = Path(worktree_base_root).expanduser().resolve()

    @staticmethod
    def _run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )

    def _repo_root(self, workspace_root: str) -> Path:
        root = Path(workspace_root).resolve()
        if shutil.which(self._git) is None:
            raise WorkspaceIsolationError("git executable is unavailable")
        result = self._run([self._git, "-C", str(root), "rev-parse", "--show-toplevel"])
        if result.returncode != 0:
            raise WorkspaceIsolationError("workspace is not a Git worktree")
        top = Path(result.stdout.strip()).resolve()
        if top != root:
            raise WorkspaceIsolationError(
                "high-risk isolation requires workspace_root to equal the Git toplevel"
            )
        return root

    def _target(self, root: Path, task_id: UUID) -> Path:
        normalized_root = os.path.normcase(str(root.resolve()))
        repo_key = sha256(normalized_root.encode()).hexdigest()[:24]
        return self._worktree_base_root / repo_key / task_id.hex

    def worktree_available(self, task_contract: TaskContract) -> bool:
        try:
            root = self._repo_root(task_contract.scope.workspace_root)
            status = self._run(
                [self._git, "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"]
            )
            if status.returncode != 0 or status.stdout.strip():
                return False
            target = self._target(root, task_contract.task_id)
            if not target.exists():
                return True
            probe = self._run(
                [self._git, "-C", str(target), "rev-parse", "--is-inside-work-tree"]
            )
            return probe.returncode == 0 and probe.stdout.strip().casefold() == "true"
        except WorkspaceIsolationError:
            return False

    def acquire(
        self,
        *,
        task_contract: TaskContract,
        decision: IsolationDecision,
        task_id: UUID,
    ) -> IsolationLease:
        root = Path(task_contract.scope.workspace_root).resolve()
        if decision.mode is IsolationMode.NONE:
            return IsolationLease(mode=IsolationMode.NONE, workspace_root=str(root))
        if decision.mode is IsolationMode.SNAPSHOT:
            return IsolationLease(mode=IsolationMode.SNAPSHOT, workspace_root=str(root))
        if decision.mode is not IsolationMode.WORKTREE:
            raise WorkspaceIsolationError(f"unsupported isolation mode: {decision.mode}")
        if not decision.allowed or not decision.worktree_required:
            raise WorkspaceIsolationError("runtime policy did not authorize worktree isolation")

        root = self._repo_root(task_contract.scope.workspace_root)
        status = self._run(
            [self._git, "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"]
        )
        if status.returncode != 0:
            raise WorkspaceIsolationError("git status failed before worktree creation")
        if status.stdout.strip():
            raise WorkspaceIsolationError("high-risk worktree isolation requires a clean workspace")

        target = self._target(root, task_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            probe = self._run(
                [self._git, "-C", str(target), "rev-parse", "--is-inside-work-tree"]
            )
            if probe.returncode != 0 or probe.stdout.strip().casefold() != "true":
                raise WorkspaceIsolationError(
                    "deterministic worktree path exists but is not a valid Git worktree"
                )
            return IsolationLease(
                mode=IsolationMode.WORKTREE,
                workspace_root=str(target.resolve()),
                cleanup_required=True,
            )

        created = self._run(
            [self._git, "-C", str(root), "worktree", "add", "--detach", str(target), "HEAD"]
        )
        if created.returncode != 0:
            raise WorkspaceIsolationError(
                "git worktree add failed: " + (created.stderr.strip() or created.stdout.strip())
            )
        return IsolationLease(
            mode=IsolationMode.WORKTREE,
            workspace_root=str(target.resolve()),
            cleanup_required=True,
        )

    @staticmethod
    def _normalized_text(raw: bytes) -> str:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceIsolationError(
                "isolated write baseline must be UTF-8 text"
            ) from exc
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def align_text_baseline(
        self,
        *,
        source_workspace_root: str,
        isolated_workspace_root: str,
        relative_path: str,
    ) -> None:
        """Align only line-ending-equivalent text before an isolated mutation.

        Git may materialize a clean linked worktree with different CRLF/LF bytes than
        the owner's source worktree.  Exact write preconditions must remain bound to
        the bytes Luna actually inspected, so the isolated target is aligned only
        when both versions are UTF-8 text and differ solely by line endings.
        """
        try:
            source = canonical_workspace_path(source_workspace_root, relative_path)
            target = canonical_workspace_path(isolated_workspace_root, relative_path)
        except WorkspacePathError as exc:
            raise WorkspaceIsolationError(str(exc)) from exc

        if not source.exists():
            if target.exists():
                raise WorkspaceIsolationError(
                    "isolated worktree contains a target absent from the source baseline"
                )
            return
        if source.is_symlink() or not source.is_file():
            raise WorkspaceIsolationError(
                "source isolation baseline must be a regular file"
            )
        if not target.exists() or target.is_symlink() or not target.is_file():
            raise WorkspaceIsolationError(
                "isolated worktree baseline target must be a regular file"
            )

        source_bytes = source.read_bytes()
        target_bytes = target.read_bytes()
        if source_bytes == target_bytes:
            return
        if self._normalized_text(source_bytes) != self._normalized_text(target_bytes):
            raise WorkspaceIsolationError(
                "isolated worktree baseline differs from source beyond line endings"
            )

        target.write_bytes(source_bytes)
        if target.read_bytes() != source_bytes:
            raise WorkspaceIsolationError(
                "isolated worktree baseline byte alignment could not be verified"
            )

    def cleanup(self, *, task_contract: TaskContract, task_id: UUID) -> None:
        root = self._repo_root(task_contract.scope.workspace_root)
        target = self._target(root, task_id)
        if not target.exists():
            self._run([self._git, "-C", str(root), "worktree", "prune"])
            return
        removed = self._run(
            [self._git, "-C", str(root), "worktree", "remove", "--force", str(target)]
        )
        if removed.returncode != 0:
            raise WorkspaceIsolationError(
                "git worktree remove failed: "
                + (removed.stderr.strip() or removed.stdout.strip())
            )
        self._run([self._git, "-C", str(root), "worktree", "prune"])
