"""Evidence records used by the deterministic verifier."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import EvidenceResult, EvidenceSourceKind


class Evidence(LunaContractModel):
    """Versioned evidence linked to one task requirement."""

    evidence_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    requirement_id: str = Field(min_length=1, max_length=500)
    source_kind: EvidenceSourceKind
    source_ref: str = Field(min_length=1, max_length=4000)
    result: EvidenceResult
    observed_at: datetime = Field(default_factory=utc_now)
    environment_fingerprint: str = Field(min_length=1, max_length=1000)
    revision: str | None = Field(default=None, max_length=500)
    freshness_seconds: int | None = Field(default=None, ge=0)
    reproducible: bool
    confidence: float = Field(ge=0.0, le=1.0)
    details: str | None = Field(default=None, max_length=8000)

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_model_inference_limit(self) -> Evidence:
        if self.source_kind is EvidenceSourceKind.MODEL_INFERENCE:
            if self.result is EvidenceResult.PASS:
                raise ValueError("model inference alone cannot be PASS evidence")
            if self.confidence > 0.5:
                raise ValueError("model inference confidence cannot exceed 0.5")
        return self
