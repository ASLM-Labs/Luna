"""Deterministic C-007 held-out debugging transfer evaluator."""

from __future__ import annotations

from collections.abc import Iterable

from luna.debugging.models import (
    ControlledLessonTransferBinding,
    DebuggingEvaluationCase,
    DebuggingMetric,
    DebuggingMetricDelta,
    DebuggingStage,
    DebuggingTransferAssessment,
    DebuggingTransferPolicy,
    DebuggingTransferVerdict,
)
from luna.experience import DistillationDisposition, DistilledExperienceCandidate
from luna.trajectories import DatasetSplit

_STAGE_METRIC = {
    DebuggingMetric.FAILURE_LOCALIZATION: DebuggingStage.FAILURE_LOCALIZATION,
    DebuggingMetric.HYPOTHESIS_QUALITY: DebuggingStage.HYPOTHESIS_GENERATION_RANKING,
    DebuggingMetric.BROKEN_ASSUMPTION_DETECTION: DebuggingStage.BROKEN_ASSUMPTION_DETECTION,
    DebuggingMetric.STATE_CONTEXT_INSPECTION: DebuggingStage.STATE_CONTEXT_INSPECTION,
    DebuggingMetric.MINIMAL_REPAIR_PLANNING: DebuggingStage.MINIMAL_REPAIR_PLANNING,
    DebuggingMetric.TOOL_SELECTION: DebuggingStage.TOOL_SELECTION,
    DebuggingMetric.PATCH_ACTION_QUALITY: DebuggingStage.PATCH_ACTION,
    DebuggingMetric.TARGETED_VERIFICATION: DebuggingStage.TARGETED_VERIFICATION,
    DebuggingMetric.FULL_REGRESSION_VERIFICATION: DebuggingStage.FULL_REGRESSION_VERIFICATION,
    DebuggingMetric.CHANGED_BASIS_REPLAN: DebuggingStage.CHANGED_BASIS_REPLAN,
    DebuggingMetric.PREVENTION_LESSON: DebuggingStage.PREVENTION_PROCESS_LESSON,
}


class DebuggingTransferEvaluator:
    """Test a reviewed C-003 lesson against unseen paired debugging cases."""

    def evaluate(
        self,
        *,
        lesson: DistilledExperienceCandidate,
        binding: ControlledLessonTransferBinding,
        policy: DebuggingTransferPolicy,
        baseline_cases: tuple[DebuggingEvaluationCase, ...],
        transfer_cases: tuple[DebuggingEvaluationCase, ...],
    ) -> DebuggingTransferAssessment:
        blocked = self._preflight(
            lesson=lesson,
            binding=binding,
            policy=policy,
            baseline_cases=baseline_cases,
            transfer_cases=transfer_cases,
        )
        if blocked:
            return DebuggingTransferAssessment(
                lesson_id=lesson.lesson_id,
                policy_sha256=policy.locked_sha256,
                verdict=DebuggingTransferVerdict.INSUFFICIENT_EVIDENCE,
                blocked_reasons=tuple(blocked),
            )

        baseline_by_id = {case.case_id: case for case in baseline_cases}
        transfer_by_id = {case.case_id: case for case in transfer_cases}
        case_ids = tuple(sorted(baseline_by_id))
        metrics = tuple(DebuggingMetric)
        deltas = tuple(
            self._metric_delta(
                metric,
                tuple(baseline_by_id[case_id] for case_id in case_ids),
                tuple(transfer_by_id[case_id] for case_id in case_ids),
            )
            for metric in metrics
        )

        regressed = tuple(
            item.metric
            for item in deltas
            if item.delta < -policy.regression_tolerance - 1e-12
        )
        improved = tuple(
            item.metric
            for item in deltas
            if item.delta >= policy.meaningful_improvement - 1e-12
        )
        critical = tuple(
            sorted(case.case_id for case in transfer_cases if case.critical_regression)
        )
        required_improved = set(policy.required_outcome_metrics) & set(improved)
        evidence_refs = self._evidence_refs(transfer_cases)

        reasons: list[str] = []
        if regressed:
            reasons.append("debugging_metric_regression_detected")
        if critical:
            reasons.append("critical_debugging_regression_detected")
        if not required_improved:
            reasons.append("no_meaningful_repair_or_diagnosis_improvement")

        verdict = (
            DebuggingTransferVerdict.SUPPORTED
            if not reasons
            else DebuggingTransferVerdict.NOT_SUPPORTED
        )
        return DebuggingTransferAssessment(
            lesson_id=lesson.lesson_id,
            policy_sha256=policy.locked_sha256,
            verdict=verdict,
            held_out_case_ids=case_ids,
            metric_deltas=deltas,
            meaningfully_improved_metrics=improved,
            regressed_metrics=regressed,
            critical_regression_case_ids=critical,
            blocked_reasons=tuple(reasons),
            evidence_refs=evidence_refs,
        )

    @staticmethod
    def _preflight(
        *,
        lesson: DistilledExperienceCandidate,
        binding: ControlledLessonTransferBinding,
        policy: DebuggingTransferPolicy,
        baseline_cases: tuple[DebuggingEvaluationCase, ...],
        transfer_cases: tuple[DebuggingEvaluationCase, ...],
    ) -> list[str]:
        reasons: list[str] = []
        if lesson.disposition is not DistillationDisposition.REVIEW_REQUIRED_CANDIDATE:
            reasons.append("lesson_is_not_a_review_required_c003_candidate")
        if not lesson.generalization_test_passed:
            reasons.append("lesson_generalization_test_not_passed")
        if binding.lesson_id != lesson.lesson_id:
            reasons.append("controlled_transfer_binding_lesson_mismatch")
        if len(baseline_cases) < policy.min_held_out_cases:
            reasons.append("insufficient_held_out_case_count")
        if len(transfer_cases) != len(baseline_cases):
            reasons.append("baseline_transfer_case_count_mismatch")

        baseline_by_id = {case.case_id: case for case in baseline_cases}
        transfer_by_id = {case.case_id: case for case in transfer_cases}
        if len(baseline_by_id) != len(baseline_cases) or len(transfer_by_id) != len(transfer_cases):
            reasons.append("duplicate_debugging_case_id")
        if set(baseline_by_id) != set(transfer_by_id):
            reasons.append("baseline_transfer_case_identity_mismatch")

        training_groups = set(lesson.supporting_split_groups)
        for case_id in sorted(set(baseline_by_id) & set(transfer_by_id)):
            before = baseline_by_id[case_id]
            after = transfer_by_id[case_id]
            if before.dataset_split is not DatasetSplit.HELD_OUT:
                reasons.append(f"baseline_case_not_held_out:{case_id}")
            if after.dataset_split is not DatasetSplit.HELD_OUT:
                reasons.append(f"transfer_case_not_held_out:{case_id}")
            if (
                before.split_group_key in training_groups
                or after.split_group_key in training_groups
            ):
                reasons.append(f"training_group_reused_in_transfer_eval:{case_id}")
            if before.split_group_key != after.split_group_key:
                reasons.append(f"paired_case_group_mismatch:{case_id}")
            if before.task_family != after.task_family:
                reasons.append(f"paired_case_task_family_mismatch:{case_id}")
            if before.initial_repair_failed != after.initial_repair_failed:
                reasons.append(f"paired_case_replan_applicability_mismatch:{case_id}")
            if before.applied_lesson_ids:
                reasons.append(f"baseline_case_has_lesson_confound:{case_id}")
            if after.applied_lesson_ids != (lesson.lesson_id,):
                if lesson.lesson_id not in after.applied_lesson_ids:
                    reasons.append(f"transfer_case_missing_lesson_binding:{case_id}")
                else:
                    reasons.append(f"transfer_case_has_lesson_confound:{case_id}")
        return reasons

    @staticmethod
    def _metric_delta(
        metric: DebuggingMetric,
        baseline_cases: tuple[DebuggingEvaluationCase, ...],
        transfer_cases: tuple[DebuggingEvaluationCase, ...],
    ) -> DebuggingMetricDelta:
        baseline_values = DebuggingTransferEvaluator._metric_values(metric, baseline_cases)
        transfer_values = DebuggingTransferEvaluator._metric_values(metric, transfer_cases)
        if len(baseline_values) != len(transfer_values) or not baseline_values:
            raise ValueError(f"metric has no paired applicable cases: {metric.value}")
        baseline_mean = sum(baseline_values) / len(baseline_values)
        candidate_mean = sum(transfer_values) / len(transfer_values)
        return DebuggingMetricDelta(
            metric=metric,
            case_count=len(baseline_values),
            baseline_mean=baseline_mean,
            candidate_mean=candidate_mean,
            delta=candidate_mean - baseline_mean,
        )

    @staticmethod
    def _metric_values(
        metric: DebuggingMetric,
        cases: Iterable[DebuggingEvaluationCase],
    ) -> tuple[float, ...]:
        materialized = tuple(cases)
        if metric is DebuggingMetric.REPAIR_SUCCESS:
            return tuple(float(case.repair_succeeded) for case in materialized)
        if metric is DebuggingMetric.DIAGNOSIS_QUALITY:
            return tuple(float(case.diagnosis_correct) for case in materialized)

        stage = _STAGE_METRIC[metric]
        values: list[float] = []
        for case in materialized:
            if stage is DebuggingStage.CHANGED_BASIS_REPLAN and not case.initial_repair_failed:
                continue
            values.append(case.stage_score(stage))
        if stage is DebuggingStage.CHANGED_BASIS_REPLAN and not values:
            # No failed initial repair means no replan opportunity; neutral paired evidence.
            return tuple(1.0 for _ in materialized)
        return tuple(values)

    @staticmethod
    def _evidence_refs(cases: tuple[DebuggingEvaluationCase, ...]) -> tuple[str, ...]:
        refs = {
            ref
            for case in cases
            for assessment in case.stage_assessments
            for ref in assessment.evidence_refs
        }
        return tuple(sorted(refs))


def build_default_debugging_transfer_policy() -> DebuggingTransferPolicy:
    """Freeze the conservative C-007 foundation policy."""
    return DebuggingTransferPolicy.freeze(revision="0.1.0")
