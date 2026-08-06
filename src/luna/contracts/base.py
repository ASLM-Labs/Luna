"""Shared validation helpers for versioned Luna contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator

SCHEMA_VERSION = "1.0"


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(UTC)


class LunaContractModel(BaseModel):
    """Strict base class for persistent and cross-module contracts."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    schema_version: str = SCHEMA_VERSION

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {value}")
        return value

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> Self:
        """Validate a model from its JSON representation."""
        return cls.model_validate_json(value)

    def to_json(self) -> str:
        """Serialize a model using stable JSON-compatible values."""
        return self.model_dump_json(indent=2)


def require_utc(value: datetime) -> datetime:
    """Require a timezone-aware datetime and normalize it to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def stable_payload(model: BaseModel) -> dict[str, Any]:
    """Return a JSON-mode payload suitable for revalidation."""
    return model.model_dump(mode="json")
