"""Runtime-owned autonomy levels and FREE_RESEARCH authorization contracts."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from urllib.parse import urlparse
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import RiskLevel


class AutonomyLevel(StrEnum):
    """Five runtime-enforced autonomy levels defined by the Luna constitution."""

    LEVEL_0_ADVISORY = "LEVEL_0_ADVISORY"
    LEVEL_1_READ_ONLY = "LEVEL_1_READ_ONLY"
    LEVEL_2_CONTROLLED = "LEVEL_2_CONTROLLED"
    LEVEL_3_TASK = "LEVEL_3_TASK"
    LEVEL_4_FREE_RESEARCH = "LEVEL_4_FREE_RESEARCH"

    # Backward-compatible Phase 4/5 names. Enum aliases resolve to canonical levels.
    OBSERVE_ONLY = "LEVEL_1_READ_ONLY"
    BOUNDED = "LEVEL_2_CONTROLLED"
    OWNER_APPROVED = "LEVEL_3_TASK"

    @classmethod
    def _missing_(cls, value: object) -> AutonomyLevel | None:
        legacy = {
            "OBSERVE_ONLY": cls.LEVEL_1_READ_ONLY,
            "BOUNDED": cls.LEVEL_2_CONTROLLED,
            "OWNER_APPROVED": cls.LEVEL_3_TASK,
        }
        return legacy.get(value) if isinstance(value, str) else None

    @property
    def number(self) -> int:
        return {
            AutonomyLevel.LEVEL_0_ADVISORY: 0,
            AutonomyLevel.LEVEL_1_READ_ONLY: 1,
            AutonomyLevel.LEVEL_2_CONTROLLED: 2,
            AutonomyLevel.LEVEL_3_TASK: 3,
            AutonomyLevel.LEVEL_4_FREE_RESEARCH: 4,
        }[self]


class AutonomyGrantSource(StrEnum):
    """Only trusted runtime actors may grant an autonomy level."""

    USER = "USER"
    RUNTIME_POLICY = "RUNTIME_POLICY"


class FreeResearchContract(LunaContractModel):
    """Time- and scope-bounded authorization required for Level 4 research."""

    contract_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    purpose: str = Field(min_length=1, max_length=2000)
    allowed_tools: tuple[str, ...] = Field(min_length=1, max_length=100)
    allowed_domains: tuple[str, ...] = Field(min_length=1, max_length=100)
    max_requests: int = Field(default=20, ge=1, le=1000)
    max_duration_seconds: int = Field(default=1800, ge=1, le=86400)
    allow_workspace_writes: bool = False
    issued_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    granted_by: str = Field(default="user", min_length=1, max_length=200)

    @field_validator("issued_at", "expires_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("allowed_tools")
    @classmethod
    def validate_tools(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("FREE_RESEARCH tool names cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("FREE_RESEARCH tool names must be unique")
        return cleaned

    @field_validator("allowed_domains")
    @classmethod
    def validate_domains(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip().lower().rstrip(".") for value in values)
        if any(not value or "/" in value or ":" in value for value in cleaned):
            raise ValueError("allowed domains must be bare host names")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("allowed domains must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_window(self) -> FreeResearchContract:
        if self.expires_at <= self.issued_at:
            raise ValueError("FREE_RESEARCH expiry must be after issue time")
        if self.expires_at - self.issued_at > timedelta(days=1):
            raise ValueError("FREE_RESEARCH authorization cannot exceed 24 hours")
        if self.allow_workspace_writes:
            raise ValueError("FREE_RESEARCH cannot authorize workspace writes")
        return self

    def active_at(self, value: datetime) -> bool:
        current = require_utc(value)
        return self.issued_at <= current < self.expires_at

    def allows_domain(self, value: str) -> bool:
        """Match a bare host or URL against exact and subdomain authorizations."""
        parsed = urlparse(value if "://" in value else f"https://{value}")
        host = (parsed.hostname or "").lower().rstrip(".")
        return any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains)


class AutonomyPolicy(LunaContractModel):
    """Effective runtime authority; model output is not a valid grant source."""

    task_id: UUID
    level: AutonomyLevel = AutonomyLevel.LEVEL_1_READ_ONLY
    grant_source: AutonomyGrantSource = AutonomyGrantSource.RUNTIME_POLICY
    allowed_tools: tuple[str, ...] = ()
    max_risk: RiskLevel = RiskLevel.LOW
    free_research_contract: FreeResearchContract | None = None
    free_research_requests_used: int = Field(default=0, ge=0)
    free_research_session_started_at: datetime | None = None

    @field_validator("allowed_tools")
    @classmethod
    def validate_tool_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("autonomy tool names cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("autonomy tool names must be unique")
        return cleaned

    @field_validator("free_research_session_started_at")
    @classmethod
    def validate_session_start(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value)

    @model_validator(mode="after")
    def validate_level(self) -> AutonomyPolicy:
        if self.level is AutonomyLevel.LEVEL_1_READ_ONLY and self.max_risk is not RiskLevel.LOW:
            raise ValueError("Level 1 risk ceiling must remain LOW")
        if self.level is AutonomyLevel.LEVEL_2_CONTROLLED and self.max_risk in {
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        }:
            raise ValueError("Level 2 risk ceiling cannot exceed MEDIUM")
        if self.level is AutonomyLevel.LEVEL_4_FREE_RESEARCH:
            contract = self.free_research_contract
            if contract is None:
                raise ValueError("Level 4 requires a separate FREE_RESEARCH contract")
            if contract.task_id != self.task_id:
                raise ValueError("FREE_RESEARCH contract task must match autonomy policy")
            if not set(self.allowed_tools).issubset(contract.allowed_tools):
                raise ValueError("Level 4 tools must be allowed by FREE_RESEARCH contract")
        elif self.free_research_contract is not None:
            raise ValueError("FREE_RESEARCH contract is valid only at Level 4")
        return self

    def research_budget_available(self) -> bool:
        contract = self.free_research_contract
        return (
            self.level is AutonomyLevel.LEVEL_4_FREE_RESEARCH
            and contract is not None
            and self.free_research_requests_used < contract.max_requests
        )

    def research_window_active(self, value: datetime) -> bool:
        contract = self.free_research_contract
        if self.level is not AutonomyLevel.LEVEL_4_FREE_RESEARCH or contract is None:
            return False
        current = require_utc(value)
        if not contract.active_at(current):
            return False
        if self.free_research_session_started_at is None:
            return True
        elapsed = (current - self.free_research_session_started_at).total_seconds()
        return 0 <= elapsed <= contract.max_duration_seconds
