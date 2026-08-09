"""RECONCILE and READINESS gate over explicitly recalled context."""

from __future__ import annotations

from collections.abc import Iterable

from luna.context.authority import ContextAuthorityResolver
from luna.context.integrity_models import (
    ContextClaim,
    ContextFailureAction,
    ContextReadinessReport,
    ContextRequirement,
    ContextResolutionStatus,
    ReadinessDecision,
)
from luna.context.layered import LayeredContextBundle
from luna.contracts.base import stable_payload, utc_now
from luna.contracts.decision import AssumptionRecord, AssumptionStatus
from luna.contracts.state import TaskState
from luna.decision_state import DecisionStateService


class ContextIntegrityGate:
    """Reconcile critical context, update A2 state, and return READY/VERIFY/STOP."""

    def __init__(
        self,
        *,
        resolver: ContextAuthorityResolver | None = None,
        decision_state: DecisionStateService | None = None,
    ) -> None:
        self._resolver = resolver or ContextAuthorityResolver()
        self._decision_state = decision_state or DecisionStateService()

    def evaluate(
        self,
        *,
        state: TaskState,
        bundle: LayeredContextBundle,
        claims: Iterable[ContextClaim] = (),
        requirements: Iterable[ContextRequirement] = (),
    ) -> tuple[ContextReadinessReport, TaskState]:
        snapshot = self._decision_state.ensure(state.task_id, state.decision_state)
        claims_tuple = tuple(claims)
        requirements_tuple = tuple(requirements)
        if any(claim.task_id != state.task_id for claim in claims_tuple):
            raise ValueError("context claim task_id mismatch")

        resolutions = tuple(
            self._resolver.resolve(
                task_id=state.task_id,
                requirement=requirement,
                claims=claims_tuple,
            )
            for requirement in requirements_tuple
        )

        for resolution in resolutions:
            requirement = resolution.requirement
            latest = self._decision_state.latest_assumption(snapshot, requirement.key)
            if resolution.status is ContextResolutionStatus.RESOLVED:
                selected = next(
                    claim
                    for claim in claims_tuple
                    if claim.claim_id == resolution.selected_claim_id
                )
                statement = f"{requirement.key}={selected.value}"
                evidence_refs = tuple(
                    dict.fromkeys((*selected.evidence_refs, f"context:{selected.claim_id}"))
                )
                provenance_refs = (selected.source_ref,)
                if latest is None:
                    snapshot = self._decision_state.record_assumption(
                        snapshot,
                        AssumptionRecord(
                            task_id=state.task_id,
                            key=requirement.key,
                            statement=statement,
                            claim_type=requirement.claim_type.value,
                            critical=requirement.critical,
                            status=AssumptionStatus.SUPPORTED,
                            evidence_refs=evidence_refs,
                            provenance_refs=provenance_refs,
                        ),
                    )
                elif latest.statement == statement:
                    snapshot = self._decision_state.transition_assumption(
                        snapshot,
                        assumption_id=latest.assumption_id,
                        status=AssumptionStatus.SUPPORTED,
                        evidence_refs=evidence_refs,
                        provenance_refs=provenance_refs,
                        reason=None,
                    )
                else:
                    replacement = AssumptionRecord(
                        task_id=state.task_id,
                        key=requirement.key,
                        statement=statement,
                        claim_type=requirement.claim_type.value,
                        critical=requirement.critical,
                        status=AssumptionStatus.SUPPORTED,
                        evidence_refs=evidence_refs,
                        provenance_refs=provenance_refs,
                    )
                    snapshot = self._decision_state.supersede_and_record(
                        snapshot,
                        previous=latest,
                        replacement=replacement,
                        reason=(
                            f"authoritative context changed {requirement.key} "
                            f"from {latest.statement!r} to {statement!r}"
                        ),
                    )
                continue

            target_status = (
                AssumptionStatus.CONTRADICTED
                if resolution.status is ContextResolutionStatus.CONFLICTING
                else AssumptionStatus.UNVERIFIED
            )
            reason = "; ".join(resolution.reasons) or "context requirement unresolved"
            if latest is None:
                snapshot = self._decision_state.record_assumption(
                    snapshot,
                    AssumptionRecord(
                        task_id=state.task_id,
                        key=requirement.key,
                        statement=f"unresolved:{requirement.key}",
                        claim_type=requirement.claim_type.value,
                        critical=requirement.critical,
                        status=target_status,
                        reason=(reason if target_status is AssumptionStatus.CONTRADICTED else None),
                    ),
                )
            else:
                snapshot = self._decision_state.transition_assumption(
                    snapshot,
                    assumption_id=latest.assumption_id,
                    status=target_status,
                    reason=(reason if target_status is AssumptionStatus.CONTRADICTED else None),
                )

        unresolved_critical = tuple(
            resolution.requirement.key
            for resolution in resolutions
            if resolution.requirement.critical
            and resolution.status is ContextResolutionStatus.UNRESOLVED
        )
        conflicting_critical = tuple(
            resolution.requirement.key
            for resolution in resolutions
            if resolution.requirement.critical
            and resolution.status is ContextResolutionStatus.CONFLICTING
        )
        critical_problem_keys = set((*unresolved_critical, *conflicting_critical))
        stop_required = any(
            requirement.critical
            and requirement.key in critical_problem_keys
            and requirement.failure_action is ContextFailureAction.STOP
            for requirement in requirements_tuple
        )

        if stop_required:
            decision = ReadinessDecision.STOP
        elif bundle.missing_sources or critical_problem_keys:
            decision = ReadinessDecision.VERIFY
        else:
            decision = ReadinessDecision.READY

        reasons: list[str] = []
        if bundle.missing_sources:
            reasons.append("required raw context sources are missing")
        if unresolved_critical:
            reasons.append("critical structured context is unresolved")
        if conflicting_critical:
            reasons.append("critical structured context is conflicting")
        if not reasons:
            reasons.append("all required context is reconciled and ready")

        report = ContextReadinessReport(
            task_id=state.task_id,
            decision=decision,
            resolutions=resolutions,
            raw_missing_sources=bundle.missing_sources,
            unresolved_critical_keys=unresolved_critical,
            conflicting_critical_keys=conflicting_critical,
            reasons=tuple(reasons),
        )
        state_payload = stable_payload(state)
        state_payload.update(
            {
                "decision_state": snapshot.model_dump(mode="json"),
                "revision": state.revision + 1,
                "updated_at": utc_now(),
            }
        )
        return report, TaskState.model_validate(state_payload)
