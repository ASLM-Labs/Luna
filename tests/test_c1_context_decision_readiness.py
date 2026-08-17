from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from luna.context import (
    ContextAuthorityRole,
    ContextClaim,
    ContextClaimType,
    ContextIntegrityGate,
    ContextRequirement,
    ContextSourceKind,
    LayeredContextComposer,
    ReadinessDecision,
)
from luna.contracts import (
    AssumptionRecord,
    AssumptionStatus,
    DecisionRecord,
    DecisionStateSnapshot,
    DecisionStatus,
    RiskLevel,
    TaskContract,
    TaskScope,
    TaskState,
)
from luna.decision_state import DecisionStateService


def _state(task_id):
    return TaskState(
        task_id=task_id,
        contract=TaskContract(
            task_id=task_id,
            objective="Validate C1 context and decision readiness.",
            required_conditions=("Critical context is reconciled.",),
            evidence_required=("Structured context evidence exists.",),
            scope=TaskScope(workspace_root="C:/repo"),
            risk_level=RiskLevel.LOW,
        ),
        decision_state=DecisionStateSnapshot.empty(task_id),
    )


def _bundle(task_id):
    return LayeredContextComposer().compose(task_id=task_id, candidates=())


def _claim(*, task_id, key: str, value: str, verified: bool = True):
    return ContextClaim(
        task_id=task_id,
        key=key,
        value=value,
        claim_type=ContextClaimType.REPOSITORY_STATE,
        source_kind=ContextSourceKind.COMMAND_OUTPUT,
        source_ref=f"git://{key}/{value}",
        authority_role=ContextAuthorityRole.CURRENT_OBSERVATION,
        observed_at=datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
        verified=verified,
        evidence_refs=((f"git:{key}:{value}",) if verified else ()),
    )


def test_verified_context_claim_requires_evidence_refs() -> None:
    task_id = uuid4()

    with pytest.raises(ValueError, match="verified context claim requires evidence refs"):
        ContextClaim(
            task_id=task_id,
            key="current_head",
            value="abc123",
            claim_type=ContextClaimType.REPOSITORY_STATE,
            source_kind=ContextSourceKind.COMMAND_OUTPUT,
            source_ref="git://head/abc123",
            authority_role=ContextAuthorityRole.CURRENT_OBSERVATION,
            observed_at=datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
            verified=True,
        )


def test_unverified_claim_cannot_satisfy_verified_requirement() -> None:
    task_id = uuid4()
    report, state = ContextIntegrityGate().evaluate(
        state=_state(task_id),
        bundle=_bundle(task_id),
        claims=(_claim(task_id=task_id, key="current_head", value="abc123", verified=False),),
        requirements=(
            ContextRequirement(
                key="current_head",
                claim_type=ContextClaimType.REPOSITORY_STATE,
            ),
        ),
    )

    assert report.decision is ReadinessDecision.VERIFY
    assert report.unresolved_critical_keys == ("current_head",)
    assert len(report.blocking_assumption_ids) == 1
    assert state.decision_state is not None
    assumption = DecisionStateService.latest_assumption(
        state.decision_state,
        "current_head",
        ContextClaimType.REPOSITORY_STATE.value,
    )
    assert assumption is not None
    assert assumption.status is AssumptionStatus.UNVERIFIED


def test_explicit_nonverified_requirement_can_accept_observed_claim() -> None:
    task_id = uuid4()
    report, state = ContextIntegrityGate().evaluate(
        state=_state(task_id),
        bundle=_bundle(task_id),
        claims=(_claim(task_id=task_id, key="current_head", value="abc123", verified=False),),
        requirements=(
            ContextRequirement(
                key="current_head",
                claim_type=ContextClaimType.REPOSITORY_STATE,
                require_verified=False,
            ),
        ),
    )

    assert report.decision is ReadinessDecision.READY
    assert report.blocking_assumption_ids == ()
    assert state.decision_state is not None
    assumption = DecisionStateService.latest_assumption(
        state.decision_state,
        "current_head",
        ContextClaimType.REPOSITORY_STATE.value,
    )
    assert assumption is not None
    assert assumption.status is AssumptionStatus.SUPPORTED


def test_lost_support_invalidates_dependent_active_decision() -> None:
    task_id = uuid4()
    service = DecisionStateService()
    state = _state(task_id)
    assumption = AssumptionRecord(
        task_id=task_id,
        key="current_head",
        statement="current_head=abc123",
        claim_type=ContextClaimType.REPOSITORY_STATE.value,
        critical=True,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("git:head:abc123",),
        provenance_refs=("git://head/abc123",),
    )
    snapshot = service.record_assumption(state.decision_state, assumption)  # type: ignore[arg-type]
    decision = DecisionRecord(
        task_id=task_id,
        action_key="use-current-head",
        description="Continue from the verified current HEAD.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(assumption.assumption_id,),
    )
    snapshot = service.record_decision(snapshot, decision)
    state = state.revise(decision_state=snapshot)

    report, state = ContextIntegrityGate(decision_state=service).evaluate(
        state=state,
        bundle=_bundle(task_id),
        claims=(),
        requirements=(
            ContextRequirement(
                key="current_head",
                claim_type=ContextClaimType.REPOSITORY_STATE,
            ),
        ),
    )

    assert report.decision is ReadinessDecision.VERIFY
    assert report.invalidated_decision_ids == (decision.decision_id,)
    assert state.decision_state is not None
    updated = next(
        item for item in state.decision_state.decisions if item.decision_id == decision.decision_id
    )
    assert updated.status is DecisionStatus.INVALIDATED


def test_persisted_contradicted_critical_assumption_blocks_readiness() -> None:
    task_id = uuid4()
    service = DecisionStateService()
    state = _state(task_id)
    contradicted = AssumptionRecord(
        task_id=task_id,
        key="workspace_identity",
        statement="workspace_identity=old",
        claim_type=ContextClaimType.CURRENT_STATE.value,
        critical=True,
        status=AssumptionStatus.CONTRADICTED,
        reason="current workspace evidence disagrees",
    )
    snapshot = service.record_assumption(
        state.decision_state,  # type: ignore[arg-type]
        contradicted,
    )
    state = state.revise(decision_state=snapshot)

    report, _ = ContextIntegrityGate(decision_state=service).evaluate(
        state=state,
        bundle=_bundle(task_id),
    )

    assert report.decision is ReadinessDecision.STOP
    assert report.blocking_assumption_ids == (contradicted.assumption_id,)
    assert report.contradicted_assumption_ids == (contradicted.assumption_id,)


def test_same_key_different_claim_type_does_not_supersede_other_identity() -> None:
    task_id = uuid4()
    service = DecisionStateService()
    state = _state(task_id)
    repository_assumption = AssumptionRecord(
        task_id=task_id,
        key="status",
        statement="status=repository-clean",
        claim_type=ContextClaimType.REPOSITORY_STATE.value,
        critical=False,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("git:status:clean",),
        provenance_refs=("git://status",),
    )
    snapshot = service.record_assumption(
        state.decision_state,  # type: ignore[arg-type]
        repository_assumption,
    )
    state = state.revise(decision_state=snapshot)

    report, state = ContextIntegrityGate(decision_state=service).evaluate(
        state=state,
        bundle=_bundle(task_id),
        claims=(
            ContextClaim(
                task_id=task_id,
                key="status",
                value="runtime-ready",
                claim_type=ContextClaimType.CURRENT_STATE,
                source_kind=ContextSourceKind.COMMAND_OUTPUT,
                source_ref="runtime://status",
                authority_role=ContextAuthorityRole.CURRENT_OBSERVATION,
                observed_at=datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
                verified=True,
                evidence_refs=("runtime:status:ready",),
            ),
        ),
        requirements=(
            ContextRequirement(
                key="status",
                claim_type=ContextClaimType.CURRENT_STATE,
            ),
        ),
    )

    assert report.decision is ReadinessDecision.READY
    assert state.decision_state is not None
    repository_latest = service.latest_assumption(
        state.decision_state,
        "status",
        ContextClaimType.REPOSITORY_STATE.value,
    )
    current_latest = service.latest_assumption(
        state.decision_state,
        "status",
        ContextClaimType.CURRENT_STATE.value,
    )
    assert repository_latest is not None
    assert repository_latest.status is AssumptionStatus.SUPPORTED
    assert current_latest is not None
    assert current_latest.statement == "status=runtime-ready"


def test_context_bundle_task_mismatch_is_rejected() -> None:
    task_id = uuid4()

    with pytest.raises(ValueError, match="context bundle task_id mismatch"):
        ContextIntegrityGate().evaluate(
            state=_state(task_id),
            bundle=_bundle(uuid4()),
        )


def test_persisted_unverified_critical_assumption_requires_verification() -> None:
    task_id = uuid4()
    service = DecisionStateService()
    state = _state(task_id)
    unresolved = AssumptionRecord(
        task_id=task_id,
        key="current_branch",
        statement="current_branch=unknown",
        claim_type=ContextClaimType.REPOSITORY_STATE.value,
        critical=True,
        status=AssumptionStatus.UNVERIFIED,
    )
    snapshot = service.record_assumption(state.decision_state, unresolved)  # type: ignore[arg-type]
    state = state.revise(decision_state=snapshot)

    report, _ = ContextIntegrityGate(decision_state=service).evaluate(
        state=state,
        bundle=_bundle(task_id),
    )

    assert report.decision is ReadinessDecision.VERIFY
    assert report.blocking_assumption_ids == (unresolved.assumption_id,)
    assert report.contradicted_assumption_ids == ()


def test_current_conflict_respects_verify_failure_action() -> None:
    task_id = uuid4()
    observed_at = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)
    claims = (
        ContextClaim(
            task_id=task_id,
            key="current_branch",
            value="main",
            claim_type=ContextClaimType.REPOSITORY_STATE,
            source_kind=ContextSourceKind.COMMAND_OUTPUT,
            source_ref="git://branch/main",
            authority_role=ContextAuthorityRole.CURRENT_OBSERVATION,
            observed_at=observed_at,
            verified=True,
            evidence_refs=("git:branch:main",),
        ),
        ContextClaim(
            task_id=task_id,
            key="current_branch",
            value="feature/c1",
            claim_type=ContextClaimType.REPOSITORY_STATE,
            source_kind=ContextSourceKind.COMMAND_OUTPUT,
            source_ref="git://branch/feature-c1",
            authority_role=ContextAuthorityRole.CURRENT_OBSERVATION,
            observed_at=observed_at,
            verified=True,
            evidence_refs=("git:branch:feature-c1",),
        ),
    )

    report, _ = ContextIntegrityGate().evaluate(
        state=_state(task_id),
        bundle=_bundle(task_id),
        claims=claims,
        requirements=(
            ContextRequirement(
                key="current_branch",
                claim_type=ContextClaimType.REPOSITORY_STATE,
            ),
        ),
    )

    assert report.decision is ReadinessDecision.VERIFY
    assert report.conflicting_critical_keys == ("current_branch",)
    assert len(report.blocking_assumption_ids) == 1


def test_verified_requirement_ignores_unverified_higher_authority_claim() -> None:
    task_id = uuid4()
    observed_at = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)
    claims = (
        ContextClaim(
            task_id=task_id,
            key="current_head",
            value="unverified-head",
            claim_type=ContextClaimType.REPOSITORY_STATE,
            source_kind=ContextSourceKind.COMMAND_OUTPUT,
            source_ref="git://head/unverified",
            authority_role=ContextAuthorityRole.CURRENT_OBSERVATION,
            observed_at=observed_at,
            verified=False,
        ),
        ContextClaim(
            task_id=task_id,
            key="current_head",
            value="verified-head",
            claim_type=ContextClaimType.REPOSITORY_STATE,
            source_kind=ContextSourceKind.DOCUMENT,
            source_ref="project://head/verified",
            authority_role=ContextAuthorityRole.CANONICAL_PROJECT,
            observed_at=observed_at,
            verified=True,
            evidence_refs=("project:head:verified",),
        ),
    )

    report, _ = ContextIntegrityGate().evaluate(
        state=_state(task_id),
        bundle=_bundle(task_id),
        claims=claims,
        requirements=(
            ContextRequirement(
                key="current_head",
                claim_type=ContextClaimType.REPOSITORY_STATE,
            ),
        ),
    )

    assert report.decision is ReadinessDecision.READY
    assert report.resolutions[0].selected_value == "verified-head"
