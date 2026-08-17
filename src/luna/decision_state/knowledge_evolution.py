"""DecisionState-owned consumption of non-authoritative KE advisories."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.decision import (
    AssumptionRecord,
    AssumptionStatus,
    DecisionStateSnapshot,
    DecisionStatus,
)
from luna.decision_state.service import DecisionStateService
from luna.knowledge_evolution import (
    KnowledgeApplicabilitySignalState,
    KnowledgeReevaluationAdvisory,
    KnowledgeReevaluationAdvisoryKind,
    KnowledgeValiditySignalState,
)


class KnowledgeDecisionStateIntegrationDisposition(StrEnum):
    """Observable DecisionState-owner response to one KE advisory."""

    CONTRADICTION_APPLIED = "CONTRADICTION_APPLIED"
    CONTRADICTION_ALREADY_REFLECTED = (
        "CONTRADICTION_ALREADY_REFLECTED"
    )
    VERIFY_STOP_DEFERRED = "VERIFY_STOP_DEFERRED"
    REEVALUATION_DEFERRED = "REEVALUATION_DEFERRED"


class KnowledgeDecisionStateBinding(LunaContractModel):
    """Explicit caller-owned binding from one knowledge ref to one assumption."""

    task_id: UUID
    knowledge_ref: str = Field(min_length=1, max_length=4000)
    assumption_id: UUID
    provenance_refs: tuple[str, ...] = Field(min_length=1)

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    decision_mutation_authority: Literal[False] = False
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
                "knowledge DecisionState binding ref cannot be blank"
            )

        return cleaned

    @field_validator("provenance_refs")
    @classmethod
    def validate_provenance_refs(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        cleaned = tuple(
            value.strip()
            for value in values
        )

        if any(not value for value in cleaned):
            raise ValueError(
                "knowledge DecisionState binding provenance "
                "cannot be blank"
            )

        if len(cleaned) != len(set(cleaned)):
            raise ValueError(
                "knowledge DecisionState binding provenance "
                "must be unique"
            )

        return tuple(sorted(cleaned))


class KnowledgeDecisionStateIntegrationResult(
    LunaContractModel
):
    """Observable result; authority remains with canonical owners."""

    task_id: UUID
    knowledge_ref: str = Field(min_length=1, max_length=4000)
    assumption_id: UUID

    advisory_kind: KnowledgeReevaluationAdvisoryKind
    disposition: KnowledgeDecisionStateIntegrationDisposition

    input_revision: int = Field(ge=0)
    output_revision: int = Field(ge=0)

    affected_decision_ids: tuple[UUID, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = Field(min_length=1)

    mutation_applied: bool
    verify_stop_candidate: bool
    reevaluation_candidate: bool

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    invalidation_authority: Literal[False] = False
    stop_authority: Literal[False] = False
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
                "knowledge DecisionState result ref cannot be blank"
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
                "knowledge DecisionState result refs cannot be blank"
            )

        if len(cleaned) != len(set(cleaned)):
            raise ValueError(
                "knowledge DecisionState result refs must be unique"
            )

        return tuple(sorted(cleaned))

    @field_validator("affected_decision_ids")
    @classmethod
    def validate_affected_decision_ids(
        cls,
        values: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError(
                "affected DecisionState decisions must be unique"
            )

        return tuple(
            sorted(
                values,
                key=str,
            )
        )

    @model_validator(mode="after")
    def validate_result_consistency(
        self,
    ) -> Self:
        mutation_expected = (
            self.disposition
            is KnowledgeDecisionStateIntegrationDisposition.CONTRADICTION_APPLIED
        )

        if self.mutation_applied is not mutation_expected:
            raise ValueError(
                "DecisionState mutation flag must match disposition"
            )

        if mutation_expected:
            if self.output_revision <= self.input_revision:
                raise ValueError(
                    "DecisionState mutation must advance revision"
                )
        else:
            if self.output_revision != self.input_revision:
                raise ValueError(
                    "non-mutating KE integration cannot advance revision"
                )

            if self.affected_decision_ids:
                raise ValueError(
                    "non-mutating KE integration cannot affect decisions"
                )

        verify_expected = (
            self.disposition
            is KnowledgeDecisionStateIntegrationDisposition.VERIFY_STOP_DEFERRED
        )

        if self.verify_stop_candidate is not verify_expected:
            raise ValueError(
                "VERIFY/STOP candidate flag must match disposition"
            )

        reevaluation_expected = (
            self.disposition
            is KnowledgeDecisionStateIntegrationDisposition.REEVALUATION_DEFERRED
        )

        if self.reevaluation_candidate is not reevaluation_expected:
            raise ValueError(
                "reevaluation candidate flag must match disposition"
            )

        return self


class DecisionStateKnowledgeEvolutionAdapter:
    """Canonical-owner adapter for bounded KE advisory consumption."""

    def __init__(
        self,
        decision_state: DecisionStateService | None = None,
    ) -> None:
        self._decision_state = (
            decision_state
            if decision_state is not None
            else DecisionStateService()
        )

    def _bound_assumption(
        self,
        *,
        snapshot: DecisionStateSnapshot,
        binding: KnowledgeDecisionStateBinding,
    ) -> AssumptionRecord:
        target = next(
            (
                item
                for item in snapshot.assumptions
                if item.assumption_id == binding.assumption_id
            ),
            None,
        )

        if target is None:
            raise ValueError(
                "KE-F4 binding references unknown DecisionState assumption"
            )

        current_ids = {
            item.assumption_id
            for item in self._decision_state.current_assumptions(
                snapshot
            )
        }

        if binding.assumption_id not in current_ids:
            raise ValueError(
                "KE-F4 binding must target current DecisionState assumption"
            )

        return target

    @staticmethod
    def _validate_advisory_semantics(
        advisory: KnowledgeReevaluationAdvisory,
    ) -> None:
        if (
            advisory.kind
            is KnowledgeReevaluationAdvisoryKind.INVALIDATION_CANDIDATE
        ):
            if (
                advisory.validity_state
                is not KnowledgeValiditySignalState.CONTRADICTED
            ):
                raise ValueError(
                    "KE-F4 invalidation candidate requires "
                    "CONTRADICTED external validity"
                )

            if not advisory.evidence_refs:
                raise ValueError(
                    "KE-F4 invalidation candidate requires "
                    "external evidence"
                )

            return

        if (
            advisory.kind
            is KnowledgeReevaluationAdvisoryKind.VERIFY_STOP_CANDIDATE
        ):
            unresolved = (
                advisory.validity_state
                is KnowledgeValiditySignalState.UNRESOLVED
                or advisory.applicability_state
                is KnowledgeApplicabilitySignalState.UNRESOLVED
            )

            if not unresolved:
                raise ValueError(
                    "KE-F4 VERIFY/STOP candidate requires "
                    "an unresolved external signal"
                )

            return

        if (
            advisory.kind
            is KnowledgeReevaluationAdvisoryKind.REEVALUATION_CANDIDATE
        ):
            valid_reevaluation = (
                advisory.validity_state
                is KnowledgeValiditySignalState.SUPPORTED
                and advisory.applicability_state
                is KnowledgeApplicabilitySignalState.APPLICABLE
                and advisory.material_option_space_change
            )

            if not valid_reevaluation:
                raise ValueError(
                    "KE-F4 reevaluation candidate requires "
                    "SUPPORTED + APPLICABLE + material change"
                )

            if not advisory.evidence_refs:
                raise ValueError(
                    "KE-F4 reevaluation candidate requires "
                    "external evidence"
                )

            return

        raise ValueError(
            "unsupported KE-F4 advisory kind"
        )

    def integrate(
        self,
        *,
        snapshot: DecisionStateSnapshot,
        advisory: KnowledgeReevaluationAdvisory,
        binding: KnowledgeDecisionStateBinding,
    ) -> tuple[
        KnowledgeDecisionStateIntegrationResult,
        DecisionStateSnapshot,
    ]:
        if binding.task_id != snapshot.task_id:
            raise ValueError(
                "KE-F4 binding task does not match DecisionState task"
            )

        if binding.knowledge_ref != advisory.knowledge_ref:
            raise ValueError(
                "KE-F4 binding knowledge ref does not match advisory"
            )

        target = self._bound_assumption(
            snapshot=snapshot,
            binding=binding,
        )

        self._validate_advisory_semantics(
            advisory
        )

        basis_provenance = tuple(
            sorted(
                {
                    *advisory.provenance_refs,
                    *binding.provenance_refs,
                }
            )
        )

        if (
            advisory.kind
            is KnowledgeReevaluationAdvisoryKind.INVALIDATION_CANDIDATE
        ):
            if target.status in {
                AssumptionStatus.INVALIDATED,
                AssumptionStatus.SUPERSEDED,
            }:
                raise ValueError(
                    "KE-F4 invalidation binding targets "
                    "non-actionable historical assumption"
                )

            combined_evidence = tuple(
                sorted(
                    {
                        *target.evidence_refs,
                        *advisory.evidence_refs,
                    }
                )
            )
            combined_provenance = tuple(
                sorted(
                    {
                        *target.provenance_refs,
                        *basis_provenance,
                    }
                )
            )

            if target.status is AssumptionStatus.CONTRADICTED:
                result = KnowledgeDecisionStateIntegrationResult(
                    task_id=snapshot.task_id,
                    knowledge_ref=advisory.knowledge_ref,
                    assumption_id=binding.assumption_id,
                    advisory_kind=advisory.kind,
                    disposition=(
                        KnowledgeDecisionStateIntegrationDisposition
                        .CONTRADICTION_ALREADY_REFLECTED
                    ),
                    input_revision=snapshot.revision,
                    output_revision=snapshot.revision,
                    affected_decision_ids=(),
                    evidence_refs=combined_evidence,
                    provenance_refs=combined_provenance,
                    mutation_applied=False,
                    verify_stop_candidate=False,
                    reevaluation_candidate=False,
                )

                return result, snapshot

            previous_statuses = {
                item.decision_id: item.status
                for item in snapshot.decisions
            }

            revised = self._decision_state.transition_assumption(
                snapshot,
                assumption_id=binding.assumption_id,
                status=AssumptionStatus.CONTRADICTED,
                evidence_refs=combined_evidence,
                provenance_refs=combined_provenance,
                reason=(
                    "external KE validity contradiction accepted "
                    "by DecisionState owner for "
                    f"{advisory.knowledge_ref}"
                ),
            )

            affected_decision_ids = tuple(
                sorted(
                    (
                        item.decision_id
                        for item in revised.decisions
                        if (
                            item.status
                            is DecisionStatus.INVALIDATED
                            and previous_statuses.get(
                                item.decision_id
                            )
                            is not DecisionStatus.INVALIDATED
                        )
                    ),
                    key=str,
                )
            )

            result = KnowledgeDecisionStateIntegrationResult(
                task_id=snapshot.task_id,
                knowledge_ref=advisory.knowledge_ref,
                assumption_id=binding.assumption_id,
                advisory_kind=advisory.kind,
                disposition=(
                    KnowledgeDecisionStateIntegrationDisposition
                    .CONTRADICTION_APPLIED
                ),
                input_revision=snapshot.revision,
                output_revision=revised.revision,
                affected_decision_ids=affected_decision_ids,
                evidence_refs=combined_evidence,
                provenance_refs=combined_provenance,
                mutation_applied=True,
                verify_stop_candidate=False,
                reevaluation_candidate=False,
            )

            return result, revised

        if (
            advisory.kind
            is KnowledgeReevaluationAdvisoryKind.VERIFY_STOP_CANDIDATE
        ):
            result = KnowledgeDecisionStateIntegrationResult(
                task_id=snapshot.task_id,
                knowledge_ref=advisory.knowledge_ref,
                assumption_id=binding.assumption_id,
                advisory_kind=advisory.kind,
                disposition=(
                    KnowledgeDecisionStateIntegrationDisposition
                    .VERIFY_STOP_DEFERRED
                ),
                input_revision=snapshot.revision,
                output_revision=snapshot.revision,
                affected_decision_ids=(),
                evidence_refs=advisory.evidence_refs,
                provenance_refs=basis_provenance,
                mutation_applied=False,
                verify_stop_candidate=True,
                reevaluation_candidate=False,
            )

            return result, snapshot

        result = KnowledgeDecisionStateIntegrationResult(
            task_id=snapshot.task_id,
            knowledge_ref=advisory.knowledge_ref,
            assumption_id=binding.assumption_id,
            advisory_kind=advisory.kind,
            disposition=(
                KnowledgeDecisionStateIntegrationDisposition
                .REEVALUATION_DEFERRED
            ),
            input_revision=snapshot.revision,
            output_revision=snapshot.revision,
            affected_decision_ids=(),
            evidence_refs=advisory.evidence_refs,
            provenance_refs=basis_provenance,
            mutation_applied=False,
            verify_stop_candidate=False,
            reevaluation_candidate=True,
        )

        return result, snapshot
