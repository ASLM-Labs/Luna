"""Phase 14 Research Gateway and citation-bound evidence RAG."""

from luna.research.evidence_adapter import EvidenceRAGAdapter
from luna.research.gateway import (
    ResearchBackend,
    ResearchFetchRequest,
    ResearchGateway,
    ResearchRequest,
    ScriptedResearchBackend,
    UrllibResearchBackend,
)
from luna.research.injection_guard import ResearchInjectionGuard
from luna.research.policy import ResearchPolicy
from luna.research.provenance import build_research_source
from luna.research.sources import (
    InjectionAssessment,
    RawResearchSource,
    ResearchBlockCode,
    ResearchBlockedTarget,
    ResearchCitation,
    ResearchClaim,
    ResearchClaimAssessment,
    ResearchClaimStatus,
    ResearchResult,
    ResearchResultStatus,
    ResearchSource,
    ResearchTarget,
    ResearchUsage,
    domain_from_url,
    normalize_domain,
)

__all__ = [
    "EvidenceRAGAdapter",
    "InjectionAssessment",
    "RawResearchSource",
    "ResearchBackend",
    "ResearchBlockCode",
    "ResearchBlockedTarget",
    "ResearchCitation",
    "ResearchClaim",
    "ResearchClaimAssessment",
    "ResearchClaimStatus",
    "ResearchFetchRequest",
    "ResearchGateway",
    "ResearchInjectionGuard",
    "ResearchPolicy",
    "ResearchRequest",
    "ResearchResult",
    "ResearchResultStatus",
    "ResearchSource",
    "ResearchTarget",
    "ResearchUsage",
    "ScriptedResearchBackend",
    "UrllibResearchBackend",
    "build_research_source",
    "domain_from_url",
    "normalize_domain",
]
