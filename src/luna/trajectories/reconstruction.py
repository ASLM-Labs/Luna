"""Deterministic reconstruction of already-observable source trace rows."""

from __future__ import annotations

from pydantic import Field, model_validator

from luna.cognition import FailureLabel
from luna.contracts.base import LunaContractModel
from luna.tools.models import ToolArgumentValue
from luna.trajectories.models import (
    DatasetTaxonomy,
    ObservableDecisionEvent,
    StructuredDecisionTrace,
    TraceStage,
    TrajectoryOutcome,
)


class SourceTraceRow(LunaContractModel):
    source_trajectory_id: str = Field(min_length=1, max_length=500)
    sequence: int = Field(ge=0)
    stage: TraceStage
    summary: str = Field(min_length=1, max_length=8000)
    decision_basis: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    tool_name: str | None = Field(default=None, max_length=120)
    tool_arguments: dict[str, ToolArgumentValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tool_binding(self) -> SourceTraceRow:
        if self.tool_arguments and self.tool_name is None:
            raise ValueError("tool arguments require tool_name")
        return self


class TrajectoryReconstructor:
    """Build one canonical trace without inventing missing observations."""

    def reconstruct(
        self,
        *,
        rows: tuple[SourceTraceRow, ...],
        trajectory_family: str,
        task_family: str,
        repository_family: str,
        taxonomy: DatasetTaxonomy,
        task_summary: str,
        outcome: TrajectoryOutcome,
        failure_labels: tuple[FailureLabel, ...] = (),
        provenance_refs: tuple[str, ...],
        license_reviewed: bool,
        pii_reviewed: bool,
    ) -> StructuredDecisionTrace:
        if not rows:
            raise ValueError("trajectory reconstruction requires source rows")
        source_ids = {row.source_trajectory_id for row in rows}
        if len(source_ids) != 1:
            raise ValueError("source rows must belong to one trajectory")
        ordered = tuple(sorted(rows, key=lambda row: row.sequence))
        if tuple(row.sequence for row in ordered) != tuple(range(len(ordered))):
            raise ValueError("missing/duplicate source sequence must be repaired or dropped")
        return StructuredDecisionTrace(
            source_trajectory_id=ordered[0].source_trajectory_id,
            trajectory_family=trajectory_family,
            task_family=task_family,
            repository_family=repository_family,
            taxonomy=taxonomy,
            task_summary=task_summary,
            events=tuple(
                ObservableDecisionEvent(
                    sequence=row.sequence,
                    stage=row.stage,
                    summary=row.summary,
                    decision_basis=row.decision_basis,
                    evidence_refs=row.evidence_refs,
                    tool_name=row.tool_name,
                    tool_arguments=row.tool_arguments,
                )
                for row in ordered
            ),
            outcome=outcome,
            failure_labels=failure_labels,
            provenance_refs=provenance_refs,
            license_reviewed=license_reviewed,
            pii_reviewed=pii_reviewed,
        )
