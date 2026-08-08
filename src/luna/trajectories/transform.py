"""Training transformation that preserves observable decisions and split boundaries."""

from __future__ import annotations

from pydantic import Field, model_validator

from luna.cognition import FailureLabel
from luna.contracts.base import LunaContractModel
from luna.trajectories.models import StructuredDecisionTrace, TraceStage
from luna.trajectories.split import DatasetSplit


class TrainingExample(LunaContractModel):
    example_id: str = Field(min_length=1, max_length=600)
    source_trajectory_id: str
    split: DatasetSplit
    context: tuple[str, ...] = Field(min_length=1)
    target: str = Field(min_length=1, max_length=16000)
    target_stage: TraceStage
    target_only_loss: bool = True
    failure_labels: tuple[FailureLabel, ...] = ()
    provenance_refs: tuple[str, ...] = Field(min_length=1)
    contains_raw_hidden_chain_of_thought: bool = False

    @model_validator(mode="after")
    def validate_training_boundary(self) -> TrainingExample:
        if self.split is DatasetSplit.HELD_OUT:
            raise ValueError("held-out trajectories cannot become training examples")
        if not self.target_only_loss:
            raise ValueError("Phase 19 training examples require target-only loss")
        if self.contains_raw_hidden_chain_of_thought:
            raise ValueError("raw hidden chain-of-thought is forbidden")
        return self


class TrainingTransformer:
    """Create next-observable-decision targets without exposing hidden reasoning."""

    def transform(
        self,
        *,
        trace: StructuredDecisionTrace,
        split: DatasetSplit,
    ) -> tuple[TrainingExample, ...]:
        if split is DatasetSplit.HELD_OUT:
            raise ValueError("held-out evaluation data cannot enter training transformation")
        if not trace.license_reviewed or not trace.pii_reviewed:
            raise ValueError("training transformation requires license and PII review")
        examples: list[TrainingExample] = []
        visible: list[str] = [f"TASK: {trace.task_summary}"]
        for event in trace.events[1:]:
            if event.stage in {
                TraceStage.ACTION,
                TraceStage.REPLAN,
                TraceStage.VERIFICATION,
                TraceStage.FINAL,
            }:
                examples.append(
                    TrainingExample(
                        example_id=(
                            f"{trace.source_trajectory_id}:{event.sequence}:{event.stage.value}"
                        ),
                        source_trajectory_id=trace.source_trajectory_id,
                        split=split,
                        context=tuple(visible),
                        target=f"{event.stage.value}: {event.summary}",
                        target_stage=event.stage,
                        failure_labels=trace.failure_labels,
                        provenance_refs=trace.provenance_refs,
                    )
                )
            visible.append(f"{event.stage.value}: {event.summary}")
        return tuple(examples)
