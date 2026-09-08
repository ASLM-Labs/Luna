"""Serializable contracts for Luna procedural skill packages."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


class SkillScope(StrEnum):
    """Installation scope; precedence never implies trust."""

    BUILTIN = "BUILTIN"
    ORGANIZATION = "ORGANIZATION"
    USER = "USER"
    PROJECT = "PROJECT"


class SkillProvenance(StrEnum):
    """Source classification; provenance never grants authority by itself."""

    BUILTIN = "BUILTIN"
    USER_AUTHORED = "USER_AUTHORED"
    ORGANIZATION = "ORGANIZATION"
    TRUSTED_PROJECT = "TRUSTED_PROJECT"
    UNTRUSTED_PROJECT = "UNTRUSTED_PROJECT"
    EXTERNAL_PACKAGE = "EXTERNAL_PACKAGE"
    GENERATED_CANDIDATE = "GENERATED_CANDIDATE"


class SkillTrustState(StrEnum):
    """Host-owned trust state for one immutable installed version."""

    TRUSTED = "TRUSTED"
    QUARANTINED = "QUARANTINED"


class SkillResourceKind(StrEnum):
    """Portable package resource class; none implies execution authority."""

    SCRIPT = "SCRIPT"
    REFERENCE = "REFERENCE"
    ASSET = "ASSET"
    OTHER = "OTHER"


class SkillDiscoveryMatchReason(StrEnum):
    """Explain one deterministic non-authoritative discovery match."""

    EXACT_NAME = "EXACT_NAME"
    NAME_TOKEN = "NAME_TOKEN"
    DESCRIPTION_TOKEN = "DESCRIPTION_TOKEN"


class SkillActivationSource(StrEnum):
    """Why the host admitted one exact skill version for a task."""

    USER_EXPLICIT = "USER_EXPLICIT"
    RUNTIME_DISCOVERY = "RUNTIME_DISCOVERY"
    POLICY_REQUIRED = "POLICY_REQUIRED"


class SkillResource(LunaContractModel):
    """Content-addressed package resource metadata; content is not model-visible here."""

    relative_path: str = Field(min_length=1, max_length=4000)
    kind: SkillResourceKind
    size_bytes: int = Field(ge=0, le=4 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        path = PurePosixPath(normalized)
        if not normalized or normalized == "." or path.is_absolute() or ".." in path.parts:
            raise ValueError("skill resource path must stay relative to the package root")
        return path.as_posix()


class SkillPackage(LunaContractModel):
    """Strict portable package projection with no runtime authority."""

    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1024)
    body: str = Field(default="", max_length=262_144)
    license: str | None = Field(default=None, max_length=1000)
    compatibility: str | None = Field(default=None, min_length=1, max_length=500)
    metadata: tuple[tuple[str, str], ...] = ()
    allowed_tool_hints: tuple[str, ...] = ()
    resources: tuple[SkillResource, ...] = ()
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value.strip())
        if normalized != normalized.lower():
            raise ValueError("skill name must be lowercase")
        if normalized.startswith("-") or normalized.endswith("-"):
            raise ValueError("skill name cannot start or end with a hyphen")
        if "--" in normalized:
            raise ValueError("skill name cannot contain consecutive hyphens")
        if not all(char.isalnum() or char == "-" for char in normalized):
            raise ValueError("skill name may contain only letters, digits, and hyphens")
        return normalized

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls, values: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, str], ...]:
        keys = tuple(key.strip() for key, _ in values)
        if any(not key for key in keys):
            raise ValueError("skill metadata keys must not be blank")
        if len(keys) != len(set(keys)):
            raise ValueError("skill metadata keys must be unique")
        if any(len(key) > 200 or len(value) > 2000 for key, value in values):
            raise ValueError("skill metadata key/value exceeds bounded size")
        return tuple((key.strip(), value) for key, value in values)

    @field_validator("allowed_tool_hints")
    @classmethod
    def validate_allowed_tool_hints(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("skill allowed-tool hints must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("skill allowed-tool hints must be unique")
        return cleaned

    @field_validator("resources")
    @classmethod
    def validate_resources(
        cls, values: tuple[SkillResource, ...]
    ) -> tuple[SkillResource, ...]:
        paths = tuple(item.relative_path.casefold() for item in values)
        if len(paths) != len(set(paths)):
            raise ValueError("skill resource paths must be unique")
        return values


class SkillVersion(LunaContractModel):
    """Registry-owned immutable package version identity."""

    skill_id: UUID
    version_id: UUID
    package: SkillPackage
    scope: SkillScope
    provenance: SkillProvenance
    trust_state: SkillTrustState
    installed_at: datetime = Field(default_factory=utc_now)

    @field_validator("installed_at")
    @classmethod
    def validate_installed_at(cls, value: datetime) -> datetime:
        return require_utc(value)


class SkillDiscoveryCandidate(LunaContractModel):
    """Bounded metadata-only candidate; never an activation or authority grant."""

    skill_id: UUID
    version_id: UUID
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    scope: SkillScope
    provenance: SkillProvenance
    trust_state: SkillTrustState
    match_reasons: tuple[SkillDiscoveryMatchReason, ...] = Field(min_length=1)
    authority_granted: bool = False

    @field_validator("match_reasons")
    @classmethod
    def validate_match_reasons(
        cls, values: tuple[SkillDiscoveryMatchReason, ...]
    ) -> tuple[SkillDiscoveryMatchReason, ...]:
        if len(values) != len(set(values)):
            raise ValueError("skill discovery match reasons must be unique")
        return values

    @model_validator(mode="after")
    def validate_non_authority(self) -> SkillDiscoveryCandidate:
        if self.authority_granted:
            raise ValueError("skill discovery can never grant authority")
        return self


class SkillDiscoveryResult(LunaContractModel):
    """One bounded retrieval-first skill search result."""

    query: str = Field(min_length=1, max_length=512)
    candidates: tuple[SkillDiscoveryCandidate, ...] = Field(max_length=16)
    authority_granted: bool = False

    @model_validator(mode="after")
    def validate_result(self) -> SkillDiscoveryResult:
        ids = tuple(item.version_id for item in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("skill discovery candidate versions must be unique")
        if self.authority_granted:
            raise ValueError("skill discovery can never grant authority")
        return self


class SkillActivation(LunaContractModel):
    """Task-specific admission of one exact immutable skill version."""

    activation_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    skill_id: UUID
    version_id: UUID
    skill_scope: SkillScope
    activation_source: SkillActivationSource
    activated_at: datetime = Field(default_factory=utc_now)
    authority_granted: bool = False

    @field_validator("activated_at")
    @classmethod
    def validate_activated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_non_authority(self) -> SkillActivation:
        if self.authority_granted:
            raise ValueError("skill activation can never grant execution authority")
        return self
