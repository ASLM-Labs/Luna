"""Deterministic pre/post workspace change inspection for Phase 12E."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from luna.actions import ActionKind, ActionProposal
from luna.contracts.task import TaskContract
from luna.recovery import ChangeEstimate
from luna.tools import ToolCapability
from luna.tools.paths import canonical_workspace_path


class ChangeInspectionError(RuntimeError):
    """Raised when a workspace mutation cannot be bounded before execution."""


@dataclass(frozen=True, slots=True)
class ChangeInspection:
    """Internal before-image retained only long enough to verify one mutation."""

    estimate: ChangeEstimate
    relative_path: str
    before_text: str | None
    target_path: Path


def _line_delta(before: str | None, after: str | None) -> tuple[int, int]:
    before_lines = [] if before is None else before.splitlines(keepends=True)
    after_lines = [] if after is None else after.splitlines(keepends=True)
    matcher = SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    added = 0
    deleted = 0
    for tag, first_start, first_end, second_start, second_end in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            deleted += first_end - first_start
        if tag in {"replace", "insert"}:
            added += second_end - second_start
    return added, deleted


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ChangeInspectionError("workspace mutation target must be a regular file")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ChangeInspectionError("workspace mutation target must be UTF-8 text") from exc


class WorkspaceChangeInspector:
    """Derive exact line-change bounds for built-in write tools and verify actual diff."""

    def inspect_declared(
        self,
        *,
        proposal: ActionProposal,
        task_contract: TaskContract,
    ) -> ChangeInspection | None:
        if ToolCapability.WRITE not in proposal.required_capabilities:
            return None
        if proposal.kind is ActionKind.ROLLBACK:
            return None

        tool_name = proposal.preferred_tool_name
        path_value = proposal.arguments.get("path")
        if not isinstance(path_value, str):
            raise ChangeInspectionError("write proposal requires a string path")
        target = canonical_workspace_path(task_contract.scope.workspace_root, path_value)
        before = _read_text(target)

        if tool_name == "filesystem.write_text":
            content = proposal.arguments.get("content")
            if not isinstance(content, str):
                raise ChangeInspectionError("write_text proposal requires string content")
            after = content
        elif tool_name == "filesystem.replace_text":
            old_text = proposal.arguments.get("old_text")
            new_text = proposal.arguments.get("new_text")
            expected_occurrences = proposal.arguments.get("expected_occurrences")
            if not isinstance(old_text, str) or not isinstance(new_text, str):
                raise ChangeInspectionError("replace_text proposal requires string old/new text")
            if not isinstance(expected_occurrences, int) or isinstance(expected_occurrences, bool):
                raise ChangeInspectionError("replace_text proposal requires occurrence count")
            if before is None:
                raise ChangeInspectionError("replace_text target must already exist")
            if before.count(old_text) != expected_occurrences:
                raise ChangeInspectionError(
                    "replace_text before-image does not match expected occurrence count"
                )
            after = before.replace(old_text, new_text)
        else:
            raise ChangeInspectionError(
                "Phase 12E cannot derive a minimal-change bound for this write tool"
            )

        added, deleted = _line_delta(before, after)
        estimate = ChangeEstimate(
            touched_paths=(path_value,),
            added_lines=added,
            deleted_lines=deleted,
        )
        return ChangeInspection(
            estimate=estimate,
            relative_path=path_value,
            before_text=before,
            target_path=target,
        )

    def inspect_observed(self, inspection: ChangeInspection) -> ChangeEstimate:
        after = _read_text(inspection.target_path)
        added, deleted = _line_delta(inspection.before_text, after)
        return ChangeEstimate(
            touched_paths=(inspection.relative_path,),
            added_lines=added,
            deleted_lines=deleted,
        )
