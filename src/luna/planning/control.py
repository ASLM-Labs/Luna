"""Evidence-bound decision compression, alternatives, and C2 control advisory.

This module coordinates already-observed decision state. It does not execute tools, grant
runtime authority, or persist hidden reasoning. The output is structured advisory state for
Luna's cognitive control plane.
"""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.decision import (
    AssumptionRecord,
    AssumptionStatus,
    DecisionRecord,
    DecisionStateSnapshot,
    DecisionStatus,
)
from luna.contracts.invalidation import InvalidationLayer
from luna.contracts.state import TaskState
from luna.decision_state import DecisionStateService
from luna.planning.judgment import DecisionBasis, InformationGainPlan, InformationNeed


class DecisionControlAction(StrEnum):
    """Evidence-bound control choice for the current cognition basis."""

    CONTINUE = "CONTINUE"
    SWITCH = "SWITCH"
    STOP_VERIFY = "STOP_VERIFY"


class DecisionCompression(LunaContractModel):
    """Bounded, decision-relevant view that keeps source evidence externally intact."""

    task_id: UUID
    step_id: UUID
    source_task_state_revision: int = Field(ge=0)
    source_decision_state_revision: int = Field(ge=0)
    decision_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_information_need_id: str = Field(pattern=r"^information:sha256:[0-9a-f]{64}$")
    decision_question: str = Field(min_length=1, max_length=4000)
    source_evidence_refs: tuple[str, ...] = ()
    decision_changing_evidence_refs: tuple[str, ...] = ()
    supporting_evidence_refs: tuple[str, ...] = ()
    current_assumption_refs: tuple[str, ...] = ()
    current_decision_refs: tuple[str, ...] = ()
    blocker_refs: tuple[str, ...] = ()
    hard_constraint_refs: tuple[str, ...] = ()
    invalidated_decision_refs: tuple[str, ...] = ()
    evidence_bound_invalidated_decision_refs: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)
    raw_evidence_preserved: Literal[True] = True
    runtime_authority: Literal[False] = False

    @field_validator(
        "source_evidence_refs",
        "decision_changing_evidence_refs",
        "supporting_evidence_refs",
        "current_assumption_refs",
        "current_decision_refs",
        "blocker_refs",
        "hard_constraint_refs",
        "invalidated_decision_refs",
        "evidence_bound_invalidated_decision_refs",
        "reason_codes",
    )
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("decision compression entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("decision compression entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_evidence_partition(self) -> Self:
        source = set(self.source_evidence_refs)
        changing = set(self.decision_changing_evidence_refs)
        supporting = set(self.supporting_evidence_refs)
        if changing & supporting:
            raise ValueError("decision-changing and supporting evidence must be disjoint")
        if changing | supporting != source:
            raise ValueError("compressed evidence partition must cover source evidence exactly")
        invalidated = set(self.invalidated_decision_refs)
        evidence_bound = set(self.evidence_bound_invalidated_decision_refs)
        if not evidence_bound.issubset(invalidated):
            raise ValueError(
                "evidence-bound invalidated refs must be current invalidated decisions"
            )
        if bool(evidence_bound) != bool(changing):
            raise ValueError("basis-change evidence and invalidated-decision binding must agree")
        return self



class DecisionRouteTradeoffSignal(LunaContractModel):
    """External route trade-off input; planning reconciles but does not invent it."""

    task_id: UUID
    step_id: UUID
    decision_basis_fingerprint: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    decision_ref: str = Field(
        min_length=1,
        max_length=1000,
    )

    expected_information_gain: int = Field(
        ge=0,
        le=100,
    )
    risk_cost: int = Field(
        ge=0,
        le=100,
    )

    violated_hard_constraint_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = Field(
        min_length=1
    )

    truth_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    decision_control_authority: Literal[False] = False
    ranking_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    runtime_authority: Literal[False] = False

    @field_validator(
        "violated_hard_constraint_refs",
        "evidence_refs",
        "provenance_refs",
    )
    @classmethod
    def validate_tradeoff_refs(
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
                "decision route trade-off refs cannot be blank"
            )

        if len(cleaned) != len(set(cleaned)):
            raise ValueError(
                "decision route trade-off refs must be unique"
            )

        return tuple(sorted(cleaned))

    @model_validator(mode="after")
    def validate_material_tradeoff_basis(
        self,
    ) -> Self:
        material = bool(
            self.expected_information_gain
            or self.risk_cost
            or self.violated_hard_constraint_refs
        )

        if material and not self.evidence_refs:
            raise ValueError(
                "material route trade-off requires external evidence"
            )

        return self


class DecisionAlternative(LunaContractModel):
    """One observable decision route ranked without creating execution authority."""

    decision_ref: str = Field(min_length=1, max_length=1000)
    action_key: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=4000)
    status: DecisionStatus
    evidence_refs: tuple[str, ...] = ()
    blocker_refs: tuple[str, ...] = ()

    expected_information_gain: int = Field(
        default=0,
        ge=0,
        le=100,
    )
    risk_cost: int = Field(
        default=0,
        ge=0,
        le=100,
    )

    hard_constraint_violation_refs: tuple[str, ...] = ()
    tradeoff_evidence_refs: tuple[str, ...] = ()
    tradeoff_provenance_refs: tuple[str, ...] = ()

    admissible: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)
    runtime_authority: Literal[False] = False

    @field_validator(
        "evidence_refs",
        "blocker_refs",
        "hard_constraint_violation_refs",
        "tradeoff_evidence_refs",
        "tradeoff_provenance_refs",
        "reason_codes",
    )
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("decision alternative entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("decision alternative entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_admissibility(self) -> Self:
        material_tradeoff = bool(
            self.expected_information_gain
            or self.risk_cost
            or self.hard_constraint_violation_refs
        )

        if material_tradeoff and (
            not self.tradeoff_evidence_refs
            or not self.tradeoff_provenance_refs
        ):
            raise ValueError(
                "material decision trade-off requires "
                "evidence and provenance"
            )

        expected_admissible = (
            self.status
            in {
                DecisionStatus.ACTIVE,
                DecisionStatus.PENDING,
            }
            and not self.blocker_refs
            and not self.hard_constraint_violation_refs
        )

        if self.admissible is not expected_admissible:
            raise ValueError(
                "decision alternative admissibility must match "
                "status, blockers, and hard constraints"
            )

        return self


def _alternative_rank_key(
    item: DecisionAlternative,
) -> tuple[int, int, int, int, int, str]:
    status_order = {
        DecisionStatus.ACTIVE: 0,
        DecisionStatus.PENDING: 1,
        DecisionStatus.COMPLETED: 2,
        DecisionStatus.BLOCKED: 3,
        DecisionStatus.INVALIDATED: 4,
    }

    evidence_count = len(
        {
            *item.evidence_refs,
            *item.tradeoff_evidence_refs,
        }
    )

    return (
        0 if item.admissible else 1,
        status_order[item.status],
        -item.expected_information_gain,
        item.risk_cost,
        -evidence_count,
        item.decision_ref,
    )


class DecisionAlternativeSet(LunaContractModel):
    """Regenerated and ranked current decision routes for one compressed basis."""

    task_id: UUID
    step_id: UUID
    source_task_state_revision: int = Field(ge=0)
    source_decision_state_revision: int = Field(ge=0)
    decision_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    alternatives: tuple[DecisionAlternative, ...] = ()
    ranked_alternative_refs: tuple[str, ...] = ()
    selected_alternative_ref: str | None = Field(default=None, min_length=1, max_length=1000)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    runtime_authority: Literal[False] = False

    @field_validator("ranked_alternative_refs", "reason_codes")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("decision alternative-set entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("decision alternative-set entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_ranking(self) -> Self:
        refs = tuple(item.decision_ref for item in self.alternatives)
        if len(refs) != len(set(refs)):
            raise ValueError("decision alternatives must be unique")
        if set(self.ranked_alternative_refs) != set(refs):
            raise ValueError("decision alternative ranking must cover the current set exactly")
        by_ref = {item.decision_ref: item for item in self.alternatives}
        expected_ranking = tuple(
            item.decision_ref
            for item in sorted(self.alternatives, key=_alternative_rank_key)
        )
        if self.ranked_alternative_refs != expected_ranking:
            raise ValueError("decision alternatives must use deterministic ranking")
        expected_selected = next(
            (
                ref
                for ref in self.ranked_alternative_refs
                if by_ref[ref].admissible
            ),
            None,
        )
        if self.selected_alternative_ref != expected_selected:
            raise ValueError("selected alternative must be the highest-ranked admissible route")
        return self


class DecisionControlAssessment(LunaContractModel):
    """CONTINUE/SWITCH/STOP-VERIFY advisory with explicit changed-basis evidence."""

    task_id: UUID
    step_id: UUID
    action: DecisionControlAction
    selected_information_need_id: str = Field(pattern=r"^information:sha256:[0-9a-f]{64}$")
    selected_alternative_ref: str | None = Field(default=None, min_length=1, max_length=1000)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    blocker_refs: tuple[str, ...] = ()
    changed_basis_refs: tuple[str, ...] = ()
    verification_required: bool = False
    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("reason_codes", "blocker_refs", "changed_basis_refs")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("decision-control entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("decision-control entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_control_contract(self) -> Self:
        if self.action is DecisionControlAction.SWITCH and (
            not self.changed_basis_refs or self.selected_alternative_ref is None
        ):
            raise ValueError("SWITCH requires changed-basis refs and an alternate route")
        if self.action is DecisionControlAction.STOP_VERIFY and (
            not self.verification_required or not self.blocker_refs
        ):
            raise ValueError("STOP_VERIFY requires blockers and verification")
        if self.action is not DecisionControlAction.STOP_VERIFY and self.verification_required:
            raise ValueError("only STOP_VERIFY may require verification")
        return self


class DecisionControlAdvisor:
    """Compress, regenerate alternatives, and choose C2 control deterministically."""

    _BASIS_CHANGE_STATUSES: ClassVar[frozenset[AssumptionStatus]] = frozenset(
        {
            AssumptionStatus.CONTRADICTED,
            AssumptionStatus.INVALIDATED,
            AssumptionStatus.SUPERSEDED,
        }
    )

    def __init__(self) -> None:
        self._decision_state = DecisionStateService()

    @staticmethod
    def _selected_need(information_gain: InformationGainPlan) -> InformationNeed:
        return next(
            item
            for item in information_gain.needs
            if item.need_id == information_gain.selected_need_id
        )

    @staticmethod
    def _assumption_ref(assumption: AssumptionRecord) -> str:
        return f"assumption:{assumption.assumption_id}:{assumption.status.value}"

    @staticmethod
    def _decision_ref(decision: DecisionRecord) -> str:
        return f"decision:{decision.decision_id}:{decision.status.value}"

    @staticmethod
    def _current_decisions(snapshot: DecisionStateSnapshot) -> tuple[DecisionRecord, ...]:
        """Return the latest decision for each semantic action key."""
        latest: dict[str, DecisionRecord] = {}
        for decision in snapshot.decisions:
            previous = latest.get(decision.action_key)
            if previous is None or (
                decision.updated_at,
                decision.created_at,
                str(decision.decision_id),
            ) > (
                previous.updated_at,
                previous.created_at,
                str(previous.decision_id),
            ):
                latest[decision.action_key] = decision
        return tuple(latest[key] for key in sorted(latest))

    def _current_state(
        self,
        state: TaskState,
    ) -> tuple[
        DecisionStateSnapshot,
        tuple[AssumptionRecord, ...],
        tuple[DecisionRecord, ...],
    ]:
        snapshot = self._decision_state.ensure(state.task_id, state.decision_state)
        return (
            snapshot,
            self._decision_state.current_assumptions(snapshot),
            self._current_decisions(snapshot),
        )

    @staticmethod
    def _basis_fingerprint(
        *,
        state: TaskState,
        information_gain: InformationGainPlan,
        decision_basis: DecisionBasis,
        decision_state_revision: int,
        assumption_refs: tuple[str, ...],
        decision_refs: tuple[str, ...],
        blocker_refs: tuple[str, ...],
    ) -> str:
        payload = {
            "assumption_refs": assumption_refs,
            "blocker_refs": blocker_refs,
            "decision_refs": decision_refs,
            "decision_state_revision": decision_state_revision,
            "evidence_refs": decision_basis.evidence_refs,
            "acceptance_target_ids": decision_basis.acceptance_target_ids,
            "hard_constraints": decision_basis.hard_constraints,
            "objective": decision_basis.objective,
            "selected_information_need_id": information_gain.selected_need_id,
            "specification_basis_fingerprint": (
                state.specification_judgment.specification_basis_fingerprint
                if state.specification_judgment is not None
                else None
            ),
            "verification_depth": decision_basis.verification_depth,
            "step_id": str(information_gain.step_id),
            "task_id": str(state.task_id),
            "task_state_revision": state.revision,
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(serialized.encode("utf-8")).hexdigest()

    def compress(
        self,
        *,
        state: TaskState,
        information_gain: InformationGainPlan,
        decision_basis: DecisionBasis,
    ) -> DecisionCompression:
        """Partition evidence without mutating or deleting the authoritative source basis."""
        if information_gain.task_id != state.task_id or decision_basis.task_id != state.task_id:
            raise ValueError("C2 decision compression task mismatch")
        if information_gain.step_id != decision_basis.step_id:
            raise ValueError("C2 decision compression step mismatch")
        if decision_basis.selected_information_need_id != information_gain.selected_need_id:
            raise ValueError("C2 decision compression information-need mismatch")

        selected = self._selected_need(information_gain)
        snapshot, assumptions, decisions = self._current_state(state)
        assumption_refs = tuple(self._assumption_ref(item) for item in assumptions)
        decision_refs = tuple(self._decision_ref(item) for item in decisions)
        invalidated_decisions = tuple(
            item for item in decisions if item.status is DecisionStatus.INVALIDATED
        )
        invalidated_refs = tuple(self._decision_ref(item) for item in invalidated_decisions)
        blocker_refs = tuple(
            dict.fromkeys(
                (
                    *decision_basis.blocker_refs,
                    *(
                        self._assumption_ref(item)
                        for item in assumptions
                        if item.critical and item.status is not AssumptionStatus.SUPPORTED
                    ),
                    *(
                        self._decision_ref(item)
                        for item in decisions
                        if item.status is DecisionStatus.BLOCKED
                    ),
                )
            )
        )

        source_evidence = tuple(dict.fromkeys(decision_basis.evidence_refs))
        changed_basis_evidence: set[str] = set()
        evidence_bound_invalidated_refs: list[str] = []
        c3_report = (
            state.invalidation_state.latest_report
            if state.invalidation_state is not None
            else None
        )
        c3_decision_changed_evidence = (
            {
                item.target_ref: set(item.changed_basis_evidence_refs)
                for item in c3_report.impacts
                if item.layer is InvalidationLayer.DECISION
            }
            if c3_report is not None
            else {}
        )
        c3_changed_evidence = (
            set(c3_report.changed_basis_evidence_refs)
            if c3_report is not None
            else set()
        )
        for decision in invalidated_decisions:
            canonical_decision_ref = f"decision:{decision.decision_id}"
            if canonical_decision_ref in c3_decision_changed_evidence:
                linked_change_evidence = set(
                    c3_decision_changed_evidence[canonical_decision_ref]
                )
            else:
                linked_change_evidence = {
                    ref
                    for assumption in assumptions
                    if assumption.status in self._BASIS_CHANGE_STATUSES
                    and decision.decision_id in assumption.dependent_decision_ids
                    for ref in assumption.evidence_refs
                }
            if linked_change_evidence:
                evidence_bound_invalidated_refs.append(self._decision_ref(decision))
                changed_basis_evidence.update(linked_change_evidence)
        changing = tuple(ref for ref in source_evidence if ref in changed_basis_evidence)
        changing_set = set(changing)
        supporting = tuple(ref for ref in source_evidence if ref not in changing_set)

        reasons = ["decision_relevance_only", "raw_evidence_preserved"]
        if blocker_refs:
            reasons.append("blockers_prioritized")
        if invalidated_refs:
            reasons.append("invalidated_current_decision_present")
        if changing:
            reasons.append("decision_changing_evidence_identified")
            if c3_report is not None and c3_changed_evidence.intersection(changing_set):
                reasons.append("c3_changed_basis_evidence_applied")
        else:
            reasons.append("no_explicit_basis_change_evidence")

        basis_fingerprint = self._basis_fingerprint(
            state=state,
            information_gain=information_gain,
            decision_basis=decision_basis,
            decision_state_revision=snapshot.revision,
            assumption_refs=assumption_refs,
            decision_refs=decision_refs,
            blocker_refs=blocker_refs,
        )
        return DecisionCompression(
            task_id=state.task_id,
            step_id=information_gain.step_id,
            source_task_state_revision=state.revision,
            source_decision_state_revision=snapshot.revision,
            decision_basis_fingerprint=basis_fingerprint,
            selected_information_need_id=information_gain.selected_need_id,
            decision_question=selected.description,
            source_evidence_refs=source_evidence,
            decision_changing_evidence_refs=changing,
            supporting_evidence_refs=supporting,
            current_assumption_refs=assumption_refs,
            current_decision_refs=decision_refs,
            blocker_refs=blocker_refs,
            hard_constraint_refs=decision_basis.hard_constraints,
            invalidated_decision_refs=invalidated_refs,
            evidence_bound_invalidated_decision_refs=tuple(evidence_bound_invalidated_refs),
            reason_codes=tuple(reasons),
        )

    def alternatives(
        self,
        *,
        state: TaskState,
        compression: DecisionCompression,
        tradeoff_signals: tuple[
            DecisionRouteTradeoffSignal,
            ...,
        ] = (),
    ) -> DecisionAlternativeSet:
        """Regenerate and rank current observable decision routes from C1 state."""
        if compression.task_id != state.task_id:
            raise ValueError("C2 decision alternatives task mismatch")
        snapshot, assumptions, decisions = self._current_state(state)
        if compression.source_task_state_revision != state.revision:
            raise ValueError("C2 decision alternatives require a current task-state compression")
        if compression.source_decision_state_revision != snapshot.revision:
            raise ValueError(
                "C2 decision alternatives require a current decision-state compression"
            )

        signal_refs = tuple(
            item.decision_ref
            for item in tradeoff_signals
        )

        if len(signal_refs) != len(set(signal_refs)):
            raise ValueError(
                "decision route trade-off signals must be unique"
            )

        current_decision_refs = {
            self._decision_ref(item)
            for item in decisions
        }

        for signal in tradeoff_signals:
            if (
                signal.task_id != state.task_id
                or signal.step_id != compression.step_id
            ):
                raise ValueError(
                    "decision route trade-off task/step mismatch"
                )

            if (
                signal.decision_basis_fingerprint
                != compression.decision_basis_fingerprint
            ):
                raise ValueError(
                    "stale decision route trade-off basis"
                )

            if signal.decision_ref not in current_decision_refs:
                raise ValueError(
                    "decision route trade-off references "
                    "a non-current decision"
                )

            if not set(
                signal.violated_hard_constraint_refs
            ).issubset(
                set(compression.hard_constraint_refs)
            ):
                raise ValueError(
                    "decision route trade-off references "
                    "an unknown hard constraint"
                )

        tradeoff_by_ref = {
            item.decision_ref: item
            for item in tradeoff_signals
        }

        assumptions_by_id = {item.assumption_id: item for item in assumptions}
        alternatives: list[DecisionAlternative] = []
        for decision in decisions:
            linked = tuple(
                assumptions_by_id[assumption_id]
                for assumption_id in decision.assumption_ids
                if assumption_id in assumptions_by_id
            )
            evidence_refs = tuple(
                dict.fromkeys(ref for assumption in linked for ref in assumption.evidence_refs)
            )
            blocker_refs = tuple(
                dict.fromkeys(
                    (
                        *(
                            self._assumption_ref(assumption)
                            for assumption in linked
                            if assumption.status in self._BASIS_CHANGE_STATUSES
                            or (
                                assumption.critical
                                and assumption.status is not AssumptionStatus.SUPPORTED
                            )
                        ),
                        *(
                            (self._decision_ref(decision),)
                            if decision.status in {
                                DecisionStatus.BLOCKED,
                                DecisionStatus.INVALIDATED,
                            }
                            else ()
                        ),
                    )
                )
            )
            decision_ref = self._decision_ref(
                decision
            )
            tradeoff = tradeoff_by_ref.get(
                decision_ref
            )

            expected_information_gain = (
                tradeoff.expected_information_gain
                if tradeoff is not None
                else 0
            )
            risk_cost = (
                tradeoff.risk_cost
                if tradeoff is not None
                else 0
            )
            hard_constraint_violations = (
                tradeoff.violated_hard_constraint_refs
                if tradeoff is not None
                else ()
            )
            tradeoff_evidence_refs = (
                tradeoff.evidence_refs
                if tradeoff is not None
                else ()
            )
            tradeoff_provenance_refs = (
                tradeoff.provenance_refs
                if tradeoff is not None
                else ()
            )

            admissible = (
                decision.status
                in {
                    DecisionStatus.ACTIVE,
                    DecisionStatus.PENDING,
                }
                and not blocker_refs
                and not hard_constraint_violations
            )

            reasons = [
                f"status:{decision.status.value}"
            ]

            if tradeoff is not None:
                reasons.append(
                    "external_tradeoff_signal_consumed"
                )

            if hard_constraint_violations:
                reasons.append(
                    "hard_constraint_violation"
                )
            if evidence_refs:
                reasons.append("evidence_linked")
            if blocker_refs:
                reasons.append("basis_blocked")
            if admissible:
                reasons.append("admissible_current_route")
            else:
                reasons.append("inadmissible_current_route")
            alternatives.append(
                DecisionAlternative(
                    decision_ref=decision_ref,
                    action_key=decision.action_key,
                    description=decision.description,
                    status=decision.status,
                    evidence_refs=evidence_refs,
                    blocker_refs=blocker_refs,
                    expected_information_gain=(
                        expected_information_gain
                    ),
                    risk_cost=risk_cost,
                    hard_constraint_violation_refs=(
                        hard_constraint_violations
                    ),
                    tradeoff_evidence_refs=(
                        tradeoff_evidence_refs
                    ),
                    tradeoff_provenance_refs=(
                        tradeoff_provenance_refs
                    ),
                    admissible=admissible,
                    reason_codes=tuple(reasons),
                )
            )

        ranked = tuple(
            item.decision_ref
            for item in sorted(alternatives, key=_alternative_rank_key)
        )
        by_ref = {item.decision_ref: item for item in alternatives}
        selected_ref = next((ref for ref in ranked if by_ref[ref].admissible), None)
        reasons = ["alternatives_regenerated_from_current_decision_state"]
        if selected_ref is None:
            reasons.append("no_admissible_alternate_route")
        else:
            reasons.append("highest_ranked_admissible_route_selected")
        return DecisionAlternativeSet(
            task_id=state.task_id,
            step_id=compression.step_id,
            source_task_state_revision=state.revision,
            source_decision_state_revision=snapshot.revision,
            decision_basis_fingerprint=compression.decision_basis_fingerprint,
            alternatives=tuple(alternatives),
            ranked_alternative_refs=ranked,
            selected_alternative_ref=selected_ref,
            reason_codes=tuple(reasons),
        )

    def assess(
        self,
        *,
        state: TaskState,
        information_gain: InformationGainPlan,
        compression: DecisionCompression,
        alternatives: DecisionAlternativeSet,
    ) -> DecisionControlAssessment:
        """Choose CONTINUE, SWITCH, or STOP_VERIFY from current evidence-linked state."""
        if information_gain.task_id != state.task_id or compression.task_id != state.task_id:
            raise ValueError("C2 decision control task mismatch")
        if information_gain.step_id != compression.step_id:
            raise ValueError("C2 decision control step mismatch")
        if compression.selected_information_need_id != information_gain.selected_need_id:
            raise ValueError("C2 decision control information-need mismatch")
        if alternatives.task_id != state.task_id or alternatives.step_id != compression.step_id:
            raise ValueError("C2 decision control alternatives binding mismatch")
        if alternatives.decision_basis_fingerprint != compression.decision_basis_fingerprint:
            raise ValueError("C2 decision alternatives must match the compressed decision basis")

        selected = self._selected_need(information_gain)
        snapshot, assumptions, decisions = self._current_state(state)
        stale_blockers: list[str] = []
        if compression.source_task_state_revision != state.revision:
            stale_blockers.append(
                "stale_task_state_revision:"
                f"{compression.source_task_state_revision}->{state.revision}"
            )
        if compression.source_decision_state_revision != snapshot.revision:
            stale_blockers.append(
                "stale_decision_state_revision:"
                f"{compression.source_decision_state_revision}->{snapshot.revision}"
            )
        if alternatives.source_task_state_revision != state.revision:
            stale_blockers.append("stale_decision_alternative_task_state")
        if alternatives.source_decision_state_revision != snapshot.revision:
            stale_blockers.append("stale_decision_alternative_decision_state")
        if stale_blockers:
            return DecisionControlAssessment(
                task_id=state.task_id,
                step_id=information_gain.step_id,
                action=DecisionControlAction.STOP_VERIFY,
                selected_information_need_id=information_gain.selected_need_id,
                reason_codes=(
                    "stale_cognition_basis_requires_refresh",
                    "stop_verify_before_using_stale_compression",
                ),
                blocker_refs=tuple(dict.fromkeys(stale_blockers)),
                verification_required=True,
            )

        contradicted = tuple(
            self._assumption_ref(item)
            for item in assumptions
            if item.critical and item.status is AssumptionStatus.CONTRADICTED
        )
        unsupported = tuple(
            self._assumption_ref(item)
            for item in assumptions
            if item.critical and item.status is not AssumptionStatus.SUPPORTED
        )
        blocked_decisions = tuple(
            self._decision_ref(item)
            for item in decisions
            if item.status is DecisionStatus.BLOCKED
        )
        invalidated = tuple(
            self._decision_ref(item)
            for item in decisions
            if item.status is DecisionStatus.INVALIDATED
        )

        specification_blockers = tuple(
            ref for ref in compression.blocker_refs if ref.startswith("c4:")
        )
        if specification_blockers:
            return DecisionControlAssessment(
                task_id=state.task_id,
                step_id=information_gain.step_id,
                action=DecisionControlAction.STOP_VERIFY,
                selected_information_need_id=information_gain.selected_need_id,
                reason_codes=(
                    "c4_specification_requires_stop_verify",
                    "hard_constraint_or_critical_ambiguity_unresolved",
                ),
                blocker_refs=specification_blockers,
                verification_required=True,
            )

        if contradicted:
            return DecisionControlAssessment(
                task_id=state.task_id,
                step_id=information_gain.step_id,
                action=DecisionControlAction.STOP_VERIFY,
                selected_information_need_id=information_gain.selected_need_id,
                reason_codes=(
                    "critical_contradiction_requires_stop_verify",
                    "evidence_over_confidence",
                ),
                blocker_refs=tuple(dict.fromkeys((*compression.blocker_refs, *contradicted))),
                changed_basis_refs=tuple(
                    dict.fromkeys(
                        (*contradicted, *compression.decision_changing_evidence_refs)
                    )
                ),
                verification_required=True,
            )

        if unsupported or blocked_decisions:
            blockers = tuple(
                dict.fromkeys((*compression.blocker_refs, *unsupported, *blocked_decisions))
            )
            return DecisionControlAssessment(
                task_id=state.task_id,
                step_id=information_gain.step_id,
                action=DecisionControlAction.STOP_VERIFY,
                selected_information_need_id=information_gain.selected_need_id,
                reason_codes=(
                    "critical_uncertainty_requires_verification",
                    f"information_need:{selected.kind.value}",
                ),
                blocker_refs=blockers,
                verification_required=True,
            )

        hard_constraint_blocked_active = tuple(
            item
            for item in alternatives.alternatives
            if (
                item.status is DecisionStatus.ACTIVE
                and item.hard_constraint_violation_refs
            )
        )

        if hard_constraint_blocked_active:
            violating_decision_refs = tuple(
                item.decision_ref
                for item in hard_constraint_blocked_active
            )
            violated_constraints = tuple(
                dict.fromkeys(
                    ref
                    for item in hard_constraint_blocked_active
                    for ref in item.hard_constraint_violation_refs
                )
            )
            tradeoff_evidence = tuple(
                dict.fromkeys(
                    ref
                    for item in hard_constraint_blocked_active
                    for ref in item.tradeoff_evidence_refs
                )
            )
            selected_alternative = (
                alternatives.selected_alternative_ref
            )

            if (
                tradeoff_evidence
                and selected_alternative is not None
                and selected_alternative
                not in set(violating_decision_refs)
            ):
                return DecisionControlAssessment(
                    task_id=state.task_id,
                    step_id=information_gain.step_id,
                    action=DecisionControlAction.SWITCH,
                    selected_information_need_id=(
                        information_gain.selected_need_id
                    ),
                    selected_alternative_ref=(
                        selected_alternative
                    ),
                    reason_codes=(
                        "hard_constraint_blocks_current_route",
                        "evidence_bound_constraint_change",
                        "admissible_alternative_present",
                    ),
                    changed_basis_refs=tuple(
                        dict.fromkeys(
                            (
                                *violating_decision_refs,
                                *violated_constraints,
                                *tradeoff_evidence,
                                selected_alternative,
                            )
                        )
                    ),
                )

            reasons = [
                "stop_verify_before_constraint_switch"
            ]
            constraint_switch_blockers = [
                *violating_decision_refs,
                *violated_constraints,
            ]

            if not tradeoff_evidence:
                reasons.append(
                    "hard_constraint_violation_lacks_evidence"
                )
                constraint_switch_blockers.append(
                    "missing_constraint_change_evidence"
                )

            if selected_alternative is None:
                reasons.append(
                    "hard_constraint_violation_lacks_admissible_alternative"
                )
                constraint_switch_blockers.append(
                    "missing_admissible_alternative"
                )

            return DecisionControlAssessment(
                task_id=state.task_id,
                step_id=information_gain.step_id,
                action=DecisionControlAction.STOP_VERIFY,
                selected_information_need_id=(
                    information_gain.selected_need_id
                ),
                reason_codes=tuple(reasons),
                blocker_refs=tuple(
                    dict.fromkeys(constraint_switch_blockers)
                ),
                verification_required=True,
            )

        if invalidated:
            evidence_bound_invalidated = set(
                compression.evidence_bound_invalidated_decision_refs
            )
            unbound_invalidated = tuple(
                ref for ref in invalidated if ref not in evidence_bound_invalidated
            )
            changed_basis_evidence = compression.decision_changing_evidence_refs
            selected_alternative = alternatives.selected_alternative_ref
            if (
                not unbound_invalidated
                and changed_basis_evidence
                and selected_alternative is not None
            ):
                return DecisionControlAssessment(
                    task_id=state.task_id,
                    step_id=information_gain.step_id,
                    action=DecisionControlAction.SWITCH,
                    selected_information_need_id=information_gain.selected_need_id,
                    selected_alternative_ref=selected_alternative,
                    reason_codes=(
                        "current_decision_basis_invalidated",
                        "changed_basis_required",
                        "changed_basis_evidence_present",
                        "stronger_admissible_alternative_present",
                    ),
                    changed_basis_refs=tuple(
                        dict.fromkeys(
                            (*invalidated, *changed_basis_evidence, selected_alternative)
                        )
                    ),
                )

            reasons = ["stop_verify_before_switch"]
            switch_blockers = list(invalidated)
            if unbound_invalidated:
                reasons.append("invalidated_decision_lacks_evidence_binding")
                switch_blockers.extend(unbound_invalidated)
            if not changed_basis_evidence:
                reasons.append("invalidated_decision_lacks_changed_basis_evidence")
                switch_blockers.append("missing_changed_basis_evidence")
            if selected_alternative is None:
                reasons.append("invalidated_decision_lacks_admissible_alternative")
                switch_blockers.append("missing_admissible_alternative")
            return DecisionControlAssessment(
                task_id=state.task_id,
                step_id=information_gain.step_id,
                action=DecisionControlAction.STOP_VERIFY,
                selected_information_need_id=information_gain.selected_need_id,
                reason_codes=tuple(reasons),
                blocker_refs=tuple(dict.fromkeys(switch_blockers)),
                verification_required=True,
            )

        return DecisionControlAssessment(
            task_id=state.task_id,
            step_id=information_gain.step_id,
            action=DecisionControlAction.CONTINUE,
            selected_information_need_id=information_gain.selected_need_id,
            selected_alternative_ref=alternatives.selected_alternative_ref,
            reason_codes=(
                "current_basis_supported",
                f"information_need:{selected.kind.value}",
            ),
        )
