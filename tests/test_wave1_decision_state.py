from __future__ import annotations

from uuid import uuid4

import pytest

from luna.contracts import (
    AssumptionRecord,
    AssumptionStatus,
    DecisionRecord,
    DecisionStateSnapshot,
    DecisionStatus,
)
from luna.decision_state import DecisionStateService


def _supported_assumption(*, task_id, key: str, statement: str, critical: bool = True):
    return AssumptionRecord(
        task_id=task_id,
        key=key,
        statement=statement,
        claim_type="TEST",
        critical=critical,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=(f"evidence:{key}",),
        provenance_refs=(f"source:{key}",),
    )


def test_active_decision_requires_supported_critical_assumption() -> None:
    task_id = uuid4()
    service = DecisionStateService()
    snapshot = DecisionStateSnapshot.empty(task_id)
    assumption = AssumptionRecord(
        task_id=task_id,
        key="current_head",
        statement="current_head=unknown",
        claim_type="REPOSITORY_STATE",
        critical=True,
    )
    snapshot = service.record_assumption(snapshot, assumption)

    with pytest.raises(ValueError, match="unsupported critical assumption"):
        service.record_decision(
            snapshot,
            DecisionRecord(
                task_id=task_id,
                action_key="apply:update",
                description="Apply repository update.",
                status=DecisionStatus.ACTIVE,
                assumption_ids=(assumption.assumption_id,),
            ),
        )


def test_contradiction_invalidates_only_dependent_decisions() -> None:
    task_id = uuid4()
    service = DecisionStateService()
    snapshot = DecisionStateSnapshot.empty(task_id)
    head = _supported_assumption(
        task_id=task_id,
        key="current_head",
        statement="current_head=6984870",
    )
    artifact = _supported_assumption(
        task_id=task_id,
        key="artifact_direction",
        statement="artifact_direction=Desktop",
    )
    snapshot = service.record_assumption(snapshot, head)
    snapshot = service.record_assumption(snapshot, artifact)

    head_decision = DecisionRecord(
        task_id=task_id,
        action_key="baseline:6984870",
        description="Use 6984870 as the current baseline.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(head.assumption_id,),
    )
    artifact_decision = DecisionRecord(
        task_id=task_id,
        action_key="artifact:Desktop",
        description="Read user artifact from Desktop.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(artifact.assumption_id,),
    )
    snapshot = service.record_decision(snapshot, head_decision)
    snapshot = service.record_decision(snapshot, artifact_decision)

    snapshot = service.transition_assumption(
        snapshot,
        assumption_id=head.assumption_id,
        status=AssumptionStatus.CONTRADICTED,
        reason="current Git evidence reports f535a43",
    )

    decisions = {item.decision_id: item for item in snapshot.decisions}
    assert decisions[head_decision.decision_id].status is DecisionStatus.INVALIDATED
    assert decisions[artifact_decision.decision_id].status is DecisionStatus.ACTIVE


def test_completed_decision_is_preserved_as_history_after_assumption_change() -> None:
    task_id = uuid4()
    service = DecisionStateService()
    snapshot = DecisionStateSnapshot.empty(task_id)
    assumption = _supported_assumption(
        task_id=task_id,
        key="ci_count",
        statement="ci_count=4/4",
    )
    snapshot = service.record_assumption(snapshot, assumption)
    completed = DecisionRecord(
        task_id=task_id,
        action_key="record:old-ci",
        description="Record the historical CI state.",
        status=DecisionStatus.COMPLETED,
        assumption_ids=(assumption.assumption_id,),
    )
    snapshot = service.record_decision(snapshot, completed)

    snapshot = service.transition_assumption(
        snapshot,
        assumption_id=assumption.assumption_id,
        status=AssumptionStatus.SUPERSEDED,
        reason="current GitHub evidence reports 2/2",
    )

    assert snapshot.decisions[0].status is DecisionStatus.COMPLETED
