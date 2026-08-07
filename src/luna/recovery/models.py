"""Serializable Phase 12D failure, recovery, change, and isolation contracts."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.enums import RiskLevel
from luna.planning.models import RetryReason


class FailureSource(StrEnum):
    """Runtime-owned origin of a classified failure."""

    ACTION_DENIAL = "ACTION_DENIAL"
    TOOL_RESULT = "TOOL_RESULT"
    OBSERVATION = "OBSERVATION"
    WORKSPACE = "WORKSPACE"
    VERIFICATION = "VERIFICATION"
    RUNTIME = "RUNTIME"


class FailureCategory(StrEnum):
    """Stable failure taxonomy used by deterministic recovery policy."""

    INVALID_ACTION = "INVALID_ACTION"
    PERMISSION_OR_SCOPE_DENIED = "PERMISSION_OR_SCOPE_DENIED"
    STALE_STATE = "STALE_STATE"
    TRANSIENT_ENVIRONMENT = "TRANSIENT_ENVIRONMENT"
    DETERMINISTIC_EXECUTION = "DETERMINISTIC_EXECUTION"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class RecoveryAction(StrEnum):
    """Permitted runtime reactions to one classified failure."""

    RETRY = "RETRY"
    REPLAN = "REPLAN"
    REINSPECT = "REINSPECT"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    ROLLBACK = "ROLLBACK"
    SUSPEND = "SUSPEND"
    STOP = "STOP"


class FailureRecord(LunaContractModel):
    """Machine-readable failure classification; model text cannot grant retryability."""

    failure_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    trace_id: UUID
    source: FailureSource
    category: FailureCategory
    reason: str = Field(min_length=1, max_length=4000)
    source_ref: str | None = Field(default=None, max_length=500)
    error_class: str | None = Field(default=None, max_length=300)
    retryable: bool = False
    requires_changed_basis: bool = False
    rollback_recommended: bool = False
    owner_action_required: bool = False
    integrity_critical: bool = False

    @model_validator(mode="after")
    def validate_failure(self) -> FailureRecord:
        if self.retryable and not self.requires_changed_basis:
            raise ValueError("retryable failure must require a changed basis")
        if self.integrity_critical and self.retryable:
            raise ValueError("integrity-critical failure cannot be retryable")
        if (
            self.integrity_critical
            and self.category is not FailureCategory.INTEGRITY_FAILURE
        ):
            raise ValueError("integrity_critical is reserved for integrity failures")
        if self.category is FailureCategory.INTEGRITY_FAILURE and not self.integrity_critical:
            raise ValueError("integrity failure must be marked integrity_critical")
        if self.category is FailureCategory.VERIFICATION_FAILURE and not self.rollback_recommended:
            raise ValueError("verification failure must recommend rollback")
        return self


class RecoveryDecision(LunaContractModel):
    """Deterministic next-step decision after one classified failure."""

    failure_id: UUID
    action: RecoveryAction
    reason: str = Field(min_length=1, max_length=4000)
    retry_reason: RetryReason | None = None
    changed_dimensions: tuple[str, ...] = ()
    rollback_required: bool = False
    owner_action_required: bool = False

    @field_validator("changed_dimensions")
    @classmethod
    def validate_changed_dimensions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("changed dimensions must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("changed dimensions must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_decision(self) -> RecoveryDecision:
        if self.action is RecoveryAction.RETRY:
            if self.retry_reason is not RetryReason.CHANGED_BASIS:
                raise ValueError("RETRY requires a CHANGED_BASIS retry decision")
            if not self.changed_dimensions:
                raise ValueError("RETRY requires changed_dimensions")
        elif self.retry_reason is not None or self.changed_dimensions:
            raise ValueError("non-RETRY recovery cannot carry retry metadata")
        if self.action is RecoveryAction.ROLLBACK and not self.rollback_required:
            raise ValueError("ROLLBACK action requires rollback_required")
        if self.rollback_required and self.action is not RecoveryAction.ROLLBACK:
            raise ValueError("rollback_required is valid only for ROLLBACK")
        if self.owner_action_required and self.action is not RecoveryAction.REQUEST_APPROVAL:
            raise ValueError("owner action is valid only for REQUEST_APPROVAL")
        return self


def _normalize_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute() or ".." in pure.parts:
        raise ValueError("change paths must be relative and cannot contain '..'")
    return pure.as_posix()


class ChangeEstimate(LunaContractModel):
    """Declared or observed workspace change shape used for minimal-change enforcement."""

    touched_paths: tuple[str, ...] = Field(min_length=1)
    added_lines: int = Field(default=0, ge=0, le=1000000)
    deleted_lines: int = Field(default=0, ge=0, le=1000000)

    @field_validator("touched_paths")
    @classmethod
    def validate_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_normalize_relative_path(value) for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("touched paths must be unique")
        return normalized

    @property
    def changed_files(self) -> int:
        return len(self.touched_paths)

    @property
    def has_effect(self) -> bool:
        return bool(self.added_lines or self.deleted_lines)


class MinimalChangeDenialCode(StrEnum):
    """Stable reasons a proposed or observed change exceeds runtime authority."""

    WRITE_NOT_ALLOWED = "WRITE_NOT_ALLOWED"
    OUTSIDE_ALLOWED_PATHS = "OUTSIDE_ALLOWED_PATHS"
    PROTECTED_PATH = "PROTECTED_PATH"
    FILE_BUDGET_EXCEEDED = "FILE_BUDGET_EXCEEDED"
    ADDED_LINE_BUDGET_EXCEEDED = "ADDED_LINE_BUDGET_EXCEEDED"
    DELETED_LINE_BUDGET_EXCEEDED = "DELETED_LINE_BUDGET_EXCEEDED"
    NO_EFFECT = "NO_EFFECT"
    UNDECLARED_SCOPE_GROWTH = "UNDECLARED_SCOPE_GROWTH"
    UNDECLARED_LINE_GROWTH = "UNDECLARED_LINE_GROWTH"


class MinimalChangeDecision(LunaContractModel):
    """Result of checking a declared or observed change against hard budgets."""

    allowed: bool
    checks: tuple[str, ...] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=4000)
    denial_code: MinimalChangeDenialCode | None = None

    @field_validator("checks")
    @classmethod
    def validate_checks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("minimal-change checks must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("minimal-change checks must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_decision(self) -> MinimalChangeDecision:
        if self.allowed and self.denial_code is not None:
            raise ValueError("allowed change cannot carry a denial code")
        if not self.allowed and self.denial_code is None:
            raise ValueError("denied change requires a denial code")
        return self


class IsolationMode(StrEnum):
    """Workspace isolation strength selected by runtime policy."""

    NONE = "NONE"
    SNAPSHOT = "SNAPSHOT"
    WORKTREE = "WORKTREE"


class IsolationDecision(LunaContractModel):
    """Pure isolation plan; it does not create snapshots or Git worktrees itself."""

    allowed: bool
    mode: IsolationMode
    risk_level: RiskLevel
    checks: tuple[str, ...] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=4000)
    snapshot_required: bool = False
    worktree_required: bool = False
    clean_workspace_required: bool = False

    @field_validator("checks")
    @classmethod
    def validate_checks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("isolation checks must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("isolation checks must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_isolation(self) -> IsolationDecision:
        if (
            self.mode is IsolationMode.NONE
            and (self.snapshot_required or self.worktree_required)
        ):
            raise ValueError("NONE isolation cannot require workspace isolation")
        if self.mode is IsolationMode.SNAPSHOT and not self.snapshot_required:
            raise ValueError("SNAPSHOT mode requires snapshot_required")
        if (
            self.mode is IsolationMode.WORKTREE
            and (not self.worktree_required or not self.clean_workspace_required)
        ):
            raise ValueError("WORKTREE mode requires worktree and clean workspace")
        if self.allowed and self.mode is IsolationMode.WORKTREE and not self.worktree_required:
            raise ValueError("allowed WORKTREE decision must require worktree")
        return self
