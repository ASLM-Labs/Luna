"""Evidence-bound knowledge-evolution relation contracts.

Knowledge evolution records relationships between externally owned knowledge
references. It does not own canonical truth, verification, ranking, execution,
or runtime authority.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now


class KnowledgeEvolutionRelationKind(StrEnum):
    """Allowed semantic relations between externally owned knowledge refs."""

    ALTERNATIVE_TO = "ALTERNATIVE_TO"
    EXTENDS = "EXTENDS"
    COEXISTS_WITH = "COEXISTS_WITH"
    REPLACES_UNDER = "REPLACES_UNDER"
    INCOMPATIBLE_WITH = "INCOMPATIBLE_WITH"
    DERIVED_FROM = "DERIVED_FROM"


_SYMMETRIC_RELATION_KINDS = frozenset(
    {
        KnowledgeEvolutionRelationKind.ALTERNATIVE_TO,
        KnowledgeEvolutionRelationKind.COEXISTS_WITH,
        KnowledgeEvolutionRelationKind.INCOMPATIBLE_WITH,
    }
)


class KnowledgeEvolutionRelation(LunaContractModel):
    """One evidence-bound semantic relation without independent truth authority."""

    source_ref: str = Field(min_length=1, max_length=4000)
    target_ref: str = Field(min_length=1, max_length=4000)
    relation_kind: KnowledgeEvolutionRelationKind

    applicability_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    provenance_refs: tuple[str, ...] = Field(min_length=1)

    observed_at: datetime = Field(default_factory=utc_now)

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False

    @field_validator("source_ref", "target_ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("knowledge-evolution refs cannot be blank")
        return cleaned

    @field_validator(
        "applicability_refs",
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
                "knowledge-evolution relation refs cannot be blank"
            )

        if len(cleaned) != len(set(cleaned)):
            raise ValueError(
                "knowledge-evolution relation refs must be unique"
            )

        return tuple(sorted(cleaned))

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(
        cls,
        value: datetime,
    ) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_relation(
        self,
    ) -> Self:
        if self.source_ref == self.target_ref:
            raise ValueError(
                "knowledge-evolution relation cannot self-reference"
            )

        if (
            self.relation_kind
            is KnowledgeEvolutionRelationKind.REPLACES_UNDER
            and not self.applicability_refs
        ):
            raise ValueError(
                "REPLACES_UNDER requires explicit applicability refs"
            )

        return self

    def semantic_identity(
        self,
    ) -> tuple[
        str,
        str,
        KnowledgeEvolutionRelationKind,
        tuple[str, ...],
    ]:
        """Return identity without treating evidence/provenance as relation ownership."""

        source = self.source_ref
        target = self.target_ref

        if self.relation_kind in _SYMMETRIC_RELATION_KINDS:
            source, target = sorted(
                (source, target)
            )

        return (
            source,
            target,
            self.relation_kind,
            self.applicability_refs,
        )


class KnowledgeEvolutionProjection(LunaContractModel):
    """Derived non-authoritative relation projection for one task-state revision."""

    task_id: UUID
    source_task_state_revision: int = Field(ge=0)

    relations: tuple[
        KnowledgeEvolutionRelation,
        ...
    ] = ()

    captured_at: datetime = Field(
        default_factory=utc_now
    )

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(
        cls,
        value: datetime,
    ) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_relation_uniqueness(
        self,
    ) -> Self:
        identities = tuple(
            relation.semantic_identity()
            for relation in self.relations
        )

        if len(identities) != len(
            set(identities)
        ):
            raise ValueError(
                "knowledge-evolution projection "
                "cannot contain duplicate semantic relations"
            )

        return self



class KnowledgeValiditySignalState(StrEnum):
    """Normalized external validity input; KE does not originate this judgment."""

    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNRESOLVED = "UNRESOLVED"


class KnowledgeApplicabilitySignalState(StrEnum):
    """Normalized external applicability input without selection authority."""

    APPLICABLE = "APPLICABLE"
    INAPPLICABLE = "INAPPLICABLE"
    UNRESOLVED = "UNRESOLVED"


class KnowledgeValiditySignal(LunaContractModel):
    """Externally supplied evidence-bound validity state for one knowledge ref."""

    knowledge_ref: str = Field(min_length=1, max_length=4000)
    state: KnowledgeValiditySignalState
    source_ref: str = Field(min_length=1, max_length=4000)

    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = Field(min_length=1)

    observed_at: datetime = Field(default_factory=utc_now)

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False

    @field_validator("knowledge_ref", "source_ref")
    @classmethod
    def validate_text_ref(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "knowledge validity refs cannot be blank"
            )

        return cleaned

    @field_validator(
        "evidence_refs",
        "provenance_refs",
    )
    @classmethod
    def validate_signal_refs(
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
                "knowledge validity signal refs cannot be blank"
            )

        if len(cleaned) != len(set(cleaned)):
            raise ValueError(
                "knowledge validity signal refs must be unique"
            )

        return tuple(sorted(cleaned))

    @field_validator("observed_at")
    @classmethod
    def validate_signal_time(
        cls,
        value: datetime,
    ) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_evidence_requirement(
        self,
    ) -> Self:
        if (
            self.state
            in {
                KnowledgeValiditySignalState.SUPPORTED,
                KnowledgeValiditySignalState.CONTRADICTED,
            }
            and not self.evidence_refs
        ):
            raise ValueError(
                "supported/contradicted validity "
                "requires external evidence refs"
            )

        return self


class KnowledgeApplicabilitySignal(LunaContractModel):
    """Externally supplied applicability state under explicit conditions."""

    knowledge_ref: str = Field(min_length=1, max_length=4000)
    state: KnowledgeApplicabilitySignalState
    source_ref: str = Field(min_length=1, max_length=4000)

    condition_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = Field(min_length=1)

    observed_at: datetime = Field(default_factory=utc_now)

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False

    @field_validator("knowledge_ref", "source_ref")
    @classmethod
    def validate_text_ref(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "knowledge applicability refs cannot be blank"
            )

        return cleaned

    @field_validator(
        "condition_refs",
        "evidence_refs",
        "provenance_refs",
    )
    @classmethod
    def validate_signal_refs(
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
                "knowledge applicability signal refs cannot be blank"
            )

        if len(cleaned) != len(set(cleaned)):
            raise ValueError(
                "knowledge applicability signal refs must be unique"
            )

        return tuple(sorted(cleaned))

    @field_validator("observed_at")
    @classmethod
    def validate_signal_time(
        cls,
        value: datetime,
    ) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_evidence_requirement(
        self,
    ) -> Self:
        if (
            self.state
            in {
                KnowledgeApplicabilitySignalState.APPLICABLE,
                KnowledgeApplicabilitySignalState.INAPPLICABLE,
            }
            and not self.evidence_refs
        ):
            raise ValueError(
                "applicable/inapplicable state "
                "requires external evidence refs"
            )

        return self



class KnowledgeReevaluationAdvisoryKind(StrEnum):
    """Candidate-only KE advisory without mutation or selection authority."""

    INVALIDATION_CANDIDATE = "INVALIDATION_CANDIDATE"
    VERIFY_STOP_CANDIDATE = "VERIFY_STOP_CANDIDATE"
    REEVALUATION_CANDIDATE = "REEVALUATION_CANDIDATE"


class KnowledgeOptionSpaceChangeSignal(LunaContractModel):
    """External material option-space change input; KE does not infer it."""

    knowledge_ref: str = Field(min_length=1, max_length=4000)
    material_change: bool
    source_ref: str = Field(min_length=1, max_length=4000)

    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = Field(min_length=1)

    observed_at: datetime = Field(default_factory=utc_now)

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False

    @field_validator("knowledge_ref", "source_ref")
    @classmethod
    def validate_text_ref(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "knowledge option-space refs cannot be blank"
            )

        return cleaned

    @field_validator(
        "evidence_refs",
        "provenance_refs",
    )
    @classmethod
    def validate_signal_refs(
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
                "knowledge option-space refs cannot be blank"
            )

        if len(cleaned) != len(set(cleaned)):
            raise ValueError(
                "knowledge option-space refs must be unique"
            )

        return tuple(sorted(cleaned))

    @field_validator("observed_at")
    @classmethod
    def validate_signal_time(
        cls,
        value: datetime,
    ) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_material_change_evidence(
        self,
    ) -> Self:
        if (
            self.material_change
            and not self.evidence_refs
        ):
            raise ValueError(
                "material option-space change "
                "requires external evidence refs"
            )

        return self


class KnowledgeReevaluationAdvisory(LunaContractModel):
    """Structured candidate advisory derived only from external KE inputs."""

    knowledge_ref: str = Field(min_length=1, max_length=4000)
    kind: KnowledgeReevaluationAdvisoryKind

    validity_state: KnowledgeValiditySignalState
    applicability_state: KnowledgeApplicabilitySignalState
    material_option_space_change: bool

    validity_source_ref: str = Field(
        min_length=1,
        max_length=4000,
    )
    applicability_source_ref: str = Field(
        min_length=1,
        max_length=4000,
    )
    option_space_source_ref: str = Field(
        min_length=1,
        max_length=4000,
    )

    condition_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = Field(min_length=1)

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    invalidation_authority: Literal[False] = False
    stop_authority: Literal[False] = False
    decision_mutation_authority: Literal[False] = False
    memory_mutation_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False

    @field_validator(
        "knowledge_ref",
        "validity_source_ref",
        "applicability_source_ref",
        "option_space_source_ref",
    )
    @classmethod
    def validate_text_ref(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "knowledge reevaluation advisory refs cannot be blank"
            )

        return cleaned

    @field_validator(
        "condition_refs",
        "evidence_refs",
        "provenance_refs",
    )
    @classmethod
    def validate_advisory_refs(
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
                "knowledge reevaluation advisory refs cannot be blank"
            )

        if len(cleaned) != len(set(cleaned)):
            raise ValueError(
                "knowledge reevaluation advisory refs must be unique"
            )

        return tuple(sorted(cleaned))


def project_knowledge_reevaluation_advisory(
    *,
    validity: KnowledgeValiditySignal,
    applicability: KnowledgeApplicabilitySignal,
    option_space_change: KnowledgeOptionSpaceChangeSignal,
) -> KnowledgeReevaluationAdvisory | None:
    """Project candidate-only advisory state without mutating canonical owners."""

    knowledge_refs = {
        validity.knowledge_ref,
        applicability.knowledge_ref,
        option_space_change.knowledge_ref,
    }

    if len(knowledge_refs) != 1:
        raise ValueError(
            "KE-F3 signals must bind to the same knowledge ref"
        )

    kind: KnowledgeReevaluationAdvisoryKind | None = None

    if (
        validity.state
        is KnowledgeValiditySignalState.CONTRADICTED
    ):
        kind = (
            KnowledgeReevaluationAdvisoryKind.INVALIDATION_CANDIDATE
        )
    elif (
        validity.state
        is KnowledgeValiditySignalState.UNRESOLVED
        or applicability.state
        is KnowledgeApplicabilitySignalState.UNRESOLVED
    ):
        kind = (
            KnowledgeReevaluationAdvisoryKind.VERIFY_STOP_CANDIDATE
        )
    elif (
        validity.state
        is KnowledgeValiditySignalState.SUPPORTED
        and applicability.state
        is KnowledgeApplicabilitySignalState.APPLICABLE
        and option_space_change.material_change
    ):
        kind = (
            KnowledgeReevaluationAdvisoryKind.REEVALUATION_CANDIDATE
        )

    if kind is None:
        return None

    evidence_refs = tuple(
        sorted(
            {
                *validity.evidence_refs,
                *applicability.evidence_refs,
                *option_space_change.evidence_refs,
            }
        )
    )

    provenance_refs = tuple(
        sorted(
            {
                *validity.provenance_refs,
                *applicability.provenance_refs,
                *option_space_change.provenance_refs,
            }
        )
    )

    return KnowledgeReevaluationAdvisory(
        knowledge_ref=validity.knowledge_ref,
        kind=kind,
        validity_state=validity.state,
        applicability_state=applicability.state,
        material_option_space_change=(
            option_space_change.material_change
        ),
        validity_source_ref=validity.source_ref,
        applicability_source_ref=applicability.source_ref,
        option_space_source_ref=option_space_change.source_ref,
        condition_refs=applicability.condition_refs,
        evidence_refs=evidence_refs,
        provenance_refs=provenance_refs,
    )
