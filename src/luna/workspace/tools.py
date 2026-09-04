"""Write-capable tool handlers backed by snapshot-first workspace mutations."""

from __future__ import annotations

from uuid import UUID

from luna.tools.models import ToolArgumentValue
from luna.tools.registry import (
    ToolExecutionContext,
    ToolExecutionDenied,
    ToolExecutionOutput,
)
from luna.workspace.mutator import WorkspaceMutationError, WorkspaceMutator


def _string(arguments: dict[str, ToolArgumentValue], name: str) -> str:
    value = arguments[name]
    if not isinstance(value, str):
        raise TypeError(f"validated argument '{name}' is not a string")
    return value


def _boolean(arguments: dict[str, ToolArgumentValue], name: str) -> bool:
    value = arguments[name]
    if not isinstance(value, bool):
        raise TypeError(f"validated argument '{name}' is not a boolean")
    return value


def _integer(arguments: dict[str, ToolArgumentValue], name: str) -> int:
    value = arguments[name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"validated argument '{name}' is not an integer")
    return value


def _mutator(context: ToolExecutionContext) -> WorkspaceMutator:
    scope = context.task_contract.scope
    return WorkspaceMutator(
        workspace_root=scope.workspace_root,
        task_id=context.task_contract.task_id,
        request_id=context.lifecycle.execution_id,
        runtime_receipt_id=context.runtime_receipt_id,
        allowed_paths=scope.allowed_paths,
        protected_paths=scope.protected_paths,
    )


def _rolled_back_output(exc: WorkspaceMutationError) -> ToolExecutionOutput | None:
    rollback = exc.rollback
    if rollback is None:
        return None
    return ToolExecutionOutput(
        exit_code=1,
        stderr=str(exc),
        metadata={
            "rollback_snapshot_id": str(rollback.snapshot_id),
            "rollback_status": rollback.status.value,
            "rollback_verified": rollback.verified,
        },
    )


class WriteTextTool:
    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        expected = arguments.get("expected_sha256")
        if expected is not None and not isinstance(expected, str):
            raise TypeError("validated expected_sha256 is not a string")
        try:
            result = _mutator(context).write_text(
                relative_path=_string(arguments, "path"),
                content=_string(arguments, "content"),
                expected_sha256=expected,
                create_if_missing=_boolean(arguments, "create_if_missing"),
            )
        except WorkspaceMutationError as exc:
            rolled_back = _rolled_back_output(exc)
            if rolled_back is not None:
                return rolled_back
            raise ToolExecutionDenied(str(exc)) from exc
        change = result.changes[0]
        return ToolExecutionOutput(
            stdout="workspace text write committed",
            changed_files=(change.relative_path,),
            applied_changes=result.applied_changes,
            metadata={
                "snapshot_id": str(result.snapshot.snapshot_id),
                "before_sha256": change.before_digest or "ABSENT",
                "after_sha256": change.after_digest or "ABSENT",
                "after_mode": change.after_mode,
                "operation": "write_text",
            },
        )


class ReplaceTextTool:
    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        try:
            result = _mutator(context).replace_text(
                relative_path=_string(arguments, "path"),
                old_text=_string(arguments, "old_text"),
                new_text=_string(arguments, "new_text"),
                expected_sha256=_string(arguments, "expected_sha256"),
                expected_occurrences=_integer(arguments, "expected_occurrences"),
            )
        except WorkspaceMutationError as exc:
            rolled_back = _rolled_back_output(exc)
            if rolled_back is not None:
                return rolled_back
            raise ToolExecutionDenied(str(exc)) from exc
        change = result.changes[0]
        return ToolExecutionOutput(
            stdout="workspace text replacement committed",
            changed_files=(change.relative_path,),
            applied_changes=result.applied_changes,
            metadata={
                "snapshot_id": str(result.snapshot.snapshot_id),
                "before_sha256": change.before_digest or "ABSENT",
                "after_sha256": change.after_digest or "ABSENT",
                "after_mode": change.after_mode,
                "operation": "replace_text",
            },
        )


class SafeUndoSnapshotTool:
    """Canonical explicit conditional safe-undo tool."""

    _stdout_operation = "safe undo"

    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        try:
            snapshot_id = UUID(
                _string(arguments, "snapshot_id")
            )
        except ValueError as exc:
            raise ToolExecutionDenied(
                "snapshot_id must be a UUID"
            ) from exc

        try:
            result = _mutator(
                context
            ).safe_undo(snapshot_id)
        except WorkspaceMutationError as exc:
            raise ToolExecutionDenied(
                str(exc)
            ) from exc

        changed = tuple(
            dict.fromkeys(
                (
                    *result.restored_files,
                    *result.removed_files,
                )
            )
        )

        return ToolExecutionOutput(
            stdout=(
                f"snapshot {self._stdout_operation} "
                f"{result.status.value.lower()}"
            ),
            changed_files=changed,
            metadata={
                "snapshot_id": str(
                    result.snapshot_id
                ),
                "rollback_status": (
                    result.status.value
                ),
                "verified": result.verified,
                "operation": "safe_undo",
            },
        )


class RollbackSnapshotTool(
    SafeUndoSnapshotTool
):
    """Compatibility alias for SafeUndoSnapshotTool."""

    _stdout_operation = "rollback"
