"""Foundational Luna diagnostic scenarios."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from luna.audit import AuditedToolDispatcher, AuditSession, EvidenceBuilder
from luna.continuity import ContinuityService, ResumePolicy, SQLiteContinuityStore
from luna.contracts.enums import (
    EvidenceResult,
    EvidenceSourceKind,
    PlanStepStatus,
    RiskLevel,
    TaskPhase,
)
from luna.contracts.evidence import Evidence
from luna.contracts.plan import PlanStep
from luna.contracts.state import TaskState
from luna.contracts.task import TaskContract, TaskScope
from luna.diagnostics.models import SmokeReport, legacy_contract_report
from luna.memory import (
    MemoryCandidate,
    MemoryDecisionStatus,
    MemoryPolicy,
    MemoryQuery,
    MemoryRejectionCode,
    MemoryScope,
    MemorySensitivity,
    MemorySourceKind,
    MemoryType,
    SQLiteMemoryStore,
    VerifiedMemoryService,
)
from luna.tools import (
    AutonomyLevel,
    ProcessApproval,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    build_phase5_registry,
)
from luna.verification import (
    CompletionGate,
    VerificationPolicy,
    forbidden_absence_claim_id,
    required_condition_claim_id,
)


def _echo_contract(task_id: UUID) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Run the controlled echo smoke test.",
        required_conditions=("Dispatcher must return the supplied message.",),
        evidence_required=("ToolResult and Observation",),
        scope=TaskScope(workspace_root=str(Path.cwd())),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def _workspace_contract(task_id: UUID, root: Path) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Verify snapshot-first write and rollback in a temporary workspace.",
        required_conditions=("Temporary write must be fully rolled back.",),
        evidence_required=("Write ToolResult and rollback ToolResult",),
        scope=TaskScope(workspace_root=str(root), allowed_paths=("smoke.txt",), write_allowed=True),
        risk_level=RiskLevel.HIGH,
        owner="user",
    )


def _process_contract(task_id: UUID) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Verify exact-argv process execution without a shell.",
        required_conditions=("Python version command must exit successfully.",),
        evidence_required=("Process ToolResult and Observation",),
        scope=TaskScope(workspace_root=str(Path.cwd()), process_allowed=True),
        risk_level=RiskLevel.HIGH,
        owner="user",
    )


def run_tool(message: str = "hello") -> SmokeReport:
    task_id = uuid4()
    outcome = ToolDispatcher(build_phase5_registry()).dispatch(
        request=ToolRequest(
            task_id=task_id,
            trace_id=uuid4(),
            tool_name="core.echo",
            arguments={"message": message},
        ),
        task_contract=_echo_contract(task_id),
        policy=ToolPolicy(
            allowed_tools=("core.echo",),
            autonomy_level=AutonomyLevel.OBSERVE_ONLY,
            max_risk=RiskLevel.LOW,
        ),
    )
    payload: dict[str, object] = json.loads(outcome.to_json())
    return legacy_contract_report(
        "tool",
        payload,
        outcome.result.status.value == "SUCCESS",
    )


def run_workspace() -> SmokeReport:
    registry = build_phase5_registry()
    dispatcher = ToolDispatcher(registry)
    with TemporaryDirectory(prefix="luna-phase5-") as directory:
        root = Path(directory)
        task_id = uuid4()
        contract = _workspace_contract(task_id, root)
        write = dispatcher.dispatch(
            request=ToolRequest(
                task_id=task_id,
                trace_id=uuid4(),
                tool_name="filesystem.write_text",
                arguments={"path": "smoke.txt", "content": "phase5", "create_if_missing": True},
                expectation_id=uuid4(),
            ),
            task_contract=contract,
            policy=ToolPolicy(
                allowed_tools=("filesystem.write_text",),
                autonomy_level=AutonomyLevel.BOUNDED,
                max_risk=RiskLevel.MEDIUM,
            ),
        )
        snapshot_id = write.result.metadata.get("snapshot_id")
        if write.result.status.value != "SUCCESS" or not isinstance(snapshot_id, str):
            return legacy_contract_report("workspace", json.loads(write.to_json()), False)
        rollback = dispatcher.dispatch(
            request=ToolRequest(
                task_id=task_id,
                trace_id=uuid4(),
                tool_name="workspace.rollback",
                arguments={"snapshot_id": snapshot_id},
                expectation_id=uuid4(),
            ),
            task_contract=contract,
            policy=ToolPolicy(
                allowed_tools=("workspace.rollback",),
                owner_approved_tools=("workspace.rollback",),
                autonomy_level=AutonomyLevel.OWNER_APPROVED,
                max_risk=RiskLevel.HIGH,
            ),
        )
        payload = {
            "write_status": write.result.status.value,
            "rollback_status": rollback.result.status.value,
            "snapshot_id": snapshot_id,
            "file_exists_after_rollback": (root / "smoke.txt").exists(),
            "rollback_verified": rollback.result.metadata.get("verified", False),
        }
        return legacy_contract_report(
            "workspace",
            payload,
            rollback.result.status.value == "SUCCESS"
            and (not payload["file_exists_after_rollback"])
            and (payload["rollback_verified"] is True),
        )


def run_process() -> SmokeReport:
    registry = build_phase5_registry()
    task_id = uuid4()
    argv = (sys.executable, "--version")
    outcome = ToolDispatcher(registry).dispatch(
        request=ToolRequest(
            task_id=task_id,
            trace_id=uuid4(),
            tool_name="process.run_argv",
            arguments={"argv": list(argv)},
            working_directory=".",
            expectation_id=uuid4(),
        ),
        task_contract=_process_contract(task_id),
        policy=ToolPolicy(
            allowed_tools=("process.run_argv",),
            owner_approved_tools=("process.run_argv",),
            process_approvals=(ProcessApproval(argv=argv, may_write_workspace=False),),
            autonomy_level=AutonomyLevel.OWNER_APPROVED,
            max_risk=RiskLevel.HIGH,
        ),
    )
    return legacy_contract_report(
        "process", json.loads(outcome.to_json()), outcome.result.status.value == "SUCCESS"
    )


def run_audit() -> SmokeReport:
    secret = "phase6-smoke-secret"
    with TemporaryDirectory(prefix="luna-phase6-") as directory:
        root = Path(directory)
        task_id = uuid4()
        trace_id = uuid4()
        contract = _echo_contract(task_id)
        audit = AuditSession(root / "audit", explicit_secrets=(secret,))
        audit.record_task_contract(contract=contract, trace_id=trace_id)
        outcome = AuditedToolDispatcher(build_phase5_registry(), audit).dispatch(
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
        evidence = EvidenceBuilder.from_observation(
            task_id=task_id,
            requirement_id="echo-output-observed",
            observation=outcome.observation,
            environment_fingerprint="cli-audit-smoke",
            revision="phase6",
            freshness_seconds=0,
            reproducible=True,
            confidence=1.0,
        )
        audit.record_evidence(
            evidence=evidence, trace_id=trace_id, observation_id=outcome.observation.observation_id
        )
        verification = audit.verify_integrity()
        persisted = audit.ledger.path.read_text(encoding="utf-8")
        full_output = audit.logs.read_text(outcome.observation.stdout_ref or "")
        common_trace_id = all(
            event.trace_id == trace_id for event in audit.events_for_task(task_id)
        )
        secret_absent = secret not in persisted and secret not in full_output
        payload = {
            "integrity": verification.valid,
            "event_count": verification.event_count,
            "common_trace_id": common_trace_id,
            "secret_absent": secret_absent,
            "redactions": list(outcome.observation.redactions_applied),
        }
        return legacy_contract_report(
            "audit", payload, verification.valid and common_trace_id and secret_absent
        )


def run_verify() -> SmokeReport:
    with TemporaryDirectory(prefix="luna-phase7-") as directory:
        root = Path(directory)
        task_id = uuid4()
        trace_id = uuid4()
        required = "Quality gate must pass."
        forbidden = "Protected files are changed."
        contract = TaskContract(
            task_id=task_id,
            objective="Verify deterministic completion gating.",
            required_conditions=(required,),
            forbidden_outcomes=(forbidden,),
            evidence_required=("test result", "hash evidence"),
            scope=TaskScope(workspace_root=str(root)),
            risk_level=RiskLevel.LOW,
            owner="user",
        )
        evidence = (
            Evidence(
                task_id=task_id,
                requirement_id=required_condition_claim_id(required),
                source_kind=EvidenceSourceKind.TEST_RESULT,
                source_ref="observation:test",
                result=EvidenceResult.PASS,
                environment_fingerprint="phase7-smoke",
                revision="phase7",
                freshness_seconds=0,
                reproducible=True,
                confidence=1.0,
            ),
            Evidence(
                task_id=task_id,
                requirement_id=forbidden_absence_claim_id(forbidden),
                source_kind=EvidenceSourceKind.HASH,
                source_ref="observation:hash",
                result=EvidenceResult.PASS,
                environment_fingerprint="phase7-smoke",
                revision="phase7",
                freshness_seconds=0,
                reproducible=True,
                confidence=1.0,
            ),
        )
        audit = AuditSession(root / "audit")
        audit.record_task_contract(contract=contract, trace_id=trace_id)
        result = CompletionGate(audit).evaluate(
            contract=contract,
            evidence=evidence,
            policy=VerificationPolicy(
                current_revision="phase7", expected_environment_fingerprint="phase7-smoke"
            ),
            trace_id=trace_id,
        )
        payload = {
            "status": result.decision.status.value,
            "claim_statuses": [item.status.value for item in result.report.claim_assessments],
            "evidence_requirements": [
                item.status.value for item in result.report.evidence_requirement_assessments
            ],
            "audit_integrity": audit.verify_integrity().valid,
            "event_kinds": [event.kind.value for event in audit.events_for_task(task_id)],
        }
        return legacy_contract_report(
            "verify",
            payload,
            result.decision.status.value == "VERIFIED_COMPLETE"
            and payload["audit_integrity"] is True,
        )


def run_checkpoint() -> SmokeReport:
    with TemporaryDirectory(prefix="luna-phase8-") as directory:
        root = Path(directory)
        task_id = uuid4()
        trace_id = uuid4()
        contract = TaskContract(
            task_id=task_id,
            objective="Verify restart-safe checkpoint continuity.",
            required_conditions=("Task resumes from the persisted plan.",),
            evidence_required=("checkpoint hash evidence",),
            scope=TaskScope(workspace_root=str(root)),
            risk_level=RiskLevel.LOW,
            owner="user",
        )
        state = TaskState(
            task_id=task_id,
            contract=contract,
            phase=TaskPhase.PLANNED,
            plan=(
                PlanStep(
                    sequence=1, description="Continue after restart.", status=PlanStepStatus.PENDING
                ),
            ),
            revision=4,
        )
        audit = AuditSession(root / "audit")
        audit.record_task_contract(contract=contract, trace_id=trace_id)
        store = SQLiteContinuityStore(root / "runtime.sqlite3")
        service = ContinuityService(store, audit)
        stored = service.create_checkpoint(
            state=state,
            workspace_fingerprint="workspace-phase8",
            environment_fingerprint="environment-phase8",
            runtime_revision="phase8",
            next_step="Activate the first pending step.",
            trace_id=trace_id,
        )
        restarted = ContinuityService(SQLiteContinuityStore(root / "runtime.sqlite3"), audit)
        decision = restarted.resume_latest(
            task_id=task_id,
            policy=ResumePolicy(
                runtime_revision="phase8",
                workspace_fingerprint="workspace-phase8",
                environment_fingerprint="environment-phase8",
            ),
            trace_id=trace_id,
        )
        payload = {
            "checkpoint_id": str(stored.envelope.checkpoint.checkpoint_id),
            "resume_status": decision.status.value,
            "resumed_phase": decision.resumed_state.phase.value
            if decision.resumed_state is not None
            else None,
            "journal_mode": store.journal_mode(),
            "integrity": store.verify_integrity().valid,
            "event_kinds": [event.kind.value for event in audit.events_for_task(task_id)],
        }
        return legacy_contract_report(
            "checkpoint",
            payload,
            payload["resume_status"] == "READY"
            and payload["resumed_phase"] == "PLANNED"
            and (payload["journal_mode"] == "wal")
            and (payload["integrity"] is True),
        )


def run_memory() -> SmokeReport:
    secret = "phase9-secret-value-123456"
    with TemporaryDirectory(prefix="luna-phase9-") as directory:
        root = Path(directory)
        task_id = uuid4()
        trace_id = uuid4()
        audit = AuditSession(root / "audit", explicit_secrets=(secret,))
        store = SQLiteMemoryStore(root / "memory.sqlite3")
        service = VerifiedMemoryService(store, audit, explicit_secrets=(secret,))
        policy = MemoryPolicy()
        verified = service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.PROJECT_DECISION,
                statement="Luna quality gate keeps the result window open.",
                source_kind=MemorySourceKind.USER_CONFIRMATION,
                source_ref="conversation:phase9-smoke",
                confidence=1.0,
                scope=MemoryScope.PROJECT,
            ),
            policy=policy,
            trace_id=trace_id,
        )
        inferred = service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.FACT,
                statement="The user probably prefers every future interface.",
                source_kind=MemorySourceKind.MODEL_INFERENCE,
                source_ref="model:phase9-smoke",
                confidence=0.9,
                scope=MemoryScope.PRIVATE_USER,
            ),
            policy=policy,
            trace_id=trace_id,
        )
        one_off = service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.PREFERENCE,
                statement="Prefer compact output.",
                source_kind=MemorySourceKind.USER_STATEMENT,
                source_ref="conversation:single-mention",
                confidence=1.0,
                scope=MemoryScope.PRIVATE_USER,
            ),
            policy=policy,
            trace_id=trace_id,
        )
        secret_decision = service.commit_candidate(
            candidate=MemoryCandidate(
                task_id=task_id,
                memory_type=MemoryType.SECRET_REFERENCE,
                statement=f"api_key={secret}",
                source_kind=MemorySourceKind.SECRET_REFERENCE,
                source_ref="owner:secret-registration",
                confidence=1.0,
                scope=MemoryScope.PRIVATE_USER,
                sensitivity=MemorySensitivity.SECRET,
                explicit_persistence=True,
                secret_ref="secret://local/phase9-smoke",
            ),
            policy=policy,
            trace_id=trace_id,
        )
        retrieval = service.retrieve(
            query=MemoryQuery(
                scope=MemoryScope.PROJECT, terms=("quality",), minimum_confidence=0.8
            ),
            task_id=task_id,
            trace_id=trace_id,
        )
        integrity = store.verify_integrity()
        persisted = (
            b"".join(path.read_bytes() for path in root.glob("memory.sqlite3*") if path.is_file())
            + audit.ledger.path.read_bytes()
        )
        event_kinds = [event.kind.value for event in audit.events_for_task(task_id)]
        payload = {
            "journal_mode": store.journal_mode(),
            "schema_version": store.schema_version(),
            "integrity": integrity.valid,
            "verified_committed": verified.status.value,
            "model_inference_rejected": MemoryRejectionCode.MODEL_INFERENCE_UNVERIFIED.value
            in {code.value for code in inferred.rejection_codes},
            "one_off_preference_rejected": MemoryRejectionCode.ONE_OFF_PREFERENCE.value
            in {code.value for code in one_off.rejection_codes},
            "secret_committed": secret_decision.status.value,
            "secret_absent_from_persistence": secret.encode("utf-8") not in persisted,
            "retrieval_count": len(retrieval.records),
            "retrieved_scope": retrieval.query.scope.value,
            "source_preserved": len(retrieval.records) == 1
            and retrieval.records[0].source_ref == "conversation:phase9-smoke"
            and (retrieval.records[0].confidence == 1.0),
            "audit_integrity": audit.verify_integrity().valid,
            "event_kinds": event_kinds,
        }
        return legacy_contract_report(
            "memory",
            payload,
            payload["journal_mode"] == "wal"
            and payload["schema_version"] == 1
            and (payload["integrity"] is True)
            and (payload["verified_committed"] == MemoryDecisionStatus.COMMIT.value)
            and (payload["model_inference_rejected"] is True)
            and (payload["one_off_preference_rejected"] is True)
            and (payload["secret_committed"] == MemoryDecisionStatus.COMMIT.value)
            and (payload["secret_absent_from_persistence"] is True)
            and (payload["retrieval_count"] == 1)
            and (payload["source_preserved"] is True)
            and (payload["audit_integrity"] is True),
        )
