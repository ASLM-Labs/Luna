"""Phase 19B evaluation-governance public API."""

from luna.evaluation_governance.comparison import compare_release_snapshots
from luna.evaluation_governance.contamination import detect_benchmark_contamination
from luna.evaluation_governance.models import (
    BenchmarkContaminationReport,
    ContaminationFinding,
    ContaminationReason,
    EvaluationCase,
    EvaluationPartition,
    EvaluatorKind,
    EvaluatorSpec,
    FrozenEvaluationSuite,
    FrozenRegressionSuite,
    ReleaseComparison,
    ReleaseComparisonStatus,
    ReleaseEvaluationSnapshot,
    TrainingExposure,
)
from luna.evaluation_governance.suite import build_release_snapshot, freeze_regression_suite

__all__ = [
    "BenchmarkContaminationReport",
    "ContaminationFinding",
    "ContaminationReason",
    "EvaluationCase",
    "EvaluationPartition",
    "EvaluatorKind",
    "EvaluatorSpec",
    "FrozenEvaluationSuite",
    "FrozenRegressionSuite",
    "ReleaseComparison",
    "ReleaseComparisonStatus",
    "ReleaseEvaluationSnapshot",
    "TrainingExposure",
    "build_release_snapshot",
    "compare_release_snapshots",
    "detect_benchmark_contamination",
    "freeze_regression_suite",
]
