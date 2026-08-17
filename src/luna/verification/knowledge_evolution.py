"""Verification-owner projection into bounded Knowledge Evolution signals.

This module does not verify knowledge itself. It consumes already-authoritative
Verification ClaimAssessment output through explicit knowledge/claim bindings.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.knowledge_evolution import (
    KnowledgeApplicabilitySignal,
    KnowledgeApplicabilitySignalState,
    KnowledgeValiditySignal,
    KnowledgeValiditySignalState,
)
from luna.verification.models import (
    ClaimAssessment,
    ClaimStatus,
    VerificationReport,
)


class KnowledgeVerificationClaimRole(StrEnum):
    """Explicit semantic role assigned to one verifier claim binding."""

    VALIDITY = "VALIDITY"
    APPLICABILITY_CONDITION = "APPLICABILITY_CONDITION"


class KnowledgeVerificationClaimBinding(LunaContractModel):
    """Bind one knowledge item to one already-defined verification claim."""

    task_id: UUID
    knowledge_ref: str = Field(
        min_length=1,
        max_length=1000,
    )
    claim_id: str = Field(
        pattern=r"^(required|forbidden_absent):sha256:[0-9a-f]{64}$"
    )
    role: KnowledgeVerificationClaimRole
    condition_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=1000,
    )
    provenance_refs: tuple[str, ...] = Field(
        min_length=1
    )

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    decision_mutation_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False

    @field_validator(
        "knowledge_ref",
        "condition_ref",
    )
    @classmethod
    def validate_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "knowledge verification binding text "
                "cannot be blank"
            )

        return cleaned

    @field_validator("provenance_refs")
    @classmethod
    def validate_provenance(
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
                "knowledge verification provenance "
                "cannot be blank"
            )

        if len(cleaned) != len(set(cleaned)):
            raise ValueError(
                "knowledge verification provenance "
                "must be unique"
            )

        return tuple(sorted(cleaned))

    @model_validator(mode="after")
    def validate_role_binding(
        self,
    ) -> KnowledgeVerificationClaimBinding:
        if (
            self.role
            is KnowledgeVerificationClaimRole.VALIDITY
            and self.condition_ref is not None
        ):
            raise ValueError(
                "validity claim binding cannot carry "
                "an applicability condition"
            )

        if (
            self.role
            is KnowledgeVerificationClaimRole.APPLICABILITY_CONDITION
            and self.condition_ref is None
        ):
            raise ValueError(
                "applicability claim binding requires "
                "an explicit condition ref"
            )

        return self


class VerificationKnowledgeEvolutionAdapter:
    """Project existing verifier decisions without gaining verification authority."""

    @staticmethod
    def _assessment_map(
        report: VerificationReport,
    ) -> dict[str, ClaimAssessment]:
        result = {
            item.claim.claim_id: item
            for item in report.claim_assessments
        }

        if len(result) != len(
            report.claim_assessments
        ):
            raise ValueError(
                "verification report contains duplicate claim IDs"
            )

        return result

    @staticmethod
    def _evidence_refs(
        assessments: tuple[
            ClaimAssessment,
            ...,
        ],
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    f"evidence:{evidence_id}"
                    for assessment in assessments
                    for evidence_id in (
                        assessment.qualifying_evidence_ids
                    )
                }
            )
        )

    @staticmethod
    def _validity_state(
        assessments: tuple[
            ClaimAssessment,
            ...,
        ],
    ) -> KnowledgeValiditySignalState:
        statuses = tuple(
            item.status
            for item in assessments
        )

        if ClaimStatus.FAIL in statuses:
            return (
                KnowledgeValiditySignalState.CONTRADICTED
            )

        if statuses and all(
            status is ClaimStatus.PASS
            for status in statuses
        ):
            return (
                KnowledgeValiditySignalState.SUPPORTED
            )

        return KnowledgeValiditySignalState.UNRESOLVED

    @staticmethod
    def _applicability_state(
        assessments: tuple[
            ClaimAssessment,
            ...,
        ],
    ) -> KnowledgeApplicabilitySignalState:
        statuses = tuple(
            item.status
            for item in assessments
        )

        if ClaimStatus.FAIL in statuses:
            return (
                KnowledgeApplicabilitySignalState.INAPPLICABLE
            )

        if statuses and all(
            status is ClaimStatus.PASS
            for status in statuses
        ):
            return (
                KnowledgeApplicabilitySignalState.APPLICABLE
            )

        return (
            KnowledgeApplicabilitySignalState.UNRESOLVED
        )

    def project(
        self,
        *,
        report: VerificationReport,
        bindings: tuple[
            KnowledgeVerificationClaimBinding,
            ...,
        ],
    ) -> tuple[
        KnowledgeValiditySignal,
        KnowledgeApplicabilitySignal,
    ]:
        """Project one knowledge item's explicitly bound verifier claims."""

        if not bindings:
            raise ValueError(
                "verification KE projection requires "
                "explicit claim bindings"
            )

        task_ids = {
            item.task_id
            for item in bindings
        }
        knowledge_refs = {
            item.knowledge_ref
            for item in bindings
        }

        if len(task_ids) != 1:
            raise ValueError(
                "verification KE bindings must share "
                "one task"
            )

        if len(knowledge_refs) != 1:
            raise ValueError(
                "verification KE bindings must share "
                "one knowledge ref"
            )

        if next(iter(task_ids)) != report.task_id:
            raise ValueError(
                "verification KE binding task does not "
                "match verification report"
            )

        assessment_by_id = self._assessment_map(
            report
        )

        binding_keys = tuple(
            (
                item.role,
                item.claim_id,
                item.condition_ref,
            )
            for item in bindings
        )

        if len(binding_keys) != len(
            set(binding_keys)
        ):
            raise ValueError(
                "verification KE bindings must be unique"
            )

        missing = tuple(
            sorted(
                {
                    item.claim_id
                    for item in bindings
                    if item.claim_id
                    not in assessment_by_id
                }
            )
        )

        if missing:
            raise ValueError(
                "verification KE binding references "
                "claim absent from report"
            )

        validity_bindings = tuple(
            item
            for item in bindings
            if item.role
            is KnowledgeVerificationClaimRole.VALIDITY
        )
        applicability_bindings = tuple(
            item
            for item in bindings
            if item.role
            is KnowledgeVerificationClaimRole.APPLICABILITY_CONDITION
        )

        if not validity_bindings:
            raise ValueError(
                "verification KE projection requires "
                "at least one validity claim"
            )

        if not applicability_bindings:
            raise ValueError(
                "verification KE projection requires "
                "at least one applicability condition"
            )

        condition_refs = tuple(
            sorted(
                {
                    item.condition_ref
                    for item in applicability_bindings
                    if item.condition_ref is not None
                }
            )
        )

        if len(condition_refs) != len(
            applicability_bindings
        ):
            raise ValueError(
                "applicability conditions must have "
                "unique explicit refs"
            )

        validity_assessments = tuple(
            assessment_by_id[
                item.claim_id
            ]
            for item in validity_bindings
        )
        applicability_assessments = tuple(
            assessment_by_id[
                item.claim_id
            ]
            for item in applicability_bindings
        )

        provenance_refs = tuple(
            sorted(
                {
                    *(
                        ref
                        for item in bindings
                        for ref in item.provenance_refs
                    ),
                    *(
                        "verification:claim:"
                        + item.claim_id
                        for item in bindings
                    ),
                    (
                        "verification:report:"
                        + str(report.report_id)
                    ),
                }
            )
        )

        source_ref = (
            "verification:report:"
            + str(report.report_id)
        )
        knowledge_ref = next(
            iter(knowledge_refs)
        )

        validity = KnowledgeValiditySignal(
            knowledge_ref=knowledge_ref,
            state=self._validity_state(
                validity_assessments
            ),
            source_ref=source_ref,
            evidence_refs=self._evidence_refs(
                validity_assessments
            ),
            provenance_refs=provenance_refs,
        )

        applicability = KnowledgeApplicabilitySignal(
            knowledge_ref=knowledge_ref,
            state=self._applicability_state(
                applicability_assessments
            ),
            source_ref=source_ref,
            condition_refs=condition_refs,
            evidence_refs=self._evidence_refs(
                applicability_assessments
            ),
            provenance_refs=provenance_refs,
        )

        return validity, applicability
