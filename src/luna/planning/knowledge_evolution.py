"""Planning-side information-gain refresh from DecisionState-owned KE output."""

from __future__ import annotations

from hashlib import sha256
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.state import TaskState
from luna.decision_state import (
    KnowledgeDecisionStateIntegrationDisposition,
    KnowledgeDecisionStateIntegrationResult,
)
from luna.planning.judgment import (
    InformationGainPlan,
    InformationNeed,
    InformationNeedKind,
)


class KnowledgeInformationGainRefresh(LunaContractModel):
    """Evidence-bound F2 refresh without decision-control or execution authority."""

    task_id: UUID
    step_id: UUID
    knowledge_ref: str = Field(min_length=1, max_length=4000)

    source_disposition: KnowledgeDecisionStateIntegrationDisposition
    source_decision_state_revision: int = Field(ge=0)

    refreshed_plan: InformationGainPlan

    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = Field(min_length=1)

    information_need_present: bool
    plan_changed: bool
    selected_need_changed: bool

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    planning_authority: Literal[False] = False
    decision_control_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    decision_mutation_authority: Literal[False] = False
    memory_mutation_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False

    @field_validator("knowledge_ref")
    @classmethod
    def validate_knowledge_ref(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "F2 refresh knowledge ref cannot be blank"
            )

        return cleaned

    @field_validator(
        "evidence_refs",
        "provenance_refs",
    )
    @classmethod
    def validate_refs(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        cleaned = tuple(
            value.strip()
            for value in values
        )

        if any(not value for value in cleaned):
            raise ValueError(
                "F2 refresh references cannot be blank"
            )

        if len(cleaned) != len(set(cleaned)):
            raise ValueError(
                "F2 refresh references must be unique"
            )

        return tuple(sorted(cleaned))

    @model_validator(mode="after")
    def validate_refresh_consistency(
        self,
    ) -> Self:
        if self.refreshed_plan.task_id != self.task_id:
            raise ValueError(
                "F2 refresh plan task mismatch"
            )

        if self.refreshed_plan.step_id != self.step_id:
            raise ValueError(
                "F2 refresh plan step mismatch"
            )

        deferred = self.source_disposition in {
            KnowledgeDecisionStateIntegrationDisposition
            .VERIFY_STOP_DEFERRED,
            KnowledgeDecisionStateIntegrationDisposition
            .REEVALUATION_DEFERRED,
        }

        if self.information_need_present is not deferred:
            raise ValueError(
                "F2 refresh information-need presence "
                "must match deferred disposition"
            )

        if (
            not deferred
            and (
                self.plan_changed
                or self.selected_need_changed
            )
        ):
            raise ValueError(
                "non-deferred F4 result cannot alter "
                "information-gain planning"
            )

        return self


class KnowledgeInformationGainRefresher:
    """Refresh F2 priority from observable DecisionState-owner output only."""

    _VERIFY_PRIORITY = 100
    _REEVALUATION_PRIORITY = 95

    @staticmethod
    def _stable_need_id(
        *,
        kind: InformationNeedKind,
        description: str,
    ) -> str:
        digest = sha256(
            f"{kind.value}\0{description}".encode()
        ).hexdigest()

        return f"information:sha256:{digest}"

    @staticmethod
    def _selected_need(
        plan: InformationGainPlan,
    ) -> InformationNeed:
        return next(
            item
            for item in plan.needs
            if item.need_id == plan.selected_need_id
        )

    @staticmethod
    def _validate_owner_output(
        integration: KnowledgeDecisionStateIntegrationResult,
    ) -> None:
        expected_kind = {
            KnowledgeDecisionStateIntegrationDisposition
            .CONTRADICTION_APPLIED: "INVALIDATION_CANDIDATE",
            KnowledgeDecisionStateIntegrationDisposition
            .CONTRADICTION_ALREADY_REFLECTED: (
                "INVALIDATION_CANDIDATE"
            ),
            KnowledgeDecisionStateIntegrationDisposition
            .VERIFY_STOP_DEFERRED: "VERIFY_STOP_CANDIDATE",
            KnowledgeDecisionStateIntegrationDisposition
            .REEVALUATION_DEFERRED: "REEVALUATION_CANDIDATE",
        }[integration.disposition]

        if integration.advisory_kind.value != expected_kind:
            raise ValueError(
                "F2 refresh DecisionState-owner output "
                "has inconsistent advisory kind"
            )

    def refresh(
        self,
        *,
        state: TaskState,
        plan: InformationGainPlan,
        integration: KnowledgeDecisionStateIntegrationResult,
    ) -> KnowledgeInformationGainRefresh:
        if plan.task_id != state.task_id:
            raise ValueError(
                "F2 refresh information-gain task mismatch"
            )

        if integration.task_id != state.task_id:
            raise ValueError(
                "F2 refresh owner-output task mismatch"
            )

        if not any(
            step.step_id == plan.step_id
            for step in state.plan
        ):
            raise ValueError(
                "F2 refresh information-gain step "
                "must belong to authoritative task plan"
            )

        snapshot = state.decision_state

        if snapshot is None:
            raise ValueError(
                "F2 refresh requires current DecisionState"
            )

        if (
            integration.output_revision
            != snapshot.revision
        ):
            raise ValueError(
                "stale KE-F4 integration result "
                "cannot refresh information gain"
            )

        self._validate_owner_output(
            integration
        )

        deferred = integration.disposition in {
            KnowledgeDecisionStateIntegrationDisposition
            .VERIFY_STOP_DEFERRED,
            KnowledgeDecisionStateIntegrationDisposition
            .REEVALUATION_DEFERRED,
        }

        if not deferred:
            return KnowledgeInformationGainRefresh(
                task_id=state.task_id,
                step_id=plan.step_id,
                knowledge_ref=integration.knowledge_ref,
                source_disposition=integration.disposition,
                source_decision_state_revision=(
                    integration.output_revision
                ),
                refreshed_plan=plan,
                evidence_refs=integration.evidence_refs,
                provenance_refs=integration.provenance_refs,
                information_need_present=False,
                plan_changed=False,
                selected_need_changed=False,
            )

        target_ids = tuple(
            sorted(
                {
                    target_id
                    for need in plan.needs
                    for target_id in need.acceptance_target_ids
                }
            )
        )

        if not target_ids:
            raise ValueError(
                "F2 refresh requires acceptance-bound "
                "information needs"
            )

        if (
            integration.disposition
            is KnowledgeDecisionStateIntegrationDisposition
            .VERIFY_STOP_DEFERRED
        ):
            kind = InformationNeedKind.RESOLVE_UNCERTAINTY
            priority = self._VERIFY_PRIORITY
            description = (
                "Resolve owner-validated knowledge uncertainty "
                "before relying on "
                f"{integration.knowledge_ref}."
            )
            reason = (
                "ke_verify_stop_candidate_prioritized"
            )
        else:
            kind = InformationNeedKind.OBSERVE_STATE
            priority = self._REEVALUATION_PRIORITY
            description = (
                "Observe the material option-space change for "
                f"{integration.knowledge_ref} "
                "before reusing the current decision basis."
            )
            reason = (
                "ke_reevaluation_candidate_prioritized"
            )

        need = InformationNeed(
            need_id=self._stable_need_id(
                kind=kind,
                description=description,
            ),
            kind=kind,
            description=description,
            acceptance_target_ids=target_ids,
            priority=priority,
        )

        by_id = {
            item.need_id: item
            for item in plan.needs
        }

        existing = by_id.get(
            need.need_id
        )

        if (
            existing is not None
            and existing != need
        ):
            raise ValueError(
                "F2 refresh information-need ID collision"
            )

        needs = (
            (*plan.needs, need)
            if existing is None
            else plan.needs
        )

        ordered = tuple(
            sorted(
                needs,
                key=lambda item: (
                    -item.priority,
                    item.need_id,
                ),
            )
        )

        current_selected = self._selected_need(
            plan
        )

        if need.priority > current_selected.priority:
            selected_need_id = need.need_id
        else:
            selected_need_id = plan.selected_need_id

        refreshed = InformationGainPlan(
            task_id=plan.task_id,
            step_id=plan.step_id,
            needs=ordered,
            selected_need_id=selected_need_id,
            reason_codes=tuple(
                dict.fromkeys(
                    (
                        *plan.reason_codes,
                        "ke_owner_validated_signal_consumed",
                        reason,
                    )
                )
            ),
        )

        return KnowledgeInformationGainRefresh(
            task_id=state.task_id,
            step_id=plan.step_id,
            knowledge_ref=integration.knowledge_ref,
            source_disposition=integration.disposition,
            source_decision_state_revision=(
                integration.output_revision
            ),
            refreshed_plan=refreshed,
            evidence_refs=integration.evidence_refs,
            provenance_refs=integration.provenance_refs,
            information_need_present=True,
            plan_changed=refreshed != plan,
            selected_need_changed=(
                refreshed.selected_need_id
                != plan.selected_need_id
            ),
        )
