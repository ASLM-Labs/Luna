"""Phase 17 Discord gateway contracts.

The Discord layer transports verified ingress metadata into Luna runtime contracts. It does
not infer authority from message text, grant workspace/process/network access, or perform
external Discord moderation actions.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.runtime import ActorRole


class DiscordChannelPurpose(StrEnum):
    """Runtime-owned purpose for one configured Discord channel."""

    UPDATES = "UPDATES"
    CHAT = "CHAT"
    AION_QA = "AION_QA"
    MAINTENANCE = "MAINTENANCE"
    FEEDBACK = "FEEDBACK"


class DiscordIngressDisposition(StrEnum):
    """Observable gateway result; no value implies runtime completion."""

    QUEUED = "QUEUED"
    QUEUED_FOR_MODEL = "QUEUED_FOR_MODEL"
    DUPLICATE = "DUPLICATE"
    DENIED_UNVERIFIED_TRANSPORT = "DENIED_UNVERIFIED_TRANSPORT"
    DENIED_GUILD = "DENIED_GUILD"
    DENIED_CHANNEL = "DENIED_CHANNEL"
    DENIED_ROLE_POLICY = "DENIED_ROLE_POLICY"
    DENIED_MODERATION = "DENIED_MODERATION"
    DENIED_RATE_LIMIT = "DENIED_RATE_LIMIT"


class DiscordChannelBinding(LunaContractModel):
    """Trusted mapping from a Discord channel snowflake to product purpose."""

    channel_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    purpose: DiscordChannelPurpose


class DiscordAuthorityConfig(LunaContractModel):
    """Runtime-owned Discord identity and channel configuration."""

    guild_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    workspace_root: str = Field(min_length=1, max_length=2000)
    channels: tuple[DiscordChannelBinding, ...] = Field(min_length=1, max_length=100)
    owner_user_ids: tuple[str, ...] = ()
    trusted_role_ids: tuple[str, ...] = ()
    community_role_ids: tuple[str, ...] = ()

    @field_validator("workspace_root")
    @classmethod
    def normalize_workspace_root(cls, value: str) -> str:
        return str(Path(value).expanduser().resolve())

    @field_validator("owner_user_ids", "trusted_role_ids", "community_role_ids")
    @classmethod
    def validate_snowflake_sets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.isdigit() or len(value) > 32 for value in values):
            raise ValueError("Discord identity mappings must contain numeric snowflake strings")
        if len(values) != len(set(values)):
            raise ValueError("Discord identity mappings must be unique")
        return values

    @model_validator(mode="after")
    def validate_unique_channels(self) -> DiscordAuthorityConfig:
        channel_ids = tuple(binding.channel_id for binding in self.channels)
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("Discord channel bindings must be unique")
        return self


class DiscordTransportEnvelope(LunaContractModel):
    """One event supplied by a transport adapter after Discord source verification."""

    guild_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    channel_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    message_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    author_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    author_role_ids: tuple[str, ...] = ()
    content: str = Field(min_length=1, max_length=4000)
    transport_verified: bool = False
    verified_at: datetime | None = None
    received_at: datetime = Field(default_factory=utc_now)
    is_bot: bool = False
    is_webhook: bool = False
    mentions_everyone: bool = False

    @field_validator("author_role_ids")
    @classmethod
    def validate_role_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.isdigit() or len(value) > 32 for value in values):
            raise ValueError("Discord role IDs must be numeric snowflake strings")
        if len(values) != len(set(values)):
            raise ValueError("Discord role IDs must be unique")
        return values

    @field_validator("verified_at", "received_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Discord content cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_transport_verification(self) -> DiscordTransportEnvelope:
        if self.transport_verified and self.verified_at is None:
            raise ValueError("verified Discord transport requires verified_at")
        if not self.transport_verified and self.verified_at is not None:
            raise ValueError("unverified Discord transport cannot carry verified_at")
        return self

    @property
    def content_sha256(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


class DiscordReplyRoute(LunaContractModel):
    """Transport-neutral location for a future Discord response."""

    channel_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    reply_to_message_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")


class DiscordIngressResult(LunaContractModel):
    """Gateway result returned to the transport adapter."""

    disposition: DiscordIngressDisposition
    actor_role: ActorRole | None = None
    channel_purpose: DiscordChannelPurpose | None = None
    queue_item_id: UUID | None = None
    request_id: UUID | None = None
    task_id: UUID | None = None
    trace_id: UUID | None = None
    acknowledgment: str = Field(min_length=1, max_length=1000)
    reply_route: DiscordReplyRoute
    reason: str = Field(min_length=1, max_length=1000)

    @property
    def queued(self) -> bool:
        return self.disposition in {
            DiscordIngressDisposition.QUEUED,
            DiscordIngressDisposition.QUEUED_FOR_MODEL,
            DiscordIngressDisposition.DUPLICATE,
        }
