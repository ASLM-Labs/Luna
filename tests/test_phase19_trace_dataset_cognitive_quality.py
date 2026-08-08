from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from luna.cognition import (
    CognitiveComparisonVerdict,
    CognitiveDimension,
    CognitiveScorecard,
    ConfidenceBand,
    EvidenceState,
    FailureLabel,
    FrozenCognitiveBaseline,
    SelfCorrectionAssessment,
    UncertaintyDirective,
    assess_uncertainty,
    compare_to_baseline,
)
from luna.trajectories import (
    DatasetSplit,
    DatasetTaxonomy,
    LeakFreeSplitter,
    SemanticAction,
    SourceTraceRow,
    StructuredDecisionTrace,
    ToolEventNormalizer,
    ToolNormalizationStatus,
    TraceStage,
    TrainingTransformer,
    TrajectoryOutcome,
    TrajectoryReconstructor,
)


def _rows(source_id: str = "source-1") -> tuple[SourceTraceRow, ...]:
    return (
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=0,
            stage=TraceStage.TASK,
            summary="Fix the failing quality gate.",
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=1,
            stage=TraceStage.PLAN,
            summary="Inspect the first failing gate before editing.",
            decision_basis=("gate-output",),
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=2,
            stage=TraceStage.ACTION,
            summary="Run the focused verifier.",
            tool_name="pytest",
            tool_arguments={"argv": ["pytest", "-q"]},
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=3,
            stage=TraceStage.OBSERVATION,
            summary="Verifier exposes an import-order failure only.",
            evidence_refs=("ruff:I001",),
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=4,
            stage=TraceStage.REPLAN,
            summary="Change only import ordering; preserve behavior.",
            decision_basis=("ruff:I001",),
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=5,
            stage=TraceStage.VERIFICATION,
            summary="Focused and full gates pass.",
            evidence_refs=("full-gate:PASS",),
        ),
        SourceTraceRow(
            source_trajectory_id=source_id,
            sequence=6,
            stage=TraceStage.FINAL,
            summary="Import-order regression fixed with no behavior change.",
            evidence_refs=("full-gate:PASS",),
        ),
    )


def _trace(
    *,
    source_id: str = "source-1",
    task_family: str = "quality-gate-debug",
    repository_family: str = "luna",
    trajectory_family: str = "ruff-import-order",
) -> StructuredDecisionTrace:
    return TrajectoryReconstructor().reconstruct(
        rows=_rows(source_id),
        trajectory_family=trajectory_family,
        task_family=task_family,
        repository_family=repository_family,
        taxonomy=DatasetTaxonomy.IMPLEMENTATION_CODING,
        task_summary="Fix the failing quality gate.",
        outcome=TrajectoryOutcome.SUCCESS,
        provenance_refs=(f"trace:{source_id}",),
        license_reviewed=True,
        pii_reviewed=True,
    )


def _scores(value: float) -> dict[CognitiveDimension, float]:
    return {dimension: value for dimension in CognitiveDimension}


def test_structured_trace_is_observable_and_rejects_raw_hidden_chain_of_thought() -> None:
    trace = _trace()
    assert trace.events[0].stage is TraceStage.TASK
    assert trace.events[-1].stage is TraceStage.FINAL
    assert trace.raw_hidden_chain_of_thought_included is False

    payload = trace.model_dump(mode="python")
    payload["raw_hidden_chain_of_thought_included"] = True
    with pytest.raises(ValidationError, match="raw hidden chain-of-thought is forbidden"):
        StructuredDecisionTrace.model_validate(payload)


def test_reconstruction_rejects_missing_source_rows_instead_of_inventing_them() -> None:
    rows = list(_rows())
    rows.pop(3)
    with pytest.raises(ValueError, match="repaired or dropped"):
        TrajectoryReconstructor().reconstruct(
            rows=tuple(rows),
            trajectory_family="family",
            task_family="task",
            repository_family="repo",
            taxonomy=DatasetTaxonomy.IMPLEMENTATION_CODING,
            task_summary="Task",
            outcome=TrajectoryOutcome.SUCCESS,
            provenance_refs=("source",),
            license_reviewed=True,
            pii_reviewed=True,
        )


def test_failure_taxonomy_covers_cognitive_and_tool_failure_sources() -> None:
    assert {label.value for label in FailureLabel} == {
        "INTENT_ERROR",
        "CONTEXT_ERROR",
        "PLANNING_ERROR",
        "TOOL_SELECTION_ERROR",
        "TOOL_ARGUMENT_ERROR",
        "EXECUTION_ERROR",
        "OBSERVATION_INTERPRETATION_ERROR",
        "EVIDENCE_ERROR",
        "VERIFICATION_ERROR",
        "UNCERTAINTY_ERROR",
        "SELF_CORRECTION_ERROR",
    }


def test_failed_trace_requires_specific_failure_labels() -> None:
    with pytest.raises(ValidationError, match="failure taxonomy labels"):
        StructuredDecisionTrace(
            source_trajectory_id="failed-1",
            trajectory_family="family",
            task_family="task",
            repository_family="repo",
            taxonomy=DatasetTaxonomy.FAILED_RISKY_ACTION,
            task_summary="Failed task",
            events=(
                _trace().events[0].model_copy(update={"sequence": 0}),
                _trace().events[-1].model_copy(update={"sequence": 1}),
            ),
            outcome=TrajectoryOutcome.FAILED,
            provenance_refs=("trace:failed",),
            license_reviewed=True,
            pii_reviewed=True,
        )


def test_tool_normalization_maps_semantics_without_creating_executable_request() -> None:
    normalized = ToolEventNormalizer().normalize(
        source_tool_name="shell",
        arguments={"argv": ["python", "-m", "pytest"]},
    )
    assert normalized.status is ToolNormalizationStatus.MAPPED
    assert normalized.semantic_action is SemanticAction.PROCESS
    assert normalized.luna_tool_name == "process.run_argv"
    assert normalized.executable_request_created is False


def test_unknown_tool_is_preserved_as_unmapped_not_guessed() -> None:
    normalized = ToolEventNormalizer().normalize(source_tool_name="mystery_wrapper")
    assert normalized.status is ToolNormalizationStatus.UNMAPPED
    assert normalized.semantic_action is SemanticAction.OTHER
    assert normalized.luna_tool_name is None


def test_leak_free_split_keeps_family_group_together() -> None:
    first = _trace(source_id="a")
    second = _trace(source_id="b")
    report = LeakFreeSplitter(
        held_out_task_families=("unseen-held-out",),
        validation_percent=20,
    ).assign((first, second))
    assert report.assignments[0].split == report.assignments[1].split
    assert report.assignments[0].split is not DatasetSplit.HELD_OUT


def test_explicit_held_out_task_family_never_enters_train_or_validation() -> None:
    train = _trace(source_id="train", task_family="known-task")
    held = _trace(
        source_id="held",
        task_family="unseen-task",
        trajectory_family="novel-behavior",
    )
    report = LeakFreeSplitter(
        held_out_task_families=("unseen-task",),
        validation_percent=10,
    ).assign((train, held))
    by_source = {item.source_trajectory_id: item.split for item in report.assignments}
    assert by_source["held"] is DatasetSplit.HELD_OUT
    assert by_source["train"] is not DatasetSplit.HELD_OUT


def test_training_transformation_rejects_held_out_data() -> None:
    with pytest.raises(ValueError, match="held-out evaluation data"):
        TrainingTransformer().transform(trace=_trace(), split=DatasetSplit.HELD_OUT)


def test_training_transformation_is_target_only_and_observable() -> None:
    examples = TrainingTransformer().transform(trace=_trace(), split=DatasetSplit.TRAIN)
    assert examples
    assert all(example.target_only_loss for example in examples)
    assert all(not example.contains_raw_hidden_chain_of_thought for example in examples)
    assert {example.target_stage for example in examples}.issuperset(
        {TraceStage.ACTION, TraceStage.REPLAN, TraceStage.VERIFICATION, TraceStage.FINAL}
    )


def test_training_transformation_requires_license_and_pii_review() -> None:
    payload = _trace().model_dump(mode="python")
    payload["pii_reviewed"] = False
    trace = StructuredDecisionTrace.model_validate(payload)
    with pytest.raises(ValueError, match="license and PII review"):
        TrainingTransformer().transform(trace=trace, split=DatasetSplit.TRAIN)


def test_uncertainty_high_confidence_contradictory_evidence_stops() -> None:
    assessment = assess_uncertainty(
        confidence=ConfidenceBand.HIGH,
        evidence=EvidenceState.CONTRADICTORY,
        evidence_refs=("verifier:conflict",),
    )
    assert assessment.directive is UncertaintyDirective.STOP


def test_uncertainty_insufficient_evidence_reinspects_instead_of_proceeding() -> None:
    assessment = assess_uncertainty(
        confidence=ConfidenceBand.LOW,
        evidence=EvidenceState.INSUFFICIENT,
    )
    assert assessment.directive is UncertaintyDirective.INSPECT


def test_self_correction_requires_changed_basis_not_blind_retry() -> None:
    genuine = SelfCorrectionAssessment(
        failed_assumption_identified=True,
        new_evidence_observed=True,
        strategy_changed=True,
        changed_dimensions=("tool", "assumption"),
    )
    blind = SelfCorrectionAssessment(
        failed_assumption_identified=False,
        new_evidence_observed=False,
        strategy_changed=False,
        blind_retry=True,
    )
    assert genuine.changed_basis is True
    assert blind.changed_basis is False


def test_frozen_baseline_digest_is_deterministic() -> None:
    card = CognitiveScorecard(
        case_id="held-001",
        scores=_scores(0.5),
        evidence_refs=("eval:held-001",),
    )
    first = FrozenCognitiveBaseline.freeze(
        baseline_name="phase19-pretraining",
        revision="1.0.0",
        scorecards=(card,),
    )
    second = FrozenCognitiveBaseline.freeze(
        baseline_name="phase19-pretraining",
        revision="1.0.0",
        scorecards=(card,),
    )
    assert first.locked_sha256 == second.locked_sha256
    assert first.computed_sha256() == first.locked_sha256


def test_cognitive_comparison_reports_dimension_specific_improvement() -> None:
    baseline_card = CognitiveScorecard(
        case_id="held-001",
        scores=_scores(0.5),
        evidence_refs=("eval:before",),
    )
    baseline = FrozenCognitiveBaseline.freeze(
        baseline_name="phase19-pretraining",
        revision="1.0.0",
        scorecards=(baseline_card,),
    )
    candidate_scores = deepcopy(_scores(0.5))
    candidate_scores[CognitiveDimension.PLANNING] = 0.7
    candidate_scores[CognitiveDimension.SELF_CORRECTION] = 0.8
    candidate = CognitiveScorecard(
        case_id="held-001",
        scores=candidate_scores,
        evidence_refs=("eval:after",),
    )
    comparison = compare_to_baseline(
        baseline=baseline,
        candidate_scorecards=(candidate,),
    )
    assert comparison.verdict is CognitiveComparisonVerdict.ACCEPT
    assert comparison.dimension_deltas[CognitiveDimension.PLANNING] == pytest.approx(0.2)
    assert comparison.dimension_deltas[CognitiveDimension.SELF_CORRECTION] == pytest.approx(0.3)


def test_cognitive_comparison_rejects_critical_regression_or_contamination() -> None:
    card = CognitiveScorecard(
        case_id="held-001",
        scores=_scores(0.5),
        evidence_refs=("eval:before",),
    )
    baseline = FrozenCognitiveBaseline.freeze(
        baseline_name="phase19-pretraining",
        revision="1.0.0",
        scorecards=(card,),
    )
    regression = card.model_copy(
        update={"critical_regression": True, "evidence_refs": ("eval:regression",)}
    )
    comparison = compare_to_baseline(
        baseline=baseline,
        candidate_scorecards=(regression,),
    )
    assert comparison.verdict is CognitiveComparisonVerdict.REJECT

    contaminated = compare_to_baseline(
        baseline=baseline,
        candidate_scorecards=(card,),
        held_out_contamination_detected=True,
    )
    assert contaminated.verdict is CognitiveComparisonVerdict.REJECT


def test_cognitive_comparison_rejects_any_dimension_regression() -> None:
    card = CognitiveScorecard(
        case_id="held-001",
        scores=_scores(0.5),
        evidence_refs=("eval:before",),
    )
    baseline = FrozenCognitiveBaseline.freeze(
        baseline_name="phase19-pretraining",
        revision="1.0.0",
        scorecards=(card,),
    )
    degraded_scores = _scores(0.5)
    degraded_scores[CognitiveDimension.UNCERTAINTY_CALIBRATION] = 0.4
    degraded = CognitiveScorecard(
        case_id="held-001",
        scores=degraded_scores,
        evidence_refs=("eval:after",),
    )
    comparison = compare_to_baseline(
        baseline=baseline,
        candidate_scorecards=(degraded,),
    )
    assert comparison.verdict is CognitiveComparisonVerdict.REJECT
    assert comparison.regressed_dimensions == (CognitiveDimension.UNCERTAINTY_CALIBRATION,)
