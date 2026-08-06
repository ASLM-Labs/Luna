"""End-to-end Phase 2 task preparation without tools or side effects."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import model_validator

from luna.context import ContextBudget, ContextBundle, ContextCandidate, ContextCollector
from luna.contracts.base import LunaContractModel
from luna.contracts.enums import RiskLevel
from luna.contracts.task import TaskContract, TaskScope
from luna.intent import DeterministicIntentResolver, IntentResolution
from luna.tasking import ContractDraftStatus, TaskContractBuilder, TaskContractDraft


class PreparationStatus(StrEnum):
    """Outcome of intent, contract and context preparation."""

    READY_FOR_PLANNING = "READY_FOR_PLANNING"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    CONTEXT_INCOMPLETE = "CONTEXT_INCOMPLETE"


class TaskPreparation(LunaContractModel):
    """Traceable Phase 2 output before planning begins."""

    task_id: UUID
    intent: IntentResolution
    contract_draft: TaskContractDraft
    context: ContextBundle
    status: PreparationStatus
    reasons: tuple[str, ...] = ()
    contract: TaskContract | None = None

    @model_validator(mode="after")
    def validate_status(self) -> TaskPreparation:
        if self.contract_draft.task_id != self.task_id:
            raise ValueError("contract draft task_id must match preparation task_id")
        if self.context.task_id != self.task_id:
            raise ValueError("context task_id must match preparation task_id")
        if self.status is PreparationStatus.READY_FOR_PLANNING:
            if self.contract is None:
                raise ValueError("ready preparation requires a finalized contract")
            if self.contract_draft.status is not ContractDraftStatus.READY:
                raise ValueError("ready preparation requires a READY contract draft")
            if self.context.missing_sources:
                raise ValueError("ready preparation cannot have missing required context")
        return self


class TaskPreparer:
    """Compose Phase 2 components using explicit dependency injection."""

    def __init__(
        self,
        *,
        resolver: DeterministicIntentResolver | None = None,
        contract_builder: TaskContractBuilder | None = None,
        context_collector: ContextCollector | None = None,
    ) -> None:
        self._resolver = resolver or DeterministicIntentResolver()
        self._contract_builder = contract_builder or TaskContractBuilder()
        self._context_collector = context_collector or ContextCollector()

    def prepare(
        self,
        *,
        request: str,
        scope: TaskScope,
        context_candidates: Iterable[ContextCandidate],
        context_budget: ContextBudget,
        required_conditions: Iterable[str] = (),
        forbidden_outcomes: Iterable[str] = (),
        evidence_required: Iterable[str] = (),
        risk_level: RiskLevel = RiskLevel.LOW,
        owner: str = "user",
        task_id: UUID | None = None,
    ) -> TaskPreparation:
        active_task_id = task_id or uuid4()
        intent = self._resolver.resolve(request)
        draft = self._contract_builder.draft(
            intent=intent,
            scope=scope,
            required_conditions=required_conditions,
            forbidden_outcomes=forbidden_outcomes,
            evidence_required=evidence_required,
            risk_level=risk_level,
            owner=owner,
            task_id=active_task_id,
        )
        context = self._context_collector.collect(
            task_id=active_task_id,
            candidates=context_candidates,
            budget=context_budget,
        )

        reasons: list[str] = []
        contract: TaskContract | None = None

        if draft.status is ContractDraftStatus.BLOCKED or intent.requires_clarification:
            status = PreparationStatus.NEEDS_CLARIFICATION
            reasons.extend(draft.blocking_unknowns)
            reasons.extend(draft.conflicts)
            if intent.requires_clarification:
                reasons.extend(intent.unknowns)
        elif context.missing_sources:
            status = PreparationStatus.CONTEXT_INCOMPLETE
            reasons.extend(f"missing_context:{value}" for value in context.missing_sources)
        else:
            status = PreparationStatus.READY_FOR_PLANNING
            contract = self._contract_builder.finalize(draft)

        return TaskPreparation(
            task_id=active_task_id,
            intent=intent,
            contract_draft=draft,
            context=context,
            status=status,
            reasons=tuple(dict.fromkeys(reasons)),
            contract=contract,
        )
