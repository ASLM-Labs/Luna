"""Layered, provenance-preserving context contracts for Phase 12B."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.context.models import (
    ContextAvailability,
    ContextBudget,
    ContextCandidate,
    ContextExclusion,
    ContextSource,
    ContextSourceKind,
)
from luna.contracts.base import LunaContractModel, require_utc, utc_now


class ContextLayer(StrEnum):
    """Stable layers admitted to the single policy-agent context."""

    ACTIVE = "ACTIVE"
    TASK = "TASK"
    RUNTIME_CONTINUITY = "RUNTIME_CONTINUITY"
    WORKSPACE = "WORKSPACE"
    VERIFIED_MEMORY = "VERIFIED_MEMORY"


CONTEXT_LAYER_ORDER: tuple[ContextLayer, ...] = (
    ContextLayer.ACTIVE,
    ContextLayer.TASK,
    ContextLayer.RUNTIME_CONTINUITY,
    ContextLayer.WORKSPACE,
    ContextLayer.VERIFIED_MEMORY,
)


class ContextInterpretation(StrEnum):
    """How the model is allowed to interpret an admitted entry."""

    CONTROL = "CONTROL"
    DATA_ONLY = "DATA_ONLY"


class ContextSensitivity(StrEnum):
    """Whether candidate material is model-visible at all."""

    MODEL_VISIBLE = "MODEL_VISIBLE"
    SECRET = "SECRET"


class LayeredContextCandidate(LunaContractModel):
    """One explicit candidate assigned to exactly one context layer."""

    layer: ContextLayer
    source: ContextSource
    priority: int = Field(default=50, ge=0, le=100)
    required: bool = False
    interpretation: ContextInterpretation = ContextInterpretation.DATA_ONLY
    sensitivity: ContextSensitivity = ContextSensitivity.MODEL_VISIBLE
    max_age_seconds: int | None = Field(default=None, ge=0)
    relevance_basis: str | None = Field(default=None, min_length=1, max_length=1000)

    @field_validator("relevance_basis")
    @classmethod
    def validate_relevance_basis(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("relevance_basis cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_interpretation_boundary(self) -> LayeredContextCandidate:
        if self.interpretation is ContextInterpretation.CONTROL and self.layer not in {
            ContextLayer.ACTIVE,
            ContextLayer.TASK,
            ContextLayer.RUNTIME_CONTINUITY,
        }:
            raise ValueError("workspace and memory context must remain DATA_ONLY")
        if self.layer is ContextLayer.VERIFIED_MEMORY and self.relevance_basis is None:
            raise ValueError("verified memory context requires an explicit relevance_basis")
        return self

    @classmethod
    def from_candidate(
        cls,
        candidate: ContextCandidate,
        *,
        layer: ContextLayer = ContextLayer.WORKSPACE,
        interpretation: ContextInterpretation = ContextInterpretation.DATA_ONLY,
        sensitivity: ContextSensitivity = ContextSensitivity.MODEL_VISIBLE,
        max_age_seconds: int | None = None,
        relevance_basis: str | None = None,
    ) -> LayeredContextCandidate:
        """Bridge a legacy Phase 2 candidate without observing new content."""
        return cls(
            layer=layer,
            source=candidate.source,
            priority=candidate.priority,
            required=candidate.required,
            interpretation=interpretation,
            sensitivity=sensitivity,
            max_age_seconds=max_age_seconds,
            relevance_basis=relevance_basis,
        )

    @classmethod
    def from_text(
        cls,
        *,
        layer: ContextLayer,
        kind: ContextSourceKind,
        locator: str,
        text: str,
        priority: int = 50,
        required: bool = False,
        interpretation: ContextInterpretation = ContextInterpretation.DATA_ONLY,
        sensitivity: ContextSensitivity = ContextSensitivity.MODEL_VISIBLE,
        verified: bool = False,
        max_age_seconds: int | None = None,
        observed_at: datetime | None = None,
        relevance_basis: str | None = None,
    ) -> LayeredContextCandidate:
        """Create a candidate only from text already observed by the caller."""
        return cls(
            layer=layer,
            source=ContextSource.from_text(
                kind=kind,
                locator=locator,
                text=text,
                verified=verified,
                observed_at=observed_at,
            ),
            priority=priority,
            required=required,
            interpretation=interpretation,
            sensitivity=sensitivity,
            max_age_seconds=max_age_seconds,
            relevance_basis=relevance_basis,
        )


class ContextLayerPolicy(LunaContractModel):
    """Per-layer hard budget."""

    layer: ContextLayer
    budget: ContextBudget


def _default_layer_policies() -> tuple[ContextLayerPolicy, ...]:
    return (
        ContextLayerPolicy(
            layer=ContextLayer.ACTIVE,
            budget=ContextBudget(max_sources=4, max_chars=12_000, max_estimated_tokens=3_000),
        ),
        ContextLayerPolicy(
            layer=ContextLayer.TASK,
            budget=ContextBudget(max_sources=8, max_chars=16_000, max_estimated_tokens=4_000),
        ),
        ContextLayerPolicy(
            layer=ContextLayer.RUNTIME_CONTINUITY,
            budget=ContextBudget(max_sources=8, max_chars=16_000, max_estimated_tokens=4_000),
        ),
        ContextLayerPolicy(
            layer=ContextLayer.WORKSPACE,
            budget=ContextBudget(max_sources=24, max_chars=48_000, max_estimated_tokens=12_000),
        ),
        ContextLayerPolicy(
            layer=ContextLayer.VERIFIED_MEMORY,
            budget=ContextBudget(max_sources=8, max_chars=12_000, max_estimated_tokens=3_000),
        ),
    )


class LayeredContextPolicy(LunaContractModel):
    """Runtime-owned composition policy; lower-value context cannot crowd out control state."""

    overall_budget: ContextBudget = Field(default_factory=ContextBudget)
    layers: tuple[ContextLayerPolicy, ...] = Field(default_factory=_default_layer_policies)
    block_unverified_memory: bool = True
    redact_detected_secrets: bool = True

    @model_validator(mode="after")
    def validate_layers(self) -> LayeredContextPolicy:
        layer_names = tuple(item.layer for item in self.layers)
        if len(layer_names) != len(set(layer_names)):
            raise ValueError("context layer policies must be unique")
        if set(layer_names) != set(CONTEXT_LAYER_ORDER):
            raise ValueError("context policy must define every Phase 12B layer")
        if not self.block_unverified_memory:
            raise ValueError("unverified memory blocking cannot be disabled")
        if not self.redact_detected_secrets:
            raise ValueError("context secret redaction cannot be disabled")
        return self

    def budget_for(self, layer: ContextLayer) -> ContextBudget:
        for item in self.layers:
            if item.layer is layer:
                return item.budget
        raise ValueError(f"missing context layer policy: {layer.value}")


class LayeredContextEntry(LunaContractModel):
    """One model-visible, sanitized entry with provenance and interpretation."""

    layer: ContextLayer
    source: ContextSource
    priority: int = Field(ge=0, le=100)
    required: bool
    interpretation: ContextInterpretation
    age_seconds: int = Field(ge=0)
    max_age_seconds: int | None = Field(default=None, ge=0)
    relevance_basis: str | None = Field(default=None, min_length=1, max_length=1000)
    redactions_applied: tuple[str, ...] = ()

    @field_validator("redactions_applied")
    @classmethod
    def validate_redactions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("redaction labels must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("redaction labels must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_model_visible_source(self) -> LayeredContextEntry:
        if self.source.availability is not ContextAvailability.OBSERVED:
            raise ValueError("layered context entries must be observed")
        if self.source.content_excerpt is None:
            raise ValueError("layered context entries require model-visible content")
        if self.interpretation is ContextInterpretation.CONTROL and self.layer not in {
            ContextLayer.ACTIVE,
            ContextLayer.TASK,
            ContextLayer.RUNTIME_CONTINUITY,
        }:
            raise ValueError("workspace and memory entries cannot become control instructions")
        if self.layer is ContextLayer.VERIFIED_MEMORY and self.relevance_basis is None:
            raise ValueError("verified memory entry must retain relevance_basis")
        return self


class ContextLayerSection(LunaContractModel):
    """One deterministic layer of the final context bundle."""

    layer: ContextLayer
    entries: tuple[LayeredContextEntry, ...] = ()
    missing_sources: tuple[str, ...] = ()
    exclusions: tuple[ContextExclusion, ...] = ()
    budget: ContextBudget
    chars_used: int = Field(ge=0)
    estimated_tokens_used: int = Field(ge=0)

    @field_validator("missing_sources")
    @classmethod
    def validate_missing_sources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("missing source locators must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("missing source locators must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_section(self) -> ContextLayerSection:
        if any(entry.layer is not self.layer for entry in self.entries):
            raise ValueError("context entry layer must match its section")
        if len(self.entries) > self.budget.max_sources:
            raise ValueError("context layer source count exceeds budget")
        if self.chars_used != sum(entry.source.char_count for entry in self.entries):
            raise ValueError("context layer chars_used mismatch")
        if self.estimated_tokens_used != sum(
            entry.source.token_estimate for entry in self.entries
        ):
            raise ValueError("context layer token estimate mismatch")
        if self.chars_used > self.budget.max_chars:
            raise ValueError("context layer characters exceed budget")
        if self.estimated_tokens_used > self.budget.max_estimated_tokens:
            raise ValueError("context layer tokens exceed budget")
        locators = tuple(entry.source.locator.casefold() for entry in self.entries)
        if len(locators) != len(set(locators)):
            raise ValueError("context layer locators must be unique")
        return self


class LayeredContextBundle(LunaContractModel):
    """Final model-facing context with stable layers, gaps, provenance, and budgets."""

    bundle_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    sections: tuple[ContextLayerSection, ...]
    overall_budget: ContextBudget
    chars_used: int = Field(ge=0)
    estimated_tokens_used: int = Field(ge=0)
    missing_sources: tuple[str, ...] = ()
    redactions_applied: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("missing_sources", "redactions_applied")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("context bundle text values must not be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("context bundle text values must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_bundle(self) -> LayeredContextBundle:
        if tuple(section.layer for section in self.sections) != CONTEXT_LAYER_ORDER:
            raise ValueError("context sections must use the canonical layer order")
        if self.chars_used != sum(section.chars_used for section in self.sections):
            raise ValueError("context bundle chars_used mismatch")
        if self.estimated_tokens_used != sum(
            section.estimated_tokens_used for section in self.sections
        ):
            raise ValueError("context bundle token estimate mismatch")
        if self.chars_used > self.overall_budget.max_chars:
            raise ValueError("context bundle characters exceed overall budget")
        if self.estimated_tokens_used > self.overall_budget.max_estimated_tokens:
            raise ValueError("context bundle tokens exceed overall budget")
        entry_count = sum(len(section.entries) for section in self.sections)
        if entry_count > self.overall_budget.max_sources:
            raise ValueError("context bundle source count exceeds overall budget")
        expected_missing = tuple(
            dict.fromkeys(
                locator
                for section in self.sections
                for locator in section.missing_sources
            )
        )
        if self.missing_sources != expected_missing:
            raise ValueError("context bundle missing_sources must match layer sections")
        return self

    @property
    def ready(self) -> bool:
        """Required model context is complete."""
        return not self.missing_sources

    def entries(self) -> tuple[LayeredContextEntry, ...]:
        """Return entries in canonical layer order."""
        return tuple(entry for section in self.sections for entry in section.entries)

    def fingerprint(self) -> str:
        """Stable digest independent from bundle UUID and wall-clock composition time."""
        sections_payload: list[dict[str, object]] = []
        for section in self.sections:
            entries_payload: list[dict[str, object]] = []
            for entry in section.entries:
                entries_payload.append(
                    {
                        "locator": entry.source.locator,
                        "kind": entry.source.kind.value,
                        "content_digest": entry.source.content_digest,
                        "observed_at": (
                            entry.source.observed_at.isoformat()
                            if entry.source.observed_at is not None
                            else None
                        ),
                        "verified": entry.source.verified,
                        "priority": entry.priority,
                        "required": entry.required,
                        "interpretation": entry.interpretation.value,
                        "max_age_seconds": entry.max_age_seconds,
                        "relevance_basis": entry.relevance_basis,
                        "redactions_applied": list(entry.redactions_applied),
                    }
                )
            sections_payload.append(
                {
                    "layer": section.layer.value,
                    "entries": entries_payload,
                    "missing_sources": list(section.missing_sources),
                    "exclusions": [
                        exclusion.model_dump(mode="json") for exclusion in section.exclusions
                    ],
                    "budget": section.budget.model_dump(mode="json"),
                }
            )
        payload = {
            "task_id": str(self.task_id),
            "sections": sections_payload,
            "overall_budget": self.overall_budget.model_dump(mode="json"),
            "chars_used": self.chars_used,
            "estimated_tokens_used": self.estimated_tokens_used,
            "missing_sources": list(self.missing_sources),
            "redactions_applied": list(self.redactions_applied),
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()

    def render_for_model(self) -> str:
        """Render only admitted, sanitized content; metadata and secret references stay out."""
        lines: list[str] = []
        for section in self.sections:
            if not section.entries:
                continue
            lines.append(f"## {section.layer.value}")
            for entry in section.entries:
                source = entry.source
                lines.append(
                    "["
                    + entry.interpretation.value
                    + "] source="
                    + source.locator
                    + " verified="
                    + str(source.verified).lower()
                )
                if source.content_excerpt is None:
                    raise ValueError("model context entry unexpectedly lacks content")
                lines.append(source.content_excerpt)
        return "\n".join(lines)
