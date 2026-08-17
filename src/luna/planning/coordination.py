"""C7 observable multi-worker coordination over bounded task evidence.

C7 selects an execution topology and bounded worker assignments. It does not
execute workers, widen task scope, allocate runtime resources, mutate task
state, or grant runtime, execution, or completion authority.
"""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.plan import PlanStep
from luna.contracts.task import TaskContract


class CoordinationMode(StrEnum):
    """Execution topology selected for one bounded coordination decision."""

    SOLO = "SOLO"
    PARALLEL_WORKERS = "PARALLEL_WORKERS"
    INDEPENDENT_REVIEW = "INDEPENDENT_REVIEW"


class WorkerRole(StrEnum):
    """Task-local worker role; roles do not create persistent specialist identity."""

    PARALLEL = "PARALLEL"
    INDEPENDENT_REVIEWER = "INDEPENDENT_REVIEWER"


class WorkerAssignment(LunaContractModel):
    """One evidence-bound, non-authoritative assignment for an independent worker."""

    assignment_id: str = Field(pattern=r"^assignment:sha256:[0-9a-f]{64}$")
    task_id: UUID
    role: WorkerRole
    objective: str = Field(min_length=1, max_length=4000)
    source_task_revision: int = Field(ge=0)
    source_step_ids: tuple[UUID, ...] = Field(min_length=1)
    acceptance_target_refs: tuple[str, ...] = ()
    allowed_path_refs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    assignment_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_refs: tuple[str, ...] = Field(min_length=1)
    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator(
        "acceptance_target_refs",
        "allowed_path_refs",
        "depends_on",
        "provenance_refs",
    )
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("worker-assignment references cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("worker-assignment references must be unique")
        return cleaned

    @field_validator("source_step_ids")
    @classmethod
    def validate_source_steps(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("worker-assignment source steps must be unique")
        return values

    @model_validator(mode="after")
    def validate_assignment_identity(self) -> Self:
        expected_id = f"assignment:sha256:{self.assignment_basis_fingerprint}"
        if self.assignment_id != expected_id:
            raise ValueError("worker assignment ID must derive from its basis fingerprint")
        return self


class CoordinationPlan(LunaContractModel):
    """Deterministic, non-authoritative C7 topology and assignment plan."""

    task_id: UUID
    source_task_revision: int = Field(ge=0)
    capability_selection_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: CoordinationMode
    assignments: tuple[WorkerAssignment, ...] = ()
    coordination_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_codes: tuple[str, ...] = Field(min_length=1)
    provenance_refs: tuple[str, ...] = Field(min_length=1)
    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_authority: Literal[False] = False

    @field_validator("reason_codes", "provenance_refs")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("coordination-plan references cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("coordination-plan references must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_topology(self) -> Self:
        if any(item.task_id != self.task_id for item in self.assignments):
            raise ValueError("all worker assignments must belong to the coordination task")
        if any(
            item.source_task_revision != self.source_task_revision
            for item in self.assignments
        ):
            raise ValueError(
                "all worker assignments must share the coordination source revision"
            )
        if any(item.depends_on for item in self.assignments):
            raise ValueError(
                "C7 Patch1 worker assignments must remain dependency-free"
            )

        assignment_ids = tuple(
            item.assignment_id for item in self.assignments
        )
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("coordination assignments must have unique IDs")

        assignment_bases = tuple(
            item.assignment_basis_fingerprint for item in self.assignments
        )
        if len(assignment_bases) != len(set(assignment_bases)):
            raise ValueError(
                "coordination assignments must have unique basis fingerprints"
            )

        if self.mode is CoordinationMode.SOLO:
            if self.assignments:
                raise ValueError("SOLO coordination cannot contain worker assignments")
            return self

        if self.mode is CoordinationMode.PARALLEL_WORKERS:
            if len(self.assignments) < 2:
                raise ValueError(
                    "PARALLEL_WORKERS coordination requires at least two assignments"
                )
            if any(item.role is not WorkerRole.PARALLEL for item in self.assignments):
                raise ValueError(
                    "PARALLEL_WORKERS coordination may contain only parallel workers"
                )
            return self

        if len(self.assignments) != 1:
            raise ValueError(
                "INDEPENDENT_REVIEW coordination requires exactly one reviewer assignment"
            )
        if self.assignments[0].role is not WorkerRole.INDEPENDENT_REVIEWER:
            raise ValueError(
                "INDEPENDENT_REVIEW coordination requires an independent reviewer"
            )
        return self


class GeneralCoordinationPlanner:
    """Select bounded C7 topology without executing or authorizing workers."""

    @staticmethod
    def _fingerprint(payload: dict[str, object]) -> str:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def _assignment(
        cls,
        *,
        task_id: UUID,
        role: WorkerRole,
        objective: str,
        source_task_revision: int,
        source_step_ids: tuple[UUID, ...],
        acceptance_target_refs: tuple[str, ...],
        allowed_path_refs: tuple[str, ...],
        capability_selection_basis_fingerprint: str,
    ) -> WorkerAssignment:
        provenance_refs = (
            f"task:{task_id}",
            f"task_revision:{source_task_revision}",
            f"c6:{capability_selection_basis_fingerprint}",
            *(f"step:{step_id}" for step_id in source_step_ids),
        )
        basis = cls._fingerprint(
            {
                "acceptance_target_refs": acceptance_target_refs,
                "allowed_path_refs": allowed_path_refs,
                "capability_selection_basis_fingerprint": (
                    capability_selection_basis_fingerprint
                ),
                "objective": objective,
                "role": role.value,
                "source_step_ids": tuple(str(step_id) for step_id in source_step_ids),
                "task_id": str(task_id),
            }
        )
        return WorkerAssignment(
            assignment_id=f"assignment:sha256:{basis}",
            task_id=task_id,
            role=role,
            objective=objective,
            source_task_revision=source_task_revision,
            source_step_ids=source_step_ids,
            acceptance_target_refs=acceptance_target_refs,
            allowed_path_refs=allowed_path_refs,
            assignment_basis_fingerprint=basis,
            provenance_refs=provenance_refs,
        )

    def plan(
        self,
        *,
        task_contract: TaskContract,
        source_task_revision: int,
        steps: tuple[PlanStep, ...],
        capability_selection_basis_fingerprint: str,
        acceptance_target_refs: tuple[str, ...] = (),
        allowed_path_refs: tuple[str, ...] = (),
        parallelizable_step_ids: tuple[UUID, ...] = (),
        independent_review_required: bool = False,
        independent_review_step_id: UUID | None = None,
        worker_capacity: int = 1,
    ) -> CoordinationPlan:
        """Return one deterministic topology over caller-supplied coordination evidence."""
        if source_task_revision < 0:
            raise ValueError("source task revision cannot be negative")
        if worker_capacity < 1:
            raise ValueError("worker capacity must be at least one")

        step_ids = tuple(step.step_id for step in steps)
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("coordination input step IDs must be unique")
        steps_by_id = {step.step_id: step for step in steps}

        cleaned_acceptance_refs = tuple(
            value.strip() for value in acceptance_target_refs
        )
        cleaned_allowed_paths = tuple(value.strip() for value in allowed_path_refs)

        if any(not value for value in cleaned_acceptance_refs):
            raise ValueError("acceptance target refs cannot be blank")
        if len(cleaned_acceptance_refs) != len(set(cleaned_acceptance_refs)):
            raise ValueError("acceptance target refs must be unique")
        if any(not value for value in cleaned_allowed_paths):
            raise ValueError("allowed path refs cannot be blank")
        if len(cleaned_allowed_paths) != len(set(cleaned_allowed_paths)):
            raise ValueError("allowed path refs must be unique")

        task_allowed_paths = set(task_contract.scope.allowed_paths)
        if not set(cleaned_allowed_paths).issubset(task_allowed_paths):
            raise ValueError(
                "C7 worker path bounds must remain within TaskContract scope"
            )

        if len(parallelizable_step_ids) != len(set(parallelizable_step_ids)):
            raise ValueError("parallelizable step IDs must be unique")
        if any(step_id not in steps_by_id for step_id in parallelizable_step_ids):
            raise ValueError("parallelizable step must exist in the supplied plan")
        if any(
            dependency not in steps_by_id
            for step in steps
            for dependency in step.depends_on
        ):
            raise ValueError("coordination input plan contains an unknown dependency")

        canonical_parallelizable_step_ids = tuple(
            sorted(
                parallelizable_step_ids,
                key=lambda step_id: steps_by_id[step_id].sequence,
            )
        )
        parallelizable_set = set(canonical_parallelizable_step_ids)

        for step_id in canonical_parallelizable_step_ids:
            pending = list(steps_by_id[step_id].depends_on)
            transitive_dependencies: set[UUID] = set()

            while pending:
                dependency = pending.pop()
                if dependency == step_id:
                    raise ValueError("coordination input plan contains a dependency cycle")
                if dependency in transitive_dependencies:
                    continue
                transitive_dependencies.add(dependency)
                pending.extend(steps_by_id[dependency].depends_on)

            if parallelizable_set.intersection(transitive_dependencies):
                raise ValueError(
                    "parallelizable steps cannot depend on one another"
                )

        if (
            independent_review_step_id is not None
            and independent_review_step_id not in steps_by_id
        ):
            raise ValueError("independent review step must exist in the supplied plan")
        if independent_review_required and independent_review_step_id is None:
            raise ValueError(
                "independent review requires an explicit step to review"
            )
        if not independent_review_required and independent_review_step_id is not None:
            raise ValueError(
                "independent review step cannot be supplied unless review is required"
            )

        assignments: tuple[WorkerAssignment, ...]
        reason_codes: tuple[str, ...]

        if independent_review_required and worker_capacity >= 2:
            assert independent_review_step_id is not None
            review_step = steps_by_id[independent_review_step_id]
            assignments = (
                self._assignment(
                    task_id=task_contract.task_id,
                    role=WorkerRole.INDEPENDENT_REVIEWER,
                    objective=review_step.description,
                    source_task_revision=source_task_revision,
                    source_step_ids=(review_step.step_id,),
                    acceptance_target_refs=cleaned_acceptance_refs,
                    allowed_path_refs=cleaned_allowed_paths,
                    capability_selection_basis_fingerprint=(
                        capability_selection_basis_fingerprint
                    ),
                ),
            )
            mode = CoordinationMode.INDEPENDENT_REVIEW
            reason_codes = (
                "independent_review_required",
                "multi_worker_capacity_available",
                "main_conclusion_not_required_by_reviewer_assignment",
            )
        elif len(canonical_parallelizable_step_ids) >= 2 and worker_capacity >= 2:
            selected_ids = canonical_parallelizable_step_ids[:worker_capacity]
            assignments = tuple(
                self._assignment(
                    task_id=task_contract.task_id,
                    role=WorkerRole.PARALLEL,
                    objective=steps_by_id[step_id].description,
                    source_task_revision=source_task_revision,
                    source_step_ids=(step_id,),
                    acceptance_target_refs=cleaned_acceptance_refs,
                    allowed_path_refs=cleaned_allowed_paths,
                    capability_selection_basis_fingerprint=(
                        capability_selection_basis_fingerprint
                    ),
                )
                for step_id in selected_ids
            )
            mode = CoordinationMode.PARALLEL_WORKERS
            reason_codes = (
                "independent_parallel_steps_available",
                "multi_worker_capacity_available",
            )
        else:
            assignments = ()
            mode = CoordinationMode.SOLO
            reasons = ["solo_default_preserved"]
            if independent_review_required and worker_capacity < 2:
                reasons.append("worker_capacity_insufficient_for_independent_review")
            elif len(canonical_parallelizable_step_ids) >= 2 and worker_capacity < 2:
                reasons.append("worker_capacity_insufficient_for_parallel_workers")
            else:
                reasons.append("insufficient_independent_work_for_multi_worker_topology")
            reason_codes = tuple(reasons)

        provenance_refs = (
            f"task:{task_contract.task_id}",
            f"task_revision:{source_task_revision}",
            f"c6:{capability_selection_basis_fingerprint}",
        )

        coordination_basis = self._fingerprint(
            {
                "assignments": tuple(
                    item.model_dump(mode="json") for item in assignments
                ),
                "capability_selection_basis_fingerprint": (
                    capability_selection_basis_fingerprint
                ),
                "mode": mode.value,
                "reason_codes": reason_codes,
                "source_task_revision": source_task_revision,
                "task_id": str(task_contract.task_id),
                "worker_capacity": worker_capacity,
            }
        )

        return CoordinationPlan(
            task_id=task_contract.task_id,
            source_task_revision=source_task_revision,
            capability_selection_basis_fingerprint=(
                capability_selection_basis_fingerprint
            ),
            mode=mode,
            assignments=assignments,
            coordination_basis_fingerprint=coordination_basis,
            reason_codes=reason_codes,
            provenance_refs=provenance_refs,
        )
