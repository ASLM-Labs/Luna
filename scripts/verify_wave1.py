"""Deterministic Wave 1 A2/A1 context and decision-state foundation gate."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.context import (  # noqa: E402
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
from luna.contracts import (  # noqa: E402
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
from luna.decision_state import DecisionStateService  # noqa: E402

_REQUIRED_FILES = (
    "src/luna/contracts/decision.py",
    "src/luna/decision_state/__init__.py",
    "src/luna/decision_state/service.py",
    "src/luna/context/integrity_models.py",
    "src/luna/context/authority.py",
    "src/luna/context/integrity.py",
    "tests/test_wave1_decision_state.py",
    "tests/test_wave1_context_integrity.py",
    "scripts/verify_wave1.py",
)

_FORBIDDEN_AUTHORITY_IMPORTS = (
    "from luna.memory",
    "import luna.memory",
    "from luna.learning",
    "import luna.learning",
    "from luna.sft",
    "import luna.sft",
    "from luna.capabilities",
    "import luna.capabilities",
)


def _state(task_id):
    contract = TaskContract(
        task_id=task_id,
        objective="Verify Wave 1 context and decision-state foundation.",
        required_conditions=("Critical context is reconciled before action.",),
        evidence_required=("Structured deterministic evidence exists.",),
        scope=TaskScope(workspace_root="C:/repo"),
        risk_level=RiskLevel.LOW,
    )
    return TaskState(
        task_id=task_id,
        contract=contract,
        decision_state=DecisionStateSnapshot.empty(task_id),
    )


def _claim(
    *,
    task_id,
    key: str,
    value: str,
    claim_type: ContextClaimType,
    role: ContextAuthorityRole,
    observed_at: datetime,
    source_kind: ContextSourceKind,
):
    return ContextClaim(
        task_id=task_id,
        key=key,
        value=value,
        claim_type=claim_type,
        source_kind=source_kind,
        source_ref=f"verify://{role.value}/{key}/{value}",
        authority_role=role,
        observed_at=observed_at,
        verified=True,
        evidence_refs=(f"verify:{key}:{value}",),
    )


def _authority_boundary_clean() -> bool:
    for relative in _REQUIRED_FILES[:6]:
        text = (ROOT / relative).read_text(encoding="utf-8")
        if any(item in text for item in _FORBIDDEN_AUTHORITY_IMPORTS):
            return False
    return True


def main() -> int:
    checks: dict[str, bool] = {
        "required_files_present": all((ROOT / item).is_file() for item in _REQUIRED_FILES),
        "authority_boundary_clean": _authority_boundary_clean(),
    }

    task_id = uuid4()
    state = _state(task_id)
    service = DecisionStateService()
    old_head = AssumptionRecord(
        task_id=task_id,
        key="current_head",
        statement="current_head=6984870",
        claim_type=ContextClaimType.REPOSITORY_STATE.value,
        critical=True,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("memory:6984870",),
        provenance_refs=("memory://checkpoint",),
    )
    stable_policy = AssumptionRecord(
        task_id=task_id,
        key="artifact_location",
        statement="artifact_location=Desktop",
        claim_type=ContextClaimType.PROJECT_POLICY.value,
        critical=True,
        status=AssumptionStatus.SUPPORTED,
        evidence_refs=("policy:desktop",),
        provenance_refs=("docs://canonical-policy",),
    )
    snapshot = service.record_assumption(state.decision_state, old_head)  # type: ignore[arg-type]
    snapshot = service.record_assumption(snapshot, stable_policy)
    head_decision = DecisionRecord(
        task_id=task_id,
        action_key="baseline:6984870",
        description="Use stale HEAD baseline.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(old_head.assumption_id,),
    )
    stable_decision = DecisionRecord(
        task_id=task_id,
        action_key="artifact:Desktop",
        description="Use canonical Desktop artifact direction.",
        status=DecisionStatus.ACTIVE,
        assumption_ids=(stable_policy.assumption_id,),
    )
    snapshot = service.record_decision(snapshot, head_decision)
    snapshot = service.record_decision(snapshot, stable_decision)
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
    bundle = LayeredContextComposer().compose(task_id=task_id, candidates=())
    report, state = ContextIntegrityGate(decision_state=service).evaluate(
        state=state,
        bundle=bundle,
        claims=claims,
        requirements=(
            ContextRequirement(
                key="current_head",
                claim_type=ContextClaimType.REPOSITORY_STATE,
            ),
        ),
    )
    assert state.decision_state is not None
    decision_by_id = {item.decision_id: item for item in state.decision_state.decisions}
    checks["authoritative_current_evidence_supersedes_stale_memory"] = bool(
        report.decision is ReadinessDecision.READY
        and report.resolutions[0].selected_value == "f535a43"
    )
    checks["dependent_decision_invalidated"] = bool(
        decision_by_id[head_decision.decision_id].status is DecisionStatus.INVALIDATED
    )
    checks["unrelated_decision_preserved"] = bool(
        decision_by_id[stable_decision.decision_id].status is DecisionStatus.ACTIVE
    )

    # Use one task ID for the missing-context fixture.
    missing_task = uuid4()
    missing_report, _ = ContextIntegrityGate().evaluate(
        state=_state(missing_task),
        bundle=LayeredContextComposer().compose(task_id=missing_task, candidates=()),
        requirements=(
            ContextRequirement(
                key="current_branch",
                claim_type=ContextClaimType.REPOSITORY_STATE,
            ),
        ),
    )
    checks["missing_critical_context_never_ready"] = bool(
        missing_report.decision is ReadinessDecision.VERIFY
        and missing_report.unresolved_critical_keys == ("current_branch",)
    )

    conflict_task = uuid4()
    conflict_time = datetime(2026, 8, 9, 17, 0, tzinfo=UTC)
    conflict_report, _ = ContextIntegrityGate().evaluate(
        state=_state(conflict_task),
        bundle=LayeredContextComposer().compose(task_id=conflict_task, candidates=()),
        claims=(
            _claim(
                task_id=conflict_task,
                key="current_branch",
                value="main",
                claim_type=ContextClaimType.REPOSITORY_STATE,
                role=ContextAuthorityRole.CURRENT_OBSERVATION,
                observed_at=conflict_time,
                source_kind=ContextSourceKind.COMMAND_OUTPUT,
            ),
            _claim(
                task_id=conflict_task,
                key="current_branch",
                value="feature/wave1",
                claim_type=ContextClaimType.REPOSITORY_STATE,
                role=ContextAuthorityRole.CURRENT_OBSERVATION,
                observed_at=conflict_time,
                source_kind=ContextSourceKind.COMMAND_OUTPUT,
            ),
        ),
        requirements=(
            ContextRequirement(
                key="current_branch",
                claim_type=ContextClaimType.REPOSITORY_STATE,
                failure_action=ContextFailureAction.STOP,
            ),
        ),
    )
    checks["equal_authority_conflict_stops"] = bool(
        conflict_report.decision is ReadinessDecision.STOP
        and conflict_report.conflicting_critical_keys == ("current_branch",)
    )

    roundtrip = TaskState.model_validate_json(state.model_dump_json())
    checks["decision_state_roundtrip"] = bool(
        roundtrip.decision_state == state.decision_state
    )

    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if failed:
        print("[REJECT] Wave 1 A2/A1 foundation failed: " + ", ".join(failed))
        return 1
    print("[PASS] Wave 1 A2/A1 context and decision-state foundation verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
