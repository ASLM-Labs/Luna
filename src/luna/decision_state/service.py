"""Immutable operations over the authoritative decision-state snapshot."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from luna.contracts.base import stable_payload, utc_now
from luna.contracts.decision import (
    AssumptionRecord,
    AssumptionStatus,
    DecisionRecord,
    DecisionStateSnapshot,
    DecisionStatus,
)


class DecisionStateService:
    """Update assumption/decision state without owning a second persistence authority."""

    @staticmethod
    def ensure(task_id: UUID, snapshot: DecisionStateSnapshot | None) -> DecisionStateSnapshot:
        if snapshot is None:
            return DecisionStateSnapshot.empty(task_id)
        if snapshot.task_id != task_id:
            raise ValueError("decision-state task_id mismatch")
        return snapshot

    @staticmethod
    def latest_assumption(
        snapshot: DecisionStateSnapshot,
        key: str,
        claim_type: str | None = None,
    ) -> AssumptionRecord | None:
        return next(
            (
                item
                for item in reversed(snapshot.assumptions)
                if item.key == key and (claim_type is None or item.claim_type == claim_type)
            ),
            None,
        )

    @classmethod
    def current_assumptions(
        cls,
        snapshot: DecisionStateSnapshot,
    ) -> tuple[AssumptionRecord, ...]:
        """Return the latest assumption for each logical key/type identity."""
        identities = sorted({(item.key, item.claim_type) for item in snapshot.assumptions})
        current: list[AssumptionRecord] = []
        for key, claim_type in identities:
            latest = cls.latest_assumption(snapshot, key, claim_type)
            if latest is not None:
                current.append(latest)
        return tuple(current)

    @classmethod
    def blocking_assumptions(
        cls,
        snapshot: DecisionStateSnapshot,
    ) -> tuple[AssumptionRecord, ...]:
        """Return current critical assumptions that cannot safely support action."""
        return tuple(
            item
            for item in cls.current_assumptions(snapshot)
            if item.critical and item.status is not AssumptionStatus.SUPPORTED
        )

    @staticmethod
    def _replace(
        snapshot: DecisionStateSnapshot,
        *,
        assumptions: Iterable[AssumptionRecord] | None = None,
        decisions: Iterable[DecisionRecord] | None = None,
    ) -> DecisionStateSnapshot:
        return DecisionStateSnapshot(
            task_id=snapshot.task_id,
            revision=snapshot.revision + 1,
            assumptions=tuple(assumptions) if assumptions is not None else snapshot.assumptions,
            decisions=tuple(decisions) if decisions is not None else snapshot.decisions,
            updated_at=utc_now(),
        )

    def record_assumption(
        self,
        snapshot: DecisionStateSnapshot,
        assumption: AssumptionRecord,
    ) -> DecisionStateSnapshot:
        if assumption.task_id != snapshot.task_id:
            raise ValueError("assumption task_id mismatch")
        if any(item.assumption_id == assumption.assumption_id for item in snapshot.assumptions):
            raise ValueError("assumption already exists")
        return self._replace(snapshot, assumptions=(*snapshot.assumptions, assumption))

    def record_decision(
        self,
        snapshot: DecisionStateSnapshot,
        decision: DecisionRecord,
    ) -> DecisionStateSnapshot:
        if decision.task_id != snapshot.task_id:
            raise ValueError("decision task_id mismatch")
        if any(item.decision_id == decision.decision_id for item in snapshot.decisions):
            raise ValueError("decision already exists")
        assumptions = {item.assumption_id: item for item in snapshot.assumptions}
        missing = [item for item in decision.assumption_ids if item not in assumptions]
        if missing:
            raise ValueError("decision references unknown assumptions")

        updated_assumptions: list[AssumptionRecord] = []
        for assumption in snapshot.assumptions:
            if assumption.assumption_id not in decision.assumption_ids:
                updated_assumptions.append(assumption)
                continue
            payload = stable_payload(assumption)
            payload.update(
                {
                    "dependent_decision_ids": [
                        *assumption.dependent_decision_ids,
                        decision.decision_id,
                    ],
                    "updated_at": utc_now(),
                }
            )
            updated_assumptions.append(AssumptionRecord.model_validate(payload))

        return self._replace(
            snapshot,
            assumptions=updated_assumptions,
            decisions=(*snapshot.decisions, decision),
        )

    def transition_assumption(
        self,
        snapshot: DecisionStateSnapshot,
        *,
        assumption_id: UUID,
        status: AssumptionStatus,
        evidence_refs: tuple[str, ...] | None = None,
        provenance_refs: tuple[str, ...] | None = None,
        reason: str | None = None,
    ) -> DecisionStateSnapshot:
        target = next(
            (item for item in snapshot.assumptions if item.assumption_id == assumption_id),
            None,
        )
        if target is None:
            raise ValueError("assumption does not exist")

        updated_assumptions: list[AssumptionRecord] = []
        for assumption in snapshot.assumptions:
            if assumption.assumption_id != assumption_id:
                updated_assumptions.append(assumption)
                continue
            payload = stable_payload(assumption)
            payload.update(
                {
                    "status": status,
                    "evidence_refs": (
                        list(evidence_refs)
                        if evidence_refs is not None
                        else list(assumption.evidence_refs)
                    ),
                    "provenance_refs": (
                        list(provenance_refs)
                        if provenance_refs is not None
                        else list(assumption.provenance_refs)
                    ),
                    "reason": reason,
                    "updated_at": utc_now(),
                }
            )
            updated_assumptions.append(AssumptionRecord.model_validate(payload))

        invalidating = status in {
            AssumptionStatus.CONTRADICTED,
            AssumptionStatus.INVALIDATED,
            AssumptionStatus.SUPERSEDED,
        } or (target.critical and status is not AssumptionStatus.SUPPORTED)
        updated_decisions: list[DecisionRecord] = []
        for decision in snapshot.decisions:
            if not invalidating or assumption_id not in decision.assumption_ids:
                updated_decisions.append(decision)
                continue
            if decision.status in {DecisionStatus.COMPLETED, DecisionStatus.INVALIDATED}:
                updated_decisions.append(decision)
                continue
            payload = stable_payload(decision)
            payload.update(
                {
                    "status": DecisionStatus.INVALIDATED,
                    "reason": reason or f"assumption {assumption_id} invalidated",
                    "updated_at": utc_now(),
                }
            )
            updated_decisions.append(DecisionRecord.model_validate(payload))

        return self._replace(
            snapshot,
            assumptions=updated_assumptions,
            decisions=updated_decisions,
        )

    def supersede_and_record(
        self,
        snapshot: DecisionStateSnapshot,
        *,
        previous: AssumptionRecord,
        replacement: AssumptionRecord,
        reason: str,
    ) -> DecisionStateSnapshot:
        superseded = self.transition_assumption(
            snapshot,
            assumption_id=previous.assumption_id,
            status=AssumptionStatus.SUPERSEDED,
            reason=reason,
        )
        return self.record_assumption(superseded, replacement)

    @staticmethod
    def affected_decisions(
        snapshot: DecisionStateSnapshot,
        assumption_id: UUID,
    ) -> tuple[DecisionRecord, ...]:
        return tuple(
            item for item in snapshot.decisions if assumption_id in item.assumption_ids
        )
