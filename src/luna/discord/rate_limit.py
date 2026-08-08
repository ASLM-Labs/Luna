"""Deterministic local ingress rate limiting for Phase 17."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar

from luna.contracts.base import require_utc
from luna.runtime import ActorRole


@dataclass(frozen=True, slots=True)
class DiscordRateLimitDecision:
    allowed: bool
    duplicate: bool
    limit: int
    observed: int
    reason: str


class DiscordRateLimiter:
    """Small fixed-window limiter; it never grants authority or mutates Discord state."""

    _LIMITS: ClassVar[dict[ActorRole, int]] = {
        ActorRole.OWNER: 30,
        ActorRole.TRUSTED_TEAM: 20,
        ActorRole.COMMUNITY: 8,
        ActorRole.GUEST: 4,
    }

    def __init__(self, *, window_seconds: int = 60) -> None:
        if window_seconds < 1 or window_seconds > 3600:
            raise ValueError("Discord rate-limit window must be in [1, 3600]")
        self._window = timedelta(seconds=window_seconds)
        self._events: dict[str, deque[datetime]] = defaultdict(deque)
        self._seen_messages: set[str] = set()

    def evaluate(
        self,
        *,
        actor_id: str,
        role: ActorRole,
        message_id: str,
        now: datetime,
    ) -> DiscordRateLimitDecision:
        current = require_utc(now)
        limit = self._LIMITS.get(role, self._LIMITS[ActorRole.GUEST])
        if message_id in self._seen_messages:
            return DiscordRateLimitDecision(
                allowed=True,
                duplicate=True,
                limit=limit,
                observed=len(self._events[actor_id]),
                reason="duplicate Discord delivery does not consume another rate-limit slot",
            )
        history = self._events[actor_id]
        cutoff = current - self._window
        while history and history[0] <= cutoff:
            history.popleft()
        if len(history) >= limit:
            return DiscordRateLimitDecision(
                allowed=False,
                duplicate=False,
                limit=limit,
                observed=len(history),
                reason="Discord ingress rate limit exceeded",
            )
        history.append(current)
        self._seen_messages.add(message_id)
        return DiscordRateLimitDecision(
            allowed=True,
            duplicate=False,
            limit=limit,
            observed=len(history),
            reason="Discord ingress rate limit passed",
        )
