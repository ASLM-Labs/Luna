"""Evidence-aware knowledge-routing contracts for Luna C-001."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel


class KnowledgeSource(StrEnum):
    """Canonical source families available to the adaptive retrieval router."""

    INTERNAL = "INTERNAL"
    WORKING_CONTEXT = "WORKING_CONTEXT"
    VERIFIED_MEMORY = "VERIFIED_MEMORY"
    PROJECT_RAG = "PROJECT_RAG"
    RESEARCH_GATEWAY = "RESEARCH_GATEWAY"
    STRUCTURED_API = "STRUCTURED_API"


class KnowledgeVolatility(StrEnum):
    """Expected rate at which the requested fact can become stale."""

    STABLE = "STABLE"
    DYNAMIC = "DYNAMIC"
    UNKNOWN = "UNKNOWN"


class KnowledgeUncertainty(StrEnum):
    """Evidence-bound uncertainty before selecting a source."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RetrievalDecision(StrEnum):
    """Whether Luna can answer now, must retrieve, or must stop and reinspect."""

    ANSWER_DIRECT = "ANSWER_DIRECT"
    RETRIEVE = "RETRIEVE"
    STOP_REINSPECT = "STOP_REINSPECT"


class RetrievalReason(StrEnum):
    """Stable explanations for deterministic source selection."""

    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    CURRENT_INFORMATION_REQUIRED = "CURRENT_INFORMATION_REQUIRED"
    HIGH_UNCERTAINTY = "HIGH_UNCERTAINTY"
    EXTERNAL_VERIFICATION_REQUIRED = "EXTERNAL_VERIFICATION_REQUIRED"
    USER_SPECIFIC = "USER_SPECIFIC"
    PROJECT_SPECIFIC = "PROJECT_SPECIFIC"
    DOCUMENT_SPECIFIC = "DOCUMENT_SPECIFIC"
    WORKING_CONTEXT_SUFFICIENT = "WORKING_CONTEXT_SUFFICIENT"
    INTERNAL_KNOWLEDGE_SUFFICIENT = "INTERNAL_KNOWLEDGE_SUFFICIENT"
    INSUFFICIENT_INTERNAL_EVIDENCE = "INSUFFICIENT_INTERNAL_EVIDENCE"
    STRUCTURED_SOURCE_PREFERRED = "STRUCTURED_SOURCE_PREFERRED"
    REQUIRED_SOURCE_UNAVAILABLE = "REQUIRED_SOURCE_UNAVAILABLE"


class KnowledgeRequestProfile(LunaContractModel):
    """Observable routing facts supplied to C-001 without granting retrieval authority."""

    task_id: UUID
    query: str = Field(min_length=1, max_length=8000)
    volatility: KnowledgeVolatility = KnowledgeVolatility.UNKNOWN
    uncertainty: KnowledgeUncertainty = KnowledgeUncertainty.MEDIUM
    currentness_required: bool = False
    external_verification_required: bool = False
    user_specific: bool = False
    project_specific: bool = False
    document_specific: bool = False
    structured_data_suitable: bool = False
    contradictory_evidence: bool = False
    internal_knowledge_sufficient: bool = False
    working_context_sufficient: bool = False
    verified_memory_available: bool = False
    project_rag_available: bool = False
    research_gateway_available: bool = False
    structured_api_available: bool = False

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("knowledge query cannot be blank")
        return cleaned


class KnowledgeRetrievalPlan(LunaContractModel):
    """Deterministic, non-executing source-routing decision."""

    task_id: UUID
    decision: RetrievalDecision
    primary_source: KnowledgeSource | None = None
    reasons: tuple[RetrievalReason, ...] = Field(min_length=1)
    requires_freshness: bool = False
    requires_citation: bool = False
    automatic_memory_commit_allowed: Literal[False] = False
    memory_review_required: bool = False
    runtime_authority: Literal[False] = False
    external_action_allowed: Literal[False] = False

    @field_validator("reasons")
    @classmethod
    def validate_unique_reasons(
        cls,
        values: tuple[RetrievalReason, ...],
    ) -> tuple[RetrievalReason, ...]:
        if len(values) != len(set(values)):
            raise ValueError("retrieval reasons must be unique")
        return values

    @model_validator(mode="after")
    def validate_decision_contract(self) -> Self:
        if self.decision is RetrievalDecision.STOP_REINSPECT:
            if self.primary_source is not None:
                raise ValueError("STOP_REINSPECT cannot select a primary source")
            return self

        if self.primary_source is None:
            raise ValueError("non-stop retrieval decision requires a primary source")

        direct_sources = {KnowledgeSource.INTERNAL, KnowledgeSource.WORKING_CONTEXT}
        if self.decision is RetrievalDecision.ANSWER_DIRECT:
            if self.primary_source not in direct_sources:
                raise ValueError("ANSWER_DIRECT is limited to internal or working context")
        elif self.primary_source in direct_sources:
            raise ValueError("RETRIEVE cannot select an already-present direct source")

        external_sources = {
            KnowledgeSource.RESEARCH_GATEWAY,
            KnowledgeSource.STRUCTURED_API,
        }
        if self.primary_source in external_sources and not self.requires_citation:
            raise ValueError("external retrieval requires citation/provenance")
        if self.primary_source in external_sources and not self.requires_freshness:
            raise ValueError("external retrieval requires freshness tracking")
        return self
