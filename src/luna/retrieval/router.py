"""Deterministic source router for C-001 Adaptive Knowledge Retrieval."""

from __future__ import annotations

from luna.retrieval.models import (
    KnowledgeRequestProfile,
    KnowledgeRetrievalPlan,
    KnowledgeSource,
    KnowledgeUncertainty,
    KnowledgeVolatility,
    RetrievalDecision,
    RetrievalReason,
)


class AdaptiveKnowledgeRouter:
    """Choose a knowledge source without fetching, executing, or granting authority."""

    def route(self, profile: KnowledgeRequestProfile) -> KnowledgeRetrievalPlan:
        if profile.contradictory_evidence:
            return self._stop(profile, RetrievalReason.CONTRADICTORY_EVIDENCE)

        if profile.working_context_sufficient and not self._requires_fresh_external(profile):
            return self._direct(
                profile,
                KnowledgeSource.WORKING_CONTEXT,
                RetrievalReason.WORKING_CONTEXT_SUFFICIENT,
            )

        if profile.user_specific:
            if profile.verified_memory_available and not profile.currentness_required:
                return self._retrieve(
                    profile,
                    KnowledgeSource.VERIFIED_MEMORY,
                    RetrievalReason.USER_SPECIFIC,
                )
            if profile.structured_data_suitable and profile.structured_api_available:
                return self._retrieve_external(
                    profile,
                    KnowledgeSource.STRUCTURED_API,
                    (
                        RetrievalReason.USER_SPECIFIC,
                        RetrievalReason.STRUCTURED_SOURCE_PREFERRED,
                    ),
                )
            return self._stop(
                profile,
                RetrievalReason.USER_SPECIFIC,
                RetrievalReason.REQUIRED_SOURCE_UNAVAILABLE,
            )

        if profile.document_specific:
            if profile.project_rag_available:
                return self._retrieve(
                    profile,
                    KnowledgeSource.PROJECT_RAG,
                    RetrievalReason.DOCUMENT_SPECIFIC,
                )
            return self._stop(
                profile,
                RetrievalReason.DOCUMENT_SPECIFIC,
                RetrievalReason.REQUIRED_SOURCE_UNAVAILABLE,
            )

        if profile.project_specific:
            if profile.project_rag_available:
                return self._retrieve(
                    profile,
                    KnowledgeSource.PROJECT_RAG,
                    RetrievalReason.PROJECT_SPECIFIC,
                )
            if profile.verified_memory_available and not profile.currentness_required:
                return self._retrieve(
                    profile,
                    KnowledgeSource.VERIFIED_MEMORY,
                    RetrievalReason.PROJECT_SPECIFIC,
                )
            return self._stop(
                profile,
                RetrievalReason.PROJECT_SPECIFIC,
                RetrievalReason.REQUIRED_SOURCE_UNAVAILABLE,
            )

        if profile.currentness_required or profile.volatility is KnowledgeVolatility.DYNAMIC:
            reasons = (RetrievalReason.CURRENT_INFORMATION_REQUIRED,)
            if profile.structured_data_suitable and profile.structured_api_available:
                return self._retrieve_external(
                    profile,
                    KnowledgeSource.STRUCTURED_API,
                    (*reasons, RetrievalReason.STRUCTURED_SOURCE_PREFERRED),
                )
            if profile.research_gateway_available:
                return self._retrieve_external(
                    profile,
                    KnowledgeSource.RESEARCH_GATEWAY,
                    reasons,
                )
            return self._stop(
                profile,
                *reasons,
                RetrievalReason.REQUIRED_SOURCE_UNAVAILABLE,
            )

        if (
            profile.external_verification_required
            or profile.uncertainty is KnowledgeUncertainty.HIGH
        ):
            reason = (
                RetrievalReason.EXTERNAL_VERIFICATION_REQUIRED
                if profile.external_verification_required
                else RetrievalReason.HIGH_UNCERTAINTY
            )
            if profile.structured_data_suitable and profile.structured_api_available:
                return self._retrieve_external(
                    profile,
                    KnowledgeSource.STRUCTURED_API,
                    (reason, RetrievalReason.STRUCTURED_SOURCE_PREFERRED),
                )
            if profile.research_gateway_available:
                return self._retrieve_external(
                    profile,
                    KnowledgeSource.RESEARCH_GATEWAY,
                    (reason,),
                )
            return self._stop(
                profile,
                reason,
                RetrievalReason.REQUIRED_SOURCE_UNAVAILABLE,
            )

        if (
            profile.internal_knowledge_sufficient
            and profile.volatility is KnowledgeVolatility.STABLE
            and profile.uncertainty is KnowledgeUncertainty.LOW
        ):
            return self._direct(
                profile,
                KnowledgeSource.INTERNAL,
                RetrievalReason.INTERNAL_KNOWLEDGE_SUFFICIENT,
            )

        if profile.research_gateway_available:
            return self._retrieve_external(
                profile,
                KnowledgeSource.RESEARCH_GATEWAY,
                (RetrievalReason.INSUFFICIENT_INTERNAL_EVIDENCE,),
            )

        return self._stop(profile, RetrievalReason.REQUIRED_SOURCE_UNAVAILABLE)

    @staticmethod
    def _requires_fresh_external(profile: KnowledgeRequestProfile) -> bool:
        return bool(
            profile.currentness_required
            or profile.volatility is KnowledgeVolatility.DYNAMIC
            or profile.external_verification_required
            or profile.uncertainty is KnowledgeUncertainty.HIGH
        )

    @staticmethod
    def _direct(
        profile: KnowledgeRequestProfile,
        source: KnowledgeSource,
        reason: RetrievalReason,
    ) -> KnowledgeRetrievalPlan:
        return KnowledgeRetrievalPlan(
            task_id=profile.task_id,
            decision=RetrievalDecision.ANSWER_DIRECT,
            primary_source=source,
            reasons=(reason,),
        )

    @staticmethod
    def _retrieve(
        profile: KnowledgeRequestProfile,
        source: KnowledgeSource,
        reason: RetrievalReason,
    ) -> KnowledgeRetrievalPlan:
        return KnowledgeRetrievalPlan(
            task_id=profile.task_id,
            decision=RetrievalDecision.RETRIEVE,
            primary_source=source,
            reasons=(reason,),
            memory_review_required=source is KnowledgeSource.PROJECT_RAG,
        )

    @staticmethod
    def _retrieve_external(
        profile: KnowledgeRequestProfile,
        source: KnowledgeSource,
        reasons: tuple[RetrievalReason, ...],
    ) -> KnowledgeRetrievalPlan:
        return KnowledgeRetrievalPlan(
            task_id=profile.task_id,
            decision=RetrievalDecision.RETRIEVE,
            primary_source=source,
            reasons=reasons,
            requires_freshness=True,
            requires_citation=True,
            memory_review_required=True,
        )

    @staticmethod
    def _stop(
        profile: KnowledgeRequestProfile,
        *reasons: RetrievalReason,
    ) -> KnowledgeRetrievalPlan:
        return KnowledgeRetrievalPlan(
            task_id=profile.task_id,
            decision=RetrievalDecision.STOP_REINSPECT,
            reasons=reasons,
        )
