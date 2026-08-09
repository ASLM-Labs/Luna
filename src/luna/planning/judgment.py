"""Observable local-judgment contracts for Wave 2.

The records in this module contain decision-relevant facts and references only. They are
not raw or hidden chain-of-thought and grant no execution or completion authority.
"""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.decision import AssumptionStatus, DecisionStatus
from luna.contracts.plan import PlanStep
from luna.contracts.state import TaskState
from luna.contracts.task import TaskContract


class AcceptanceTargetKind(StrEnum):
    """Contract item that must be supported before completion."""

    REQUIRED_CONDITION = "REQUIRED_CONDITION"
    FORBIDDEN_OUTCOME_ABSENT = "FORBIDDEN_OUTCOME_ABSENT"
    EVIDENCE_REQUIREMENT = "EVIDENCE_REQUIREMENT"


class InformationNeedKind(StrEnum):
    """Decision-critical information class for the current step."""

    OBSERVE_STATE = "OBSERVE_STATE"
    RESOLVE_UNCERTAINTY = "RESOLVE_UNCERTAINTY"
    VERIFY_ACCEPTANCE = "VERIFY_ACCEPTANCE"


class AcceptanceTarget(LunaContractModel):
    """One externally checkable completion target derived from TaskContract."""

    target_id: str = Field(pattern=r"^acceptance:sha256:[0-9a-f]{64}$")
    kind: AcceptanceTargetKind
    text: str = Field(min_length=1, max_length=4000)
    evidence_requirements: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_requirements")
    @classmethod
    def validate_requirements(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("acceptance evidence requirements cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("acceptance evidence requirements must be unique")
        return cleaned


class AcceptanceBackchain(LunaContractModel):
    """Acceptance-first reverse-planning view of the task contract."""

    task_id: UUID
    targets: tuple[AcceptanceTarget, ...] = Field(min_length=1)

    @field_validator("targets")
    @classmethod
    def validate_targets(
        cls, values: tuple[AcceptanceTarget, ...]
    ) -> tuple[AcceptanceTarget, ...]:
        target_ids = tuple(item.target_id for item in values)
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("acceptance target IDs must be unique")
        return values


class InformationNeed(LunaContractModel):
    """One bounded uncertainty or evidence need whose resolution can change a decision."""

    need_id: str = Field(pattern=r"^information:sha256:[0-9a-f]{64}$")
    kind: InformationNeedKind
    description: str = Field(min_length=1, max_length=4000)
    acceptance_target_ids: tuple[str, ...] = Field(min_length=1)
    priority: int = Field(ge=1, le=100)

    @field_validator("acceptance_target_ids")
    @classmethod
    def validate_target_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("information need target IDs must be unique")
        return values


class InformationGainPlan(LunaContractModel):
    """Prioritized information needs for one plan step."""

    task_id: UUID
    step_id: UUID
    needs: tuple[InformationNeed, ...] = Field(min_length=1)
    selected_need_id: str = Field(pattern=r"^information:sha256:[0-9a-f]{64}$")
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("information-gain reason codes cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("information-gain reason codes must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_selection(self) -> InformationGainPlan:
        if self.selected_need_id not in {item.need_id for item in self.needs}:
            raise ValueError("selected information need must exist in needs")
        return self


class DecisionBasis(LunaContractModel):
    """Compressed, evidence-linked basis exposed to the policy model."""

    task_id: UUID
    step_id: UUID
    objective: str = Field(min_length=1, max_length=4000)
    selected_information_need_id: str = Field(pattern=r"^information:sha256:[0-9a-f]{64}$")
    acceptance_target_ids: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    assumption_refs: tuple[str, ...] = ()
    blocker_refs: tuple[str, ...] = ()
    hard_constraints: tuple[str, ...] = Field(min_length=1)
    verification_depth: str = Field(min_length=1, max_length=40)
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "acceptance_target_ids",
        "evidence_refs",
        "assumption_refs",
        "blocker_refs",
        "hard_constraints",
        "reason_codes",
    )
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("decision-basis entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("decision-basis entries must be unique")
        return cleaned


class LocalJudgmentContext(LunaContractModel):
    """Derived advisory context for one policy turn; it grants no authority."""

    acceptance: AcceptanceBackchain
    information_gain: InformationGainPlan
    decision_basis: DecisionBasis


class LocalJudgmentBuilder:
    """Build acceptance, information-gain, and decision-basis records deterministically."""

    @staticmethod
    def _stable_id(prefix: str, kind: str, text: str) -> str:
        digest = sha256(f"{kind}\0{text}".encode()).hexdigest()
        return f"{prefix}:sha256:{digest}"

    def acceptance_from_contract(self, contract: TaskContract) -> AcceptanceBackchain:
        common_evidence = contract.evidence_required
        targets: list[AcceptanceTarget] = []

        for condition in contract.required_conditions:
            targets.append(
                AcceptanceTarget(
                    target_id=self._stable_id(
                        "acceptance", AcceptanceTargetKind.REQUIRED_CONDITION.value, condition
                    ),
                    kind=AcceptanceTargetKind.REQUIRED_CONDITION,
                    text=condition,
                    evidence_requirements=common_evidence,
                )
            )
        for outcome in contract.forbidden_outcomes:
            targets.append(
                AcceptanceTarget(
                    target_id=self._stable_id(
                        "acceptance", AcceptanceTargetKind.FORBIDDEN_OUTCOME_ABSENT.value, outcome
                    ),
                    kind=AcceptanceTargetKind.FORBIDDEN_OUTCOME_ABSENT,
                    text=outcome,
                    evidence_requirements=common_evidence,
                )
            )
        for requirement in contract.evidence_required:
            targets.append(
                AcceptanceTarget(
                    target_id=self._stable_id(
                        "acceptance", AcceptanceTargetKind.EVIDENCE_REQUIREMENT.value, requirement
                    ),
                    kind=AcceptanceTargetKind.EVIDENCE_REQUIREMENT,
                    text=requirement,
                    evidence_requirements=(requirement,),
                )
            )

        return AcceptanceBackchain(task_id=contract.task_id, targets=tuple(targets))

    def acceptance_backchain(self, state: TaskState) -> AcceptanceBackchain:
        return self.acceptance_from_contract(state.contract)

    def information_gain(
        self,
        *,
        state: TaskState,
        step: PlanStep,
        acceptance: AcceptanceBackchain,
    ) -> InformationGainPlan:
        if not state.plan or all(item.step_id != step.step_id for item in state.plan):
            raise ValueError("information-gain step must belong to authoritative task plan")
        target_ids = tuple(item.target_id for item in acceptance.targets)
        needs: list[InformationNeed] = []
        reasons: list[str] = []

        decision_state = state.decision_state
        critical_gap = False
        if decision_state is not None:
            critical_gap = any(
                item.critical and item.status is not AssumptionStatus.SUPPORTED
                for item in decision_state.assumptions
            )
        if state.contract.unknowns or critical_gap:
            description = "Resolve task-critical unknowns or unsupported critical assumptions."
            needs.append(
                InformationNeed(
                    need_id=self._stable_id(
                        "information", InformationNeedKind.RESOLVE_UNCERTAINTY.value, description
                    ),
                    kind=InformationNeedKind.RESOLVE_UNCERTAINTY,
                    description=description,
                    acceptance_target_ids=target_ids,
                    priority=100,
                )
            )
            reasons.append("critical_uncertainty_present")

        is_last_step = step.sequence == max(item.sequence for item in state.plan)
        if is_last_step:
            description = "Collect evidence that directly supports every acceptance target."
            kind = InformationNeedKind.VERIFY_ACCEPTANCE
            priority = 90
            reasons.append("final_step_requires_acceptance_evidence")
        else:
            description = "Observe the decision-critical state before selecting the next action."
            kind = InformationNeedKind.OBSERVE_STATE
            priority = 80
            reasons.append("observe_before_action")

        needs.append(
            InformationNeed(
                need_id=self._stable_id("information", kind.value, description),
                kind=kind,
                description=description,
                acceptance_target_ids=target_ids,
                priority=priority,
            )
        )
        ordered = tuple(sorted(needs, key=lambda item: (-item.priority, item.need_id)))
        return InformationGainPlan(
            task_id=state.task_id,
            step_id=step.step_id,
            needs=ordered,
            selected_need_id=ordered[0].need_id,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    def decision_basis(
        self,
        *,
        state: TaskState,
        step: PlanStep,
        acceptance: AcceptanceBackchain,
        information_gain: InformationGainPlan,
        verification_depth: str,
    ) -> DecisionBasis:
        evidence_refs = [f"evidence:{value}" for value in state.evidence_ids[-8:]]
        evidence_refs.extend(f"observation:{value}" for value in state.observation_ids[-8:])
        assumption_refs: list[str] = []
        blocker_refs = list(state.failed_assumptions[-8:])
        reasons = ["contract_bound", "evidence_linked", "authority_preserved"]

        if state.decision_state is not None:
            for assumption in state.decision_state.assumptions:
                if assumption.status in {AssumptionStatus.SUPPORTED, AssumptionStatus.UNVERIFIED}:
                    assumption_refs.append(f"assumption:{assumption.assumption_id}")
                if (
                    assumption.critical
                    and assumption.status is not AssumptionStatus.SUPPORTED
                ) or assumption.status in {
                    AssumptionStatus.CONTRADICTED,
                    AssumptionStatus.INVALIDATED,
                }:
                    blocker_refs.append(
                        f"assumption:{assumption.assumption_id}:{assumption.status.value}"
                    )
                evidence_refs.extend(assumption.evidence_refs)
            for decision in state.decision_state.decisions:
                if decision.status in {DecisionStatus.BLOCKED, DecisionStatus.INVALIDATED}:
                    blocker_refs.append(f"decision:{decision.decision_id}:{decision.status.value}")

        scope = state.contract.scope
        hard_constraints = (
            f"risk_level:{state.contract.risk_level.value}",
            f"write_allowed:{str(scope.write_allowed).lower()}",
            f"network_allowed:{str(scope.network_allowed).lower()}",
            f"process_allowed:{str(scope.process_allowed).lower()}",
            *(f"forbidden_outcome:{item}" for item in state.contract.forbidden_outcomes),
        )
        if blocker_refs:
            reasons.append("blockers_present")

        return DecisionBasis(
            task_id=state.task_id,
            step_id=step.step_id,
            objective=state.contract.objective,
            selected_information_need_id=information_gain.selected_need_id,
            acceptance_target_ids=tuple(item.target_id for item in acceptance.targets),
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            assumption_refs=tuple(dict.fromkeys(assumption_refs)),
            blocker_refs=tuple(dict.fromkeys(blocker_refs)),
            hard_constraints=hard_constraints,
            verification_depth=verification_depth,
            reason_codes=tuple(reasons),
        )

    def build(
        self,
        *,
        state: TaskState,
        step: PlanStep,
        verification_depth: str,
    ) -> LocalJudgmentContext:
        acceptance = self.acceptance_backchain(state)
        information_gain = self.information_gain(
            state=state,
            step=step,
            acceptance=acceptance,
        )
        decision_basis = self.decision_basis(
            state=state,
            step=step,
            acceptance=acceptance,
            information_gain=information_gain,
            verification_depth=verification_depth,
        )
        return LocalJudgmentContext(
            acceptance=acceptance,
            information_gain=information_gain,
            decision_basis=decision_basis,
        )
