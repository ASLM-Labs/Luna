"""Build task contracts without silently inventing success criteria."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID, uuid4

from luna.contracts.enums import RiskLevel
from luna.contracts.task import TaskContract, TaskScope
from luna.intent.models import IntentResolution, RequestedAction
from luna.tasking.models import ContractDraftStatus, TaskContractDraft


def _clean(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


class TaskContractBuilder:
    """Create an auditable draft, then finalize only when ready."""

    def draft(
        self,
        *,
        intent: IntentResolution,
        scope: TaskScope,
        required_conditions: Iterable[str] = (),
        forbidden_outcomes: Iterable[str] = (),
        evidence_required: Iterable[str] = (),
        soft_preferences: Iterable[str] = (),
        risk_level: RiskLevel = RiskLevel.LOW,
        owner: str = "user",
        task_id: UUID | None = None,
    ) -> TaskContractDraft:
        required = _clean(required_conditions)
        forbidden = _clean(forbidden_outcomes)
        evidence = _clean(evidence_required)
        preferences = _clean(soft_preferences)

        unresolved = list(intent.unknowns)
        blocking: list[str] = []
        conflicts: list[str] = []

        if not required:
            unresolved.append("required_conditions")
            blocking.append("required_conditions")
        if not evidence:
            unresolved.append("evidence_required")
            blocking.append("evidence_required")

        write_actions = {
            RequestedAction.MODIFY,
            RequestedAction.CREATE,
            RequestedAction.DELETE,
        }
        if write_actions.intersection(intent.actions):
            if not scope.write_allowed or not scope.allowed_paths:
                unresolved.append("write_scope")
                blocking.append("write_scope")
            unresolved = [value for value in unresolved if value != "target_scope"]

        overlap = sorted(set(required) & set(forbidden))
        if overlap:
            conflicts.extend(f"required_and_forbidden:{value}" for value in overlap)

        status = (
            ContractDraftStatus.BLOCKED
            if blocking or conflicts
            else ContractDraftStatus.READY
        )
        return TaskContractDraft(
            task_id=task_id or uuid4(),
            objective=intent.objective,
            required_conditions=required,
            forbidden_outcomes=forbidden,
            evidence_required=evidence,
            soft_preferences=preferences,
            scope=scope,
            risk_level=risk_level,
            unresolved_unknowns=_clean(unresolved),
            blocking_unknowns=_clean(blocking),
            conflicts=_clean(conflicts),
            owner=owner,
            status=status,
        )

    def finalize(self, draft: TaskContractDraft) -> TaskContract:
        """Finalize a READY draft into the authoritative Phase 1 contract."""
        if draft.status is not ContractDraftStatus.READY:
            raise ValueError("cannot finalize a blocked task-contract draft")
        return TaskContract(
            task_id=draft.task_id,
            objective=draft.objective,
            required_conditions=draft.required_conditions,
            forbidden_outcomes=draft.forbidden_outcomes,
            evidence_required=draft.evidence_required,
            scope=draft.scope,
            risk_level=draft.risk_level,
            unknowns=draft.unresolved_unknowns,
            owner=draft.owner,
        )
