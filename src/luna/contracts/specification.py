"""C4 contracts for intent reconstruction and constraint reconciliation."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel


class ConstraintStrength(StrEnum):
    """Whether a constraint may be traded away during cognitive judgment."""

    HARD = "HARD"
    SOFT = "SOFT"


class ConstraintKind(StrEnum):
    """Observable semantic role for one C4 constraint."""

    REQUIRED_OUTCOME = "REQUIRED_OUTCOME"
    FORBIDDEN_OUTCOME = "FORBIDDEN_OUTCOME"
    EVIDENCE_REQUIREMENT = "EVIDENCE_REQUIREMENT"
    AUTHORITY_BOUNDARY = "AUTHORITY_BOUNDARY"
    PREFERENCE = "PREFERENCE"
    PROJECT_POLICY = "PROJECT_POLICY"


class SpecificationControlAction(StrEnum):
    """C4 control response after specification and constraint judgment."""

    ACCEPT_LITERAL = "ACCEPT_LITERAL"
    RECONSTRUCT = "RECONSTRUCT"
    TRADE_OFF = "TRADE_OFF"
    STOP_VERIFY = "STOP_VERIFY"


class SpecificationConstraint(LunaContractModel):
    """One provenance-bound hard constraint or soft preference."""

    constraint_id: str = Field(pattern=r"^constraint:sha256:[0-9a-f]{64}$")
    kind: ConstraintKind
    strength: ConstraintStrength
    statement: str = Field(min_length=1, max_length=4000)
    source_ref: str = Field(min_length=1, max_length=1000)
    provenance_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("statement", "source_ref")
    @classmethod
    def validate_nonblank_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("constraint text cannot be blank")
        return cleaned

    @field_validator("provenance_refs")
    @classmethod
    def validate_provenance_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("constraint provenance references cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("constraint provenance references must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_strength(self) -> Self:
        if self.kind is ConstraintKind.PREFERENCE:
            if self.strength is not ConstraintStrength.SOFT:
                raise ValueError("preferences must remain soft constraints")
        elif self.strength is not ConstraintStrength.HARD:
            raise ValueError("non-preference constraints must remain hard")
        return self


class ConstraintConflict(LunaContractModel):
    """Explicit conflict between two or more structured constraints."""

    conflict_id: str = Field(pattern=r"^conflict:sha256:[0-9a-f]{64}$")
    constraint_refs: tuple[str, ...] = Field(min_length=2)
    hard_conflict: bool
    reason_code: str = Field(min_length=1, max_length=300)

    @field_validator("constraint_refs")
    @classmethod
    def validate_constraint_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("conflict constraint references cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("conflict constraint references must be unique")
        return cleaned


class IntentConstraintJudgment(LunaContractModel):
    """Observable C4 interpretation without runtime or completion authority."""

    task_id: UUID
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    specification_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    literal_objective: str = Field(min_length=1, max_length=4000)
    reconstructed_objective: str = Field(min_length=1, max_length=4000)
    action: SpecificationControlAction
    solution_shaped_request: bool = False
    constraints: tuple[SpecificationConstraint, ...] = Field(min_length=1)
    conflicts: tuple[ConstraintConflict, ...] = ()
    preserved_hard_constraint_refs: tuple[str, ...] = Field(min_length=1)
    accepted_preference_refs: tuple[str, ...] = ()
    traded_off_preference_refs: tuple[str, ...] = ()
    unresolved_ambiguities: tuple[str, ...] = ()
    context_basis_refs: tuple[str, ...] = ()
    blocker_refs: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)
    raw_request_preserved: Literal[True] = True
    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator(
        "preserved_hard_constraint_refs",
        "accepted_preference_refs",
        "traded_off_preference_refs",
        "unresolved_ambiguities",
        "context_basis_refs",
        "blocker_refs",
        "reason_codes",
    )
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("C4 judgment entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("C4 judgment entries must be unique")
        return cleaned

    @staticmethod
    def _fingerprint_payload(
        *,
        task_id: UUID,
        request_fingerprint: str,
        literal_objective: str,
        reconstructed_objective: str,
        constraints: tuple[SpecificationConstraint, ...],
        conflicts: tuple[ConstraintConflict, ...],
        unresolved_ambiguities: tuple[str, ...],
        context_basis_refs: tuple[str, ...],
    ) -> dict[str, object]:
        return {
            "conflicts": tuple(item.model_dump(mode="json") for item in conflicts),
            "constraints": tuple(item.model_dump(mode="json") for item in constraints),
            "literal_objective": literal_objective,
            "reconstructed_objective": reconstructed_objective,
            "request_fingerprint": request_fingerprint,
            "task_id": str(task_id),
            "unresolved_ambiguities": unresolved_ambiguities,
            "context_basis_refs": context_basis_refs,
        }

    @classmethod
    def compute_basis_fingerprint(
        cls,
        *,
        task_id: UUID,
        request_fingerprint: str,
        literal_objective: str,
        reconstructed_objective: str,
        constraints: tuple[SpecificationConstraint, ...],
        conflicts: tuple[ConstraintConflict, ...],
        unresolved_ambiguities: tuple[str, ...],
        context_basis_refs: tuple[str, ...] = (),
    ) -> str:
        payload = cls._fingerprint_payload(
            task_id=task_id,
            request_fingerprint=request_fingerprint,
            literal_objective=literal_objective,
            reconstructed_objective=reconstructed_objective,
            constraints=constraints,
            conflicts=conflicts,
            unresolved_ambiguities=unresolved_ambiguities,
            context_basis_refs=context_basis_refs,
        )
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_judgment(self) -> Self:
        constraint_by_id = {item.constraint_id: item for item in self.constraints}
        if len(constraint_by_id) != len(self.constraints):
            raise ValueError("C4 constraint IDs must be unique")

        hard_refs = tuple(
            item.constraint_id
            for item in self.constraints
            if item.strength is ConstraintStrength.HARD
        )
        preference_refs = {
            item.constraint_id
            for item in self.constraints
            if item.kind is ConstraintKind.PREFERENCE
        }
        if set(self.preserved_hard_constraint_refs) != set(hard_refs):
            raise ValueError("all hard constraints must remain preserved")
        if set(self.accepted_preference_refs) & set(self.traded_off_preference_refs):
            raise ValueError("accepted and traded-off preferences must be disjoint")
        if (
            set(self.accepted_preference_refs) | set(self.traded_off_preference_refs)
        ) != preference_refs:
            raise ValueError("every soft preference must have an explicit disposition")

        conflicted_preference_refs: set[str] = set()
        for conflict in self.conflicts:
            if any(ref not in constraint_by_id for ref in conflict.constraint_refs):
                raise ValueError("constraint conflict references an unknown constraint")
            referenced = tuple(constraint_by_id[ref] for ref in conflict.constraint_refs)
            soft_refs = {
                item.constraint_id
                for item in referenced
                if item.strength is ConstraintStrength.SOFT
            }
            hard_refs_in_conflict = {
                item.constraint_id
                for item in referenced
                if item.strength is ConstraintStrength.HARD
            }
            if conflict.hard_conflict and soft_refs:
                raise ValueError("hard conflicts cannot contain soft preferences")
            if not conflict.hard_conflict and (not soft_refs or not hard_refs_in_conflict):
                raise ValueError("soft conflicts require both soft and hard constraints")
            conflicted_preference_refs.update(soft_refs)

        if conflicted_preference_refs != set(self.traded_off_preference_refs):
            raise ValueError("preference conflicts must exactly match traded-off preferences")

        expected_fingerprint = self.compute_basis_fingerprint(
            task_id=self.task_id,
            request_fingerprint=self.request_fingerprint,
            literal_objective=self.literal_objective,
            reconstructed_objective=self.reconstructed_objective,
            constraints=self.constraints,
            conflicts=self.conflicts,
            unresolved_ambiguities=self.unresolved_ambiguities,
            context_basis_refs=self.context_basis_refs,
        )
        if self.specification_basis_fingerprint != expected_fingerprint:
            raise ValueError("C4 specification basis fingerprint mismatch")

        hard_conflict = any(item.hard_conflict for item in self.conflicts)
        if hard_conflict and self.action is not SpecificationControlAction.STOP_VERIFY:
            raise ValueError("hard constraint conflicts require STOP_VERIFY")
        if self.action is SpecificationControlAction.STOP_VERIFY and not self.blocker_refs:
            raise ValueError("STOP_VERIFY requires explicit blockers")
        if (
            self.action is SpecificationControlAction.TRADE_OFF
            and (not self.traded_off_preference_refs or self.blocker_refs)
        ):
            raise ValueError("TRADE_OFF requires only explicit soft-preference trade-offs")
        if self.action is SpecificationControlAction.RECONSTRUCT:
            if not self.solution_shaped_request:
                raise ValueError("RECONSTRUCT requires a solution-shaped request signal")
            if self.literal_objective == self.reconstructed_objective:
                raise ValueError("RECONSTRUCT must change the advisory objective")
            if self.blocker_refs:
                raise ValueError("RECONSTRUCT cannot carry unresolved blockers")
        if self.action is SpecificationControlAction.ACCEPT_LITERAL:
            if self.literal_objective != self.reconstructed_objective:
                raise ValueError("ACCEPT_LITERAL must preserve the literal objective")
            if self.traded_off_preference_refs or self.blocker_refs:
                raise ValueError("ACCEPT_LITERAL cannot hide trade-offs or blockers")
        return self
