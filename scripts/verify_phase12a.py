"""Structural and behavioral verifier for Luna Phase 12A."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from luna.autonomy import AutonomyLevel, AutonomyPolicy
from luna.contracts import CompletionStatus, TaskContract, TaskScope, TaskState
from luna.contracts.enums import TaskPhase
from luna.runtime import (
    ActorRole,
    ActorVerificationSource,
    RequestSource,
    RuntimeActor,
    RuntimeBudget,
    RuntimeMode,
    RuntimeOutcome,
    RuntimeRequest,
    RuntimeStopReason,
    RuntimeUsage,
    build_task_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    required_files = (
        ROOT / "docs" / "rfcs" / "RFC-012A_SINGLE_POLICY_AGENT_RUNTIME.md",
        ROOT / "docs" / "baselines" / "PHASE_11_SOURCE_BASELINE.md",
        ROOT / "src" / "luna" / "runtime" / "__init__.py",
        ROOT / "src" / "luna" / "runtime" / "budgets.py",
        ROOT / "src" / "luna" / "runtime" / "dependencies.py",
        ROOT / "src" / "luna" / "runtime" / "fingerprints.py",
        ROOT / "src" / "luna" / "runtime" / "identity_context.py",
        ROOT / "src" / "luna" / "runtime" / "models.py",
        ROOT / "tests" / "test_phase12a_runtime_contracts.py",
    )
    missing = tuple(
        path.relative_to(ROOT).as_posix() for path in required_files if not path.is_file()
    )

    task_id = uuid4()
    actor = RuntimeActor(
        actor_id="phase12a-verifier",
        role=ActorRole.OWNER,
        verified=True,
        verification_source=ActorVerificationSource.TEST_FIXTURE,
        verified_at=datetime.now(UTC),
    )
    request = RuntimeRequest(
        task_id=task_id,
        raw_request="Verify the Phase 12A runtime contracts.",
        source=RequestSource.TEST,
        actor=actor,
        scope=TaskScope(workspace_root=str(ROOT)),
        autonomy=AutonomyPolicy(
            task_id=task_id,
            level=AutonomyLevel.LEVEL_1_READ_ONLY,
        ),
        runtime_budget=RuntimeBudget(),
        mode=RuntimeMode.DRY_RUN,
        required_conditions=("Runtime contracts are deterministic.",),
        evidence_required=("Phase 12A verifier",),
    )
    fingerprint_a = build_task_fingerprint(request)
    restored_request = RuntimeRequest.from_json(request.to_json())
    fingerprint_b = build_task_fingerprint(restored_request)
    second_task_id = uuid4()
    transient_variant = RuntimeRequest(
        task_id=second_task_id,
        raw_request=request.raw_request,
        source=request.source,
        actor=request.actor,
        scope=request.scope,
        autonomy=AutonomyPolicy(
            task_id=second_task_id,
            level=AutonomyLevel.LEVEL_1_READ_ONLY,
        ),
        runtime_budget=request.runtime_budget,
        mode=request.mode,
        required_conditions=request.required_conditions,
        evidence_required=request.evidence_required,
    )
    fingerprint_transient_variant = build_task_fingerprint(transient_variant)

    contract = TaskContract(
        task_id=task_id,
        objective="Verify Phase 12A completion contract.",
        required_conditions=("Contracts round-trip.",),
        evidence_required=("Phase 12A verifier",),
        scope=request.scope,
        owner=actor.actor_id,
    )
    closed_state = TaskState(
        task_id=task_id,
        contract=contract,
        phase=TaskPhase.CLOSED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
    )
    now = datetime.now(UTC)
    outcome = RuntimeOutcome(
        request_id=request.request_id,
        task_id=task_id,
        trace_id=request.trace_id,
        task_fingerprint=fingerprint_a.digest,
        state=closed_state,
        stop_reason=RuntimeStopReason.COMPLETED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
        final_report_id=uuid4(),
        usage=RuntimeUsage(budget=request.runtime_budget),
        started_at=now,
        finished_at=now,
    )

    privileged_unverified_rejected = False
    try:
        RuntimeActor(actor_id="forged-owner", role=ActorRole.OWNER)
    except ValidationError:
        privileged_unverified_rejected = True

    write_without_budget_rejected = False
    try:
        RuntimeRequest(
            task_id=task_id,
            raw_request="Write without a change budget.",
            source=RequestSource.TEST,
            actor=actor,
            scope=TaskScope(
                workspace_root=str(ROOT),
                allowed_paths=("src/luna/runtime/models.py",),
                write_allowed=True,
            ),
            autonomy=AutonomyPolicy(
                task_id=task_id,
                level=AutonomyLevel.LEVEL_2_CONTROLLED,
                max_risk="MEDIUM",
            ),
            mode=RuntimeMode.EXECUTE,
        )
    except ValidationError:
        write_without_budget_rejected = True

    checks = {
        "required_files_present": not missing,
        "request_round_trip": restored_request == request,
        "fingerprint_deterministic": fingerprint_a.digest == fingerprint_b.digest,
        "transient_ids_excluded_from_fingerprint": (
            fingerprint_a.digest == fingerprint_transient_variant.digest
        ),
        "privileged_actor_requires_verification": privileged_unverified_rejected,
        "read_only_budget_default": (
            request.runtime_budget.max_changed_files == 0
            and request.runtime_budget.max_network_requests == 0
        ),
        "write_requires_explicit_budget": write_without_budget_rejected,
        "completed_outcome_gate_bound": (
            outcome.state.phase is TaskPhase.CLOSED
            and outcome.completion_status is CompletionStatus.VERIFIED_COMPLETE
            and outcome.final_report_id is not None
        ),
        "outcome_round_trip": RuntimeOutcome.from_json(outcome.to_json()) == outcome,
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    print(
        json.dumps(
            {
                "phase": "12A",
                "checks": checks,
                "missing_files": missing,
                "status": status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
