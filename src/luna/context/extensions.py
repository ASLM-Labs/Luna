"""Authority-negative extension boundary for optional root context evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from luna.contracts import TaskState


class RootContextExtensionIntegrityError(RuntimeError):
    """An optional context provider could not prove its evidence integrity."""


class RootContextExtensionResult(Protocol):
    """Minimal data-only result consumable by the single-policy root runtime."""

    @property
    def context_available(self) -> bool:
        """Whether the result contains evidence worth adding to root context."""

    @property
    def context_locator(self) -> str:
        """Return a stable, non-authoritative provenance locator."""

    @property
    def generated_at(self) -> datetime:
        """Return the root-observed generation time."""

    def render_for_root_context(self) -> str:
        """Render verified data only, without control or completion authority."""


class RootContextExtensionProvider(Protocol):
    """Optional injected provider; absence and disabled state preserve solo behavior."""

    @property
    def enabled(self) -> bool:
        """Return whether the provider is currently enabled by explicit policy."""

    def collect_for_root(
        self,
        *,
        state: TaskState,
        root_owner_ref: str,
        cancellation_probe: Callable[[], bool],
    ) -> RootContextExtensionResult:
        """Return a bounded data-only contribution for the authoritative root."""


__all__ = [
    "RootContextExtensionIntegrityError",
    "RootContextExtensionProvider",
    "RootContextExtensionResult",
]
