from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.retrieval import (
    AdaptiveKnowledgeRouter,
    KnowledgeRequestProfile,
    KnowledgeRetrievalPlan,
    KnowledgeSource,
    KnowledgeUncertainty,
    KnowledgeVolatility,
    RetrievalDecision,
    RetrievalReason,
)


def _profile(**updates: object) -> KnowledgeRequestProfile:
    payload: dict[str, object] = {
        "task_id": uuid4(),
        "query": "Which source should Luna use?",
    }
    payload.update(updates)
    return KnowledgeRequestProfile.model_validate(payload)


def test_stable_low_uncertainty_can_answer_from_internal_knowledge() -> None:
    plan = AdaptiveKnowledgeRouter().route(
        _profile(
            volatility=KnowledgeVolatility.STABLE,
            uncertainty=KnowledgeUncertainty.LOW,
            internal_knowledge_sufficient=True,
        )
    )

    assert plan.decision is RetrievalDecision.ANSWER_DIRECT
    assert plan.primary_source is KnowledgeSource.INTERNAL
    assert plan.reasons == (RetrievalReason.INTERNAL_KNOWLEDGE_SUFFICIENT,)
    assert plan.requires_citation is False
    assert plan.automatic_memory_commit_allowed is False


def test_observed_working_context_wins_when_fresh_external_evidence_is_not_required() -> None:
    plan = AdaptiveKnowledgeRouter().route(
        _profile(
            working_context_sufficient=True,
            internal_knowledge_sufficient=True,
            volatility=KnowledgeVolatility.STABLE,
            uncertainty=KnowledgeUncertainty.LOW,
        )
    )

    assert plan.decision is RetrievalDecision.ANSWER_DIRECT
    assert plan.primary_source is KnowledgeSource.WORKING_CONTEXT


def test_user_specific_request_uses_verified_memory_when_context_is_insufficient() -> None:
    plan = AdaptiveKnowledgeRouter().route(
        _profile(user_specific=True, verified_memory_available=True)
    )

    assert plan.decision is RetrievalDecision.RETRIEVE
    assert plan.primary_source is KnowledgeSource.VERIFIED_MEMORY
    assert plan.automatic_memory_commit_allowed is False


def test_user_specific_request_does_not_fall_back_to_public_research() -> None:
    plan = AdaptiveKnowledgeRouter().route(
        _profile(user_specific=True, research_gateway_available=True)
    )

    assert plan.decision is RetrievalDecision.STOP_REINSPECT
    assert plan.primary_source is None
    assert RetrievalReason.REQUIRED_SOURCE_UNAVAILABLE in plan.reasons


def test_document_specific_request_uses_project_rag() -> None:
    plan = AdaptiveKnowledgeRouter().route(
        _profile(document_specific=True, project_rag_available=True)
    )

    assert plan.primary_source is KnowledgeSource.PROJECT_RAG
    assert plan.decision is RetrievalDecision.RETRIEVE
    assert plan.memory_review_required is True


def test_dynamic_structured_request_prefers_structured_api() -> None:
    plan = AdaptiveKnowledgeRouter().route(
        _profile(
            volatility=KnowledgeVolatility.DYNAMIC,
            currentness_required=True,
            structured_data_suitable=True,
            structured_api_available=True,
            research_gateway_available=True,
        )
    )

    assert plan.primary_source is KnowledgeSource.STRUCTURED_API
    assert plan.requires_freshness is True
    assert plan.requires_citation is True
    assert RetrievalReason.STRUCTURED_SOURCE_PREFERRED in plan.reasons


def test_dynamic_unstructured_request_routes_to_research_gateway() -> None:
    plan = AdaptiveKnowledgeRouter().route(
        _profile(
            volatility=KnowledgeVolatility.DYNAMIC,
            currentness_required=True,
            research_gateway_available=True,
        )
    )

    assert plan.primary_source is KnowledgeSource.RESEARCH_GATEWAY
    assert plan.decision is RetrievalDecision.RETRIEVE
    assert plan.memory_review_required is True


def test_current_request_stops_when_no_fresh_source_is_available() -> None:
    plan = AdaptiveKnowledgeRouter().route(
        _profile(
            volatility=KnowledgeVolatility.DYNAMIC,
            currentness_required=True,
            internal_knowledge_sufficient=True,
        )
    )

    assert plan.decision is RetrievalDecision.STOP_REINSPECT
    assert plan.primary_source is None
    assert RetrievalReason.CURRENT_INFORMATION_REQUIRED in plan.reasons


def test_high_uncertainty_requires_external_verification_when_available() -> None:
    plan = AdaptiveKnowledgeRouter().route(
        _profile(
            uncertainty=KnowledgeUncertainty.HIGH,
            research_gateway_available=True,
        )
    )

    assert plan.primary_source is KnowledgeSource.RESEARCH_GATEWAY
    assert RetrievalReason.HIGH_UNCERTAINTY in plan.reasons


def test_contradictory_evidence_always_stops_before_source_selection() -> None:
    plan = AdaptiveKnowledgeRouter().route(
        _profile(
            contradictory_evidence=True,
            working_context_sufficient=True,
            structured_api_available=True,
            research_gateway_available=True,
        )
    )

    assert plan.decision is RetrievalDecision.STOP_REINSPECT
    assert plan.primary_source is None
    assert plan.reasons == (RetrievalReason.CONTRADICTORY_EVIDENCE,)


def test_router_is_deterministic_for_same_profile() -> None:
    profile = _profile(
        currentness_required=True,
        structured_data_suitable=True,
        structured_api_available=True,
    )
    router = AdaptiveKnowledgeRouter()

    assert router.route(profile) == router.route(profile)


def test_external_plan_cannot_enable_automatic_memory_or_runtime_authority() -> None:
    plan = AdaptiveKnowledgeRouter().route(
        _profile(
            external_verification_required=True,
            research_gateway_available=True,
        )
    )

    assert plan.automatic_memory_commit_allowed is False
    assert plan.runtime_authority is False
    assert plan.external_action_allowed is False
    assert plan.memory_review_required is True


def test_answer_direct_rejects_external_primary_source() -> None:
    with pytest.raises(ValidationError):
        KnowledgeRetrievalPlan(
            task_id=uuid4(),
            decision=RetrievalDecision.ANSWER_DIRECT,
            primary_source=KnowledgeSource.RESEARCH_GATEWAY,
            reasons=(RetrievalReason.INTERNAL_KNOWLEDGE_SUFFICIENT,),
            requires_freshness=True,
            requires_citation=True,
        )
