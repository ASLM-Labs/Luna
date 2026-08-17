"""Pure reconciliation of historical and current context-readiness policy."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from luna.context.integrity_models import (
    ContextFailureAction,
    ContextRequirement,
)
from luna.continuity.cognitive import CognitiveRehydrationPolicy
from luna.contracts.base import LunaContractModel
from luna.contracts.decision import (
    DecisionStateSnapshot,
    DecisionStatus,
)


class CognitiveRequirementReconciliation(LunaContractModel):
    """Observable non-authoritative result of rehydration policy reconciliation."""

    historical_policy_id: str
    effective_requirements: tuple[ContextRequirement, ...]
    active_historical_keys: tuple[str, ...] = ()
    historical_floor_keys: tuple[str, ...] = ()
    strengthened_current_keys: tuple[str, ...] = ()
    dropped_inactive_historical_keys: tuple[str, ...] = ()

    runtime_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    completion_authority: Literal[False] = False


def _max_age_floor(
    historical: int | None,
    current: int | None,
) -> int | None:
    if historical is None:
        return current
    if current is None:
        return historical
    return min(historical, current)


def _merge_requirement_floor(
    historical: ContextRequirement,
    current: ContextRequirement,
) -> ContextRequirement:
    if historical.key != current.key:
        raise ValueError("requirement floor merge requires matching keys")
    if historical.claim_type is not current.claim_type:
        raise ValueError(
            "current requirement claim type conflicts with historical policy"
        )

    failure_action = (
        ContextFailureAction.STOP
        if (
            historical.failure_action is ContextFailureAction.STOP
            or current.failure_action is ContextFailureAction.STOP
        )
        else ContextFailureAction.VERIFY
    )

    return ContextRequirement(
        key=historical.key,
        claim_type=historical.claim_type,
        critical=historical.critical or current.critical,
        require_verified=(
            historical.require_verified or current.require_verified
        ),
        max_age_seconds=_max_age_floor(
            historical.max_age_seconds,
            current.max_age_seconds,
        ),
        failure_action=failure_action,
    )


def _active_assumption_identities(
    snapshot: DecisionStateSnapshot | None,
) -> set[tuple[str, str]] | None:
    if snapshot is None:
        return None

    assumptions = {
        item.assumption_id: item
        for item in snapshot.assumptions
    }
    identities: set[tuple[str, str]] = set()

    for decision in snapshot.decisions:
        if decision.status is not DecisionStatus.ACTIVE:
            continue
        for assumption_id in decision.assumption_ids:
            assumption = assumptions.get(assumption_id)
            if assumption is None:
                raise ValueError(
                    "ACTIVE decision references unknown assumption"
                )
            identities.add((assumption.key, assumption.claim_type))

    return identities


def reconcile_cognitive_rehydration_requirements(
    *,
    historical_policy: CognitiveRehydrationPolicy,
    current_requirements: Iterable[ContextRequirement],
    decision_state: DecisionStateSnapshot | None,
) -> CognitiveRequirementReconciliation:
    """Apply historical policy only as a floor for still-active decision basis."""

    current_tuple = tuple(current_requirements)
    current_by_key = {item.key: item for item in current_tuple}
    if len(current_by_key) != len(current_tuple):
        raise ValueError("current context requirement keys must be unique")

    active_identities = _active_assumption_identities(decision_state)

    effective = dict(current_by_key)
    active_historical_keys: list[str] = []
    historical_floor_keys: list[str] = []
    strengthened_current_keys: list[str] = []
    dropped_inactive_keys: list[str] = []

    for historical in historical_policy.requirements:
        identity = (historical.key, historical.claim_type.value)
        relevant = (
            active_identities is None
            or identity in active_identities
        )
        if not relevant:
            dropped_inactive_keys.append(historical.key)
            continue

        active_historical_keys.append(historical.key)
        current = current_by_key.get(historical.key)
        if current is None:
            effective[historical.key] = historical
            historical_floor_keys.append(historical.key)
            continue

        merged = _merge_requirement_floor(historical, current)
        effective[historical.key] = merged
        if merged != current:
            historical_floor_keys.append(historical.key)
        if merged != historical:
            strengthened_current_keys.append(historical.key)

    ordered = tuple(
        sorted(
            effective.values(),
            key=lambda item: (item.key, item.claim_type.value),
        )
    )
    return CognitiveRequirementReconciliation(
        historical_policy_id=historical_policy.policy_id,
        effective_requirements=ordered,
        active_historical_keys=tuple(sorted(active_historical_keys)),
        historical_floor_keys=tuple(sorted(historical_floor_keys)),
        strengthened_current_keys=tuple(
            sorted(strengthened_current_keys)
        ),
        dropped_inactive_historical_keys=tuple(
            sorted(dropped_inactive_keys)
        ),
    )
