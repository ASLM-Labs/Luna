"""C2 search/retrieval strategy bound to one decision-critical information need."""

from __future__ import annotations

import json
from hashlib import sha256
from threading import RLock
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.planning.judgment import InformationGainPlan, InformationNeed
from luna.retrieval.models import (
    KnowledgeRequestProfile,
    KnowledgeRetrievalPlan,
    RetrievalDecision,
    RetrievalReason,
)
from luna.retrieval.router import AdaptiveKnowledgeRouter


class ObservedRetrievalStrategyLedger:
    """Task-scoped bounded history of retrieval strategies that produced observations."""

    def __init__(self, *, max_entries_per_task: int = 64) -> None:
        if max_entries_per_task < 1:
            raise ValueError("retrieval strategy history limit must be positive")
        self._max_entries_per_task = max_entries_per_task
        self._by_task: dict[UUID, tuple[str, ...]] = {}
        self._lock = RLock()

    def fingerprints(self, task_id: UUID) -> tuple[str, ...]:
        with self._lock:
            return self._by_task.get(task_id, ())

    def record(self, *, task_id: UUID, strategy_fingerprint: str) -> None:
        if len(strategy_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in strategy_fingerprint
        ):
            raise ValueError("strategy fingerprint must be lowercase SHA256 hex")
        with self._lock:
            current = list(self._by_task.get(task_id, ()))
            if strategy_fingerprint in current:
                return
            current.append(strategy_fingerprint)
            if len(current) > self._max_entries_per_task:
                current = current[-self._max_entries_per_task :]
            self._by_task[task_id] = tuple(current)

    def forget(self, task_id: UUID) -> None:
        with self._lock:
            self._by_task.pop(task_id, None)


class InformationRetrievalStrategy(LunaContractModel):
    """Non-executing source strategy for one selected information need."""

    task_id: UUID
    information_need_id: str = Field(pattern=r"^information:sha256:[0-9a-f]{64}$")
    decision_question: str = Field(min_length=1, max_length=4000)
    decision_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    query: str = Field(min_length=1, max_length=8000)
    strategy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_plan: KnowledgeRetrievalPlan
    stop_conditions: tuple[str, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    duplicate_observed_search_blocked: bool = False
    runtime_authority: Literal[False] = False
    external_action_allowed: Literal[False] = False

    @field_validator("stop_conditions", "reason_codes")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("retrieval strategy entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("retrieval strategy entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.retrieval_plan.task_id != self.task_id:
            raise ValueError("retrieval strategy task must match routed plan")
        if (
            self.retrieval_plan.decision is RetrievalDecision.STOP_REINSPECT
            and "stop_reinspect_before_search" not in self.stop_conditions
        ):
            raise ValueError("STOP_REINSPECT strategy must expose a stop condition")
        if (
            self.retrieval_plan.decision is RetrievalDecision.ANSWER_DIRECT
            and "decision_relevant_evidence_already_sufficient" not in self.stop_conditions
        ):
            raise ValueError("ANSWER_DIRECT strategy must expose evidence sufficiency")
        if (
            self.duplicate_observed_search_blocked
            and self.retrieval_plan.reasons != (RetrievalReason.DUPLICATE_SEARCH_BLOCKED,)
        ):
            raise ValueError("duplicate search block requires its canonical retrieval reason")
        return self


class InformationRetrievalStrategist:
    """Bind C2 information gain to the existing deterministic C-001 source router."""

    def __init__(self, router: AdaptiveKnowledgeRouter | None = None) -> None:
        self._router = router or AdaptiveKnowledgeRouter()

    @staticmethod
    def _selected_need(information_gain: InformationGainPlan) -> InformationNeed:
        return next(
            item
            for item in information_gain.needs
            if item.need_id == information_gain.selected_need_id
        )

    @staticmethod
    def _fingerprint(
        *,
        information_gain: InformationGainPlan,
        profile: KnowledgeRequestProfile,
        decision_basis_fingerprint: str,
    ) -> str:
        payload = {
            "decision_basis_fingerprint": decision_basis_fingerprint,
            "information_need_id": information_gain.selected_need_id,
            "profile": profile.model_dump(mode="json"),
            "task_id": str(information_gain.task_id),
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(serialized.encode("utf-8")).hexdigest()

    def plan(
        self,
        *,
        information_gain: InformationGainPlan,
        profile: KnowledgeRequestProfile,
        decision_basis_fingerprint: str,
        observed_strategy_fingerprints: tuple[str, ...] = (),
    ) -> InformationRetrievalStrategy:
        if profile.task_id != information_gain.task_id:
            raise ValueError("retrieval strategy task mismatch")
        if len(observed_strategy_fingerprints) != len(set(observed_strategy_fingerprints)):
            raise ValueError("observed retrieval strategy fingerprints must be unique")

        selected = self._selected_need(information_gain)
        if len(decision_basis_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in decision_basis_fingerprint
        ):
            raise ValueError("decision-basis fingerprint must be lowercase SHA256 hex")
        fingerprint = self._fingerprint(
            information_gain=information_gain,
            profile=profile,
            decision_basis_fingerprint=decision_basis_fingerprint,
        )
        duplicate = fingerprint in observed_strategy_fingerprints
        if duplicate:
            retrieval = KnowledgeRetrievalPlan(
                task_id=profile.task_id,
                decision=RetrievalDecision.STOP_REINSPECT,
                reasons=(RetrievalReason.DUPLICATE_SEARCH_BLOCKED,),
            )
        else:
            retrieval = self._router.route(profile)

        stop_conditions = [
            "decision_question_resolved",
            "contradictory_evidence_detected",
        ]
        if retrieval.decision is RetrievalDecision.STOP_REINSPECT:
            stop_conditions.append("stop_reinspect_before_search")
        elif retrieval.decision is RetrievalDecision.ANSWER_DIRECT:
            stop_conditions.append("decision_relevant_evidence_already_sufficient")
        elif retrieval.requires_freshness:
            stop_conditions.append("fresh_evidence_observed")
        else:
            stop_conditions.append("sufficient_source_evidence_observed")
        if duplicate:
            stop_conditions.append("duplicate_observed_search_blocked")

        reasons = [
            f"information_need:{selected.kind.value}",
            *(f"retrieval:{reason.value}" for reason in retrieval.reasons),
            "strategy_only_no_execution_authority",
        ]
        return InformationRetrievalStrategy(
            task_id=information_gain.task_id,
            information_need_id=information_gain.selected_need_id,
            decision_question=selected.description,
            decision_basis_fingerprint=decision_basis_fingerprint,
            query=profile.query,
            strategy_fingerprint=fingerprint,
            retrieval_plan=retrieval,
            stop_conditions=tuple(dict.fromkeys(stop_conditions)),
            reason_codes=tuple(dict.fromkeys(reasons)),
            duplicate_observed_search_blocked=duplicate,
        )
