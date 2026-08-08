"""Verified Discord channel/role policy for Phase 17."""

from __future__ import annotations

from luna.contracts.base import utc_now
from luna.runtime import ActorRole, ActorVerificationSource, RuntimeActor

from .models import (
    DiscordAuthorityConfig,
    DiscordChannelBinding,
    DiscordChannelPurpose,
    DiscordTransportEnvelope,
)


class DiscordAuthorityPolicy:
    """Resolve authority only from runtime-owned mappings and verified transport metadata."""

    def __init__(self, config: DiscordAuthorityConfig) -> None:
        self.config = config
        self._channels = {binding.channel_id: binding for binding in config.channels}

    def channel_binding(self, channel_id: str) -> DiscordChannelBinding | None:
        return self._channels.get(channel_id)

    def resolve_actor(self, envelope: DiscordTransportEnvelope) -> RuntimeActor:
        role_ids = set(envelope.author_role_ids)
        if envelope.author_id in self.config.owner_user_ids:
            role = ActorRole.OWNER
        elif role_ids.intersection(self.config.trusted_role_ids):
            role = ActorRole.TRUSTED_TEAM
        elif role_ids.intersection(self.config.community_role_ids):
            role = ActorRole.COMMUNITY
        else:
            role = ActorRole.GUEST
        return RuntimeActor(
            actor_id=envelope.author_id,
            role=role,
            verified=True,
            verification_source=ActorVerificationSource.GATEWAY_ROLE,
            verified_at=envelope.verified_at or utc_now(),
        )

    @staticmethod
    def role_allowed(*, role: ActorRole, purpose: DiscordChannelPurpose) -> bool:
        if purpose is DiscordChannelPurpose.UPDATES:
            return role in {ActorRole.OWNER, ActorRole.TRUSTED_TEAM}
        return role in {
            ActorRole.OWNER,
            ActorRole.TRUSTED_TEAM,
            ActorRole.COMMUNITY,
            ActorRole.GUEST,
        }
