"""Grouped, deterministic leak-free train/validation/held-out splitting."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256

from pydantic import Field, model_validator

from luna.contracts.base import LunaContractModel
from luna.trajectories.models import StructuredDecisionTrace


class DatasetSplit(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    HELD_OUT = "HELD_OUT"


class SplitAssignment(LunaContractModel):
    trajectory_id: str
    source_trajectory_id: str
    split_group_key: str
    task_family: str
    split: DatasetSplit


class LeakFreeSplitReport(LunaContractModel):
    assignments: tuple[SplitAssignment, ...] = Field(min_length=1)
    held_out_task_families: tuple[str, ...] = Field(min_length=1)
    contamination_detected: bool = False

    @model_validator(mode="after")
    def validate_no_leak(self) -> LeakFreeSplitReport:
        group_to_split: dict[str, DatasetSplit] = {}
        for assignment in self.assignments:
            previous = group_to_split.setdefault(
                assignment.split_group_key,
                assignment.split,
            )
            if previous is not assignment.split:
                raise ValueError("split group contamination detected")
        held_out = set(self.held_out_task_families)
        for assignment in self.assignments:
            if assignment.task_family in held_out:
                if assignment.split is not DatasetSplit.HELD_OUT:
                    raise ValueError("held-out task family leaked into train/validation")
            elif assignment.split is DatasetSplit.HELD_OUT:
                raise ValueError("held-out split must use explicitly held-out task families")
        if self.contamination_detected:
            raise ValueError("contaminated split report cannot validate")
        return self


class LeakFreeSplitter:
    """Keep task/repository/trajectory families grouped before transformation."""

    def __init__(
        self,
        *,
        held_out_task_families: tuple[str, ...],
        validation_percent: int = 10,
    ) -> None:
        cleaned = tuple(value.strip() for value in held_out_task_families)
        if not cleaned or any(not value for value in cleaned):
            raise ValueError("explicit held-out task families are required")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("held-out task families must be unique")
        if validation_percent < 1 or validation_percent > 50:
            raise ValueError("validation_percent must be between 1 and 50")
        self._held_out = cleaned
        self._validation_percent = validation_percent

    def assign(self, traces: tuple[StructuredDecisionTrace, ...]) -> LeakFreeSplitReport:
        if not traces:
            raise ValueError("split requires trajectories")
        held_out = set(self._held_out)
        group_assignments: dict[str, DatasetSplit] = {}
        assignments: list[SplitAssignment] = []
        for trace in traces:
            if trace.task_family in held_out:
                split = DatasetSplit.HELD_OUT
            else:
                assigned_split = group_assignments.get(trace.split_group_key)
                if assigned_split is None:
                    bucket = int(
                        sha256(trace.split_group_key.encode("utf-8")).hexdigest()[:8],
                        16,
                    ) % 100
                    split = (
                        DatasetSplit.VALIDATION
                        if bucket < self._validation_percent
                        else DatasetSplit.TRAIN
                    )
                    group_assignments[trace.split_group_key] = split
                else:
                    split = assigned_split
            assignments.append(
                SplitAssignment(
                    trajectory_id=str(trace.trajectory_id),
                    source_trajectory_id=trace.source_trajectory_id,
                    split_group_key=trace.split_group_key,
                    task_family=trace.task_family,
                    split=split,
                )
            )
        return LeakFreeSplitReport(
            assignments=tuple(assignments),
            held_out_task_families=self._held_out,
        )
