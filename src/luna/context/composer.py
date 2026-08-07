"""Deterministic layered context composition with no hidden I/O."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from luna.audit.redaction import SecretRedactor
from luna.context.layered import (
    CONTEXT_LAYER_ORDER,
    ContextLayer,
    ContextLayerSection,
    ContextSensitivity,
    LayeredContextBundle,
    LayeredContextCandidate,
    LayeredContextEntry,
    LayeredContextPolicy,
)
from luna.context.models import (
    ContextAvailability,
    ContextExclusion,
    ContextExclusionReason,
    ContextSource,
    ContextSourceKind,
)
from luna.contracts.base import require_utc, utc_now

_LAYER_RANK = {layer: index for index, layer in enumerate(CONTEXT_LAYER_ORDER)}


class LayeredContextComposer:
    """Compose model-visible context from already-observed explicit candidates."""

    def compose(
        self,
        *,
        task_id: UUID,
        candidates: Iterable[LayeredContextCandidate],
        policy: LayeredContextPolicy | None = None,
        as_of: datetime | None = None,
        explicit_secrets: Iterable[str] = (),
    ) -> LayeredContextBundle:
        active_policy = policy or LayeredContextPolicy()
        composed_at = require_utc(as_of) if as_of is not None else utc_now()
        redactor = SecretRedactor(explicit_secrets)
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                not candidate.required,
                _LAYER_RANK[candidate.layer],
                -candidate.priority,
                candidate.source.locator.casefold(),
                candidate.source.content_digest or "",
                candidate.source.kind.value,
                str(candidate.source.source_id),
            ),
        )

        entries: dict[ContextLayer, list[LayeredContextEntry]] = {
            layer: [] for layer in CONTEXT_LAYER_ORDER
        }
        exclusions: dict[ContextLayer, list[ContextExclusion]] = {
            layer: [] for layer in CONTEXT_LAYER_ORDER
        }
        missing: dict[ContextLayer, list[str]] = {
            layer: [] for layer in CONTEXT_LAYER_ORDER
        }
        layer_chars = {layer: 0 for layer in CONTEXT_LAYER_ORDER}
        layer_tokens = {layer: 0 for layer in CONTEXT_LAYER_ORDER}
        seen_locators: set[str] = set()
        redactions_applied: list[str] = []
        total_chars = 0
        total_tokens = 0
        total_sources = 0

        def reject(
            candidate: LayeredContextCandidate,
            reason: ContextExclusionReason,
        ) -> None:
            exclusions[candidate.layer].append(
                ContextExclusion(
                    locator=candidate.source.locator,
                    reason=reason,
                    required=candidate.required,
                )
            )
            if candidate.required:
                missing[candidate.layer].append(candidate.source.locator)

        for candidate in ordered:
            source = candidate.source
            locator_key = source.locator.casefold()
            if locator_key in seen_locators:
                reject(candidate, ContextExclusionReason.DUPLICATE)
                continue
            seen_locators.add(locator_key)

            if source.availability is ContextAvailability.MISSING:
                reject(candidate, ContextExclusionReason.MISSING)
                continue
            if source.availability is ContextAvailability.DECLARED_NOT_OBSERVED:
                reject(candidate, ContextExclusionReason.NOT_OBSERVED)
                continue
            if source.content_excerpt is None:
                reject(candidate, ContextExclusionReason.CONTENT_UNAVAILABLE)
                continue
            if candidate.sensitivity is ContextSensitivity.SECRET:
                reject(candidate, ContextExclusionReason.SECRET)
                continue
            if (
                candidate.layer is ContextLayer.VERIFIED_MEMORY
                and active_policy.block_unverified_memory
                and (source.kind is not ContextSourceKind.MEMORY or not source.verified)
            ):
                reject(candidate, ContextExclusionReason.UNVERIFIED)
                continue

            observed_at = source.observed_at
            if observed_at is None:
                reject(candidate, ContextExclusionReason.NOT_OBSERVED)
                continue
            normalized_observed_at = require_utc(observed_at)
            if normalized_observed_at > composed_at:
                reject(candidate, ContextExclusionReason.FUTURE_TIMESTAMP)
                continue
            age_seconds = int((composed_at - normalized_observed_at).total_seconds())
            if candidate.max_age_seconds is not None and age_seconds > candidate.max_age_seconds:
                reject(candidate, ContextExclusionReason.STALE)
                continue

            safe_source, labels = self._sanitize_source(
                source,
                redactor=redactor,
                enabled=active_policy.redact_detected_secrets,
            )
            redactions_applied.extend(labels)

            layer_budget = active_policy.budget_for(candidate.layer)
            if len(entries[candidate.layer]) + 1 > layer_budget.max_sources:
                reject(candidate, ContextExclusionReason.SOURCE_LIMIT)
                continue
            if layer_chars[candidate.layer] + safe_source.char_count > layer_budget.max_chars:
                reject(candidate, ContextExclusionReason.CHARACTER_LIMIT)
                continue
            if (
                layer_tokens[candidate.layer] + safe_source.token_estimate
                > layer_budget.max_estimated_tokens
            ):
                reject(candidate, ContextExclusionReason.TOKEN_LIMIT)
                continue

            overall = active_policy.overall_budget
            if total_sources + 1 > overall.max_sources:
                reject(candidate, ContextExclusionReason.SOURCE_LIMIT)
                continue
            if total_chars + safe_source.char_count > overall.max_chars:
                reject(candidate, ContextExclusionReason.CHARACTER_LIMIT)
                continue
            if total_tokens + safe_source.token_estimate > overall.max_estimated_tokens:
                reject(candidate, ContextExclusionReason.TOKEN_LIMIT)
                continue

            entry = LayeredContextEntry(
                layer=candidate.layer,
                source=safe_source,
                priority=candidate.priority,
                required=candidate.required,
                interpretation=candidate.interpretation,
                age_seconds=age_seconds,
                max_age_seconds=candidate.max_age_seconds,
                relevance_basis=candidate.relevance_basis,
                redactions_applied=labels,
            )
            entries[candidate.layer].append(entry)
            layer_chars[candidate.layer] += safe_source.char_count
            layer_tokens[candidate.layer] += safe_source.token_estimate
            total_chars += safe_source.char_count
            total_tokens += safe_source.token_estimate
            total_sources += 1

        sections = tuple(
            ContextLayerSection(
                layer=layer,
                entries=tuple(entries[layer]),
                missing_sources=tuple(dict.fromkeys(missing[layer])),
                exclusions=tuple(exclusions[layer]),
                budget=active_policy.budget_for(layer),
                chars_used=layer_chars[layer],
                estimated_tokens_used=layer_tokens[layer],
            )
            for layer in CONTEXT_LAYER_ORDER
        )
        missing_sources = tuple(
            dict.fromkeys(locator for layer in CONTEXT_LAYER_ORDER for locator in missing[layer])
        )
        return LayeredContextBundle(
            task_id=task_id,
            sections=sections,
            overall_budget=active_policy.overall_budget,
            chars_used=total_chars,
            estimated_tokens_used=total_tokens,
            missing_sources=missing_sources,
            redactions_applied=tuple(dict.fromkeys(redactions_applied)),
            created_at=composed_at,
        )

    @staticmethod
    def _sanitize_source(
        source: ContextSource,
        *,
        redactor: SecretRedactor,
        enabled: bool,
    ) -> tuple[ContextSource, tuple[str, ...]]:
        if not enabled:
            return source, ()
        if source.content_excerpt is None:
            return source, ()
        result = redactor.redact_text(source.content_excerpt)
        if not result.redactions_applied:
            return source, ()
        metadata = dict(source.metadata)
        metadata["context_redacted"] = True
        sanitized = source.model_copy(
            update={
                "content_excerpt": result.text,
                "metadata": metadata,
            }
        )
        return sanitized, result.redactions_applied
