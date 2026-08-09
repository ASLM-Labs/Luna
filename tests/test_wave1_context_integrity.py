from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from luna.context import (
    ContextAuthorityRole,
    ContextClaim,
    ContextClaimType,
    ContextFailureAction,
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
    contract = TaskContract(
        task_id=task_id,
        objective="Validate Wave 1 context integrity.",
        required_conditions=("Context integrity is proven.",),
        evidence_required=("Deterministic context evidence exists.",),
        scope=TaskScope(workspace_root="C:/repo"),
        risk_level=RiskLevel.LOW,
    )
    return TaskState(
        task_id=task_id,
        contract=contract,
        decision_state=DecisionStateSnapshot.empty(task_id),
    )


def _bundle(task_id):
    return LayeredContextComposer().compose(task_id=task_id, candidates=())


def _claim(
    *,
    task_id,
    key: str,
    value: str,
    claim_type: ContextClaimType,
    role: ContextAuthorityRole,
    observed_at: datetime,
    source_kind: ContextSourceKind,
    verified: bool = True,
):
    return ContextClaim(
        task_id=task_id,
        key=key,
        value=value,
        claim_type=claim_type,
        source_kind=source_kind,
        source_ref=f"fixture://{role.value.lower()}/{key}/{value}",
        authority_role=role,
        observed_at=observed_at,
        verified=verified,
        evidence_refs=(f"evidence:{key}:{value}",),
    )


def test_current_git_supersedes_stale_memory_and_invalidates_dependent_decision() -> None:
    task_id = uuid4()
    service = DecisionStateService()
    state = _state(task_id)
    stale = AssumptionRecord(
        task_id=task_id,
        key="current_head",
        statement="current_head=6984870",
        claim_type=ContextClaimType.REPOSITORY_STATE.value,
        critical=True,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("memory:6984870",),
        provenance_refs=("memory://checkpoint",),
    )
    snapshot = service.record_assumption(state.decision_state, stale)  # type: ignore[arg-type]
    decision = DecisionRecord(
        task_id=task_id,
        action_key="use-baseline:6984870",
        description="Use the remembered commit as the current baseline.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(stale.assumption_id,),
    )
    snapshot = service.record_decision(snapshot, decision)
    state = state.revise(decision_state=snapshot)

    now = datetime(2026, 8, 9, 17, 0, tzinfo=UTC)
    claims = (
        _claim(
            task_id=task_id,
            key="current_head",
            value="6984870",
            claim_type=ContextClaimType.REPOSITORY_STATE,
            role=ContextAuthorityRole.VERIFIED_MEMORY,
            observed_at=now - timedelta(days=1),
            source_kind=ContextSourceKind.MEMORY,
        ),
        _claim(
            task_id=task_id,
            key="current_head",
            value="f535a43",
            claim_type=ContextClaimType.REPOSITORY_STATE,
            role=ContextAuthorityRole.CURRENT_OBSERVATION,
            observed_at=now,
            source_kind=ContextSourceKind.COMMAND_OUTPUT,
        ),
    )
    gate = ContextIntegrityGate(decision_state=service)
    report, state = gate.evaluate(
        state=state,
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
    assert report.resolutions[0].selected_value == "f535a43"
    assert state.decision_state is not None
    assumptions = [item for item in state.decision_state.assumptions if item.key == "current_head"]
    assert {item.status for item in assumptions} == {
        AssumptionStatus.SUPERSEDED,
        AssumptionStatus.SUPPORTED,
    }
    dependent = next(
        item for item in state.decision_state.decisions if item.decision_id == decision.decision_id
    )
    assert dependent.status is DecisionStatus.INVALIDATED


def test_canonical_project_rule_beats_stale_memory_for_artifact_direction() -> None:
    task_id = uuid4()
    state = _state(task_id)
    now = datetime(2026, 8, 9, 17, 0, tzinfo=UTC)
    claims = (
        _claim(
            task_id=task_id,
            key="user_to_sol_artifact_location",
            value="Downloads",
            claim_type=ContextClaimType.PROJECT_POLICY,
            role=ContextAuthorityRole.VERIFIED_MEMORY,
            observed_at=now - timedelta(hours=2),
            source_kind=ContextSourceKind.MEMORY,
        ),
        _claim(
            task_id=task_id,
            key="user_to_sol_artifact_location",
            value="Desktop",
            claim_type=ContextClaimType.PROJECT_POLICY,
            role=ContextAuthorityRole.CANONICAL_PROJECT,
            observed_at=now - timedelta(days=10),
            source_kind=ContextSourceKind.DOCUMENT,
        ),
    )
    report, state = ContextIntegrityGate().evaluate(
        state=state,
        bundle=_bundle(task_id),
        claims=claims,
        requirements=(
            ContextRequirement(
                key="user_to_sol_artifact_location",
                claim_type=ContextClaimType.PROJECT_POLICY,
            ),
        ),
    )

    assert report.decision is ReadinessDecision.READY
    assert report.resolutions[0].selected_value == "Desktop"
    assert state.decision_state is not None
    latest = DecisionStateService.latest_assumption(
        state.decision_state,
        "user_to_sol_artifact_location",
    )
    assert latest is not None and latest.statement.endswith("=Desktop")


def test_current_ci_evidence_supersedes_stale_expected_count() -> None:
    task_id = uuid4()
    state = _state(task_id)
    now = datetime(2026, 8, 9, 17, 0, tzinfo=UTC)
    claims = (
        _claim(
            task_id=task_id,
            key="ci_checks",
            value="4/4",
            claim_type=ContextClaimType.CURRENT_STATE,
            role=ContextAuthorityRole.VERIFIED_MEMORY,
            observed_at=now - timedelta(days=1),
            source_kind=ContextSourceKind.MEMORY,
        ),
        _claim(
            task_id=task_id,
            key="ci_checks",
            value="2/2",
            claim_type=ContextClaimType.CURRENT_STATE,
            role=ContextAuthorityRole.CURRENT_OBSERVATION,
            observed_at=now,
            source_kind=ContextSourceKind.COMMAND_OUTPUT,
        ),
    )
    report, _ = ContextIntegrityGate().evaluate(
        state=state,
        bundle=_bundle(task_id),
        claims=claims,
        requirements=(
            ContextRequirement(key="ci_checks", claim_type=ContextClaimType.CURRENT_STATE),
        ),
    )

    assert report.decision is ReadinessDecision.READY
    assert report.resolutions[0].selected_value == "2/2"


def test_missing_critical_context_never_returns_ready() -> None:
    task_id = uuid4()
    report, state = ContextIntegrityGate().evaluate(
        state=_state(task_id),
        bundle=_bundle(task_id),
        claims=(),
        requirements=(
            ContextRequirement(
                key="current_branch",
                claim_type=ContextClaimType.REPOSITORY_STATE,
            ),
        ),
    )

    assert report.decision is ReadinessDecision.VERIFY
    assert report.unresolved_critical_keys == ("current_branch",)
    assert state.decision_state is not None
    assumption = DecisionStateService.latest_assumption(state.decision_state, "current_branch")
    assert assumption is not None
    assert assumption.status is AssumptionStatus.UNVERIFIED


def test_equal_authority_conflict_can_force_stop() -> None:
    task_id = uuid4()
    state = _state(task_id)
    now = datetime(2026, 8, 9, 17, 0, tzinfo=UTC)
    claims = (
        _claim(
            task_id=task_id,
            key="current_branch",
            value="main",
            claim_type=ContextClaimType.REPOSITORY_STATE,
            role=ContextAuthorityRole.CURRENT_OBSERVATION,
            observed_at=now,
            source_kind=ContextSourceKind.COMMAND_OUTPUT,
        ),
        _claim(
            task_id=task_id,
            key="current_branch",
            value="feature/x",
            claim_type=ContextClaimType.REPOSITORY_STATE,
            role=ContextAuthorityRole.CURRENT_OBSERVATION,
            observed_at=now,
            source_kind=ContextSourceKind.COMMAND_OUTPUT,
        ),
    )
    report, state = ContextIntegrityGate().evaluate(
        state=state,
        bundle=_bundle(task_id),
        claims=claims,
        requirements=(
            ContextRequirement(
                key="current_branch",
                claim_type=ContextClaimType.REPOSITORY_STATE,
                failure_action=ContextFailureAction.STOP,
            ),
        ),
    )

    assert report.decision is ReadinessDecision.STOP
    assert report.conflicting_critical_keys == ("current_branch",)
    assert state.decision_state is not None
    assumption = DecisionStateService.latest_assumption(state.decision_state, "current_branch")
    assert assumption is not None and assumption.status is AssumptionStatus.CONTRADICTED


def test_changed_failure_basis_updates_execution_assumption() -> None:
    task_id = uuid4()
    service = DecisionStateService()
    state = _state(task_id)
    old = AssumptionRecord(
        task_id=task_id,
        key="active_failure_class",
        statement="active_failure_class=Ruff",
        claim_type=ContextClaimType.EXECUTION_STATE.value,
        critical=True,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("test:ruff-fail",),
        provenance_refs=("tool://ruff",),
    )
    snapshot = service.record_assumption(state.decision_state, old)  # type: ignore[arg-type]
    decision = DecisionRecord(
        task_id=task_id,
        action_key="repair:ruff",
        description="Repair Ruff failures.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(old.assumption_id,),
    )
    state = state.revise(decision_state=service.record_decision(snapshot, decision))
    now = datetime(2026, 8, 9, 17, 0, tzinfo=UTC)
    claims = (
        _claim(
            task_id=task_id,
            key="active_failure_class",
            value="mypy",
            claim_type=ContextClaimType.EXECUTION_STATE,
            role=ContextAuthorityRole.CURRENT_OBSERVATION,
            observed_at=now,
            source_kind=ContextSourceKind.COMMAND_OUTPUT,
        ),
    )
    report, state = ContextIntegrityGate(decision_state=service).evaluate(
        state=state,
        bundle=_bundle(task_id),
        claims=claims,
        requirements=(
            ContextRequirement(
                key="active_failure_class",
                claim_type=ContextClaimType.EXECUTION_STATE,
            ),
        ),
    )

    assert report.decision is ReadinessDecision.READY
    assert state.decision_state is not None
    old_record = next(
        item for item in state.decision_state.assumptions if item.assumption_id == old.assumption_id
    )
    assert old_record.status is AssumptionStatus.SUPERSEDED
    assert state.decision_state.decisions[0].status is DecisionStatus.INVALIDATED
