"""Deterministic benchmark contamination checks for Phase 19B."""

from __future__ import annotations

from luna.evaluation_governance.models import (
    BenchmarkContaminationReport,
    ContaminationFinding,
    ContaminationReason,
    FrozenEvaluationSuite,
    TrainingExposure,
)


def detect_benchmark_contamination(
    *,
    evaluation_suite: FrozenEvaluationSuite,
    training_exposures: tuple[TrainingExposure, ...],
) -> BenchmarkContaminationReport:
    """Detect exact and grouped training/evaluation overlap without inspecting hidden reasoning."""
    findings: list[ContaminationFinding] = []
    seen: set[tuple[str, str, ContaminationReason]] = set()

    for case in evaluation_suite.cases:
        for exposure in training_exposures:
            reasons: list[ContaminationReason] = []
            if case.content_sha256 == exposure.content_sha256:
                reasons.append(ContaminationReason.EXACT_CONTENT)
            if case.source_trajectory_id == exposure.source_trajectory_id:
                reasons.append(ContaminationReason.SOURCE_TRAJECTORY)
            if case.task_family == exposure.task_family:
                reasons.append(ContaminationReason.TASK_FAMILY)
            if case.repository_family == exposure.repository_family:
                reasons.append(ContaminationReason.REPOSITORY_FAMILY)
            if case.trajectory_family == exposure.trajectory_family:
                reasons.append(ContaminationReason.TRAJECTORY_FAMILY)

            for reason in reasons:
                key = (case.case_id, exposure.source_trajectory_id, reason)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    ContaminationFinding(
                        case_id=case.case_id,
                        exposure_source_trajectory_id=exposure.source_trajectory_id,
                        reason=reason,
                    )
                )

    findings.sort(
        key=lambda finding: (
            finding.case_id,
            finding.exposure_source_trajectory_id,
            finding.reason.value,
        )
    )
    return BenchmarkContaminationReport(findings=tuple(findings))
