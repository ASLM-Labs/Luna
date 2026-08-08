"""Provenance helpers for admitted Phase 14 research sources."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from luna.contracts.base import require_utc
from luna.research.sources import (
    InjectionAssessment,
    RawResearchSource,
    ResearchSource,
    domain_from_url,
)


def build_research_source(
    raw: RawResearchSource,
    *,
    retrieved_at: datetime,
    request_index: int,
    injection: InjectionAssessment,
) -> ResearchSource:
    """Bind untrusted backend content to runtime-owned retrieval provenance."""
    current = require_utc(retrieved_at)
    content = raw.content
    return ResearchSource(
        requested_url=raw.requested_url,
        final_url=raw.final_url,
        domain=domain_from_url(raw.final_url),
        title=raw.title,
        publisher=raw.publisher,
        source_family=raw.source_family,
        content=content,
        content_sha256=sha256(content.encode("utf-8")).hexdigest(),
        retrieved_at=current,
        published_at=raw.published_at,
        request_index=request_index,
        token_estimate=(len(content) + 3) // 4,
        injection=injection,
    )
