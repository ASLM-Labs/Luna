"""C3 targeted cross-layer invalidation over explicit observable dependencies.

The coordinator does not decide truth, execute tools, or grant completion authority. It receives
an already-observed authoritative state delta, traces only explicit dependency edges, blocks
invalidated plan dependents, and records which derived cognition must be refreshed.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from typing import ClassVar, Protocol
from uuid import UUID

from luna.contracts import (
    AssumptionRecord,
    AssumptionStatus,
    CrossLayerInvalidationReport,
    DecisionRecord,
    DecisionStatus,
    InvalidationControlAction,
    InvalidationImpact,
    InvalidationLayer,
    InvalidationStateSnapshot,
    PlanStep,
    PlanStepStatus,
    TaskState,
)
from luna.contracts.base import utc_now
from luna.decision_state import DecisionStateService


class _CompressionLike(Protocol):
    decision_basis_fingerprint: str
    current_assumption_refs: tuple[str, ...]
    current_decision_refs: tuple[str, ...]


class _AlternativeSetLike(Protocol):
    decision_basis_fingerprint: str


class _RetrievalStrategyLike(Protocol):
    strategy_fingerprint: str
    decision_basis_fingerprint: str


class TargetedInvalidationCoordinator:
    """Propagate changed basis only through explicit cross-layer dependency edges."""

    _INVALIDATING_ASSUMPTION_STATUSES: ClassVar[frozenset[AssumptionStatus]] = frozenset(
        {
            AssumptionStatus.CONTRADICTED,
            AssumptionStatus.INVALIDATED,
            AssumptionStatus.SUPERSEDED,
        }
    )

    def __init__(self) -> None:
        self._decision_state = DecisionStateService()

    @staticmethod
    def assumption_ref(assumption_id: UUID) -> str:
        return f"assumption:{assumption_id}"

    @staticmethod
    def decision_ref(decision_id: UUID) -> str:
        return f"decision:{decision_id}"

    @staticmethod
    def plan_step_ref(step_id: UUID) -> str:
        return f"plan_step:{step_id}"

    @staticmethod
    def _compression_ref(compression: _CompressionLike) -> str:
        return f"decision_compression:{compression.decision_basis_fingerprint}"

    @staticmethod
    def _alternatives_ref(alternatives: _AlternativeSetLike) -> str:
        return f"decision_alternatives:{alternatives.decision_basis_fingerprint}"

    @staticmethod
    def _retrieval_ref(strategy: _RetrievalStrategyLike) -> str:
        return f"retrieval_strategy:{strategy.strategy_fingerprint}"

    @staticmethod
    def _completion_ref(state: TaskState) -> str | None:
        if state.completion_status is None:
            return None
        return f"completion_claim:{state.completion_status.value}"

    @staticmethod
    def _canonical_c2_ref(value: str) -> str:
        parts = value.split(":")
        if len(parts) >= 2 and parts[0] in {"assumption", "decision"}:
            return ":".join(parts[:2])
        return value

    @classmethod
    def _assumption_invalidating(cls, assumption: AssumptionRecord) -> bool:
        return assumption.status in cls._INVALIDATING_ASSUMPTION_STATUSES or (
            assumption.critical and assumption.status is not AssumptionStatus.SUPPORTED
        )

    @staticmethod
    def _decision_snapshot_revision(state: TaskState) -> int:
        return state.decision_state.revision if state.decision_state is not None else 0

    @staticmethod
    def _unique(values: Iterable[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))

    def _direct_assumption_seeds(
        self,
        *,
        previous: TaskState,
        current: TaskState,
    ) -> tuple[AssumptionRecord, ...]:
        previous_snapshot = self._decision_state.ensure(previous.task_id, previous.decision_state)
        current_snapshot = self._decision_state.ensure(current.task_id, current.decision_state)
        previous_by_id = {item.assumption_id: item for item in previous_snapshot.assumptions}
        seeds: list[AssumptionRecord] = []
        for assumption in current_snapshot.assumptions:
            old = previous_by_id.get(assumption.assumption_id)
            if old is None:
                continue
            if not self._assumption_invalidating(old) and self._assumption_invalidating(assumption):
                seeds.append(assumption)
        return tuple(seeds)

    def _direct_decision_seeds(
        self,
        *,
        previous: TaskState,
        current: TaskState,
        assumption_seed_ids: set[UUID],
    ) -> tuple[DecisionRecord, ...]:
        previous_snapshot = self._decision_state.ensure(previous.task_id, previous.decision_state)
        current_snapshot = self._decision_state.ensure(current.task_id, current.decision_state)
        previous_by_id = {item.decision_id: item for item in previous_snapshot.decisions}
        seeds: list[DecisionRecord] = []
        for decision in current_snapshot.decisions:
            old = previous_by_id.get(decision.decision_id)
            if old is None or decision.status is not DecisionStatus.INVALIDATED:
                continue
            if old.status is DecisionStatus.INVALIDATED:
                continue
            if assumption_seed_ids.intersection(decision.assumption_ids):
                continue
            seeds.append(decision)
        return tuple(seeds)

    @staticmethod
    def _direct_plan_seeds(
        *,
        previous: TaskState,
        current: TaskState,
    ) -> tuple[PlanStep, ...]:
        previous_by_id = {item.step_id: item for item in previous.plan}
        invalid_statuses = {PlanStepStatus.FAILED, PlanStepStatus.BLOCKED}
        seeds: list[PlanStep] = []
        for step in current.plan:
            old = previous_by_id.get(step.step_id)
            if old is None:
                continue
            if step.status in invalid_statuses and old.status not in invalid_statuses:
                seeds.append(step)
        return tuple(seeds)

    def _replacement_evidence(
        self,
        *,
        state: TaskState,
        seed: AssumptionRecord,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        snapshot = self._decision_state.ensure(state.task_id, state.decision_state)
        latest = self._decision_state.latest_assumption(snapshot, seed.key, seed.claim_type)
        if latest is None or latest.assumption_id == seed.assumption_id:
            return (), ()
        return latest.evidence_refs, latest.provenance_refs

    def _assumption_changed_evidence(
        self,
        *,
        previous_state: TaskState,
        current_state: TaskState,
        seed: AssumptionRecord,
    ) -> tuple[str, ...]:
        previous_snapshot = self._decision_state.ensure(
            previous_state.task_id,
            previous_state.decision_state,
        )
        previous = next(
            item
            for item in previous_snapshot.assumptions
            if item.assumption_id == seed.assumption_id
        )
        direct_delta = tuple(
            ref for ref in seed.evidence_refs if ref not in set(previous.evidence_refs)
        )
        replacement_evidence, _ = self._replacement_evidence(
            state=current_state,
            seed=seed,
        )
        return self._unique((*direct_delta, *replacement_evidence))

    def _graph(
        self,
        *,
        previous: TaskState,
        current: TaskState,
        compression: _CompressionLike | None,
        alternatives: _AlternativeSetLike | None,
        retrieval_strategy: _RetrievalStrategyLike | None,
    ) -> tuple[dict[str, InvalidationLayer], dict[str, set[str]]]:
        layers: dict[str, InvalidationLayer] = {}
        dependents: dict[str, set[str]] = defaultdict(set)
        previous_snapshot = self._decision_state.ensure(previous.task_id, previous.decision_state)
        current_snapshot = self._decision_state.ensure(current.task_id, current.decision_state)

        for assumption in (*previous_snapshot.assumptions, *current_snapshot.assumptions):
            layers[self.assumption_ref(assumption.assumption_id)] = InvalidationLayer.ASSUMPTION

        all_decisions: dict[UUID, DecisionRecord] = {
            item.decision_id: item for item in previous_snapshot.decisions
        }
        all_decisions.update({item.decision_id: item for item in current_snapshot.decisions})
        for decision in all_decisions.values():
            decision_ref = self.decision_ref(decision.decision_id)
            layers[decision_ref] = InvalidationLayer.DECISION
            for assumption_id in decision.assumption_ids:
                assumption_ref = self.assumption_ref(assumption_id)
                layers.setdefault(assumption_ref, InvalidationLayer.ASSUMPTION)
                dependents[assumption_ref].add(decision_ref)

        all_steps: dict[UUID, PlanStep] = {item.step_id: item for item in previous.plan}
        all_steps.update({item.step_id: item for item in current.plan})
        for step in all_steps.values():
            step_ref = self.plan_step_ref(step.step_id)
            layers[step_ref] = InvalidationLayer.PLAN_STEP
            for dependency_id in step.depends_on:
                dependency_ref = self.plan_step_ref(dependency_id)
                layers.setdefault(dependency_ref, InvalidationLayer.PLAN_STEP)
                dependents[dependency_ref].add(step_ref)

        for decision in all_decisions.values():
            subject_ref = decision.subject_ref
            if subject_ref is None or not subject_ref.startswith("plan_step:"):
                continue
            if subject_ref not in layers:
                continue
            dependents[self.decision_ref(decision.decision_id)].add(subject_ref)

        if compression is not None:
            compression_ref = self._compression_ref(compression)
            layers[compression_ref] = InvalidationLayer.DECISION_COMPRESSION
            for source_ref in (
                *compression.current_assumption_refs,
                *compression.current_decision_refs,
            ):
                canonical = self._canonical_c2_ref(source_ref)
                if canonical in layers:
                    dependents[canonical].add(compression_ref)

            if alternatives is not None:
                alternatives_ref = self._alternatives_ref(alternatives)
                layers[alternatives_ref] = InvalidationLayer.DECISION_ALTERNATIVES
                dependents[compression_ref].add(alternatives_ref)

            if retrieval_strategy is not None:
                retrieval_ref = self._retrieval_ref(retrieval_strategy)
                layers[retrieval_ref] = InvalidationLayer.RETRIEVAL_STRATEGY
                dependents[compression_ref].add(retrieval_ref)

        completion_ref = self._completion_ref(current)
        if completion_ref is not None:
            layers[completion_ref] = InvalidationLayer.COMPLETION_CLAIM
            for step in current.plan:
                dependents[self.plan_step_ref(step.step_id)].add(completion_ref)
            for decision in current_snapshot.decisions:
                dependents[self.decision_ref(decision.decision_id)].add(completion_ref)
            for assumption in self._decision_state.current_assumptions(current_snapshot):
                if assumption.critical:
                    dependents[self.assumption_ref(assumption.assumption_id)].add(completion_ref)

        return layers, dependents

    @staticmethod
    def _walk(
        *,
        seeds: tuple[str, ...],
        dependents: dict[str, set[str]],
        seed_changed_evidence: dict[str, tuple[str, ...]],
    ) -> tuple[
        tuple[str, ...],
        dict[str, tuple[str, ...]],
        dict[str, tuple[str, ...]],
    ]:
        queue: deque[str] = deque(seeds)
        visited: set[str] = set(seeds)
        causes: dict[str, set[str]] = {seed: {seed} for seed in seeds}
        evidence: dict[str, set[str]] = {
            seed: set(seed_changed_evidence.get(seed, ())) for seed in seeds
        }
        order: list[str] = list(seeds)

        while queue:
            source = queue.popleft()
            for target in sorted(dependents.get(source, ())):
                causes.setdefault(target, set()).add(source)
                target_evidence = evidence.setdefault(target, set())
                before = len(target_evidence)
                target_evidence.update(evidence.get(source, set()))
                evidence_changed = len(target_evidence) != before
                if target not in visited:
                    visited.add(target)
                    order.append(target)
                    queue.append(target)
                elif evidence_changed:
                    queue.append(target)
        frozen_causes = {key: tuple(sorted(value)) for key, value in causes.items()}
        frozen_evidence = {key: tuple(sorted(value)) for key, value in evidence.items()}
        return tuple(order), frozen_causes, frozen_evidence

    @staticmethod
    def _block_invalidated_plan_dependents(
        *,
        state: TaskState,
        invalidated_refs: set[str],
        direct_plan_refs: set[str],
    ) -> tuple[PlanStep, ...]:
        updated: list[PlanStep] = []
        for step in state.plan:
            ref = TargetedInvalidationCoordinator.plan_step_ref(step.step_id)
            if ref not in invalidated_refs or ref in direct_plan_refs:
                updated.append(step)
                continue
            if step.status in {PlanStepStatus.FAILED, PlanStepStatus.BLOCKED}:
                updated.append(step)
                continue
            updated.append(
                step.model_copy(
                    update={
                        "status": PlanStepStatus.BLOCKED,
                        "status_reason": "C3 dependency basis was invalidated",
                    }
                )
            )
        return tuple(updated)

    def reconcile(
        self,
        *,
        previous_state: TaskState,
        current_state: TaskState,
        evidence_refs: Iterable[str] = (),
        provenance_refs: Iterable[str] = (),
        compression: _CompressionLike | None = None,
        alternatives: _AlternativeSetLike | None = None,
        retrieval_strategy: _RetrievalStrategyLike | None = None,
    ) -> tuple[CrossLayerInvalidationReport, TaskState]:
        """Trace one observed state delta and invalidate only explicit dependent state."""
        if previous_state.task_id != current_state.task_id:
            raise ValueError("C3 state delta task mismatch")
        if current_state.revision < previous_state.revision:
            raise ValueError("C3 cannot reconcile a stale task-state revision")
        previous_decision_revision = self._decision_snapshot_revision(previous_state)
        current_decision_revision = self._decision_snapshot_revision(current_state)
        if current_decision_revision < previous_decision_revision:
            raise ValueError("C3 cannot reconcile a stale decision-state revision")

        assumption_seeds = self._direct_assumption_seeds(
            previous=previous_state,
            current=current_state,
        )
        assumption_seed_ids = {item.assumption_id for item in assumption_seeds}
        decision_seeds = self._direct_decision_seeds(
            previous=previous_state,
            current=current_state,
            assumption_seed_ids=assumption_seed_ids,
        )
        plan_seeds = self._direct_plan_seeds(
            previous=previous_state,
            current=current_state,
        )

        seed_refs = self._unique(
            (
                *(self.assumption_ref(item.assumption_id) for item in assumption_seeds),
                *(self.decision_ref(item.decision_id) for item in decision_seeds),
                *(self.plan_step_ref(item.step_id) for item in plan_seeds),
            )
        )
        if not seed_refs:
            report = CrossLayerInvalidationReport(
                task_id=current_state.task_id,
                previous_task_state_revision=previous_state.revision,
                input_task_state_revision=current_state.revision,
                result_task_state_revision=current_state.revision,
                previous_decision_state_revision=previous_decision_revision,
                current_decision_state_revision=current_decision_revision,
                reason_codes=("no_new_invalidating_basis",),
            )
            return report, current_state

        collected_evidence = list(evidence_refs)
        collected_provenance = list(provenance_refs)
        seed_changed_evidence: dict[str, tuple[str, ...]] = {}
        for seed in assumption_seeds:
            collected_evidence.extend(seed.evidence_refs)
            collected_provenance.extend(seed.provenance_refs)
            replacement_evidence, replacement_provenance = self._replacement_evidence(
                state=current_state,
                seed=seed,
            )
            collected_evidence.extend(replacement_evidence)
            collected_provenance.extend(replacement_provenance)
            seed_changed_evidence[self.assumption_ref(seed.assumption_id)] = (
                self._assumption_changed_evidence(
                    previous_state=previous_state,
                    current_state=current_state,
                    seed=seed,
                )
            )
        previous_observations = set(previous_state.observation_ids)
        new_observations = tuple(
            item for item in current_state.observation_ids if item not in previous_observations
        )
        new_observation_refs = tuple(f"observation:{item}" for item in new_observations)
        collected_evidence.extend(new_observation_refs)
        evidence = self._unique(collected_evidence)
        provenance = self._unique(collected_provenance)
        if not evidence and not provenance:
            raise ValueError(
                "C3 invalidation requires evidence or provenance for the changed basis"
            )

        layers, dependents = self._graph(
            previous=previous_state,
            current=current_state,
            compression=compression,
            alternatives=alternatives,
            retrieval_strategy=retrieval_strategy,
        )
        invalidated_order, causes, impact_evidence = self._walk(
            seeds=seed_refs,
            dependents=dependents,
            seed_changed_evidence=seed_changed_evidence,
        )
        invalidated = set(invalidated_order)
        direct = set(seed_refs)
        impacts = tuple(
            InvalidationImpact(
                target_ref=target,
                layer=layers[target],
                direct=target in direct,
                cause_refs=causes[target],
                changed_basis_evidence_refs=impact_evidence.get(target, ()),
                reason_codes=(
                    ("direct_basis_invalidated",)
                    if target in direct
                    else ("dependent_basis_invalidated", "targeted_dependency_propagation")
                ),
            )
            for target in invalidated_order
        )
        changed_evidence = self._unique(
            ref
            for impact in impacts
            for ref in impact.changed_basis_evidence_refs
        )
        preserved = tuple(sorted(set(layers) - invalidated))
        completion_claim_stale = any(
            item.layer is InvalidationLayer.COMPLETION_CLAIM for item in impacts
        )
        critical_invalidated = any(
            item.critical and self._assumption_invalidating(item) for item in assumption_seeds
        )
        control_action = (
            InvalidationControlAction.STOP_VERIFY
            if completion_claim_stale or critical_invalidated
            else InvalidationControlAction.REPLAN
        )
        reasons = [
            "targeted_dependency_traversal",
            "unrelated_state_preserved",
            "changed_basis_required",
        ]
        if critical_invalidated:
            reasons.append("critical_basis_requires_verification")
        elif control_action is InvalidationControlAction.REPLAN:
            reasons.append("changed_basis_replan_required")
        if completion_claim_stale:
            reasons.append("completion_claim_basis_invalidated")

        direct_plan_refs = {self.plan_step_ref(item.step_id) for item in plan_seeds}
        updated_plan = self._block_invalidated_plan_dependents(
            state=current_state,
            invalidated_refs=invalidated,
            direct_plan_refs=direct_plan_refs,
        )
        result_revision = current_state.revision + 1
        report = CrossLayerInvalidationReport(
            task_id=current_state.task_id,
            previous_task_state_revision=previous_state.revision,
            input_task_state_revision=current_state.revision,
            result_task_state_revision=result_revision,
            previous_decision_state_revision=previous_decision_revision,
            current_decision_state_revision=current_decision_revision,
            trigger_refs=seed_refs,
            evidence_refs=evidence,
            changed_basis_evidence_refs=changed_evidence,
            provenance_refs=provenance,
            impacts=impacts,
            preserved_refs=preserved,
            control_action=control_action,
            changed_basis_required=True,
            completion_claim_stale=completion_claim_stale,
            reason_codes=tuple(reasons),
        )
        prior_invalidation_revision = (
            current_state.invalidation_state.revision
            if current_state.invalidation_state is not None
            else 0
        )
        snapshot = InvalidationStateSnapshot(
            task_id=current_state.task_id,
            revision=prior_invalidation_revision + 1,
            latest_report=report,
            updated_at=utc_now(),
        )
        revised = current_state.revise(
            plan=updated_plan,
            invalidation_state=snapshot,
        )
        if revised.revision != report.result_task_state_revision:
            raise ValueError("C3 report revision must match the authoritative result state")
        return report, revised
