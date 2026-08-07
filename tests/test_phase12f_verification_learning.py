from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from luna.actions import ActionResolver, ToolSelector, build_phase12c_routes
from luna.audit import AuditEventKind, AuditSession, EvidenceLedger
from luna.autonomy import AutonomyLevel, AutonomyPolicy
from luna.context import LayeredContextComposer
from luna.continuity import ContinuityService, SQLiteContinuityStore
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState
from luna.contracts.enums import (
    CompletionStatus,
    EvidenceResult,
    EvidenceSourceKind,
    TaskPhase,
)
from luna.contracts.evidence import Evidence
from luna.identity import IdentityProfile
from luna.learning import LearningCandidateBuilder, LearningCandidateKind
from luna.memory import VerifiedMemoryService
from luna.modeling import (
    ModelFinishReason,
    ModelToolCall,
    ScriptedModelOutput,
    ScriptedTestBackend,
    ScriptedTurn,
)
from luna.planning import AdaptivePlanner
from luna.preparation import TaskPreparer
from luna.recovery import (
    FailureClassifier,
    MinimalChangePolicy,
    RecoveryPolicy,
    WorkspaceIsolationPolicy,
)
from luna.reporting import FinalReportComposer
from luna.runtime import (
    DeterministicFingerprintProvider,
    GitWorktreeIsolationManager,
    LunaRuntime,
    Phase12FServices,
    RequestSource,
    RuntimeActor,
    RuntimeBudget,
    RuntimeDependencies,
    RuntimeLoopDependencies,
    RuntimeMode,
    RuntimeRequest,
    RuntimeStopReason,
    SQLiteRuntimeJournal,
    WorkspaceChangeInspector,
)
from luna.runtime.environment import RuntimeFingerprintProvider
from luna.tools import ToolDispatcher, ToolPolicy, build_phase5_registry
from luna.verification import (
    CompletionGate,
    DeterministicVerifier,
    EvidenceStoreConflictError,
    EvidenceStrength,
    SQLiteEvidenceStore,
    VerificationPolicy,
    VerifiedEvidenceRegistry,
    required_condition_claim_id,
)
from luna.verification.coordinator import VerificationCoordinator


def _contract(root: Path) -> TaskContract:
    return TaskContract(
        objective="Verify the bounded task with strong evidence.",
        required_conditions=("Tests pass.",),
        evidence_required=("test result",),
        scope=TaskScope(workspace_root=str(root), allowed_paths=("note.txt",)),
        risk_level=RiskLevel.LOW,
        owner="user",
    )


def _evidence(
    contract: TaskContract,
    *,
    source_kind: EvidenceSourceKind = EvidenceSourceKind.TEST_RESULT,
    result: EvidenceResult = EvidenceResult.PASS,
    revision: str = "rev-12f",
    environment: str = "env-12f",
    evidence_id=None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id or uuid4(),
        task_id=contract.task_id,
        requirement_id=required_condition_claim_id("Tests pass."),
        source_kind=source_kind,
        source_ref="verification:phase12f",
        result=result,
        environment_fingerprint=environment,
        revision=revision,
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )


def _policy() -> VerificationPolicy:
    return VerificationPolicy(
        current_revision="rev-12f",
        expected_environment_fingerprint="env-12f",
    )


def test_strong_evidence_completes_and_generic_tool_output_does_not(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    verifier = DeterministicVerifier()

    strong = verifier.verify(
        contract=contract,
        evidence=(_evidence(contract),),
        policy=_policy(),
    )
    weak = verifier.verify(
        contract=contract,
        evidence=(
            _evidence(contract, source_kind=EvidenceSourceKind.TOOL_OUTPUT),
        ),
        policy=_policy(),
    )

    assert strong.completion_status is CompletionStatus.VERIFIED_COMPLETE
    assert strong.evidence_strength_assessments[0].strength is EvidenceStrength.DETERMINISTIC
    assert strong.evidence_strength_assessments[0].qualifying is True
    assert weak.completion_status is CompletionStatus.INCONCLUSIVE
    assert weak.evidence_strength_assessments[0].strength is EvidenceStrength.MODERATE
    assert weak.evidence_strength_assessments[0].qualifying is False


def test_equal_strength_disagreement_is_explicit_and_blocks_success(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=(
            _evidence(contract, result=EvidenceResult.PASS),
            _evidence(contract, result=EvidenceResult.FAIL),
        ),
        policy=_policy(),
    )

    assert report.completion_status is CompletionStatus.CONFLICTING_EVIDENCE
    assert len(report.disagreements) == 1
    disagreement = report.disagreements[0]
    assert disagreement.strongest_support is EvidenceStrength.DETERMINISTIC
    assert disagreement.strongest_contradiction is EvidenceStrength.DETERMINISTIC
    assert disagreement.unresolved is True


def test_evidence_store_is_durable_idempotent_and_conflict_safe(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    store = SQLiteEvidenceStore(tmp_path / "evidence.sqlite3")
    evidence = _evidence(contract)

    assert store.save(evidence) == evidence
    assert store.save(evidence) == evidence
    assert store.list_for_task(contract.task_id) == (evidence,)
    assert store.verify_integrity() is True

    conflicting = evidence.model_copy(update={"result": EvidenceResult.FAIL})
    with pytest.raises(EvidenceStoreConflictError):
        store.save(conflicting)


def test_learning_candidates_require_review_and_never_auto_commit(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    state = TaskState(
        task_id=contract.task_id,
        contract=contract,
        phase=TaskPhase.VERIFYING,
        failed_assumptions=("The first verification environment was current.",),
    )
    report = DeterministicVerifier().verify(
        contract=contract,
        evidence=(_evidence(contract),),
        policy=_policy(),
    )

    batch = LearningCandidateBuilder().build(state=state, report=report)

    assert len(batch.candidates) == 1
    candidate = batch.candidates[0]
    assert candidate.kind is LearningCandidateKind.RECOVERY_PATTERN
    assert candidate.review_required is True
    assert candidate.automatic_commit_allowed is False
    assert candidate.completion_status is CompletionStatus.VERIFIED_COMPLETE


def test_coordinator_binds_gate_report_and_learning_to_same_audit_chain(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    state = TaskState(
        task_id=contract.task_id,
        contract=contract,
        phase=TaskPhase.VERIFYING,
        failed_assumptions=("A stale revision could verify the task.",),
    )
    trace_id = uuid4()
    audit = AuditSession(tmp_path / "audit")
    audit.record_task_contract(contract=contract, trace_id=trace_id)
    coordinator = VerificationCoordinator(
        completion_gate=CompletionGate(audit),
        report_composer=FinalReportComposer(audit),
        identity=IdentityProfile(),
        learning_builder=LearningCandidateBuilder(audit),
    )

    finalization = coordinator.finalize(
        state=state,
        evidence=(_evidence(contract),),
        policy=_policy(),
        trace_id=trace_id,
        performed=("Ran deterministic tests.",),
    )

    assert finalization.reporting_state.phase is TaskPhase.REPORTING
    assert finalization.reporting_state.completion_status is CompletionStatus.VERIFIED_COMPLETE
    assert finalization.final_report.completion_status is CompletionStatus.VERIFIED_COMPLETE
    assert finalization.final_report.evidence_refs[0].endswith("strength:DETERMINISTIC")
    assert finalization.learning_candidates.candidates
    event_kinds = {event.kind for event in audit.events_for_task(contract.task_id)}
    assert AuditEventKind.VERIFICATION_REPORT in event_kinds
    assert AuditEventKind.COMPLETION_DECISION in event_kinds
    assert AuditEventKind.FINAL_REPORT in event_kinds
    assert AuditEventKind.LEARNING_CANDIDATE in event_kinds
    assert audit.verify_integrity().valid


def _phase12f_runtime(
    workspace: Path,
    state_root: Path,
    fingerprint_provider: RuntimeFingerprintProvider,
) -> tuple[LunaRuntime, AuditSession]:
    backend = ScriptedTestBackend(
        (
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="Read the bounded file once.",
                    tool_calls=(
                        ModelToolCall(
                            call_id="phase12f-read",
                            tool_name="filesystem.read_text",
                            arguments={"path": "note.txt"},
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        )
    )
    registry = build_phase5_registry()
    selector = ToolSelector(registry, build_phase12c_routes())
    audit = AuditSession(state_root / "audit")
    continuity = ContinuityService(
        SQLiteContinuityStore(state_root / "continuity.sqlite3"),
        audit,
    )
    completion_gate = CompletionGate(audit)
    report_composer = FinalReportComposer(audit)
    evidence_registry = VerifiedEvidenceRegistry(
        SQLiteEvidenceStore(state_root / "evidence.sqlite3"),
        EvidenceLedger(audit.ledger),
    )
    coordinator = VerificationCoordinator(
        completion_gate=completion_gate,
        report_composer=report_composer,
        identity=IdentityProfile(),
        learning_builder=LearningCandidateBuilder(audit),
    )
    core = RuntimeDependencies(
        task_preparer=TaskPreparer(),
        planner=AdaptivePlanner(),
        model_backend=backend,
        tool_dispatcher=ToolDispatcher(registry),
        completion_gate=completion_gate,
        report_composer=report_composer,
        continuity_service=continuity,
        memory_service=cast(VerifiedMemoryService, object()),
    )
    return (
        LunaRuntime(
            RuntimeLoopDependencies(
                core=core,
                context_composer=LayeredContextComposer(),
                action_resolver=ActionResolver(selector),
                failure_classifier=FailureClassifier(),
                recovery_policy=RecoveryPolicy(),
                minimal_change_policy=MinimalChangePolicy(),
                isolation_policy=WorkspaceIsolationPolicy(),
                change_inspector=WorkspaceChangeInspector(),
                runtime_journal=SQLiteRuntimeJournal(state_root / "journal.sqlite3"),
                isolation_manager=GitWorktreeIsolationManager(),
                fingerprint_provider=fingerprint_provider,
                phase12f=Phase12FServices(
                    evidence_registry=evidence_registry,
                    verification_coordinator=coordinator,
                ),
            )
        ),
        audit,
    )


def test_runtime_resume_finalizes_only_after_current_strong_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_root = tmp_path / "state"
    workspace.mkdir()
    state_root.mkdir()
    (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
    fingerprint_provider = DeterministicFingerprintProvider(
        runtime_revision="luna-0.1-phase12f-test"
    )
    runtime, audit = _phase12f_runtime(workspace, state_root, fingerprint_provider)
    task_id = uuid4()
    autonomy = AutonomyPolicy(
        task_id=task_id,
        level=AutonomyLevel.LEVEL_1_READ_ONLY,
        allowed_tools=("filesystem.read_text",),
        max_risk=RiskLevel.LOW,
    )
    request = RuntimeRequest(
        task_id=task_id,
        raw_request="Read note.txt and verify the task.",
        source=RequestSource.TEST,
        actor=RuntimeActor.verified_owner("phase12f-owner"),
        scope=TaskScope(
            workspace_root=str(workspace),
            allowed_paths=("note.txt",),
        ),
        autonomy=autonomy,
        runtime_budget=RuntimeBudget(),
        required_conditions=("Tests pass.",),
        evidence_required=("test result",),
        mode=RuntimeMode.EXECUTE,
    )
    policy = ToolPolicy(
        allowed_tools=("filesystem.read_text",),
        autonomy_level=AutonomyLevel.LEVEL_1_READ_ONLY,
        max_risk=RiskLevel.LOW,
    )

    first = runtime.run(request=request, tool_policy=policy)
    assert first.stop_reason is RuntimeStopReason.VERIFICATION_PENDING

    contract = first.state.contract
    revision = fingerprint_provider.workspace_fingerprint(task_contract=contract)
    environment = fingerprint_provider.environment_fingerprint()
    weak = Evidence(
        task_id=task_id,
        requirement_id=required_condition_claim_id("Tests pass."),
        source_kind=EvidenceSourceKind.TOOL_OUTPUT,
        source_ref="observation:phase12f-runtime",
        result=EvidenceResult.PASS,
        environment_fingerprint=environment,
        revision=revision,
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )
    runtime.record_evidence(evidence=weak, trace_id=request.trace_id)

    weak_resume = request.model_copy(
        update={
            "request_id": uuid4(),
            "mode": RuntimeMode.RESUME,
            "resume_task_id": task_id,
        }
    )
    inconclusive = runtime.resume(request=weak_resume, tool_policy=policy)
    assert inconclusive.stop_reason is RuntimeStopReason.INCONCLUSIVE
    assert inconclusive.state.phase is TaskPhase.CHECKPOINTED
    assert inconclusive.completion_status is CompletionStatus.INCONCLUSIVE
    assert inconclusive.verification_report_id is not None
    assert inconclusive.final_report_id is not None
    assert inconclusive.learning_candidate_ids
    nonterminal = runtime._deps.core.continuity_service.store.load_latest(task_id)
    assert nonterminal.envelope.terminal is False
    assert nonterminal.envelope.resume_phase is TaskPhase.VERIFYING

    strong = Evidence(
        task_id=task_id,
        requirement_id=required_condition_claim_id("Tests pass."),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:phase12f-runtime",
        result=EvidenceResult.PASS,
        environment_fingerprint=environment,
        revision=revision,
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )
    runtime.record_evidence(evidence=strong, trace_id=request.trace_id)

    strong_resume = request.model_copy(
        update={
            "request_id": uuid4(),
            "mode": RuntimeMode.RESUME,
            "resume_task_id": task_id,
        }
    )
    outcome = runtime.resume(request=strong_resume, tool_policy=policy)

    assert outcome.stop_reason is RuntimeStopReason.COMPLETED
    assert outcome.state.phase is TaskPhase.CLOSED
    assert outcome.completion_status is CompletionStatus.VERIFIED_COMPLETE
    assert outcome.verification_report_id is not None
    assert outcome.final_report_id is not None
    assert outcome.evidence_ids == (weak.evidence_id, strong.evidence_id)
    terminal = runtime._deps.core.continuity_service.store.load_latest(task_id)
    assert terminal.envelope.terminal is True
    assert terminal.envelope.state.phase is TaskPhase.CLOSED
    assert terminal.envelope.checkpoint.evidence_ids == (weak.evidence_id, strong.evidence_id)
    assert audit.verify_integrity().valid
