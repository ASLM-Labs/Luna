"""Phase 17 Discord gateway boundary."""

from luna.discord.bootstrap import build_local_discord_gateway
from luna.discord.gateway import DiscordGateway
from luna.discord.models import (
    DiscordAuthorityConfig,
    DiscordChannelBinding,
    DiscordChannelPurpose,
    DiscordIngressDisposition,
    DiscordIngressResult,
    DiscordReplyRoute,
    DiscordTransportEnvelope,
)
from luna.discord.moderation import DiscordModerationDecision, DiscordModerationGuard
from luna.discord.policy import DiscordAuthorityPolicy
from luna.discord.rate_limit import DiscordRateLimitDecision, DiscordRateLimiter

__all__ = [
    "DiscordAuthorityConfig",
    "DiscordAuthorityPolicy",
    "DiscordChannelBinding",
    "DiscordChannelPurpose",
    "DiscordGateway",
    "DiscordIngressDisposition",
    "DiscordIngressResult",
    "DiscordModerationDecision",
    "DiscordModerationGuard",
    "DiscordRateLimitDecision",
    "DiscordRateLimiter",
    "DiscordReplyRoute",
    "DiscordTransportEnvelope",
    "build_local_discord_gateway",
]
