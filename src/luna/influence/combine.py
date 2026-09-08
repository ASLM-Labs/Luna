"""Deterministic monotone composition for influence provenance."""

from __future__ import annotations

from luna.influence.models import (
    InfluenceContribution,
    InfluenceSourceClass,
    InfluenceTrust,
    derive_influence_state,
)

_MAX_CONTRIBUTIONS = 128


def _canonical_trust(
    contributions: tuple[InfluenceContribution, ...],
) -> InfluenceTrust:
    if not contributions:
        raise ValueError("influence trust requires at least one contribution")
    if len(contributions) > _MAX_CONTRIBUTIONS:
        raise ValueError("influence trust exceeds 128 provenance contributors")
    canonical = tuple(sorted(contributions, key=lambda item: item.source_ref))
    return InfluenceTrust(
        contributions=canonical,
        state=derive_influence_state(canonical),
    )


def single_influence(
    *,
    source_ref: str,
    source_class: InfluenceSourceClass,
) -> InfluenceTrust:
    """Create one host-classified influence envelope."""
    return _canonical_trust(
        (
            InfluenceContribution(
                source_ref=source_ref,
                source_class=source_class,
            ),
        )
    )


def combine_influence_trust(*values: InfluenceTrust) -> InfluenceTrust:
    """Union provenance conservatively; tainted influence can never be laundered."""
    if not values:
        raise ValueError("combine_influence_trust requires at least one value")

    by_ref: dict[str, InfluenceSourceClass] = {}
    for value in values:
        for contribution in value.contributions:
            current = by_ref.get(contribution.source_ref)
            if current is None:
                by_ref[contribution.source_ref] = contribution.source_class
            elif current is not contribution.source_class:
                by_ref[contribution.source_ref] = InfluenceSourceClass.UNKNOWN

    if len(by_ref) > _MAX_CONTRIBUTIONS:
        raise ValueError("influence trust exceeds 128 provenance contributors")

    contributions = tuple(
        InfluenceContribution(source_ref=source_ref, source_class=source_class)
        for source_ref, source_class in sorted(by_ref.items())
    )
    return _canonical_trust(contributions)
