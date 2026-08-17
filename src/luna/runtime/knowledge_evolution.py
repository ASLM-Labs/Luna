"""Bounded runtime handoff for owner-projected Knowledge Evolution signals.

The runtime coordinates already-owner-projected signals. It does not originate
truth, validity, applicability, relative fitness, bindings, or execution
authority.
"""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from luna.contracts.base import LunaContractModel
from luna.decision_state import KnowledgeDecisionStateBinding
from luna.knowledge_evolution import (
    KnowledgeApplicabilitySignal,
    KnowledgeOptionSpaceChangeSignal,
    KnowledgeValiditySignal,
)


class KnowledgeEvolutionRuntimeHandoff(LunaContractModel):
    """One bounded owner-produced KE handoff for one policy turn."""

    task_id: UUID
    step_id: UUID
    source_decision_state_revision: int = Field(ge=0)

    validity: KnowledgeValiditySignal
    applicability: KnowledgeApplicabilitySignal
    option_space_change: KnowledgeOptionSpaceChangeSignal
    binding: KnowledgeDecisionStateBinding

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    planning_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    decision_mutation_authority: Literal[False] = False
    memory_mutation_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_owner_binding(self) -> KnowledgeEvolutionRuntimeHandoff:
        if self.binding.task_id != self.task_id:
            raise ValueError(
                "KE runtime handoff binding must match the handoff task"
            )

        knowledge_refs = {
            self.validity.knowledge_ref,
            self.applicability.knowledge_ref,
            self.option_space_change.knowledge_ref,
            self.binding.knowledge_ref,
        }

        if len(knowledge_refs) != 1:
            raise ValueError(
                "KE runtime handoff signals and binding must share one knowledge ref"
            )

        return self


class KnowledgeEvolutionRuntimeHandoffProvider(Protocol):
    """External owner-output provider; runtime cannot widen this authority."""

    def handoff_for_turn(
        self,
        *,
        task_id: UUID,
        step_id: UUID,
        decision_state_revision: int,
    ) -> KnowledgeEvolutionRuntimeHandoff | None: ...
