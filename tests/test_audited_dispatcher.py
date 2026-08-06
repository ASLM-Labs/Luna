from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from luna.audit import AuditedToolDispatcher, AuditEventKind, AuditSession
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.tools import AutonomyLevel, ToolPolicy, ToolRequest, build_phase4_registry


def _contract(task_id: UUID, root: Path) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Audit one controlled echo request.",
        required_conditions=("Output must be captured and audited.",),
        evidence_required=("Observation and audit chain",),
        scope=TaskScope(workspace_root=str(root)),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def test_dispatch_records_redacted_request_result_event_and_observation(
    tmp_path: Path,
) -> None:
    secret = "phase6-owner-secret"
    task_id = uuid4()
    trace_id = uuid4()
    contract = _contract(task_id, tmp_path)
    audit = AuditSession(tmp_path / "audit", explicit_secrets=(secret,))
    audit.record_task_contract(contract=contract, trace_id=trace_id)
    dispatcher = AuditedToolDispatcher(build_phase4_registry(), audit)

    outcome = dispatcher.dispatch(
        request=ToolRequest(
            task_id=task_id,
            trace_id=trace_id,
            tool_name="core.echo",
            arguments={"message": f"token={secret}"},
            max_output_chars=8,
        ),
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("core.echo",),
            autonomy_level=AutonomyLevel.OBSERVE_ONLY,
            max_risk=RiskLevel.LOW,
            max_output_chars=8,
        ),
    )

    events = audit.events_for_task(task_id)
    kinds = tuple(event.kind for event in events)
    persisted = audit.ledger.path.read_text(encoding="utf-8")
    full_output = audit.logs.read_text(outcome.observation.stdout_ref or "")

    assert secret not in outcome.result.stdout_excerpt
    assert secret not in persisted
    assert secret not in full_output
    assert outcome.observation.redactions_applied
    assert kinds == (
        AuditEventKind.TASK_CONTRACT,
        AuditEventKind.TOOL_REQUEST,
        AuditEventKind.TOOL_RESULT,
        AuditEventKind.TOOL_EVENT,
        AuditEventKind.OBSERVATION,
    )
    assert all(event.trace_id == trace_id for event in events)
    assert audit.verify_integrity().valid


def test_full_output_artifact_survives_bounded_excerpt(tmp_path: Path) -> None:
    task_id = uuid4()
    trace_id = uuid4()
    contract = _contract(task_id, tmp_path)
    audit = AuditSession(tmp_path / "audit")
    dispatcher = AuditedToolDispatcher(build_phase4_registry(), audit)

    outcome = dispatcher.dispatch(
        request=ToolRequest(
            task_id=task_id,
            trace_id=trace_id,
            tool_name="core.echo",
            arguments={"message": "0123456789"},
            max_output_chars=3,
        ),
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=("core.echo",),
            max_output_chars=3,
        ),
    )

    assert outcome.result.stdout_excerpt == "012"
    assert outcome.result.truncated
    assert audit.logs.read_text(outcome.observation.stdout_ref or "") == "0123456789"
