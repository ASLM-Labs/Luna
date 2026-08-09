"""Governed experience-distillation contracts for Luna C-003."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel


class LessonKind(StrEnum):
    """Reusable lesson categories without claiming universal truth."""

    INVARIANT = "INVARIANT"
    HEURISTIC = "HEURISTIC"
    STRATEGY = "STRATEGY"
    FAILURE_GUARD = "FAILURE_GUARD"


class CaseRelation(StrEnum):
    """How one governed source case relates to a proposed lesson."""

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"


class EvidenceOrigin(StrEnum):
    """Allowed provenance for a case-level lesson judgment."""

    DETERMINISTIC_VERIFIER = "DETERMINISTIC_VERIFIER"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    CONTROLLED_REPLAY = "CONTROLLED_REPLAY"
    MODEL_SELF_REPORT = "MODEL_SELF_REPORT"


class GeneralizationScope(StrEnum):
    """Evidence-bounded generalization strength."""

    NONE = "NONE"
    WITHIN_TASK_FAMILY = "WITHIN_TASK_FAMILY"
    CROSS_TASK_FAMILY = "CROSS_TASK_FAMILY"


class DistillationDisposition(StrEnum):
    """Outcome of deterministic C-003 evidence checks."""

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED_CONTRADICTION = "REJECTED_CONTRADICTION"
    REVIEW_REQUIRED_CANDIDATE = "REVIEW_REQUIRED_CANDIDATE"


class LessonCaseEvidence(LunaContractModel):
    """Evidence-bound relation between one trajectory and one lesson proposal."""

    source_trajectory_id: str = Field(min_length=1, max_length=500)
    relation: CaseRelation
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    evidence_origin: EvidenceOrigin
    evaluator_ref: str = Field(min_length=1, max_length=500)
    observation_summary: str = Field(min_length=1, max_length=2000)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("lesson evidence refs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("lesson evidence refs must be unique")
        return cleaned

    @model_validator(mode="after")
    def reject_self_report(self) -> Self:
        if self.evidence_origin is EvidenceOrigin.MODEL_SELF_REPORT:
            raise ValueError("model self-report cannot establish reusable experience")
        return self


class ExperienceLessonProposal(LunaContractModel):
    """Human/reviewer-supplied lesson hypothesis evaluated against governed traces."""

    lesson_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    statement: str = Field(min_length=1, max_length=4000)
    kind: LessonKind
    applicability_scope: tuple[str, ...] = Field(min_length=1)
    cases: tuple[LessonCaseEvidence, ...] = Field(min_length=1)

    @field_validator("applicability_scope")
    @classmethod
    def validate_scope(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("applicability scope cannot contain blanks")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("applicability scope must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_case_uniqueness(self) -> Self:
        source_ids = tuple(case.source_trajectory_id for case in self.cases)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("one source trajectory may judge a lesson only once")
        return self


class DistilledExperienceCandidate(LunaContractModel):
    """Evidence-bounded output that still requires separate review/promotion."""

    lesson_id: str
    statement: str
    kind: LessonKind
    applicability_scope: tuple[str, ...]
    disposition: DistillationDisposition
    generalization_scope: GeneralizationScope
    generalization_test_passed: bool
    supporting_source_trajectories: tuple[str, ...] = ()
    contradicting_source_trajectories: tuple[str, ...] = ()
    supporting_split_groups: tuple[str, ...] = ()
    supporting_task_families: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = ()
    decision_basis: tuple[str, ...] = ()
    review_required: Literal[True] = True
    automatic_memory_commit_allowed: Literal[False] = False
    runtime_authority: Literal[False] = False
    training_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        if self.disposition is DistillationDisposition.REVIEW_REQUIRED_CANDIDATE:
            if not self.generalization_test_passed:
                raise ValueError(
                    "review candidate requires a passed cross-case generalization test"
                )
            if len(self.supporting_split_groups) < 2:
                raise ValueError("review candidate requires at least two independent split groups")
            if self.generalization_scope is GeneralizationScope.NONE:
                raise ValueError("review candidate requires a bounded generalization scope")
        else:
            if self.generalization_test_passed:
                raise ValueError("non-candidate disposition cannot pass generalization")
            if self.generalization_scope is not GeneralizationScope.NONE:
                raise ValueError("non-candidate disposition cannot claim generalization scope")
        return self
