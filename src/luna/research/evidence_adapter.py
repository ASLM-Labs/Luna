"""Citation-bound evidence RAG and Phase 12F evidence adaptation."""

from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from luna.contracts import Evidence
from luna.contracts.enums import EvidenceResult, EvidenceSourceKind
from luna.research.sources import (
    ResearchCitation,
    ResearchClaim,
    ResearchClaimAssessment,
    ResearchClaimStatus,
    ResearchSource,
)


def _supporting_excerpt(content: str, terms: tuple[str, ...], *, limit: int = 1200) -> str | None:
    folded = content.casefold()
    indexes = [folded.find(term.casefold()) for term in terms]
    if any(index < 0 for index in indexes):
        return None
    start = max(0, min(indexes) - 180)
    last_match_end = max(
        index + len(term)
        for index, term in zip(indexes, terms, strict=True)
    )
    end = min(len(content), last_match_end + 360)
    excerpt = content[start:end].strip()
    if len(excerpt) > limit:
        excerpt = excerpt[:limit].rstrip()
    if not all(term.casefold() in excerpt.casefold() for term in terms):
        return None
    return excerpt


class EvidenceRAGAdapter:
    """Link claims to exact source excerpts and emit only citation-backed document evidence."""

    def assess_claims(
        self,
        *,
        claims: tuple[ResearchClaim, ...],
        sources: tuple[ResearchSource, ...],
        max_citations_per_claim: int,
    ) -> tuple[ResearchClaimAssessment, ...]:
        assessments: list[ResearchClaimAssessment] = []
        for claim in claims:
            citations: list[ResearchCitation] = []
            used_families: set[str] = set()
            for source in sources:
                if source.source_family in used_families:
                    continue
                excerpt = _supporting_excerpt(source.content, claim.match_terms)
                if excerpt is None:
                    continue
                citations.append(
                    ResearchCitation(
                        claim_id=claim.claim_id,
                        source_id=source.source_id,
                        source_sha256=source.content_sha256,
                        source_url=source.final_url,
                        quoted_text=excerpt,
                        quoted_text_sha256=sha256(excerpt.encode("utf-8")).hexdigest(),
                        publisher=source.publisher,
                        retrieved_at=source.retrieved_at,
                    )
                )
                used_families.add(source.source_family)
                if len(citations) >= max_citations_per_claim:
                    break

            if citations:
                assessments.append(
                    ResearchClaimAssessment(
                        claim=claim,
                        status=ResearchClaimStatus.SUPPORTED,
                        citations=tuple(citations),
                        reasons=("claim terms are present in exact cited source excerpts",),
                    )
                )
            else:
                assessments.append(
                    ResearchClaimAssessment(
                        claim=claim,
                        status=ResearchClaimStatus.UNSUPPORTED,
                        reasons=("no admitted source excerpt satisfied all claim match terms",),
                    )
                )
        return tuple(assessments)

    @staticmethod
    def to_evidence(
        *,
        task_id: UUID,
        assessment: ResearchClaimAssessment,
        revision: str,
        environment_fingerprint: str,
        freshness_seconds: int,
    ) -> tuple[Evidence, ...]:
        """Convert citations to moderate DOCUMENT evidence; unsupported claims emit none."""
        if assessment.status is not ResearchClaimStatus.SUPPORTED:
            return ()
        return tuple(
            Evidence(
                task_id=task_id,
                requirement_id=assessment.claim.claim_id,
                source_kind=EvidenceSourceKind.DOCUMENT,
                source_ref=(
                    f"research:{citation.source_id}:{citation.citation_id}:"
                    f"{citation.source_sha256}"
                ),
                result=EvidenceResult.PASS,
                observed_at=citation.retrieved_at,
                environment_fingerprint=environment_fingerprint,
                revision=revision,
                freshness_seconds=freshness_seconds,
                reproducible=False,
                confidence=0.9,
                details=(
                    f"publisher={citation.publisher}; url={citation.source_url}; "
                    f"quote_sha256={citation.quoted_text_sha256}"
                ),
            )
            for citation in assessment.citations
        )
