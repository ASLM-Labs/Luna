"""Deterministic short-plan baseline for Phase 3."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from luna.contracts.enums import ObservationStatus, RiskLevel
from luna.contracts.plan import ExpectedObservation, PlanStep
from luna.contracts.specification import IntentConstraintJudgment
from luna.intent.models import IntentKind, RequestedAction
from luna.planning.judgment import LocalJudgmentBuilder
from luna.planning.models import TaskComplexity, TaskPlan
from luna.preparation import PreparationStatus, TaskPreparation


class AdaptivePlanner:
    """Create a compact plan from explicit contract, context, and risk."""

    def classify(self, preparation: TaskPreparation) -> TaskComplexity:
        contract = preparation.contract
        if preparation.status is not PreparationStatus.READY_FOR_PLANNING or contract is None:
            raise ValueError("planning requires READY_FOR_PLANNING preparation")

        write_actions = {
            RequestedAction.MODIFY,
            RequestedAction.CREATE,
            RequestedAction.DELETE,
        }
        if (
            contract.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            or len(contract.required_conditions) > 3
            or len(preparation.context.sources) > 5
        ):
            return TaskComplexity.COMPLEX
        if write_actions.intersection(preparation.intent.actions):
            return TaskComplexity.STANDARD
        if preparation.intent.kind is IntentKind.RESEARCH:
            return TaskComplexity.STANDARD
        if (
            contract.risk_level is RiskLevel.LOW
            and len(contract.required_conditions) <= 2
            and len(preparation.context.sources) <= 3
        ):
            return TaskComplexity.SIMPLE
        return TaskComplexity.STANDARD

    @staticmethod
    def _chain(descriptions: Sequence[str]) -> tuple[PlanStep, ...]:
        steps: list[PlanStep] = []
        previous_id: UUID | None = None
        for sequence, description in enumerate(descriptions, start=1):
            dependencies = () if previous_id is None else (previous_id,)
            step = PlanStep(
                sequence=sequence,
                description=description,
                depends_on=dependencies,
            )
            steps.append(step)
            previous_id = step.step_id
        return tuple(steps)

    @staticmethod
    def _change_expectation() -> ExpectedObservation:
        return ExpectedObservation(
            summary="The minimal scoped change should succeed without protected-path impact.",
            expected_status=ObservationStatus.SUCCESS,
            failure_signals=(
                "protected_path_changed",
                "scope_violation",
                "non_zero_exit",
                "test_failure",
            ),
            verification_method="Inspect the change manifest, exit status, and required tests.",
            high_impact=True,
        )

    def plan(
        self,
        preparation: TaskPreparation,
        *,
        specification_judgment: IntentConstraintJudgment | None = None,
    ) -> TaskPlan:
        contract = preparation.contract
        if preparation.status is not PreparationStatus.READY_FOR_PLANNING or contract is None:
            raise ValueError("planning requires READY_FOR_PLANNING preparation")

        specification = specification_judgment or preparation.specification_judgment
        if specification.task_id != contract.task_id:
            raise ValueError("planning specification must match task contract")
        if specification.literal_objective != contract.objective:
            raise ValueError("planning specification must preserve contract objective")

        complexity = self.classify(preparation)
        acceptance = LocalJudgmentBuilder().acceptance_from_basis(
            contract=contract,
            specification=specification,
        )
        actions = set(preparation.intent.actions)
        write_actions = {
            RequestedAction.MODIFY,
            RequestedAction.CREATE,
            RequestedAction.DELETE,
        }

        significant_ids: tuple[UUID, ...] = ()
        if write_actions.intersection(actions):
            descriptions = [
                "Inspect the declared target and confirm the smallest task-linked change.",
                "Apply the minimal change inside the declared write scope.",
                "Run the contract-required verification and capture structured evidence.",
            ]
            if complexity is TaskComplexity.COMPLEX:
                descriptions.insert(
                    0,
                    "Review risk, scope, and assumptions before any write-capable action.",
                )
            steps = list(self._chain(descriptions))
            change_index = 2 if complexity is TaskComplexity.COMPLEX else 1
            change_step = steps[change_index]
            steps[change_index] = PlanStep(
                step_id=change_step.step_id,
                sequence=change_step.sequence,
                description=change_step.description,
                status=change_step.status,
                expectation=self._change_expectation(),
                depends_on=change_step.depends_on,
                status_reason=change_step.status_reason,
            )
            significant_ids = (change_step.step_id,)
            final_steps = tuple(steps)
        elif preparation.intent.kind is IntentKind.RESEARCH:
            final_steps = self._chain(
                (
                    "Identify the required sources and make missing coverage explicit.",
                    "Compare source evidence against each contract requirement.",
                    "Synthesize the result while preserving uncertainty and source boundaries.",
                )
            )
        elif complexity is TaskComplexity.SIMPLE:
            final_steps = self._chain(
                (
                    "Inspect the observed context and produce requirement-linked evidence.",
                )
            )
        else:
            final_steps = self._chain(
                (
                    "Inspect the observed context and validate the task assumptions.",
                    "Produce and verify the requirement-linked result.",
                )
            )

        assumptions = (
            "Observed context remains current until the first action.",
            "Declared scope reflects the owner's intended boundary.",
        )
        return TaskPlan(
            task_id=contract.task_id,
            objective=specification.reconstructed_objective,
            complexity=complexity,
            steps=final_steps,
            significant_step_ids=significant_ids,
            acceptance_target_ids=tuple(item.target_id for item in acceptance.targets),
            assumptions=assumptions,
        )
