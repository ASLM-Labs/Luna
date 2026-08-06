"""Serializable contracts for controlled tool execution."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.autonomy import (
    AutonomyGrantSource,
    AutonomyLevel,
    AutonomyPolicy,
    FreeResearchContract,
)
from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import RiskLevel
from luna.contracts.observation import Observation

type ToolScalar = str | int | float | bool | None
type ToolArgumentValue = ToolScalar | list[str]


class ToolCapability(StrEnum):
    """Effects a registered tool may produce."""

    READ = "READ"
    WRITE = "WRITE"
    NETWORK = "NETWORK"
    PROCESS = "PROCESS"


class ToolOrigin(StrEnum):
    """Origin of a tool request; origin never grants permission by itself."""

    MODEL = "MODEL"
    RUNTIME = "RUNTIME"
    USER = "USER"


class ToolArgumentType(StrEnum):
    """Small auditable argument-schema vocabulary for Luna 0.1."""

    STRING = "STRING"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    STRING_LIST = "STRING_LIST"


class ToolResultStatus(StrEnum):
    """Normalized result of a tool request."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    BLOCKED = "BLOCKED"


class ToolEventDecision(StrEnum):
    """Final dispatcher decision recorded for an attempted call."""

    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ToolArgumentRule(LunaContractModel):
    """One field in a tool's explicit argument schema."""

    argument_type: ToolArgumentType
    required: bool = False
    description: str = Field(default="", max_length=1000)
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()

    @field_validator("choices")
    @classmethod
    def validate_choices(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("argument choices must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("argument choices must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_bounds(self) -> ToolArgumentRule:
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError("min_length cannot exceed max_length")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        if self.choices and self.argument_type is not ToolArgumentType.STRING:
            raise ValueError("choices are supported only for STRING arguments")
        return self


class ToolSpec(LunaContractModel):
    """Immutable public registration contract for one tool."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$", max_length=120)
    version: str = Field(default="1.0", pattern=r"^[0-9]+\.[0-9]+$")
    description: str = Field(min_length=1, max_length=2000)
    risk_level: RiskLevel = RiskLevel.LOW
    capabilities: tuple[ToolCapability, ...] = ()
    argument_schema: dict[str, ToolArgumentRule] = Field(default_factory=dict)
    default_timeout_ms: int = Field(default=5000, ge=1, le=120000)
    max_timeout_ms: int = Field(default=15000, ge=1, le=120000)
    max_output_chars: int = Field(default=16000, ge=1, le=1000000)
    requires_working_directory: bool = False

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(
        cls,
        values: tuple[ToolCapability, ...],
    ) -> tuple[ToolCapability, ...]:
        if len(values) != len(set(values)):
            raise ValueError("tool capabilities must be unique")
        return values

    @field_validator("argument_schema")
    @classmethod
    def validate_argument_names(
        cls,
        values: dict[str, ToolArgumentRule],
    ) -> dict[str, ToolArgumentRule]:
        for name in values:
            if not name or not name.replace("_", "a").isalnum() or name[0].isdigit():
                raise ValueError(f"invalid tool argument name: {name}")
        return values

    @model_validator(mode="after")
    def validate_timeout(self) -> ToolSpec:
        if self.default_timeout_ms > self.max_timeout_ms:
            raise ValueError("default timeout cannot exceed maximum timeout")
        return self


class ToolRequest(LunaContractModel):
    """One untrusted request to invoke a registered tool."""

    request_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    trace_id: UUID
    tool_name: str = Field(min_length=1, max_length=120)
    arguments: dict[str, ToolArgumentValue] = Field(default_factory=dict)
    working_directory: str | None = Field(default=None, max_length=4000)
    timeout_ms: int | None = Field(default=None, ge=1, le=120000)
    max_output_chars: int | None = Field(default=None, ge=1, le=1000000)
    expectation_id: UUID | None = None
    origin: ToolOrigin = ToolOrigin.RUNTIME
    requested_at: datetime = Field(default_factory=utc_now)

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return require_utc(value)


class ToolResult(LunaContractModel):
    """Bounded result; large raw output is represented by hashes and excerpts."""

    result_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    tool_name: str = Field(min_length=1, max_length=120)
    status: ToolResultStatus
    exit_code: int | None = None
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    stdout_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    stderr_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_chars: int = Field(ge=0)
    truncated: bool = False
    duration_ms: int = Field(ge=0)
    error_class: str | None = Field(default=None, max_length=300)
    metadata: dict[str, ToolScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_status(self) -> ToolResult:
        if self.status is ToolResultStatus.SUCCESS:
            if self.exit_code not in (None, 0) or self.error_class is not None:
                raise ValueError("successful tool result cannot carry failure fields")
        elif self.status is ToolResultStatus.FAILURE:
            if self.exit_code in (None, 0) and self.error_class is None:
                raise ValueError("failed tool result requires an observable failure")
        else:
            if self.exit_code is not None or self.error_class is None:
                raise ValueError("blocked tool result requires error_class and no exit code")
        return self


class ToolEvent(LunaContractModel):
    """Trace record linking policy checks, request, and final result."""

    event_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    result_id: UUID
    task_id: UUID
    trace_id: UUID
    tool_name: str = Field(min_length=1, max_length=120)
    decision: ToolEventDecision
    policy_checks: tuple[str, ...] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=4000)
    occurred_at: datetime = Field(default_factory=utc_now)

    @field_validator("policy_checks")
    @classmethod
    def validate_policy_checks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("policy checks must not be empty")
        return cleaned

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        return require_utc(value)


class ProcessApproval(LunaContractModel):
    """Exact argv and workspace-relative cwd approved by the runtime owner."""

    argv: tuple[str, ...] = Field(min_length=1, max_length=128)
    working_directory: str = Field(default=".", min_length=1, max_length=4000)

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or "\x00" in value for value in values):
            raise ValueError("approved argv entries must be non-empty and NUL-free")
        return values

    @field_validator("working_directory")
    @classmethod
    def validate_working_directory(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        if normalized == ".":
            return normalized
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            raise ValueError("process approval cwd must stay inside the workspace")
        return path.as_posix()


class ToolPolicy(LunaContractModel):
    """Explicit permissions and budgets; an empty allowlist denies all tools."""

    allowed_tools: tuple[str, ...] = ()
    autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_1_READ_ONLY
    autonomy_grant_source: AutonomyGrantSource = AutonomyGrantSource.RUNTIME_POLICY
    max_risk: RiskLevel = RiskLevel.LOW
    owner_approved_tools: tuple[str, ...] = ()
    process_approvals: tuple[ProcessApproval, ...] = ()
    free_research_contract: FreeResearchContract | None = None
    free_research_requests_used: int = Field(default=0, ge=0)
    free_research_session_started_at: datetime | None = None
    max_timeout_ms: int = Field(default=15000, ge=1, le=120000)
    max_output_chars: int = Field(default=16000, ge=1, le=1000000)

    @field_validator("allowed_tools", "owner_approved_tools")
    @classmethod
    def validate_tool_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("tool names must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("tool names must be unique")
        return cleaned

    @field_validator("free_research_session_started_at")
    @classmethod
    def validate_research_session_start(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value)

    @model_validator(mode="after")
    def validate_owner_approvals(self) -> ToolPolicy:
        if not set(self.owner_approved_tools).issubset(self.allowed_tools):
            raise ValueError("owner-approved tools must also be explicitly allowed")
        approval_keys = tuple(
            (approval.argv, approval.working_directory)
            for approval in self.process_approvals
        )
        if len(approval_keys) != len(set(approval_keys)):
            raise ValueError("process approvals must be unique")
        if self.autonomy_level is AutonomyLevel.LEVEL_4_FREE_RESEARCH:
            if self.free_research_contract is None:
                raise ValueError("Level 4 requires a separate FREE_RESEARCH contract")
        elif self.free_research_contract is not None:
            raise ValueError("FREE_RESEARCH contract is valid only at Level 4")
        return self

    def autonomy_policy_for(self, task_id: UUID) -> AutonomyPolicy:
        """Build the effective runtime-owned autonomy policy for one task."""
        return AutonomyPolicy(
            task_id=task_id,
            level=self.autonomy_level,
            grant_source=self.autonomy_grant_source,
            allowed_tools=self.allowed_tools,
            max_risk=self.max_risk,
            free_research_contract=self.free_research_contract,
            free_research_requests_used=self.free_research_requests_used,
            free_research_session_started_at=self.free_research_session_started_at,
        )


class DispatchOutcome(LunaContractModel):
    """Complete observable output of one dispatch attempt."""

    request: ToolRequest
    result: ToolResult
    event: ToolEvent
    observation: Observation

    @model_validator(mode="after")
    def validate_links(self) -> DispatchOutcome:
        if self.result.request_id != self.request.request_id:
            raise ValueError("result must reference request")
        if self.event.request_id != self.request.request_id:
            raise ValueError("event must reference request")
        if self.event.result_id != self.result.result_id:
            raise ValueError("event must reference result")
        if self.observation.tool_event_id != self.event.event_id:
            raise ValueError("observation must reference tool event")
        if self.observation.trace_id != self.request.trace_id:
            raise ValueError("observation and request trace IDs must match")
        return self
