"""Model backend protocol used by the Luna core."""

from __future__ import annotations

from typing import Protocol

from luna.modeling.contracts import ModelRequest, ModelResponse


class ModelBackend(Protocol):
    """Provider-independent synchronous backend boundary for Luna 0.1."""

    @property
    def backend_id(self) -> str:
        """Return a stable adapter identifier."""
        ...

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate one response correlated to the supplied request."""
        ...
