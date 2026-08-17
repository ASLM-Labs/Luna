"""C-001 adaptive knowledge routing diagnostic."""

from __future__ import annotations

from uuid import uuid4

from luna.diagnostics.models import SmokeReport, equals
from luna.retrieval import (
    AdaptiveKnowledgeRouter,
    KnowledgeRequestProfile,
    KnowledgeSource,
    KnowledgeUncertainty,
    KnowledgeVolatility,
    RetrievalDecision,
)


def run() -> SmokeReport:
    router = AdaptiveKnowledgeRouter()
    stable = router.route(
        KnowledgeRequestProfile(
            task_id=uuid4(),
            query="Explain a stable known Python language property.",
            volatility=KnowledgeVolatility.STABLE,
            uncertainty=KnowledgeUncertainty.LOW,
            internal_knowledge_sufficient=True,
        )
    )
    current = router.route(
        KnowledgeRequestProfile(
            task_id=uuid4(),
            query="Read the current structured service value.",
            volatility=KnowledgeVolatility.DYNAMIC,
            currentness_required=True,
            structured_data_suitable=True,
            structured_api_available=True,
            research_gateway_available=True,
        )
    )
    research = router.route(
        KnowledgeRequestProfile(
            task_id=uuid4(),
            query="Verify an uncertain externally checkable claim.",
            uncertainty=KnowledgeUncertainty.HIGH,
            research_gateway_available=True,
        )
    )
    contradiction = router.route(
        KnowledgeRequestProfile(
            task_id=uuid4(),
            query="Resolve contradictory evidence.",
            contradictory_evidence=True,
            working_context_sufficient=True,
            research_gateway_available=True,
        )
    )
    payload = {
        "stable_source": stable.primary_source.value if stable.primary_source else None,
        "stable_decision": stable.decision.value,
        "current_source": current.primary_source.value if current.primary_source else None,
        "research_source": (
            research.primary_source.value if research.primary_source else None
        ),
        "contradiction_decision": contradiction.decision.value,
        "automatic_memory_commit_allowed": research.automatic_memory_commit_allowed,
        "runtime_authority": research.runtime_authority,
        "external_action_allowed": research.external_action_allowed,
    }
    return SmokeReport(
        scenario_id="c001",
        payload=payload,
        checks=(
            equals("stable_decision", stable.decision, RetrievalDecision.ANSWER_DIRECT),
            equals("stable_source", stable.primary_source, KnowledgeSource.INTERNAL),
            equals("current_source", current.primary_source, KnowledgeSource.STRUCTURED_API),
            equals(
                "research_source",
                research.primary_source,
                KnowledgeSource.RESEARCH_GATEWAY,
            ),
            equals(
                "contradiction_decision",
                contradiction.decision,
                RetrievalDecision.STOP_REINSPECT,
            ),
            equals(
                "automatic_memory_commit_allowed",
                research.automatic_memory_commit_allowed,
                False,
            ),
            equals("runtime_authority", research.runtime_authority, False),
            equals("external_action_allowed", research.external_action_allowed, False),
        ),
    )
