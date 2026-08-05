from __future__ import annotations

from uuid import uuid4

from luna.context import (
    ContextAvailability,
    ContextBudget,
    ContextCandidate,
    ContextCollector,
    ContextExclusionReason,
    ContextSource,
    ContextSourceKind,
)


def test_unobserved_required_source_is_not_loaded_or_guessed() -> None:
    candidate = ContextCandidate(
        source=ContextSource(
            kind=ContextSourceKind.FILE,
            locator="src/luna/missing.py",
            availability=ContextAvailability.DECLARED_NOT_OBSERVED,
        ),
        required=True,
        priority=100,
    )

    bundle = ContextCollector().collect(
        task_id=uuid4(),
        candidates=[candidate],
        budget=ContextBudget(),
    )

    assert bundle.sources == ()
    assert bundle.missing_sources == ("src/luna/missing.py",)
    assert bundle.exclusions[0].reason is ContextExclusionReason.NOT_OBSERVED


def test_budget_selection_is_deterministic_and_priority_ordered() -> None:
    high = ContextCandidate(
        source=ContextSource.from_text(
            kind=ContextSourceKind.FILE,
            locator="high.py",
            text="a" * 20,
        ),
        priority=100,
    )
    low = ContextCandidate(
        source=ContextSource.from_text(
            kind=ContextSourceKind.FILE,
            locator="low.py",
            text="b" * 20,
        ),
        priority=10,
    )
    collector = ContextCollector()
    budget = ContextBudget(max_sources=1, max_chars=100, max_estimated_tokens=100)

    first = collector.collect(task_id=uuid4(), candidates=[low, high], budget=budget)
    second = collector.collect(task_id=uuid4(), candidates=[high, low], budget=budget)

    assert tuple(source.locator for source in first.sources) == ("high.py",)
    assert tuple(source.locator for source in second.sources) == ("high.py",)
    assert first.exclusions[0].reason is ContextExclusionReason.SOURCE_LIMIT


def test_observed_text_has_traceable_digest() -> None:
    source = ContextSource.from_text(
        kind=ContextSourceKind.DOCUMENT,
        locator="requirements.md",
        text="verified text",
        verified=True,
    )

    assert source.availability is ContextAvailability.OBSERVED
    assert source.content_digest is not None
    assert len(source.content_digest) == 64
    assert source.char_count == len("verified text")
