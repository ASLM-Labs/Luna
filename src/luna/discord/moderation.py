"""Narrow ingress moderation boundary for Phase 17 Discord messages."""

from __future__ import annotations

from dataclasses import dataclass

from .models import DiscordTransportEnvelope


@dataclass(frozen=True, slots=True)
class DiscordModerationDecision:
    allowed: bool
    reason: str


class DiscordModerationGuard:
    """Reject unsafe ingress forms without performing external moderation actions."""

    def evaluate(self, envelope: DiscordTransportEnvelope) -> DiscordModerationDecision:
        if envelope.is_bot:
            return DiscordModerationDecision(False, "bot-authored Discord messages are ignored")
        if envelope.is_webhook:
            return DiscordModerationDecision(False, "webhook-authored Discord messages are ignored")
        if envelope.mentions_everyone:
            return DiscordModerationDecision(False, "mass-mention messages are not queued")
        return DiscordModerationDecision(
            True,
            "Discord ingress passed the local moderation boundary",
        )
