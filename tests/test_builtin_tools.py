from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.tools import (
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    build_phase4_registry,
)


def make_contract(root: Path, allowed_paths: tuple[str, ...]) -> TaskContract:
    return TaskContract(
        objective="Read scoped project context",
        required_conditions=("Only allowed paths may be read",),
        evidence_required=("ToolResult hash",),
        scope=TaskScope(
            workspace_root=str(root),
            allowed_paths=allowed_paths,
        ),
        risk_level=RiskLevel.LOW,
    )


def test_scoped_read_text_returns_hash_and_content(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.txt").write_text("Luna", encoding="utf-8")
    task = make_contract(tmp_path, ("docs",))

    outcome = ToolDispatcher(build_phase4_registry()).dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.read_text",
            arguments={"path": "docs/note.txt"},
        ),
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.result.status is ToolResultStatus.SUCCESS
    assert outcome.result.stdout_excerpt == "Luna"
    assert len(outcome.result.stdout_digest) == 64


def test_read_outside_allowed_paths_is_blocked(tmp_path: Path) -> None:
    (tmp_path / "private.txt").write_text("secret", encoding="utf-8")
    task = make_contract(tmp_path, ("docs",))

    outcome = ToolDispatcher(build_phase4_registry()).dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.read_text",
            arguments={"path": "private.txt"},
        ),
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED
    assert "allowed_paths" in outcome.event.reason


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    task = make_contract(tmp_path, ("docs",))

    outcome = ToolDispatcher(build_phase4_registry()).dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.read_text",
            arguments={"path": "../outside.txt"},
        ),
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("filesystem.read_text",)),
    )

    assert outcome.result.status is ToolResultStatus.BLOCKED


def test_directory_listing_is_sorted_and_scoped(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "b.txt").write_text("b", encoding="utf-8")
    (docs / "a.txt").write_text("a", encoding="utf-8")
    (docs / "sub").mkdir()
    task = make_contract(tmp_path, ("docs",))

    outcome = ToolDispatcher(build_phase4_registry()).dispatch(
        request=ToolRequest(
            task_id=task.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.list_directory",
            arguments={"path": "docs"},
        ),
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("filesystem.list_directory",)),
    )

    assert outcome.result.status is ToolResultStatus.SUCCESS
    assert outcome.result.stdout_excerpt.splitlines() == ["a.txt", "b.txt", "sub/"]
