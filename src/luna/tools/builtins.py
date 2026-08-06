"""Safe Phase 4 built-ins: echo, scoped text read, and scoped listing."""

from __future__ import annotations

from luna.tools.models import (
    ToolArgumentRule,
    ToolArgumentType,
    ToolArgumentValue,
    ToolCapability,
    ToolSpec,
)
from luna.tools.paths import (
    WorkspacePathError,
    canonical_workspace_path,
    path_is_allowed,
)
from luna.tools.registry import (
    ToolExecutionContext,
    ToolExecutionDenied,
    ToolExecutionOutput,
    ToolRegistry,
)


def _string(arguments: dict[str, ToolArgumentValue], name: str) -> str:
    value = arguments[name]
    if not isinstance(value, str):
        raise TypeError(f"validated argument '{name}' is not a string")
    return value


class EchoTool:
    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del context
        return ToolExecutionOutput(stdout=_string(arguments, "message"))


class ReadTextTool:
    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        relative_path = _string(arguments, "path")
        try:
            if not path_is_allowed(relative_path, context.task_contract.scope.allowed_paths):
                raise ToolExecutionDenied("requested file is outside allowed_paths")
            path = canonical_workspace_path(
                context.task_contract.scope.workspace_root,
                relative_path,
            )
        except WorkspacePathError as exc:
            raise ToolExecutionDenied(str(exc)) from exc
        if not path.is_file():
            raise ToolExecutionDenied("requested path is not a regular file")
        if path.stat().st_size > context.max_output_chars * 4:
            raise ToolExecutionDenied("file exceeds the bounded Phase 4 read limit")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolExecutionDenied("file is not valid UTF-8 text") from exc
        return ToolExecutionOutput(
            stdout=text,
            metadata={"path": relative_path, "size_bytes": path.stat().st_size},
        )


class ListDirectoryTool:
    def execute(
        self,
        arguments: dict[str, ToolArgumentValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        relative_path = _string(arguments, "path")
        try:
            if not path_is_allowed(relative_path, context.task_contract.scope.allowed_paths):
                raise ToolExecutionDenied("requested directory is outside allowed_paths")
            path = canonical_workspace_path(
                context.task_contract.scope.workspace_root,
                relative_path,
            )
        except WorkspacePathError as exc:
            raise ToolExecutionDenied(str(exc)) from exc
        if not path.is_dir():
            raise ToolExecutionDenied("requested path is not a directory")
        entries = sorted(item.name + ("/" if item.is_dir() else "") for item in path.iterdir())
        if len(entries) > 500:
            raise ToolExecutionDenied("directory exceeds the Phase 4 entry limit")
        return ToolExecutionOutput(
            stdout="\n".join(entries),
            metadata={"path": relative_path, "entry_count": len(entries)},
        )


def build_phase4_registry() -> ToolRegistry:
    """Return the small default registry used by tests and CLI smoke checks."""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="core.echo",
            description="Return an explicitly supplied message without side effects.",
            capabilities=(),
            argument_schema={
                "message": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                    min_length=1,
                    max_length=16000,
                )
            },
            max_output_chars=16000,
        ),
        EchoTool(),
    )
    registry.register(
        ToolSpec(
            name="filesystem.read_text",
            description="Read one UTF-8 text file inside explicit task scope.",
            capabilities=(ToolCapability.READ,),
            argument_schema={
                "path": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                    min_length=1,
                    max_length=4000,
                )
            },
            max_output_chars=64000,
        ),
        ReadTextTool(),
    )
    registry.register(
        ToolSpec(
            name="filesystem.list_directory",
            description="List one directory inside explicit task scope.",
            capabilities=(ToolCapability.READ,),
            argument_schema={
                "path": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                    min_length=1,
                    max_length=4000,
                )
            },
            max_output_chars=32000,
        ),
        ListDirectoryTool(),
    )
    return registry


def build_phase5_registry() -> ToolRegistry:
    """Return Phase 4 read tools plus snapshot-first writes and safe argv execution."""
    from luna.contracts.enums import RiskLevel
    from luna.shell import RunArgvTool
    from luna.workspace.tools import ReplaceTextTool, RollbackSnapshotTool, WriteTextTool

    registry = build_phase4_registry()
    registry.register(
        ToolSpec(
            name="filesystem.write_text",
            description=(
                "Atomically create or overwrite one UTF-8 text file after an explicit "
                "SHA-256 precondition and pre-change snapshot."
            ),
            risk_level=RiskLevel.MEDIUM,
            capabilities=(ToolCapability.WRITE,),
            argument_schema={
                "path": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                    min_length=1,
                    max_length=4000,
                ),
                "content": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                    min_length=0,
                    max_length=250000,
                ),
                "expected_sha256": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=False,
                    min_length=64,
                    max_length=64,
                ),
                "create_if_missing": ToolArgumentRule(
                    argument_type=ToolArgumentType.BOOLEAN,
                    required=True,
                ),
            },
            default_timeout_ms=5000,
            max_timeout_ms=15000,
            max_output_chars=8000,
        ),
        WriteTextTool(),
    )
    registry.register(
        ToolSpec(
            name="filesystem.replace_text",
            description=(
                "Replace an exact UTF-8 text occurrence count after a SHA-256 "
                "precondition and pre-change snapshot."
            ),
            risk_level=RiskLevel.MEDIUM,
            capabilities=(ToolCapability.WRITE,),
            argument_schema={
                "path": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                    min_length=1,
                    max_length=4000,
                ),
                "old_text": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                    min_length=1,
                    max_length=100000,
                ),
                "new_text": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                    min_length=0,
                    max_length=100000,
                ),
                "expected_sha256": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                    min_length=64,
                    max_length=64,
                ),
                "expected_occurrences": ToolArgumentRule(
                    argument_type=ToolArgumentType.INTEGER,
                    required=True,
                    minimum=1,
                    maximum=1000,
                ),
            },
            default_timeout_ms=5000,
            max_timeout_ms=15000,
            max_output_chars=8000,
        ),
        ReplaceTextTool(),
    )
    registry.register(
        ToolSpec(
            name="workspace.rollback",
            description="Restore one task-owned snapshot and verify every restored digest.",
            risk_level=RiskLevel.HIGH,
            capabilities=(ToolCapability.WRITE,),
            argument_schema={
                "snapshot_id": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                    min_length=36,
                    max_length=36,
                )
            },
            default_timeout_ms=10000,
            max_timeout_ms=30000,
            max_output_chars=8000,
        ),
        RollbackSnapshotTool(),
    )
    registry.register(
        ToolSpec(
            name="process.run_argv",
            description=(
                "Run one exact owner-approved argv with shell=False, no stdin, "
                "bounded output, and a hard timeout."
            ),
            risk_level=RiskLevel.HIGH,
            capabilities=(ToolCapability.PROCESS,),
            argument_schema={
                "argv": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING_LIST,
                    required=True,
                    min_length=1,
                    max_length=128,
                )
            },
            default_timeout_ms=15000,
            max_timeout_ms=60000,
            max_output_chars=64000,
            requires_working_directory=True,
        ),
        RunArgvTool(),
    )
    return registry
