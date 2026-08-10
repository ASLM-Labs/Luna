"""Observable streaming events emitted by Luna-owned neural workers."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from luna.contracts.base import LunaContractModel


class NeuralStreamEventType(StrEnum):
    """Stable observable event types; these events carry no execution authority."""

    READY = "READY"
    TEXT_DELTA = "TEXT_DELTA"
    FINISH = "FINISH"
    ERROR = "ERROR"


class NeuralStreamEvent(LunaContractModel):
    """One observable neural-output event correlated to a model request."""

    request_id: UUID
    event_type: NeuralStreamEventType
    sequence: int = Field(ge=0)
    text: str = Field(default="", max_length=200000)


NeuralStreamObserver = Callable[[NeuralStreamEvent], None]
