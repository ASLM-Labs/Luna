"""Phase 16 desktop product-shell contracts.

The desktop layer is presentation and command routing only. It cannot manufacture
runtime authority, verification, completion, or external-delivery claims.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


class DesktopSection(StrEnum):
    """Primary Luna desktop navigation sections."""

    CHAT = "CHAT"
    TASKS = "TASKS"
    RESEARCH = "RESEARCH"
    SCHEDULES = "SCHEDULES"
    NOTIFICATIONS = "NOTIFICATIONS"


class DesktopTone(StrEnum):
    """Small semantic palette used by the shell."""

    NEUTRAL = "NEUTRAL"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    DANGER = "DANGER"


class DesktopTaskState(StrEnum):
    """User-facing task state derived from durable runtime/operations state."""

    QUEUED = "QUEUED"
    WORKING = "WORKING"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    VERIFIED_COMPLETE = "VERIFIED_COMPLETE"


class DesktopAccessMode(StrEnum):
    """Authority request exposed by the desktop composer."""

    READ_ONLY = "READ_ONLY"
    CONTROLLED_WRITE = "CONTROLLED_WRITE"


class DesktopApproval(LunaContractModel):
    """Explicit local-user approval for a bounded controlled-write request."""

    approved: bool = False
    workspace_root: str = Field(min_length=1, max_length=2000)
    allowed_paths: tuple[str, ...] = ()
    max_changed_files: int = Field(default=0, ge=0, le=1000)
    max_added_lines: int = Field(default=0, ge=0, le=100_000)
    max_deleted_lines: int = Field(default=0, ge=0, le=100_000)

    @field_validator("workspace_root")
    @classmethod
    def normalize_workspace_root(cls, value: str) -> str:
        return str(Path(value).expanduser().resolve())

    @field_validator("allowed_paths")
    @classmethod
    def normalize_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip().replace("\\", "/") for value in values)
        if any(not value for value in cleaned):
            raise ValueError("desktop approval paths cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("desktop approval paths must be unique")
        if any(Path(value).is_absolute() or ".." in Path(value).parts for value in cleaned):
            raise ValueError("desktop approval paths must stay relative to the workspace")
        return cleaned

    @model_validator(mode="after")
    def validate_write_budget(self) -> DesktopApproval:
        if self.approved:
            if not self.allowed_paths:
                raise ValueError("approved controlled write requires at least one allowed path")
            if self.max_changed_files < 1:
                raise ValueError("approved controlled write requires a changed-file budget")
            if self.max_added_lines == 0 and self.max_deleted_lines == 0:
                raise ValueError("approved controlled write requires a non-zero line budget")
        if not self.approved and any(
            (
                self.allowed_paths,
                self.max_changed_files,
                self.max_added_lines,
                self.max_deleted_lines,
            )
        ):
            raise ValueError("unapproved desktop write request cannot carry write authority")
        return self


class DesktopComposerDraft(LunaContractModel):
    """Untrusted UI draft before the runtime-owned request factory binds authority."""

    text: str = Field(min_length=1, max_length=32_000)
    workspace_root: str = Field(min_length=1, max_length=2000)
    access_mode: DesktopAccessMode = DesktopAccessMode.READ_ONLY
    approval: DesktopApproval | None = None

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("desktop composer text cannot be blank")
        return cleaned

    @field_validator("workspace_root")
    @classmethod
    def normalize_workspace_root(cls, value: str) -> str:
        return str(Path(value).expanduser().resolve())

    @model_validator(mode="after")
    def validate_approval_shape(self) -> DesktopComposerDraft:
        if self.access_mode is DesktopAccessMode.READ_ONLY:
            if self.approval is not None:
                raise ValueError("read-only desktop draft cannot carry write approval")
            return self
        if self.approval is None or not self.approval.approved:
            raise ValueError("controlled-write desktop draft requires explicit approval")
        if self.approval.workspace_root != self.workspace_root:
            raise ValueError("desktop approval workspace must match the composer workspace")
        return self


class DesktopTaskCard(LunaContractModel):
    """Conversation-inline task card built only from durable authoritative state."""

    item_id: UUID
    task_id: UUID
    title: str = Field(min_length=1, max_length=500)
    state: DesktopTaskState
    tone: DesktopTone
    state_label: str = Field(min_length=1, max_length=100)
    stop_reason: str | None = Field(default=None, max_length=100)
    completion_status: str | None = Field(default=None, max_length=100)
    verification_report_id: UUID | None = None
    final_report_id: UUID | None = None
    evidence_count: int = Field(default=0, ge=0)
    observation_count: int = Field(default=0, ge=0)
    unresolved_uncertainty: tuple[str, ...] = ()
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_verified_complete_claim(self) -> DesktopTaskCard:
        if self.state is DesktopTaskState.VERIFIED_COMPLETE:
            if self.completion_status != "VERIFIED_COMPLETE":
                raise ValueError("verified desktop task requires VERIFIED_COMPLETE runtime status")
            if self.stop_reason != "COMPLETED":
                raise ValueError("verified desktop task requires COMPLETED runtime stop reason")
            if self.verification_report_id is None or self.final_report_id is None:
                raise ValueError("verified desktop task requires verification and final-report IDs")
        return self


class DesktopNotificationCard(LunaContractModel):
    """Local notification presentation; it never implies external delivery."""

    notification_id: UUID
    task_id: UUID
    kind: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    tone: DesktopTone
    acknowledged: bool
    external_delivery_allowed: bool = False
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_local_only(self) -> DesktopNotificationCard:
        if self.external_delivery_allowed:
            raise ValueError("Phase 16 desktop notification cards remain local-only")
        return self


class DesktopScheduleCard(LunaContractModel):
    """Read-only schedule presentation."""

    schedule_id: UUID
    title: str = Field(min_length=1, max_length=500)
    kind: str = Field(min_length=1, max_length=100)
    next_run_at: datetime
    occurrence_count: int = Field(ge=0)
    enabled: bool

    @field_validator("next_run_at")
    @classmethod
    def validate_next_run_at(cls, value: datetime) -> datetime:
        return require_utc(value)


class DesktopResourceSummary(LunaContractModel):
    """Observed coordinator capacity; not a permission grant."""

    worker_slots_held: int = Field(ge=0)
    model_slots_held: int = Field(ge=0)
    network_slots_held: int = Field(ge=0)


class DesktopShellSnapshot(LunaContractModel):
    """Single immutable view model consumed by any desktop renderer."""

    generated_at: datetime = Field(default_factory=utc_now)
    selected_section: DesktopSection = DesktopSection.CHAT
    tasks: tuple[DesktopTaskCard, ...] = ()
    notifications: tuple[DesktopNotificationCard, ...] = ()
    schedules: tuple[DesktopScheduleCard, ...] = ()
    resources: DesktopResourceSummary = Field(
        default_factory=lambda: DesktopResourceSummary(
            worker_slots_held=0,
            model_slots_held=0,
            network_slots_held=0,
        )
    )
    composer_access_mode: DesktopAccessMode = DesktopAccessMode.READ_ONLY
    workspace_root: str
    shell_message: str = "Luna ile ne geliştirelim?"

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("workspace_root")
    @classmethod
    def normalize_workspace_root(cls, value: str) -> str:
        return str(Path(value).expanduser().resolve())
