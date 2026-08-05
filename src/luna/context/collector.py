"""Deterministic context selection without hidden file or network access."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from luna.context.models import (
    ContextAvailability,
    ContextBudget,
    ContextBundle,
    ContextCandidate,
    ContextExclusion,
    ContextExclusionReason,
    ContextSource,
)


class ContextCollector:
    """Admit only explicitly observed sources within a hard budget."""

    def collect(
        self,
        *,
        task_id: UUID,
        candidates: Iterable[ContextCandidate],
        budget: ContextBudget,
    ) -> ContextBundle:
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                not candidate.required,
                -candidate.priority,
                candidate.source.locator.casefold(),
                str(candidate.source.source_id),
            ),
        )

        selected: list[ContextSource] = []
        exclusions: list[ContextExclusion] = []
        missing_sources: list[str] = []
        seen_locators: set[str] = set()
        chars_used = 0
        tokens_used = 0

        for candidate in ordered:
            source = candidate.source
            locator_key = source.locator.casefold()

            if locator_key in seen_locators:
                exclusions.append(
                    ContextExclusion(
                        locator=source.locator,
                        reason=ContextExclusionReason.DUPLICATE,
                        required=candidate.required,
                    )
                )
                continue
            seen_locators.add(locator_key)

            if source.availability is ContextAvailability.MISSING:
                exclusions.append(
                    ContextExclusion(
                        locator=source.locator,
                        reason=ContextExclusionReason.MISSING,
                        required=candidate.required,
                    )
                )
                if candidate.required:
                    missing_sources.append(source.locator)
                continue

            if source.availability is ContextAvailability.DECLARED_NOT_OBSERVED:
                exclusions.append(
                    ContextExclusion(
                        locator=source.locator,
                        reason=ContextExclusionReason.NOT_OBSERVED,
                        required=candidate.required,
                    )
                )
                if candidate.required:
                    missing_sources.append(source.locator)
                continue

            if len(selected) + 1 > budget.max_sources:
                exclusions.append(
                    ContextExclusion(
                        locator=source.locator,
                        reason=ContextExclusionReason.SOURCE_LIMIT,
                        required=candidate.required,
                    )
                )
                if candidate.required:
                    missing_sources.append(source.locator)
                continue

            if chars_used + source.char_count > budget.max_chars:
                exclusions.append(
                    ContextExclusion(
                        locator=source.locator,
                        reason=ContextExclusionReason.CHARACTER_LIMIT,
                        required=candidate.required,
                    )
                )
                if candidate.required:
                    missing_sources.append(source.locator)
                continue

            if tokens_used + source.token_estimate > budget.max_estimated_tokens:
                exclusions.append(
                    ContextExclusion(
                        locator=source.locator,
                        reason=ContextExclusionReason.TOKEN_LIMIT,
                        required=candidate.required,
                    )
                )
                if candidate.required:
                    missing_sources.append(source.locator)
                continue

            selected.append(source)
            chars_used += source.char_count
            tokens_used += source.token_estimate

        return ContextBundle(
            task_id=task_id,
            sources=tuple(selected),
            missing_sources=tuple(dict.fromkeys(missing_sources)),
            exclusions=tuple(exclusions),
            budget=budget,
            chars_used=chars_used,
            estimated_tokens_used=tokens_used,
        )
