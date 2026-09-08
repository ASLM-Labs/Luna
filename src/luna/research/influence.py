"""Influence projection for admitted external research sources."""

from __future__ import annotations

from luna.influence import InfluenceSourceClass, InfluenceTrust, single_influence
from luna.research.sources import ResearchSource


def research_source_influence(source: ResearchSource) -> InfluenceTrust:
    """Bind external research content to digest-qualified untrusted influence."""
    return single_influence(
        source_ref=f"research://{source.source_id}/sha256/{source.content_sha256}",
        source_class=InfluenceSourceClass.EXTERNAL_UNTRUSTED,
    )
