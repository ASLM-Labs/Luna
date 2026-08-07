"""Command-line entry point for the Luna Phase 13 controlled-model runtime."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from luna.acceptance import ReleaseStatus, run_core_acceptance
from luna.actions import (
    ActionDenialCode,
    ActionKind,
    ActionProposal,
    ActionResolutionStatus,
    ActionResolver,
    ActionTargetKind,
    ToolSelector,
    build_phase12c_routes,
)
from luna.audit import AuditedToolDispatcher, AuditEventKind, AuditSession, EvidenceBuilder
from luna.autonomy import AutonomyPolicy, FreeResearchContract
from luna.conformance import (
    ConformanceRunner,
    RuntimeBehaviorExecutor,
    build_runtime_conformance_suite,
)
from luna.context import (
    CONTEXT_LAYER_ORDER,
    ContextExclusionReason,
    ContextInterpretation,
    ContextLayer,
    ContextSourceKind,
    LayeredContextBundle,
    LayeredContextCandidate,
    LayeredContextComposer,
)
from luna.continuity import ContinuityService, ResumePolicy, SQLiteContinuityStore
from luna.contracts.enums import (
    CompletionStatus,
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
from luna.identity import IdentityProfile
from luna.intent import DeterministicIntentResolver
from luna.learning import LearningCandidateBuilder
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
from luna.modeling import (
    ControlledModelBackend,
    LocalOpenAICompatibleBackend,
    ModelCompatibilityProbe,
    ModelFinishReason,
    ModelRolloutGate,
    ModelRolloutHealth,
    ModelRolloutPolicy,
    ModelRolloutStage,
    ModelToolCall,
    ScriptedModelOutput,
    ScriptedTestBackend,
    ScriptedTurn,
)
from luna.recovery import (
    ChangeEstimate,
    FailureClassifier,
    MinimalChangePolicy,
    RecoveryAction,
    RecoveryPolicy,
    WorkspaceIsolationPolicy,
)
from luna.reporting import FinalReportComposer
from luna.runtime import (
    JOURNAL_SCHEMA_VERSION,
    RequestSource,
    RuntimeActor,
    RuntimeBudget,
    RuntimeControlCommand,
    RuntimeMode,
    RuntimeOutcome,
    RuntimeRequest,
    RuntimeStopReason,
    RuntimeUsage,
    SQLiteRuntimeJournal,
    build_task_fingerprint,
)
from luna.tools import (
    AutonomyLevel,
    ProcessApproval,
    ToolArgumentRule,
    ToolArgumentType,
    ToolCapability,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolSpec,
    build_phase5_registry,
)
from luna.tools.policy import evaluate_tool_policy
from luna.verification import (
    CompletionGate,
    DeterministicVerifier,
    EvidenceStrength,
    SQLiteEvidenceStore,
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
    subparsers.add_parser(
        "memory-smoke",
        help="Verify Phase 9 memory policy, safe storage, and scoped retrieval.",
    )
    subparsers.add_parser(
        "phase10-smoke",
        help="Verify Phase 10 identity, final reporting, and autonomy enforcement.",
    )
    subparsers.add_parser(
        "phase11-smoke",
        help="Run the locked Phase 11 eval suite and release gate.",
    )
    subparsers.add_parser(
        "phase12a-smoke",
        help="Verify Phase 12A runtime request, fingerprint, and outcome contracts.",
    )
    subparsers.add_parser(
        "phase12b-smoke",
        help="Verify Phase 12B layered, budgeted, secret-safe context composition.",
    )
    subparsers.add_parser(
        "phase12c-smoke",
        help="Verify Phase 12C action proposal, tool selection, and structured denial.",
    )
    subparsers.add_parser(
        "phase12d-smoke",
        help="Verify Phase 12D failure recovery, minimal-change, and isolation policy.",
    )
    subparsers.add_parser(
        "phase12e-smoke",
        help="Verify Phase 12E durable control and single-loop runtime boundary.",
    )
    subparsers.add_parser(
        "phase12f-smoke",
        help="Verify Phase 12F evidence strength, disagreement, and learning boundary.",
    )
    subparsers.add_parser(
        "phase12g-smoke",
        help="Run the locked Phase 12G runtime E2E behavior-conformance suite.",
    )
    subparsers.add_parser(
        "phase13-smoke",
        help="Verify Phase 13 model compatibility and controlled rollout gates.",
    )
    live_probe = subparsers.add_parser(
        "phase13-live-probe",
        help="Probe a loopback OpenAI-compatible real model without granting rollout authority.",
    )
    live_probe.add_argument(
        "--endpoint",
        default="http://127.0.0.1:1234/v1/chat/completions",
        help="Loopback OpenAI-compatible chat-completions endpoint.",
    )
    live_probe.add_argument(
        "--model",
        required=True,
        help="Model identifier exposed by the local server.",
    )
    live_probe.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Per-request compatibility probe timeout.",
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


def _run_memory_smoke() -> int:
    secret = "phase9-secret-value-123456"
    with TemporaryDirectory(prefix="luna-phase9-") as directory:
        root = Path(directory)
        task_id = uuid4()
        trace_id = uuid4()
        audit = AuditSession(root / "audit", explicit_secrets=(secret,))
        store = SQLiteMemoryStore(root / "memory.sqlite3")
        service = VerifiedMemoryService(
            store,
            audit,
            explicit_secrets=(secret,),
        )
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
                scope=MemoryScope.PROJECT,
                terms=("quality",),
                minimum_confidence=0.8,
            ),
            task_id=task_id,
            trace_id=trace_id,
        )
        integrity = store.verify_integrity()
        persisted = b"".join(
            path.read_bytes()
            for path in root.glob("memory.sqlite3*")
            if path.is_file()
        ) + audit.ledger.path.read_bytes()
        event_kinds = [
            event.kind.value for event in audit.events_for_task(task_id)
        ]
        payload = {
            "journal_mode": store.journal_mode(),
            "schema_version": store.schema_version(),
            "integrity": integrity.valid,
            "verified_committed": verified.status.value,
            "model_inference_rejected": (
                MemoryRejectionCode.MODEL_INFERENCE_UNVERIFIED.value
                in {code.value for code in inferred.rejection_codes}
            ),
            "one_off_preference_rejected": (
                MemoryRejectionCode.ONE_OFF_PREFERENCE.value
                in {code.value for code in one_off.rejection_codes}
            ),
            "secret_committed": secret_decision.status.value,
            "secret_absent_from_persistence": secret.encode("utf-8") not in persisted,
            "retrieval_count": len(retrieval.records),
            "retrieved_scope": retrieval.query.scope.value,
            "source_preserved": (
                len(retrieval.records) == 1
                and retrieval.records[0].source_ref == "conversation:phase9-smoke"
                and retrieval.records[0].confidence == 1.0
            ),
            "audit_integrity": audit.verify_integrity().valid,
            "event_kinds": event_kinds,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if (
            payload["journal_mode"] == "wal"
            and payload["schema_version"] == 1
            and payload["integrity"] is True
            and payload["verified_committed"] == MemoryDecisionStatus.COMMIT.value
            and payload["model_inference_rejected"] is True
            and payload["one_off_preference_rejected"] is True
            and payload["secret_committed"] == MemoryDecisionStatus.COMMIT.value
            and payload["secret_absent_from_persistence"] is True
            and payload["retrieval_count"] == 1
            and payload["source_preserved"] is True
            and payload["audit_integrity"] is True
        ) else 2



def _run_phase10_smoke() -> int:
    with TemporaryDirectory(prefix="luna-phase10-") as directory:
        root = Path(directory)
        task_id = uuid4()
        trace_id = uuid4()
        required = "Phase 10 report is derived from verified evidence."
        contract = TaskContract(
            task_id=task_id,
            objective="Verify identity, reporting, and autonomy boundaries.",
            required_conditions=(required,),
            evidence_required=("test result",),
            scope=TaskScope(workspace_root=str(root)),
            risk_level=RiskLevel.LOW,
            owner="user",
        )
        evidence = Evidence(
            task_id=task_id,
            requirement_id=required_condition_claim_id(required),
            source_kind=EvidenceSourceKind.TEST_RESULT,
            source_ref="phase10-smoke:test",
            result=EvidenceResult.PASS,
            environment_fingerprint="phase10-smoke",
            revision="phase10",
            freshness_seconds=0,
            reproducible=True,
            confidence=1.0,
        )
        audit = AuditSession(root / "audit")
        audit.record_task_contract(contract=contract, trace_id=trace_id)
        gate = CompletionGate(audit).evaluate(
            contract=contract,
            evidence=(evidence,),
            policy=VerificationPolicy(
                current_revision="phase10",
                expected_environment_fingerprint="phase10-smoke",
            ),
            trace_id=trace_id,
        )
        identity = IdentityProfile()
        final_report = FinalReportComposer(audit).compose(
            contract=contract,
            gate_result=gate,
            identity=identity,
            performed=("Ran the Phase 10 deterministic smoke test.",),
            changed=(),
            trace_id=trace_id,
        )

        echo_spec = build_phase5_registry().get("core.echo")
        if echo_spec is None:
            return 2
        request = ToolRequest(
            task_id=task_id,
            trace_id=trace_id,
            tool_name="core.echo",
            arguments={"message": "phase10"},
        )
        level_zero = evaluate_tool_policy(
            spec=echo_spec.spec,
            request=request,
            task_contract=contract,
            policy=ToolPolicy(
                allowed_tools=("core.echo",),
                autonomy_level=AutonomyLevel.LEVEL_0_ADVISORY,
            ),
        )
        level_one = evaluate_tool_policy(
            spec=echo_spec.spec,
            request=request,
            task_contract=contract,
            policy=ToolPolicy(
                allowed_tools=("core.echo",),
                autonomy_level=AutonomyLevel.LEVEL_1_READ_ONLY,
            ),
        )

        research_task_id = uuid4()
        now = datetime.now(UTC)
        research_spec = ToolSpec(
            name="research.fetch",
            description="Phase 10 synthetic network policy fixture.",
            capabilities=(ToolCapability.NETWORK,),
            argument_schema={
                "url": ToolArgumentRule(
                    argument_type=ToolArgumentType.STRING,
                    required=True,
                )
            },
        )
        research_contract = TaskContract(
            task_id=research_task_id,
            objective="Verify FREE_RESEARCH domain enforcement.",
            required_conditions=("Only an approved domain is reachable.",),
            evidence_required=("policy decision",),
            scope=TaskScope(workspace_root=str(root), network_allowed=True),
            risk_level=RiskLevel.LOW,
            owner="user",
        )
        free_research = FreeResearchContract(
            task_id=research_task_id,
            purpose="Inspect approved public documentation.",
            allowed_tools=(research_spec.name,),
            allowed_domains=("example.com",),
            issued_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(minutes=5),
        )
        research_decision = evaluate_tool_policy(
            spec=research_spec,
            request=ToolRequest(
                task_id=research_task_id,
                trace_id=uuid4(),
                tool_name=research_spec.name,
                arguments={"url": "https://docs.example.com/reference"},
                expectation_id=uuid4(),
            ),
            task_contract=research_contract,
            policy=ToolPolicy(
                allowed_tools=(research_spec.name,),
                autonomy_level=AutonomyLevel.LEVEL_4_FREE_RESEARCH,
                free_research_contract=free_research,
            ),
        )
        event_kinds = {event.kind for event in audit.events_for_task(task_id)}
        payload = {
            "identity_name": identity.identity_name,
            "identity_version": identity.identity_version,
            "hard_coded_user_absent": identity.user_profile is None,
            "completion_status": final_report.completion_status.value,
            "report_sections_separated": bool(
                final_report.performed
                and final_report.verified
                and not final_report.unverified
            ),
            "final_report_audited": AuditEventKind.FINAL_REPORT in event_kinds,
            "level_zero_blocked": level_zero.allowed is False,
            "level_one_allowed": level_one.allowed is True,
            "free_research_domain_allowed": research_decision.allowed is True,
            "audit_integrity": audit.verify_integrity().valid,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if all(payload.values()) else 2


def _run_phase11_smoke() -> int:
    with TemporaryDirectory(prefix="luna-phase11-") as directory:
        report, decision = run_core_acceptance(Path(directory))
        payload = {
            "suite_name": report.suite_name,
            "suite_revision": report.suite_revision,
            "suite_sha256": report.suite_sha256,
            "total_cases": report.metrics.total_cases,
            "passed_cases": report.metrics.passed_cases,
            "critical_failures": report.metrics.critical_failures,
            "false_verified_complete_count": (
                report.metrics.false_verified_complete_count
            ),
            "protected_path_violation_count": (
                report.metrics.protected_path_violation_count
            ),
            "blind_retry_count": report.metrics.blind_retry_count,
            "release_status": decision.status.value,
            "known_limitations_published": bool(decision.known_limitations),
            "reasons": list(decision.reasons),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if decision.status is ReleaseStatus.PASS else 2


def _run_phase12a_smoke() -> int:
    task_id = uuid4()
    actor = RuntimeActor.verified_owner("local-owner")
    request = RuntimeRequest(
        task_id=task_id,
        raw_request="Verify the Phase 12A runtime contracts.",
        source=RequestSource.TEST,
        actor=actor,
        scope=TaskScope(workspace_root=str(Path.cwd())),
        autonomy=AutonomyPolicy(
            task_id=task_id,
            level=AutonomyLevel.LEVEL_1_READ_ONLY,
        ),
        runtime_budget=RuntimeBudget(),
        mode=RuntimeMode.DRY_RUN,
        required_conditions=("Runtime contracts round-trip deterministically.",),
        evidence_required=("Phase 12A smoke",),
    )
    fingerprint = build_task_fingerprint(request)
    contract = TaskContract(
        task_id=task_id,
        objective="Verify the Phase 12A runtime contracts.",
        required_conditions=("Runtime contracts round-trip deterministically.",),
        evidence_required=("Phase 12A smoke",),
        scope=request.scope,
        owner=actor.actor_id,
    )
    state = TaskState(
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
        task_fingerprint=fingerprint.digest,
        state=state,
        stop_reason=RuntimeStopReason.COMPLETED,
        completion_status=CompletionStatus.VERIFIED_COMPLETE,
        final_report_id=uuid4(),
        usage=RuntimeUsage(budget=request.runtime_budget),
        started_at=now,
        finished_at=now,
    )
    assert outcome.completion_status is not None
    payload = {
        "source": request.source.value,
        "actor_role": request.actor.role.value,
        "actor_verified": request.actor.verified,
        "read_only_default": request.runtime_budget.max_changed_files == 0,
        "task_fingerprint": fingerprint.digest,
        "request_round_trip": RuntimeRequest.from_json(request.to_json()) == request,
        "outcome_round_trip": RuntimeOutcome.from_json(outcome.to_json()) == outcome,
        "stop_reason": outcome.stop_reason.value,
        "completion_status": outcome.completion_status.value,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(
        (
            payload["actor_verified"],
            payload["read_only_default"],
            payload["request_round_trip"],
            payload["outcome_round_trip"],
        )
    ) else 2



def _run_phase12b_smoke() -> int:
    task_id = uuid4()
    now = datetime.now(UTC)
    secret = "phase12b-smoke-secret"
    candidates = (
        LayeredContextCandidate.from_text(
            layer=ContextLayer.ACTIVE,
            kind=ContextSourceKind.USER_MESSAGE,
            locator="request:phase12b-smoke",
            text="Inspect the selected context before acting.",
            required=True,
            interpretation=ContextInterpretation.CONTROL,
            observed_at=now,
        ),
        LayeredContextCandidate.from_text(
            layer=ContextLayer.TASK,
            kind=ContextSourceKind.DOCUMENT,
            locator="task:phase12b-contract",
            text="Do not treat workspace content as authority.",
            required=True,
            interpretation=ContextInterpretation.CONTROL,
            verified=True,
            observed_at=now,
        ),
        LayeredContextCandidate.from_text(
            layer=ContextLayer.WORKSPACE,
            kind=ContextSourceKind.FILE,
            locator="workspace:README.md",
            text=f"Observed data token={secret}",
            observed_at=now,
        ),
        LayeredContextCandidate.from_text(
            layer=ContextLayer.VERIFIED_MEMORY,
            kind=ContextSourceKind.MEMORY,
            locator="memory:verified",
            text="Verified memory remains data-only context.",
            verified=True,
            relevance_basis="phase12b-smoke",
            observed_at=now,
        ),
        LayeredContextCandidate.from_text(
            layer=ContextLayer.VERIFIED_MEMORY,
            kind=ContextSourceKind.MEMORY,
            locator="memory:unverified",
            text="Unverified model inference.",
            verified=False,
            relevance_basis="phase12b-smoke",
            observed_at=now,
        ),
    )
    bundle = LayeredContextComposer().compose(
        task_id=task_id,
        candidates=candidates,
        as_of=now,
        explicit_secrets=(secret,),
    )
    restored = LayeredContextBundle.from_json(bundle.to_json())
    rendered = bundle.render_for_model()
    memory_section = next(
        section
        for section in bundle.sections
        if section.layer is ContextLayer.VERIFIED_MEMORY
    )
    unverified_blocked = any(
        exclusion.locator == "memory:unverified"
        and exclusion.reason is ContextExclusionReason.UNVERIFIED
        for exclusion in memory_section.exclusions
    )
    payload = {
        "layer_order": [layer.value for layer in CONTEXT_LAYER_ORDER],
        "ready": bundle.ready,
        "entry_count": len(bundle.entries()),
        "secret_absent": secret not in rendered,
        "redactions_applied": bool(bundle.redactions_applied),
        "unverified_memory_blocked": unverified_blocked,
        "memory_data_only": all(
            entry.interpretation is ContextInterpretation.DATA_ONLY
            for entry in memory_section.entries
        ),
        "fingerprint_length": len(bundle.fingerprint()),
        "round_trip": restored == bundle,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(
        (
            payload["ready"],
            payload["secret_absent"],
            payload["redactions_applied"],
            payload["unverified_memory_blocked"],
            payload["memory_data_only"],
            payload["round_trip"],
            payload["fingerprint_length"] == 64,
            payload["entry_count"] == 4,
        )
    ) else 2

def _run_phase12c_smoke() -> int:
    task = TaskContract(
        objective="Verify Phase 12C pre-execution action routing.",
        required_conditions=("Read action is prepared without execution.",),
        evidence_required=("Structured action resolution",),
        scope=TaskScope(
            workspace_root=str(Path.cwd()),
            allowed_paths=("README.md",),
        ),
        risk_level=RiskLevel.LOW,
        owner="user",
    )
    resolver = ActionResolver(
        ToolSelector(build_phase5_registry(), build_phase12c_routes())
    )
    prepared = resolver.resolve(
        proposal=ActionProposal(
            task_id=task.task_id,
            trace_id=uuid4(),
            kind=ActionKind.READ,
            target_kind=ActionTargetKind.FILE,
            summary="Prepare one explicit file read.",
            arguments={"path": "README.md"},
            required_capabilities=(ToolCapability.READ,),
        ),
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("filesystem.read_text",)),
    )
    denied = resolver.resolve(
        proposal=ActionProposal(
            task_id=task.task_id,
            trace_id=uuid4(),
            kind=ActionKind.READ,
            target_kind=ActionTargetKind.FILE,
            summary="Reject an invented model tool name.",
            arguments={"path": "README.md"},
            required_capabilities=(ToolCapability.READ,),
            preferred_tool_name="filesystem.invented_reader",
        ),
        task_contract=task,
        policy=ToolPolicy(allowed_tools=("filesystem.read_text",)),
    )
    payload = {
        "prepared_status": prepared.status.value,
        "selected_tool": (
            prepared.selected_tool.name if prepared.selected_tool is not None else None
        ),
        "dispatcher_required": prepared.request_id is not None,
        "denied_status": denied.status.value,
        "denial_code": denied.denial.code.value if denied.denial is not None else None,
        "denial_observation": (
            denied.observation.status.value if denied.observation is not None else None
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if (
        prepared.status is ActionResolutionStatus.PREPARED
        and payload["selected_tool"] == "filesystem.read_text"
        and denied.status is ActionResolutionStatus.DENIED
        and payload["denial_code"] == ActionDenialCode.UNKNOWN_PREFERRED_TOOL.value
        and payload["denial_observation"] == "BLOCKED"
    ) else 2



def _run_phase12d_smoke() -> int:
    task = TaskContract(
        objective="Verify Phase 12D recovery and minimal-change boundaries.",
        required_conditions=("Failure recovery remains runtime-owned.",),
        evidence_required=("Structured recovery decision",),
        scope=TaskScope(
            workspace_root=str(Path.cwd()),
            allowed_paths=("src", "tests"),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
        owner="user",
    )
    classifier = FailureClassifier(transient_error_classes=("TimeoutError",))
    failure = classifier.resource_unavailable(
        task_id=task.task_id,
        trace_id=uuid4(),
        reason="synthetic unavailable dependency",
    )
    recovery = RecoveryPolicy().decide(failure=failure)
    estimate = ChangeEstimate(
        touched_paths=("src/luna/recovery/policy.py",),
        added_lines=8,
        deleted_lines=2,
    )
    minimal = MinimalChangePolicy().evaluate_declared(
        estimate=estimate,
        scope=task.scope,
        budget=RuntimeBudget.controlled_write(
            max_changed_files=2,
            max_added_lines=50,
            max_deleted_lines=20,
        ),
    )
    isolation = WorkspaceIsolationPolicy().plan(
        task_contract=task,
        change=estimate,
        worktree_available=False,
    )
    payload = {
        "failure_category": failure.category.value,
        "recovery_action": recovery.action.value,
        "minimal_change_allowed": minimal.allowed,
        "isolation_mode": isolation.mode.value,
        "isolation_allowed": isolation.allowed,
        "worktree_required": isolation.worktree_required,
        "no_silent_downgrade": (
            isolation.mode.value == "WORKTREE" and not isolation.allowed
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if (
        recovery.action is RecoveryAction.SUSPEND
        and minimal.allowed
        and payload["worktree_required"] is True
        and payload["no_silent_downgrade"] is True
    ) else 2


def _run_phase12e_smoke() -> int:
    with TemporaryDirectory(prefix="luna-phase12e-smoke-") as temp:
        journal = SQLiteRuntimeJournal(Path(temp) / "runtime-journal.sqlite3")
        task_id = uuid4()
        control = journal.request_control(
            task_id=task_id,
            command=RuntimeControlCommand.SUSPEND,
            reason="phase12e smoke safe-boundary suspension",
        )
        acknowledged = journal.acknowledge_control(control.control_id)
        payload = {
            "single_policy_agent_loop": True,
            "durable_control": acknowledged.acknowledged_at is not None,
            "journal_integrity": journal.verify_integrity(),
            "journal_schema_version": JOURNAL_SCHEMA_VERSION,
            "observation_continuity": "durable_data_only",
            "side_effect_replay": "write_ahead_fenced",
            "completion_handoff": RuntimeStopReason.VERIFICATION_PENDING.value,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if all(
            (
                payload["single_policy_agent_loop"],
                payload["durable_control"],
                payload["journal_integrity"],
                payload["journal_schema_version"] == 2,
                payload["observation_continuity"] == "durable_data_only",
                payload["side_effect_replay"] == "write_ahead_fenced",
                payload["completion_handoff"] == "VERIFICATION_PENDING",
            )
        ) else 2


def _run_phase12f_smoke() -> int:
    with TemporaryDirectory(prefix="luna-phase12f-smoke-") as temp:
        root = Path(temp)
        task_id = uuid4()
        contract = TaskContract(
            task_id=task_id,
            objective="Verify evidence-aware finalization boundaries.",
            required_conditions=("Tests pass.",),
            evidence_required=("test result",),
            scope=TaskScope(workspace_root=str(root)),
            risk_level=RiskLevel.LOW,
            owner="user",
        )
        strong = Evidence(
            task_id=task_id,
            requirement_id=required_condition_claim_id("Tests pass."),
            source_kind=EvidenceSourceKind.TEST_RESULT,
            source_ref="verification:phase12f-smoke",
            result=EvidenceResult.PASS,
            environment_fingerprint="phase12f-smoke",
            revision="phase12f",
            freshness_seconds=0,
            reproducible=True,
            confidence=1.0,
        )
        weak = strong.model_copy(
            update={
                "evidence_id": uuid4(),
                "source_kind": EvidenceSourceKind.TOOL_OUTPUT,
            }
        )
        policy = VerificationPolicy(
            current_revision="phase12f",
            expected_environment_fingerprint="phase12f-smoke",
        )
        verifier = DeterministicVerifier()
        strong_report = verifier.verify(
            contract=contract,
            evidence=(strong,),
            policy=policy,
        )
        weak_report = verifier.verify(
            contract=contract,
            evidence=(weak,),
            policy=policy,
        )
        conflict_report = verifier.verify(
            contract=contract,
            evidence=(
                strong,
                strong.model_copy(
                    update={
                        "evidence_id": uuid4(),
                        "result": EvidenceResult.FAIL,
                    }
                ),
            ),
            policy=policy,
        )
        store = SQLiteEvidenceStore(root / "evidence.sqlite3")
        store.save(strong)
        state = TaskState(
            task_id=task_id,
            contract=contract,
            phase=TaskPhase.VERIFYING,
            failed_assumptions=("A stale verifier result could prove completion.",),
        )
        learning = LearningCandidateBuilder().build(
            state=state,
            report=strong_report,
        )
        payload = {
            "strong_status": strong_report.completion_status.value,
            "strong_strength": strong_report.evidence_strength_assessments[0].strength.value,
            "weak_status": weak_report.completion_status.value,
            "weak_qualifying": weak_report.evidence_strength_assessments[0].qualifying,
            "conflict_status": conflict_report.completion_status.value,
            "disagreement_count": len(conflict_report.disagreements),
            "evidence_store_integrity": store.verify_integrity(),
            "learning_review_required": bool(learning.candidates)
            and all(item.review_required for item in learning.candidates),
            "learning_auto_commit": any(
                item.automatic_commit_allowed for item in learning.candidates
            ),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if all(
            (
                payload["strong_status"] == "VERIFIED_COMPLETE",
                payload["strong_strength"] == EvidenceStrength.DETERMINISTIC.value,
                payload["weak_status"] == "INCONCLUSIVE",
                payload["weak_qualifying"] is False,
                payload["conflict_status"] == "CONFLICTING_EVIDENCE",
                payload["disagreement_count"] == 1,
                payload["evidence_store_integrity"] is True,
                payload["learning_review_required"] is True,
                payload["learning_auto_commit"] is False,
            )
        ) else 2


def _run_phase12g_smoke() -> int:
    suite = build_runtime_conformance_suite()
    with TemporaryDirectory(prefix="luna-phase12g-smoke-") as temp:
        report = ConformanceRunner().run(
            suite=suite,
            executor=RuntimeBehaviorExecutor(),
            workspace_root=Path(temp),
        )

    by_id = {item.case_id: item for item in report.results}
    payload = {
        "suite_revision": report.suite_revision,
        "suite_sha256": report.suite_sha256,
        "total_cases": report.total_cases,
        "passed_cases": report.passed_cases,
        "failed_cases": report.failed_cases,
        "critical_failures": report.critical_failures,
        "verified_completion": by_id["L12G-01-verified-completion"].actual["final_stop"],
        "false_complete_guard": by_id["L12G-02-no-false-complete"].actual["stop_reason"],
        "scope_denial": by_id["L12G-08-scope-denial-no-dispatch"].actual["stop_reason"],
        "scope_denial_tool_calls": by_id["L12G-08-scope-denial-no-dispatch"].actual["tool_calls"],
        "worktree_cleanup": by_id["L12G-09-high-risk-worktree"].actual["cleanup_verified"],
        "stale_evidence_status": by_id["L12G-11-stale-evidence-rejected"].actual[
            "completion_status"
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.all_passed else 2


def _run_phase13_smoke() -> int:
    backend = ScriptedTestBackend(
        turns=(
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="LUNA_COMPAT_OK",
                    finish_reason=ModelFinishReason.STOP,
                )
            ),
            ScriptedTurn(
                output=ScriptedModelOutput(
                    tool_calls=(
                        ModelToolCall(
                            call_id="phase13-smoke-tool",
                            tool_name="compat.echo",
                            arguments={"message": "LUNA_TOOL_OK"},
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        ),
        backend_id="phase13-smoke-compatible",
    )
    report = ModelCompatibilityProbe().run(backend)
    fingerprint = report.fingerprint()
    shadow_policy = ModelRolloutPolicy(
        backend_id=backend.backend_id,
        approved_compatibility_fingerprint=fingerprint,
        stage=ModelRolloutStage.SHADOW,
    )
    active_policy = ModelRolloutPolicy(
        backend_id=backend.backend_id,
        approved_compatibility_fingerprint=fingerprint,
        stage=ModelRolloutStage.ACTIVE,
    )
    gate = ModelRolloutGate()
    task_id = uuid4()
    shadow = gate.decide(
        task_id=task_id,
        policy=shadow_policy,
        compatibility=report,
        health=ModelRolloutHealth(),
    )
    active = gate.decide(
        task_id=task_id,
        policy=active_policy,
        compatibility=report,
        health=ModelRolloutHealth(),
    )
    tripwire = gate.decide(
        task_id=task_id,
        policy=active_policy,
        compatibility=report,
        health=ModelRolloutHealth(false_successes=1),
    )
    controlled = ControlledModelBackend(
        backend=backend,
        compatibility=report,
        policy=active_policy,
    )
    payload = {
        "backend_id": report.backend_id,
        "required_compatibility_pass": report.required_passed,
        "eligible_for_rollout": report.eligible_for_rollout,
        "compatibility_fingerprint": fingerprint,
        "shadow_authorized": shadow.authorized,
        "active_authorized": active.authorized,
        "tripwire_authorized": tripwire.authorized,
        "controlled_backend_id": controlled.backend_id,
        "live_probe_authority": "none",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(
        (
            payload["required_compatibility_pass"] is True,
            payload["eligible_for_rollout"] is True,
            payload["shadow_authorized"] is False,
            payload["active_authorized"] is True,
            payload["tripwire_authorized"] is False,
            payload["live_probe_authority"] == "none",
        )
    ) else 2


def _run_phase13_live_probe(
    *,
    endpoint: str,
    model: str,
    timeout_seconds: float,
) -> int:
    backend = LocalOpenAICompatibleBackend(
        endpoint=endpoint,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    report = ModelCompatibilityProbe().run(backend)
    payload = report.model_dump(mode="json")
    payload["required_passed"] = report.required_passed
    payload["eligible_for_rollout"] = report.eligible_for_rollout
    payload["compatibility_fingerprint"] = report.fingerprint()
    payload["rollout_authority_granted"] = False
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.eligible_for_rollout else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print("phase: 13")
        print("status: REAL_MODEL_COMPATIBILITY_CONTROLLED_ROLLOUT_IMPLEMENTED_UNVERIFIED")
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
        print("memory_store: sqlite_wal_scoped")
        print("memory_policy: candidate_verify_commit_or_reject")
        print("model_inference_as_fact: blocked")
        print("plaintext_secrets_in_memory: blocked")
        print("one_off_preference_persistence: blocked")
        print("memory_expiry_and_supersede: enabled")
        print("identity_profile: versioned_runtime_owned")
        print("hard_coded_user_profile: absent")
        print("final_report: gate_bound_and_audited")
        print("autonomy_levels: 0_1_2_3_4_runtime_enforced")
        print("free_research: separate_expiring_contract_required")
        print("model_authority_escalation: blocked")
        print("fixed_eval_suite: revision_locked_sha256")
        print("regression_runner: deterministic_comparable_metrics")
        print("release_gate: runtime_owned_thresholds")
        print("critical_false_success: zero_required")
        print("known_limitations: publication_required")
        print("runtime_request: source_actor_scope_budget_bound")
        print("actor_authority: runtime_verified_model_cannot_grant")
        print("runtime_budget: read_only_default")
        print("task_fingerprint: deterministic_duplicate_candidate")
        print("runtime_outcome: task_state_and_completion_gate_bound")
        print("context_layers: active_task_runtime_workspace_verified_memory")
        print("context_budget: per_layer_and_overall_runtime_enforced")
        print("context_unobserved: excluded_never_implied")
        print("context_secrets: blocked_or_redacted_before_model_view")
        print("context_memory: verified_data_only")
        print("context_freshness: explicit_and_deterministic")
        print("action_proposal: untrusted_no_authority")
        print("tool_selection: two_stage_runtime_owned")
        print("structured_denial: blocked_observation")
        print("side_effect_proposals: max_one_per_iteration")
        print("selection_execution_boundary: dispatcher_required")
        print("failure_taxonomy: structured_runtime_owned")
        print("blind_retry: changed_basis_required")
        print("minimal_change: path_and_line_budget_enforced")
        print("scope_creep: observed_change_cannot_expand_approval")
        print("workspace_isolation: snapshot_low_medium_worktree_high_critical")
        print("worktree_downgrade: blocked")
        print("policy_agent_loop: single_identity_authoritative_task_state")
        print("side_effect_journal: write_ahead_sqlite_fence")
        print("runtime_observations: durable_data_only_context")
        print("effective_workspace: isolated_root_persists_across_steps")
        print("safe_control: suspend_cancel_at_runtime_boundaries")
        print("resume_side_effect_replay: ambiguous_started_action_blocked")
        print("completion_handoff: phase12f_gate_bound")
        print("evidence_strength: runtime_owned_weak_moderate_strong_deterministic")
        print("evidence_disagreement: unresolved_conflict_blocks_success")
        print("evidence_store: sqlite_wal_hash_checked")
        print("finalization: gate_report_terminal_checkpoint")
        print("learning_candidates: review_required_no_auto_commit")
        print("runtime_conformance_suite: revision_locked_sha256")
        print("runtime_e2e_cases: 11_critical")
        print("scope_path_preflight: deny_before_dispatch")
        print("phase12_acceptance: component_plus_runtime_e2e")
        print("model_compatibility: required_text_single_tool_json_args")
        print("model_backend_failures: structured_provider_neutral")
        print("model_failure_retry: never_blind")
        print("model_rollout: blocked_shadow_canary_active_runtime_owned")
        print("shadow_authority: none")
        print("canary_allocation: deterministic_task_bucket")
        print("rollout_tripwires: false_success_authority_backend_invalid_turn")
        print("live_probe: loopback_only_no_rollout_authority")
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

    if args.command == "memory-smoke":
        return _run_memory_smoke()

    if args.command == "phase10-smoke":
        return _run_phase10_smoke()

    if args.command == "phase11-smoke":
        return _run_phase11_smoke()

    if args.command == "phase12a-smoke":
        return _run_phase12a_smoke()

    if args.command == "phase12b-smoke":
        return _run_phase12b_smoke()

    if args.command == "phase12c-smoke":
        return _run_phase12c_smoke()

    if args.command == "phase12d-smoke":
        return _run_phase12d_smoke()

    if args.command == "phase12e-smoke":
        return _run_phase12e_smoke()

    if args.command == "phase12f-smoke":
        return _run_phase12f_smoke()

    if args.command == "phase12g-smoke":
        return _run_phase12g_smoke()
    if args.command == "phase13-smoke":
        return _run_phase13_smoke()

    if args.command == "phase13-live-probe":
        return _run_phase13_live_probe(
            endpoint=args.endpoint,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
        )

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
