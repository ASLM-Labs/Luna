from __future__ import annotations

from hashlib import sha256
from uuid import UUID

import pytest

from luna.context.integrity_models import (
    ContextClaimType,
    ContextFailureAction,
    ContextRequirement,
)
from luna.continuity.cognitive import build_cognitive_rehydration_policy
from luna.continuity.policy_reconciliation import (
    reconcile_cognitive_rehydration_requirements,
)
from luna.contracts.decision import (
    AssumptionRecord,
    AssumptionStatus,
    DecisionRecord,
    DecisionStateSnapshot,
    DecisionStatus,
)
from luna.decision_state.service import DecisionStateService

_TASK_ID = UUID("11111111-1111-4111-8111-111111111111")
_CHECKPOINT_ID = UUID("22222222-2222-4222-8222-222222222222")


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _requirement(
    *,
    key: str = "current_head",
    claim_type: ContextClaimType = ContextClaimType.REPOSITORY_STATE,
    critical: bool = True,
    require_verified: bool = True,
    max_age_seconds: int | None = 60,
    failure_action: ContextFailureAction = ContextFailureAction.STOP,
) -> ContextRequirement:
    return ContextRequirement(
        key=key,
        claim_type=claim_type,
        critical=critical,
        require_verified=require_verified,
        max_age_seconds=max_age_seconds,
        failure_action=failure_action,
    )


def _policy(
    requirements: tuple[ContextRequirement, ...],
):
    return build_cognitive_rehydration_policy(
        task_id=_TASK_ID,
        checkpoint_id=_CHECKPOINT_ID,
        task_revision=7,
        task_state_sha256=_digest("state"),
        requirements=requirements,
    )


def _decision_state(
    requirement: ContextRequirement,
    *,
    status: DecisionStatus,
) -> DecisionStateSnapshot:
    assumption = AssumptionRecord(
        task_id=_TASK_ID,
        key=requirement.key,
        statement="Historical basis.",
        claim_type=requirement.claim_type.value,
        critical=requirement.critical,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("evidence:historical",),
    )
    service = DecisionStateService()
    snapshot = service.record_assumption(
        DecisionStateSnapshot.empty(_TASK_ID),
        assumption,
    )
    reason = (
        "Historical decision is no longer active."
        if status is DecisionStatus.INVALIDATED
        else None
    )
    decision = DecisionRecord(
        task_id=_TASK_ID,
        action_key="continue",
        description="Continue using the historical basis.",
        status=status,
        assumption_ids=(assumption.assumption_id,),
        reason=reason,
    )
    return service.record_decision(snapshot, decision)


def test_exact_current_requirement_is_preserved_for_active_basis() -> None:
    historical = _requirement()
    result = reconcile_cognitive_rehydration_requirements(
        historical_policy=_policy((historical,)),
        current_requirements=(historical,),
        decision_state=_decision_state(
            historical,
            status=DecisionStatus.ACTIVE,
        ),
    )

    assert result.effective_requirements == (historical,)
    assert result.active_historical_keys == ("current_head",)
    assert result.historical_floor_keys == ()
    assert result.strengthened_current_keys == ()


def test_missing_current_requirement_preserves_active_historical_floor() -> None:
    historical = _requirement()
    result = reconcile_cognitive_rehydration_requirements(
        historical_policy=_policy((historical,)),
        current_requirements=(),
        decision_state=_decision_state(
            historical,
            status=DecisionStatus.ACTIVE,
        ),
    )

    assert result.effective_requirements == (historical,)
    assert result.historical_floor_keys == ("current_head",)


def test_current_policy_cannot_weaken_active_historical_requirement() -> None:
    historical = _requirement()
    weaker = _requirement(
        critical=False,
        require_verified=False,
        max_age_seconds=None,
        failure_action=ContextFailureAction.VERIFY,
    )

    result = reconcile_cognitive_rehydration_requirements(
        historical_policy=_policy((historical,)),
        current_requirements=(weaker,),
        decision_state=_decision_state(
            historical,
            status=DecisionStatus.ACTIVE,
        ),
    )

    assert result.effective_requirements == (historical,)
    assert result.historical_floor_keys == ("current_head",)


def test_current_policy_may_strengthen_active_historical_requirement() -> None:
    historical = _requirement(
        critical=False,
        require_verified=False,
        max_age_seconds=None,
        failure_action=ContextFailureAction.VERIFY,
    )
    stronger = _requirement(
        critical=True,
        require_verified=True,
        max_age_seconds=30,
        failure_action=ContextFailureAction.STOP,
    )

    result = reconcile_cognitive_rehydration_requirements(
        historical_policy=_policy((historical,)),
        current_requirements=(stronger,),
        decision_state=_decision_state(
            historical,
            status=DecisionStatus.ACTIVE,
        ),
    )

    assert result.effective_requirements == (stronger,)
    assert result.strengthened_current_keys == ("current_head",)


@pytest.mark.parametrize(
    "status",
    (DecisionStatus.COMPLETED, DecisionStatus.INVALIDATED),
)
def test_terminal_decision_history_does_not_resurrect_requirement(
    status: DecisionStatus,
) -> None:
    historical = _requirement()

    result = reconcile_cognitive_rehydration_requirements(
        historical_policy=_policy((historical,)),
        current_requirements=(),
        decision_state=_decision_state(historical, status=status),
    )

    assert result.effective_requirements == ()
    assert result.active_historical_keys == ()
    assert result.dropped_inactive_historical_keys == ("current_head",)


def test_pending_decision_does_not_authorize_historical_floor() -> None:
    historical = _requirement()

    result = reconcile_cognitive_rehydration_requirements(
        historical_policy=_policy((historical,)),
        current_requirements=(),
        decision_state=_decision_state(
            historical,
            status=DecisionStatus.PENDING,
        ),
    )

    assert result.effective_requirements == ()
    assert result.dropped_inactive_historical_keys == ("current_head",)


def test_missing_decision_state_conservatively_preserves_history() -> None:
    historical = _requirement()

    result = reconcile_cognitive_rehydration_requirements(
        historical_policy=_policy((historical,)),
        current_requirements=(),
        decision_state=None,
    )

    assert result.effective_requirements == (historical,)
    assert result.historical_floor_keys == ("current_head",)


def test_current_only_requirement_is_retained() -> None:
    historical = _requirement()
    current_only = _requirement(
        key="active_failure_class",
        claim_type=ContextClaimType.EXECUTION_STATE,
        max_age_seconds=15,
        failure_action=ContextFailureAction.VERIFY,
    )

    result = reconcile_cognitive_rehydration_requirements(
        historical_policy=_policy((historical,)),
        current_requirements=(current_only,),
        decision_state=_decision_state(
            historical,
            status=DecisionStatus.COMPLETED,
        ),
    )

    assert result.effective_requirements == (current_only,)


def test_active_same_key_different_claim_type_is_rejected() -> None:
    historical = _requirement()
    incompatible = _requirement(
        claim_type=ContextClaimType.EXECUTION_STATE,
    )

    with pytest.raises(ValueError, match="claim type conflicts"):
        reconcile_cognitive_rehydration_requirements(
            historical_policy=_policy((historical,)),
            current_requirements=(incompatible,),
            decision_state=_decision_state(
                historical,
                status=DecisionStatus.ACTIVE,
            ),
        )


def test_effective_requirements_are_deterministically_sorted() -> None:
    historical = _requirement()
    second = _requirement(
        key="active_failure_class",
        claim_type=ContextClaimType.EXECUTION_STATE,
        max_age_seconds=15,
        failure_action=ContextFailureAction.VERIFY,
    )

    result = reconcile_cognitive_rehydration_requirements(
        historical_policy=_policy((historical,)),
        current_requirements=(historical, second),
        decision_state=_decision_state(
            historical,
            status=DecisionStatus.ACTIVE,
        ),
    )

    assert tuple(
        item.key for item in result.effective_requirements
    ) == ("active_failure_class", "current_head")
