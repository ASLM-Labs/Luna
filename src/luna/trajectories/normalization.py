"""Tool-event normalization for dataset semantics, never runtime authorization."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from luna.contracts.base import LunaContractModel
from luna.tools.models import ToolArgumentValue


class SemanticAction(StrEnum):
    READ = "READ"
    SEARCH = "SEARCH"
    WRITE = "WRITE"
    PROCESS = "PROCESS"
    TEST = "TEST"
    VERIFY = "VERIFY"
    NETWORK_RESEARCH = "NETWORK_RESEARCH"
    OTHER = "OTHER"


class ToolNormalizationStatus(StrEnum):
    MAPPED = "MAPPED"
    UNMAPPED = "UNMAPPED"


class NormalizedToolEvent(LunaContractModel):
    source_tool_name: str = Field(min_length=1, max_length=300)
    semantic_action: SemanticAction
    luna_tool_name: str | None = Field(default=None, max_length=120)
    arguments: dict[str, ToolArgumentValue] = Field(default_factory=dict)
    status: ToolNormalizationStatus
    executable_request_created: bool = False


_DEFAULT_RULES: dict[str, tuple[SemanticAction, str | None]] = {
    "read_file": (SemanticAction.READ, "filesystem.read_text"),
    "cat": (SemanticAction.READ, "filesystem.read_text"),
    "list_directory": (SemanticAction.READ, "filesystem.list_directory"),
    "grep": (SemanticAction.SEARCH, None),
    "search": (SemanticAction.SEARCH, None),
    "write_file": (SemanticAction.WRITE, "filesystem.write_text"),
    "apply_patch": (SemanticAction.WRITE, "filesystem.replace_text"),
    "shell": (SemanticAction.PROCESS, "process.run_argv"),
    "exec": (SemanticAction.PROCESS, "process.run_argv"),
    "pytest": (SemanticAction.TEST, "process.run_argv"),
    "verify": (SemanticAction.VERIFY, None),
    "web_search": (SemanticAction.NETWORK_RESEARCH, None),
}


class ToolEventNormalizer:
    """Map wrapper-specific names to canonical semantics without copying wrapper control."""

    def normalize(
        self,
        *,
        source_tool_name: str,
        arguments: dict[str, ToolArgumentValue] | None = None,
    ) -> NormalizedToolEvent:
        normalized_name = source_tool_name.strip().lower()
        mapping = _DEFAULT_RULES.get(normalized_name)
        if mapping is None:
            return NormalizedToolEvent(
                source_tool_name=source_tool_name,
                semantic_action=SemanticAction.OTHER,
                arguments=arguments or {},
                status=ToolNormalizationStatus.UNMAPPED,
            )
        semantic_action, luna_tool_name = mapping
        return NormalizedToolEvent(
            source_tool_name=source_tool_name,
            semantic_action=semantic_action,
            luna_tool_name=luna_tool_name,
            arguments=arguments or {},
            status=ToolNormalizationStatus.MAPPED,
        )
