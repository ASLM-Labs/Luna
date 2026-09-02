from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.recovery import ChangeEstimate, WorkspaceIsolationPolicy
from luna.runtime.isolation import (
    GitWorktreeIsolationManager,
    WorkspaceIsolationError,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(
    repo: Path,
    *args: str,
) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_revision(
    value: str | None,
) -> str:
    assert value is not None
    return value


def _init_repo(path: Path, marker: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    _git(path, "config", "user.email", "luna-test@example.invalid")
    _git(path, "config", "user.name", "Luna Test")
    (path / "marker.txt").write_text(marker, encoding="utf-8")
    _git(path, "add", "marker.txt")
    _git(path, "commit", "-m", "baseline")


def test_cd02_rejects_unrelated_repo_at_deterministic_worktree_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _init_repo(source, "SOURCE")

    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Verify deterministic worktree ownership.",
        required_conditions=(
            "An unrelated repository must never be reused as Luna isolation.",
        ),
        evidence_required=("CD-02 regression",),
        scope=TaskScope(
            workspace_root=str(source),
            allowed_paths=("marker.txt",),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
        owner="test-owner",
    )

    manager = GitWorktreeIsolationManager(
        worktree_base_root=str(tmp_path / "luna-worktrees"),
    )

    target = manager._target(source.resolve(), task_id)
    _init_repo(target, "UNRELATED")

    assert manager.worktree_available(contract) is False

    decision = WorkspaceIsolationPolicy().plan(
        task_contract=contract,
        change=ChangeEstimate(
            touched_paths=("marker.txt",),
            added_lines=1,
        ),
        worktree_available=True,
    )

    with pytest.raises(WorkspaceIsolationError):
        manager.acquire(
            task_contract=contract,
            decision=decision,
            task_id=task_id,
        )

def test_cd02_reuses_owned_current_head_linked_worktree(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _init_repo(source, "SOURCE")

    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Verify owned worktree reuse.",
        required_conditions=("A Luna-owned current worktree remains reusable.",),
        evidence_required=("CD-02 positive control",),
        scope=TaskScope(
            workspace_root=str(source),
            allowed_paths=("marker.txt",),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
        owner="test-owner",
    )
    manager = GitWorktreeIsolationManager(
        worktree_base_root=str(tmp_path / "luna-worktrees"),
    )
    decision = WorkspaceIsolationPolicy().plan(
        task_contract=contract,
        change=ChangeEstimate(
            touched_paths=("marker.txt",),
            added_lines=1,
        ),
        worktree_available=True,
    )

    first = manager.acquire(
        task_contract=contract,
        decision=decision,
        task_id=task_id,
    )
    try:
        assert manager.worktree_available(contract) is True

        second = manager.acquire(
            task_contract=contract,
            decision=decision,
            task_id=task_id,
        )

        assert Path(second.workspace_root).resolve() == Path(
            first.workspace_root
        ).resolve()
    finally:
        manager.cleanup(task_contract=contract, task_id=task_id)


def test_cd02_rejects_owned_worktree_when_source_head_has_advanced(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _init_repo(source, "SOURCE")

    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Reject stale owned worktree reuse.",
        required_conditions=(
            "A Luna-owned worktree at a stale source HEAD must not be reused.",
        ),
        evidence_required=("CD-02 stale-head control",),
        scope=TaskScope(
            workspace_root=str(source),
            allowed_paths=("marker.txt",),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
        owner="test-owner",
    )
    manager = GitWorktreeIsolationManager(
        worktree_base_root=str(tmp_path / "luna-worktrees"),
    )
    decision = WorkspaceIsolationPolicy().plan(
        task_contract=contract,
        change=ChangeEstimate(
            touched_paths=("marker.txt",),
            added_lines=1,
        ),
        worktree_available=True,
    )

    manager.acquire(
        task_contract=contract,
        decision=decision,
        task_id=task_id,
    )
    try:
        (source / "next.txt").write_text("NEXT\n", encoding="utf-8")
        _git(source, "add", "next.txt")
        _git(source, "commit", "-m", "advance source head")

        assert manager.worktree_available(contract) is False

        with pytest.raises(WorkspaceIsolationError):
            manager.acquire(
                task_contract=contract,
                decision=decision,
                task_id=task_id,
            )
    finally:
        manager.cleanup(task_contract=contract, task_id=task_id)


def test_w4c_historical_worktree_revalidation_accepts_owned_stale_worktree(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _init_repo(source, "SOURCE")

    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Revalidate historical Luna worktree ownership.",
        required_conditions=(
            "Historical identity must not require the current source HEAD.",
        ),
        evidence_required=("W4C historical worktree identity",),
        scope=TaskScope(
            workspace_root=str(source),
            allowed_paths=("marker.txt",),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
        owner="test-owner",
    )
    manager = GitWorktreeIsolationManager(
        worktree_base_root=str(tmp_path / "luna-worktrees"),
    )
    decision = WorkspaceIsolationPolicy().plan(
        task_contract=contract,
        change=ChangeEstimate(
            touched_paths=("marker.txt",),
            added_lines=1,
        ),
        worktree_available=True,
    )

    lease = manager.acquire(
        task_contract=contract,
        decision=decision,
        task_id=task_id,
    )
    try:
        historical_root = Path(lease.workspace_root).resolve()

        assert lease.execution_revision == _git_output(
            historical_root,
            "rev-parse",
            "HEAD",
        )

        (source / "next.txt").write_text("NEXT\n", encoding="utf-8")
        _git(source, "add", "next.txt")
        _git(source, "commit", "-m", "advance source after isolation")

        assert manager.worktree_available(contract) is False

        (source / "dirty.txt").write_text("DIRTY\n", encoding="utf-8")

        (historical_root / "marker.txt").write_text(
            "CURRENT-DRIFT\n",
            encoding="utf-8",
        )

        validated = manager.revalidate_historical_worktree(
            source_workspace_root=str(source),
            execution_workspace_root=str(historical_root),
            execution_revision=_require_revision(lease.execution_revision),
            task_id=task_id,
        )

        assert Path(validated).resolve() == historical_root

        original_revision = _require_revision(
            lease.execution_revision
        )
        _git(
            historical_root,
            "add",
            "marker.txt",
        )
        _git(
            historical_root,
            "commit",
            "-m",
            "advance historical detached revision",
        )
        assert _git_output(
            historical_root,
            "rev-parse",
            "HEAD",
        ) != original_revision
        with pytest.raises(
            WorkspaceIsolationError,
            match="revision changed",
        ):
            manager.revalidate_historical_worktree(
                source_workspace_root=str(source),
                execution_workspace_root=str(historical_root),
                execution_revision=original_revision,
                task_id=task_id,
            )
    finally:
        manager.cleanup(
            task_contract=contract,
            task_id=task_id,
        )


def test_w4c_historical_worktree_revalidation_rejects_wrong_execution_path(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _init_repo(source, "SOURCE")

    task_id = uuid4()
    manager = GitWorktreeIsolationManager(
        worktree_base_root=str(tmp_path / "luna-worktrees"),
    )

    with pytest.raises(
        WorkspaceIsolationError,
        match="does not match the deterministic task worktree",
    ):
        manager.revalidate_historical_worktree(
            source_workspace_root=str(source),
            execution_workspace_root=str(source),
            execution_revision=_git_output(source, "rev-parse", "HEAD"),
            task_id=task_id,
        )


def test_w4c_historical_worktree_revalidation_rejects_unrelated_repo(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _init_repo(source, "SOURCE")

    task_id = uuid4()
    manager = GitWorktreeIsolationManager(
        worktree_base_root=str(tmp_path / "luna-worktrees"),
    )

    target = manager._target(source.resolve(), task_id)
    _init_repo(target, "UNRELATED")

    with pytest.raises(
        WorkspaceIsolationError,
        match="not owned by the source repository",
    ):
        manager.revalidate_historical_worktree(
            source_workspace_root=str(source),
            execution_workspace_root=str(target),
            execution_revision=_git_output(target, "rev-parse", "HEAD"),
            task_id=task_id,
        )


def test_w4c_historical_worktree_revalidation_rejects_attached_branch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _init_repo(source, "SOURCE")

    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Reject attached historical worktree state.",
        required_conditions=(
            "Historical Luna isolation must remain detached.",
        ),
        evidence_required=("W4C detached worktree identity",),
        scope=TaskScope(
            workspace_root=str(source),
            allowed_paths=("marker.txt",),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
        owner="test-owner",
    )
    manager = GitWorktreeIsolationManager(
        worktree_base_root=str(tmp_path / "luna-worktrees"),
    )
    decision = WorkspaceIsolationPolicy().plan(
        task_contract=contract,
        change=ChangeEstimate(
            touched_paths=("marker.txt",),
            added_lines=1,
        ),
        worktree_available=True,
    )

    lease = manager.acquire(
        task_contract=contract,
        decision=decision,
        task_id=task_id,
    )
    try:
        target = Path(lease.workspace_root).resolve()
        _git(target, "switch", "-c", "w4c-attached")

        with pytest.raises(
            WorkspaceIsolationError,
            match="must remain detached",
        ):
            manager.revalidate_historical_worktree(
                source_workspace_root=str(source),
                execution_workspace_root=str(target),
                execution_revision=_require_revision(lease.execution_revision),
                task_id=task_id,
            )
    finally:
        manager.cleanup(
            task_contract=contract,
            task_id=task_id,
        )
