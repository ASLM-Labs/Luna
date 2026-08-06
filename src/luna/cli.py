"""Command-line entry point for the Luna Phase 8 restart-safe runtime."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from luna.audit import AuditSession, AuditedToolDispatcher, EvidenceBuilder
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
from luna.intent import DeterministicIntentResolver
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
from luna.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="luna",
        description="Luna 0.1 local single-agent runtime",
    )
    parser.add_argument("--version", action="version", version=f"Luna {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show the current project phase and capability state.")
    subparsers.add_parser("list-tools", help="List registered Phase 5 tools.")
    subparsers.add_parser("audit-smoke", help="Verify redacted append-only Phase 6 audit.")
    subparsers.add_parser(
        "verify-smoke",
        help="Run the deterministic Phase 7 completion gate.",
    )
    subparsers.add_parser(
        "checkpoint-smoke",
        help="Persist and resume a Phase 8 SQLite WAL checkpoint.",
    )
    inspect_parser = subparsers.add_parser(
        "audit-inspect",
        help="Print one task audit from an owner-selected audit root.",
    )
    inspect_parser.add_argument("root", help="Audit root containing events.jsonl.")
    inspect_parser.add_argument("task_id", help="Task UUID to inspect.")
    subparsers.add_parser(
        "workspace-smoke",
        help="Create a temporary file through the dispatcher, then restore its snapshot.",
    )
    subparsers.add_parser(
        "process-smoke",
        help="Run the exact approved Python --version argv through the dispatcher.",
    )
    resolve_parser = subparsers.add_parser(
        "resolve-intent",
        help="Run the transparent deterministic intent baseline.",
    )
    resolve_parser.add_argument("request", help="Request text to resolve.")
    echo_parser = subparsers.add_parser(
        "tool-smoke",
        help="Run the controlled core.echo tool through the dispatcher.",
    )
    echo_parser.add_argument("message", help="Message passed to core.echo.")
    return parser


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
        scope=TaskScope(
            workspace_root=str(root),
            allowed_paths=("smoke.txt",),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
        owner="user",
    )


def _process_contract(task_id: UUID) -> TaskContract:
    return TaskContract(
        task_id=task_id,
        objective="Verify exact-argv process execution without a shell.",
        required_conditions=("Python version command must exit successfully.",),
        evidence_required=("Process ToolResult and Observation",),
        scope=TaskScope(
            workspace_root=str(Path.cwd()),
            process_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
        owner="user",
    )


def _run_workspace_smoke() -> int:
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
                arguments={
                    "path": "smoke.txt",
                    "content": "phase5",
                    "create_if_missing": True,
                },
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
            print(write.to_json())
            return 2

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
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if (
            rollback.result.status.value == "SUCCESS"
            and not payload["file_exists_after_rollback"]
            and payload["rollback_verified"] is True
        ) else 2


def _run_process_smoke() -> int:
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
            process_approvals=(ProcessApproval(argv=argv),),
            autonomy_level=AutonomyLevel.OWNER_APPROVED,
            max_risk=RiskLevel.HIGH,
        ),
    )
    print(outcome.to_json())
    return 0 if outcome.result.status.value == "SUCCESS" else 2



def _run_audit_smoke() -> int:
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
            evidence=evidence,
            trace_id=trace_id,
            observation_id=outcome.observation.observation_id,
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
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if verification.valid and common_trace_id and secret_absent else 2


def _run_verify_smoke() -> int:
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
                current_revision="phase7",
                expected_environment_fingerprint="phase7-smoke",
            ),
            trace_id=trace_id,
        )
        payload = {
            "status": result.decision.status.value,
            "claim_statuses": [
                item.status.value for item in result.report.claim_assessments
            ],
            "evidence_requirements": [
                item.status.value
                for item in result.report.evidence_requirement_assessments
            ],
            "audit_integrity": audit.verify_integrity().valid,
            "event_kinds": [
                event.kind.value for event in audit.events_for_task(task_id)
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if (
            result.decision.status.value == "VERIFIED_COMPLETE"
            and payload["audit_integrity"] is True
        ) else 2



def _run_checkpoint_smoke() -> int:
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
                    sequence=1,
                    description="Continue after restart.",
                    status=PlanStepStatus.PENDING,
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

        restarted = ContinuityService(
            SQLiteContinuityStore(root / "runtime.sqlite3"),
            audit,
        )
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
            "resumed_phase": (
                decision.resumed_state.phase.value
                if decision.resumed_state is not None
                else None
            ),
            "journal_mode": store.journal_mode(),
            "integrity": store.verify_integrity().valid,
            "event_kinds": [
                event.kind.value for event in audit.events_for_task(task_id)
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if (
            payload["resume_status"] == "READY"
            and payload["resumed_phase"] == "PLANNED"
            and payload["journal_mode"] == "wal"
            and payload["integrity"] is True
        ) else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print("phase: 8")
        print("status: CHECKPOINT_CONTINUITY_IMPLEMENTED_UNVERIFIED")
        print("tool_dispatcher: deny_by_default")
        print("registered_tools: 7")
        print("workspace_writes: snapshot_first_atomic")
        print("rollback: sha256_verified")
        print("process_execution: exact_argv_owner_approved")
        print("shell_parsing: disabled")
        print("file_delete: disabled")
        print("network_tools: disabled")
        print("audit_log: append_only_jsonl_sha256_chain")
        print("output_logs: redacted_content_addressed")
        print("completion_verifier: deterministic_requirement_evidence_gate")
        print("verified_complete: gate_only")
        print("checkpoint_store: sqlite_wal_atomic")
        print("resume_guard: revision_workspace_environment")
        print("blind_replay: blocked")
        return 0

    if args.command == "resolve-intent":
        print(DeterministicIntentResolver().resolve(args.request).to_json())
        return 0

    if args.command == "audit-smoke":
        return _run_audit_smoke()

    if args.command == "verify-smoke":
        return _run_verify_smoke()

    if args.command == "checkpoint-smoke":
        return _run_checkpoint_smoke()

    if args.command == "audit-inspect":
        task_id = UUID(args.task_id)
        events = AuditSession(Path(args.root)).events_for_task(task_id)
        print(
            json.dumps(
                [event.model_dump(mode="json") for event in events],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    registry = build_phase5_registry()
    if args.command == "list-tools":
        for spec in registry.specs():
            capabilities = ",".join(item.value for item in spec.capabilities) or "NONE"
            print(f"{spec.name}\t{spec.risk_level.value}\t{capabilities}")
        return 0

    if args.command == "tool-smoke":
        task_id = uuid4()
        contract = _echo_contract(task_id)
        outcome = ToolDispatcher(registry).dispatch(
            request=ToolRequest(
                task_id=task_id,
                trace_id=uuid4(),
                tool_name="core.echo",
                arguments={"message": args.message},
            ),
            task_contract=contract,
            policy=ToolPolicy(
                allowed_tools=("core.echo",),
                autonomy_level=AutonomyLevel.OBSERVE_ONLY,
                max_risk=RiskLevel.LOW,
            ),
        )
        print(outcome.to_json())
        return 0 if outcome.result.status.value == "SUCCESS" else 2

    if args.command == "workspace-smoke":
        return _run_workspace_smoke()

    if args.command == "process-smoke":
        return _run_process_smoke()

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
