"""Deterministic evidence checks for C-003 Experience Distillation."""

from __future__ import annotations

from collections.abc import Iterable

from luna.experience.models import (
    CaseRelation,
    DistillationDisposition,
    DistilledExperienceCandidate,
    ExperienceLessonProposal,
    GeneralizationScope,
)
from luna.trajectories import (
    DatasetSplit,
    LeakFreeSplitReport,
    SplitAssignment,
    StructuredDecisionTrace,
)


class ExperienceDistiller:
    """Validate reusable lesson candidates without executing, storing, or promoting them."""

    def __init__(self, *, minimum_support_groups: int = 2) -> None:
        if minimum_support_groups < 2:
            raise ValueError("cross-case distillation requires at least two support groups")
        self._minimum_support_groups = minimum_support_groups

    def distill(
        self,
        *,
        proposal: ExperienceLessonProposal,
        traces: tuple[StructuredDecisionTrace, ...],
        split_report: LeakFreeSplitReport,
    ) -> DistilledExperienceCandidate:
        trace_by_source = self._index_traces(traces)
        assignment_by_source = self._index_assignments(split_report)

        supporting_sources: list[str] = []
        contradicting_sources: list[str] = []
        support_groups: set[str] = set()
        support_tasks: set[str] = set()
        evidence_refs: set[str] = set()
        provenance_refs: set[str] = set()

        for case in proposal.cases:
            trace = trace_by_source.get(case.source_trajectory_id)
            if trace is None:
                raise ValueError(
                    f"lesson case references unknown trajectory: {case.source_trajectory_id}"
                )
            assignment = assignment_by_source.get(case.source_trajectory_id)
            if assignment is None:
                raise ValueError(
                    f"lesson case has no governed split assignment: {case.source_trajectory_id}"
                )
            if assignment.split is not DatasetSplit.TRAIN:
                raise ValueError(
                    "experience distillation may consume TRAIN experience only; "
                    "validation/held-out remain evaluation-only"
                )
            if assignment.split_group_key != trace.split_group_key:
                raise ValueError("split assignment does not match trajectory group lineage")
            if assignment.task_family != trace.task_family:
                raise ValueError("split assignment does not match trajectory task family")
            if not trace.license_reviewed or not trace.pii_reviewed:
                raise ValueError("distillation requires license-reviewed and PII-reviewed traces")

            observable_refs = self._observable_evidence_refs(trace)
            missing_refs = set(case.evidence_refs) - observable_refs
            if missing_refs:
                missing = ", ".join(sorted(missing_refs))
                raise ValueError(
                    f"lesson case cites evidence not observed in source trajectory: {missing}"
                )

            evidence_refs.update(case.evidence_refs)
            provenance_refs.update(trace.provenance_refs)

            if case.relation is CaseRelation.CONTRADICTS:
                contradicting_sources.append(case.source_trajectory_id)
                continue

            supporting_sources.append(case.source_trajectory_id)
            support_groups.add(trace.split_group_key)
            support_tasks.add(trace.task_family)

        basis: tuple[str, ...]
        if contradicting_sources:
            disposition = DistillationDisposition.REJECTED_CONTRADICTION
            scope = GeneralizationScope.NONE
            generalization_passed = False
            basis = (
                "observable_contradictory_case_present",
                "candidate_rejected_before_reuse",
            )
        elif len(support_groups) < self._minimum_support_groups:
            disposition = DistillationDisposition.INSUFFICIENT_EVIDENCE
            scope = GeneralizationScope.NONE
            generalization_passed = False
            basis = (
                "cross_case_support_below_minimum",
                f"required_support_groups={self._minimum_support_groups}",
            )
        else:
            disposition = DistillationDisposition.REVIEW_REQUIRED_CANDIDATE
            generalization_passed = True
            scope = (
                GeneralizationScope.CROSS_TASK_FAMILY
                if len(support_tasks) >= 2
                else GeneralizationScope.WITHIN_TASK_FAMILY
            )
            basis = (
                "observable_evidence_refs_validated",
                "independent_train_split_groups_support_lesson",
                "separate_review_and_promotion_still_required",
            )

        return DistilledExperienceCandidate(
            lesson_id=proposal.lesson_id,
            statement=proposal.statement,
            kind=proposal.kind,
            applicability_scope=proposal.applicability_scope,
            disposition=disposition,
            generalization_scope=scope,
            generalization_test_passed=generalization_passed,
            supporting_source_trajectories=tuple(sorted(supporting_sources)),
            contradicting_source_trajectories=tuple(sorted(contradicting_sources)),
            supporting_split_groups=tuple(sorted(support_groups)),
            supporting_task_families=tuple(sorted(support_tasks)),
            evidence_refs=tuple(sorted(evidence_refs)),
            provenance_refs=tuple(sorted(provenance_refs)),
            decision_basis=basis,
        )

    @staticmethod
    def _index_traces(
        traces: tuple[StructuredDecisionTrace, ...],
    ) -> dict[str, StructuredDecisionTrace]:
        if not traces:
            raise ValueError("experience distillation requires governed source traces")
        indexed: dict[str, StructuredDecisionTrace] = {}
        for trace in traces:
            if trace.source_trajectory_id in indexed:
                raise ValueError(
                    f"duplicate source trajectory: {trace.source_trajectory_id}"
                )
            indexed[trace.source_trajectory_id] = trace
        return indexed

    @staticmethod
    def _index_assignments(
        split_report: LeakFreeSplitReport,
    ) -> dict[str, SplitAssignment]:
        indexed: dict[str, SplitAssignment] = {}
        for assignment in split_report.assignments:
            if assignment.source_trajectory_id in indexed:
                raise ValueError(
                    f"duplicate split assignment: {assignment.source_trajectory_id}"
                )
            indexed[assignment.source_trajectory_id] = assignment
        return indexed

    @staticmethod
    def _observable_evidence_refs(trace: StructuredDecisionTrace) -> set[str]:
        return set(
            ExperienceDistiller._flatten(
                event.evidence_refs for event in trace.events
            )
        )

    @staticmethod
    def _flatten(values: Iterable[tuple[str, ...]]) -> Iterable[str]:
        for group in values:
            yield from group
