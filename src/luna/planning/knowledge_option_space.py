"""Planning-owner projection of knowledge-bound option-space change.

This module observes explicit C3 causal attribution plus previous/current
decision-route sets. It does not rank routes, verify truth, mutate canonical
state, or execute runtime actions.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.invalidation import (
    CrossLayerInvalidationReport,
    InvalidationImpact,
    InvalidationLayer,
)
from luna.knowledge_evolution import KnowledgeOptionSpaceChangeSignal
from luna.planning.control import (
    DecisionAlternative,
    DecisionAlternativeSet,
)


class KnowledgeOptionSpaceAttributionBinding(LunaContractModel):
    """Explicit evidence-bound attribution from knowledge to one C3 trigger."""

    task_id: UUID
    knowledge_ref: str = Field(
        min_length=1,
        max_length=4000,
    )
    trigger_ref: str = Field(
        min_length=1,
        max_length=1000,
    )
    evidence_refs: tuple[str, ...] = Field(
        min_length=1,
    )
    provenance_refs: tuple[str, ...] = Field(
        min_length=1,
    )

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    decision_control_authority: Literal[False] = False
    decision_mutation_authority: Literal[False] = False
    memory_mutation_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False

    @field_validator(
        "knowledge_ref",
        "trigger_ref",
    )
    @classmethod
    def validate_text_ref(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "knowledge option-space attribution "
                "refs cannot be blank"
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

        if any(
            not value
            for value in cleaned
        ):
            raise ValueError(
                "knowledge option-space attribution "
                "evidence/provenance cannot be blank"
            )

        if len(cleaned) != len(
            set(cleaned)
        ):
            raise ValueError(
                "knowledge option-space attribution "
                "evidence/provenance must be unique"
            )

        return tuple(
            sorted(cleaned)
        )


class KnowledgeOptionSpaceProjector:
    """Project material route-space change without relative-fitness authority."""

    @staticmethod
    def _reachable_impacts(
        *,
        report: CrossLayerInvalidationReport,
        trigger_ref: str,
    ) -> tuple[
        InvalidationImpact,
        ...,
    ]:
        reachable_refs = {
            trigger_ref,
        }

        pending = list(
            report.impacts
        )

        selected: list[
            InvalidationImpact
        ] = []

        while pending:
            progressed = False

            remaining: list[
                InvalidationImpact
            ] = []

            for impact in pending:
                if (
                    set(
                        impact.cause_refs
                    )
                    & reachable_refs
                ):
                    selected.append(
                        impact
                    )
                    reachable_refs.add(
                        impact.target_ref
                    )
                    progressed = True
                else:
                    remaining.append(
                        impact
                    )

            if not progressed:
                break

            pending = remaining

        return tuple(
            selected
        )

    @staticmethod
    def _route_map(
        alternative_set: DecisionAlternativeSet,
    ) -> dict[
        str,
        bool,
    ]:
        result: dict[
            str,
            bool,
        ] = {}

        for item in alternative_set.alternatives:
            validated_item = DecisionAlternative.model_validate(
                item.model_dump(
                    mode="python"
                )
            )

            # action_key is the semantic route identity.
            # decision_ref embeds DecisionStatus and would create
            # false route add/remove deltas on status transitions.
            if validated_item.action_key in result:
                raise ValueError(
                    "O2 option-space projection requires "
                    "unique action-key route identity"
                )

            result[
                validated_item.action_key
            ] = validated_item.admissible

        return result

    def project(
        self,
        *,
        binding: KnowledgeOptionSpaceAttributionBinding,
        report: CrossLayerInvalidationReport,
        previous: DecisionAlternativeSet,
        current: DecisionAlternativeSet,
    ) -> KnowledgeOptionSpaceChangeSignal:
        """Project only causal, evidence-bound observable option-space change."""

        validated_binding = (
            KnowledgeOptionSpaceAttributionBinding.model_validate(
                binding.model_dump(
                    mode="python"
                )
            )
        )

        validated_report = (
            CrossLayerInvalidationReport.model_validate(
                report.model_dump(
                    mode="python"
                )
            )
        )

        if (
            validated_report.task_id
            != validated_binding.task_id
        ):
            raise ValueError(
                "O2 attribution task does not match "
                "C3 report"
            )

        if (
            previous.task_id
            != validated_binding.task_id
            or current.task_id
            != validated_binding.task_id
        ):
            raise ValueError(
                "O2 alternative sets must match "
                "the bound task"
            )

        if (
            previous.step_id
            != current.step_id
        ):
            raise ValueError(
                "O2 alternative sets must describe "
                "the same planning step"
            )

        if (
            current.source_task_state_revision
            < previous.source_task_state_revision
        ):
            raise ValueError(
                "O2 current route set cannot precede "
                "the previous task revision"
            )

        if (
            current.source_decision_state_revision
            < previous.source_decision_state_revision
        ):
            raise ValueError(
                "O2 current route set cannot precede "
                "the previous DecisionState revision"
            )

        if (
            validated_binding.trigger_ref
            not in validated_report.trigger_refs
        ):
            raise ValueError(
                "O2 knowledge attribution trigger "
                "is absent from C3 report"
            )

        reachable = self._reachable_impacts(
            report=validated_report,
            trigger_ref=validated_binding.trigger_ref,
        )

        option_impacts = tuple(
            impact
            for impact in reachable
            if impact.layer
            is InvalidationLayer.DECISION_ALTERNATIVES
        )

        previous_routes = self._route_map(
            previous
        )
        current_routes = self._route_map(
            current
        )

        route_identity_changed = (
            set(previous_routes)
            != set(current_routes)
        )

        shared_routes = (
            set(previous_routes)
            & set(current_routes)
        )

        admissibility_changed = any(
            previous_routes[
                action_key
            ]
            is not current_routes[
                action_key
            ]
            for action_key in shared_routes
        )

        observable_delta = (
            route_identity_changed
            or admissibility_changed
        )

        causal_impact = bool(
            option_impacts
        )

        material_change = (
            causal_impact
            and observable_delta
        )

        causal_changed_basis_evidence = tuple(
            sorted(
                {
                    ref
                    for impact in option_impacts
                    for ref in (
                        impact.changed_basis_evidence_refs
                    )
                }
            )
        )

        if (
            material_change
            and not causal_changed_basis_evidence
        ):
            raise ValueError(
                "material O2 option-space change "
                "requires causal changed-basis evidence"
            )

        material_evidence = tuple(
            sorted(
                {
                    *validated_binding.evidence_refs,
                    *causal_changed_basis_evidence,
                }
            )
        )

        provenance_refs = tuple(
            sorted(
                {
                    *validated_binding.provenance_refs,
                    *validated_report.provenance_refs,
                    (
                        "c3:report:"
                        + str(
                            validated_report.report_id
                        )
                    ),
                    (
                        "planning:previous-basis:"
                        + previous.decision_basis_fingerprint
                    ),
                    (
                        "planning:current-basis:"
                        + current.decision_basis_fingerprint
                    ),
                }
            )
        )

        return KnowledgeOptionSpaceChangeSignal(
            knowledge_ref=validated_binding.knowledge_ref,
            material_change=material_change,
            source_ref=(
                "planning:c3-option-space:"
                + str(
                    validated_report.report_id
                )
            ),
            evidence_refs=(
                material_evidence
                if material_change
                else ()
            ),
            provenance_refs=provenance_refs,
        )
