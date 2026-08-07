from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from luna.autonomy import AutonomyLevel, AutonomyPolicy
from luna.context import ContextBudget
from luna.continuity import ContinuityService
from luna.contracts import (
    CompletionStatus,
    RiskLevel,
    TaskContract,
    TaskScope,
    TaskState,
)
from luna.contracts.enums import TaskPhase
from luna.memory import VerifiedMemoryService
from luna.modeling import ModelBackend
from luna.planning import AdaptivePlanner
from luna.preparation import TaskPreparer
from luna.reporting import FinalReportComposer
from luna.runtime import (
    ActorRole,
    ActorVerificationSource,
    RequestSource,
    RuntimeActor,
    RuntimeBudget,
    RuntimeDependencies,
    RuntimeMode,
    RuntimeOutcome,
    RuntimeRequest,
    RuntimeStopReason,
    RuntimeUsage,
    build_task_fingerprint,
)
from luna.tools import ToolDispatcher
from luna.verification import CompletionGate


def _owner() -> RuntimeActor:
    return RuntimeActor(
        actor_id="owner-1",
        role=ActorRole.OWNER,
        verified=True,
        verification_source=ActorVerificationSource.TEST_FIXTURE,
        verified_at=datetime.now(UTC),
        display_name="Owner",
    )


def _request(
    root: Path,
    *,
    raw_request: str = "Inspect the Luna runtime contracts.",
    write: bool = False,
    task_id: UUID | None = None,
) -> RuntimeRequest:
    active_task_id = task_id or uuid4()
    scope = TaskScope(
        workspace_root=str(root),
        allowed_paths=("src/luna/runtime/models.py",) if write else (),
        write_allowed=write,
    )
    budget = (
        RuntimeBudget.controlled_write(
            max_changed_files=1,
            max_added_lines=100,
            max_deleted_lines=50,
        )
        if write
        else RuntimeBudget()
    )
    return RuntimeRequest(
        task_id=active_task_id,
        raw_request=raw_request,
        source=RequestSource.TEST,
        actor=_owner(),
        scope=scope,
        autonomy=AutonomyPolicy(
            task_id=active_task_id,
            level=(
                AutonomyLevel.LEVEL_2_CONTROLLED
                if write
                else AutonomyLevel.LEVEL_1_READ_ONLY
            ),
            max_risk=RiskLevel.MEDIUM if write else RiskLevel.LOW,
        ),
        context_budget=ContextBudget(max_sources=4, max_chars=8000, max_estimated_tokens=2000),
        runtime_budget=budget,
        required_conditions=("Runtime contracts remain deterministic.",),
        evidence_required=("contract tests",),
        mode=RuntimeMode.EXECUTE if write else RuntimeMode.DRY_RUN,
    )


def _closed_state(root: Path, task_id: UUID) -> TaskState:
    contract = TaskContract(
        task_id=task_id,
        objective="Verify a completed runtime outcome.",
        required_conditions=("The result is verified.",),
        evidence_required=("verification report",),
        scope=TaskScope(workspace_root=str(root)),
        owner="owner-1",
    )
    return TaskState(
        task_id=task_id,
        contract=contract,
        phase=TaskPhase.CLOSED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
    )


def test_privileged_actor_requires_runtime_verification() -> None:
    with pytest.raises(ValidationError, match="require runtime verification"):
        RuntimeActor(actor_id="owner-1", role=ActorRole.OWNER)

    guest = RuntimeActor(actor_id="guest-1", role=ActorRole.GUEST)
    assert guest.verified is False
    assert guest.verification_source is ActorVerificationSource.UNVERIFIED


def test_runtime_budget_defaults_to_read_only_and_write_budget_is_explicit() -> None:
    read_only = RuntimeBudget()
    assert read_only.max_changed_files == 0
    assert read_only.max_network_requests == 0

    writable = RuntimeBudget.controlled_write(
        max_changed_files=2,
        max_added_lines=120,
        max_deleted_lines=40,
    )
    assert writable.max_changed_files == 2

    with pytest.raises(ValidationError, match="line change budgets"):
        RuntimeBudget(max_added_lines=1)


def test_runtime_request_rejects_incoherent_ids_and_capability_budgets(tmp_path: Path) -> None:
    task_id = uuid4()
    other_id = uuid4()

    with pytest.raises(ValidationError, match="autonomy policy task_id"):
        RuntimeRequest(
            task_id=task_id,
            raw_request="Inspect only.",
            source=RequestSource.TEST,
            actor=_owner(),
            scope=TaskScope(workspace_root=str(tmp_path)),
            autonomy=AutonomyPolicy(task_id=other_id),
        )

    with pytest.raises(ValidationError, match="read-only scope"):
        RuntimeRequest(
            task_id=task_id,
            raw_request="Inspect only.",
            source=RequestSource.TEST,
            actor=_owner(),
            scope=TaskScope(workspace_root=str(tmp_path)),
            autonomy=AutonomyPolicy(task_id=task_id),
            runtime_budget=RuntimeBudget.controlled_write(),
        )

    with pytest.raises(ValidationError, match="network-disabled"):
        RuntimeRequest(
            task_id=task_id,
            raw_request="Inspect only.",
            source=RequestSource.TEST,
            actor=_owner(),
            scope=TaskScope(workspace_root=str(tmp_path)),
            autonomy=AutonomyPolicy(task_id=task_id),
            runtime_budget=RuntimeBudget(max_network_requests=1),
        )


def test_runtime_request_enforces_autonomy_and_risk_ceiling(tmp_path: Path) -> None:
    task_id = uuid4()
    write_scope = TaskScope(
        workspace_root=str(tmp_path),
        allowed_paths=("out.txt",),
        write_allowed=True,
    )
    with pytest.raises(ValidationError, match="Level 2 or higher"):
        RuntimeRequest(
            task_id=task_id,
            raw_request="Write a scoped file.",
            source=RequestSource.TEST,
            actor=_owner(),
            scope=write_scope,
            autonomy=AutonomyPolicy(
                task_id=task_id,
                level=AutonomyLevel.LEVEL_1_READ_ONLY,
            ),
            runtime_budget=RuntimeBudget.controlled_write(),
            mode=RuntimeMode.EXECUTE,
        )

    with pytest.raises(ValidationError, match="risk ceiling"):
        RuntimeRequest(
            task_id=task_id,
            raw_request="Perform a high-risk task.",
            source=RequestSource.TEST,
            actor=_owner(),
            scope=TaskScope(workspace_root=str(tmp_path)),
            autonomy=AutonomyPolicy(
                task_id=task_id,
                level=AutonomyLevel.LEVEL_1_READ_ONLY,
                max_risk=RiskLevel.LOW,
            ),
            risk_level=RiskLevel.HIGH,
        )


def test_resume_mode_requires_matching_task_id(tmp_path: Path) -> None:
    task_id = uuid4()
    with pytest.raises(ValidationError, match="requires resume_task_id"):
        RuntimeRequest(
            task_id=task_id,
            raw_request="Resume the task.",
            source=RequestSource.TEST,
            actor=_owner(),
            scope=TaskScope(workspace_root=str(tmp_path)),
            autonomy=AutonomyPolicy(task_id=task_id),
            mode=RuntimeMode.RESUME,
        )

    request = RuntimeRequest(
        task_id=task_id,
        raw_request="Resume the task.",
        source=RequestSource.TEST,
        actor=_owner(),
        scope=TaskScope(workspace_root=str(tmp_path)),
        autonomy=AutonomyPolicy(task_id=task_id),
        mode=RuntimeMode.RESUME,
        resume_task_id=task_id,
    )
    assert request.resume_task_id == task_id


def test_task_fingerprint_ignores_transient_ids_and_normalizes_text_and_paths(
    tmp_path: Path,
) -> None:
    first = _request(tmp_path, raw_request="Inspect   the Luna runtime contracts.")
    second = _request(
        Path(str(tmp_path).replace("/", "\\")),
        raw_request="  inspect the luna runtime contracts.  ",
    )

    first_fingerprint = build_task_fingerprint(first)
    second_fingerprint = build_task_fingerprint(second)

    assert first.request_id != second.request_id
    assert first.task_id != second.task_id
    assert first_fingerprint.digest == second_fingerprint.digest

    changed = _request(tmp_path, raw_request="Modify the Luna runtime contracts.")
    assert build_task_fingerprint(changed).digest != first_fingerprint.digest


def test_runtime_usage_distinguishes_exhaustion_from_overrun() -> None:
    budget = RuntimeBudget(max_steps=2, max_tool_calls=1)
    exhausted = RuntimeUsage(budget=budget, steps=2, tool_calls=1)
    exceeded = RuntimeUsage(budget=budget, steps=3, tool_calls=2)

    assert "steps" in exhausted.exhausted_reasons()
    assert exhausted.exceeded_reasons() == ()
    assert set(exceeded.exceeded_reasons()) == {"steps", "tool_calls"}


def test_completed_runtime_outcome_requires_closed_verified_state_and_report(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    fingerprint = build_task_fingerprint(request)
    state = _closed_state(tmp_path, request.task_id)
    now = datetime.now(UTC)

    outcome = RuntimeOutcome(
        request_id=request.request_id,
        task_id=request.task_id,
        trace_id=request.trace_id,
        task_fingerprint=fingerprint.digest,
        state=state,
        stop_reason=RuntimeStopReason.COMPLETED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
        final_report_id=uuid4(),
        usage=RuntimeUsage(budget=request.runtime_budget),
        started_at=now,
        finished_at=now,
    )
    restored = RuntimeOutcome.from_json(outcome.to_json())

    assert restored == outcome

    with pytest.raises(ValidationError, match="final_report_id"):
        RuntimeOutcome(
            request_id=request.request_id,
            task_id=request.task_id,
            trace_id=request.trace_id,
            task_fingerprint=fingerprint.digest,
            state=state,
            stop_reason=RuntimeStopReason.COMPLETED,
            completion_status=CompletionStatus.VERIFIED_COMPLETE,
            usage=RuntimeUsage(budget=request.runtime_budget),
            started_at=now,
            finished_at=now,
        )


def test_budget_exhausted_outcome_requires_observable_exhaustion(tmp_path: Path) -> None:
    request = _request(tmp_path)
    contract = TaskContract(
        task_id=request.task_id,
        objective="Stop safely at a budget boundary.",
        required_conditions=("No side effect is repeated.",),
        evidence_required=("runtime usage",),
        scope=request.scope,
        owner="owner-1",
    )
    state = TaskState(task_id=request.task_id, contract=contract)
    now = datetime.now(UTC)

    with pytest.raises(ValidationError, match="exhausted budget"):
        RuntimeOutcome(
            request_id=request.request_id,
            task_id=request.task_id,
            trace_id=request.trace_id,
            task_fingerprint=build_task_fingerprint(request).digest,
            state=state,
            stop_reason=RuntimeStopReason.BUDGET_EXHAUSTED,
            usage=RuntimeUsage(budget=request.runtime_budget),
            started_at=now,
            finished_at=now,
        )


def test_runtime_dependencies_are_explicit_and_manifest_is_read_only() -> None:
    marker = object()
    dependencies = RuntimeDependencies(
        task_preparer=cast(TaskPreparer, marker),
        planner=cast(AdaptivePlanner, marker),
        model_backend=cast(ModelBackend, marker),
        tool_dispatcher=cast(ToolDispatcher, marker),
        completion_gate=cast(CompletionGate, marker),
        report_composer=cast(FinalReportComposer, marker),
        continuity_service=cast(ContinuityService, marker),
        memory_service=cast(VerifiedMemoryService, marker),
    )

    mapping = dependencies.as_mapping()
    assert dependencies.manifest().ready is True
    assert len(mapping) == 8
    assert type(mapping).__name__ == "mappingproxy"

    with pytest.raises(ValueError, match="cannot be None"):
        RuntimeDependencies(
            task_preparer=cast(TaskPreparer, None),
            planner=cast(AdaptivePlanner, marker),
            model_backend=cast(ModelBackend, marker),
            tool_dispatcher=cast(ToolDispatcher, marker),
            completion_gate=cast(CompletionGate, marker),
            report_composer=cast(FinalReportComposer, marker),
            continuity_service=cast(ContinuityService, marker),
            memory_service=cast(VerifiedMemoryService, marker),
        )
