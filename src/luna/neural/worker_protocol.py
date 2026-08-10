"""Private worker protocol for a Luna-owned native model process or binding."""

from __future__ import annotations

from typing import Protocol

from luna.modeling.contracts import ModelRequest
from luna.neural.contracts import NeuralGenerationResult, NeuralResourceBudget, NeuralWorkerState


class NeuralWorker(Protocol):
    """Lifecycle boundary; concrete native transport is intentionally deferred."""

    @property
    def worker_id(self) -> str:
        ...

    @property
    def state(self) -> NeuralWorkerState:
        ...

    def start(self, *, budget: NeuralResourceBudget) -> None:
        """Start/load under a Luna-issued immutable budget snapshot."""
        ...

    def generate(self, request: ModelRequest) -> NeuralGenerationResult:
        """Generate one normalized result without gaining Luna authority."""
        ...

    def stop(self) -> None:
        """Release worker-owned neural resources."""
        ...
