from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from luna.context import ContextBudget, ContextCandidate, ContextSource, ContextSourceKind
from luna.contracts import TaskScope, TaskState
from luna.contracts.enums import PlanStepStatus
from luna.parallel_cognition.admission import (
    AdmissionDisposition,
    AdmissionEngine,
    AdmissionReason,
    AssignmentIntent,
    CurrentAdmissionSnapshot,
    DelegationDisposition,
    DelegationIntent,
    HierarchicalBudgetEnvelope,
)
from luna.parallel_cognition.controls import (
    AttemptRuntimeBinding,
    ControlDisposition,
    ControlExpectation,
    ControlFenceController,
    ControlFencePhase,
    CurrentControlSnapshot,
    FenceDecision,
    ResultQuarantineRecord,
    evaluate_control_fence,
)
from luna.parallel_cognition.events import (
    FakeBackendRequest,
    FakeBackendResult,
    FakeBackendScript,
    RootLeaseHandle,
)
from luna.parallel_cognition.models import (
    AgentExecutionAttempt,
    AgentExecutionReceipt,
    AgentLifecycleState,
    AgentPayload,
    AssignmentSemanticSpec,
    ClaimSupportDisposition,
    CleanupState,
    ContextFreshness,
    ContextSourceReference,
    IsolationReferences,
    ParallelCognitionRole,
    ProposedClaim,
    ReadOnlyContextManifest,
    RedactionState,
    SourceStepSemantics,
    WorkerBudgetEnvelope,
    contract_sha256,
)
from luna.parallel_cognition.reconciliation import (
    DeterministicReconciler,
    IssuedClaimSpec,
    ReconciliationDisposition,
    RootIssuedClaimSchema,
)
from luna.parallel_cognition.resolution import (
    ArtifactCurrentness,
    AuthoritativeEvidenceRecord,
    AuthoritativeObservationRecord,
    AuthoritativeResolver,
    AuthoritativeSourceRecord,
    ClaimResolutionReceipt,
    ReferenceKind,
    ReferenceResolutionReceipt,
    ResolutionStatus,
    claim_resolution_subject_sha256,
)
from luna.parallel_cognition.store import (
    COORDINATION_STORE_SCHEMA_VERSION,
    CoordinationStoreConflictError,
    CoordinationStoreError,
    CoordinationStoreIntegrityError,
    SQLiteCoordinationStore,
)
from luna.planning import (
    AdaptivePlanner,
    DecisionControlAction,
    GeneralCapabilitySelector,
    LocalJudgmentBuilder,
)
from luna.preparation import TaskPreparer
from luna.retrieval import RetrievalDecision
from luna.tools import ToolPolicy
from luna.verification import VerificationDepth

TASK_ID = UUID("71000000-0000-4000-8000-000000000011")
OTHER_TASK_ID = UUID("72000000-0000-4000-8000-000000000022")
ROOT_ID = UUID("73000000-0000-4000-8000-000000000033")
STEP_ID = UUID("74000000-0000-4000-8000-000000000044")
NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
DEADLINE = NOW + timedelta(minutes=5)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


@dataclass(frozen=True, slots=True)
class _Fixture:
    context: ReadOnlyContextManifest
    assignment: AssignmentSemanticSpec


@dataclass(slots=True)
class _Clock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass(slots=True)
class _Provider:
    snapshot: CurrentControlSnapshot
    calls: list[tuple[UUID, str]] = field(default_factory=list)

    def current_control_snapshot(self, task_id: UUID, attempt_id: str) -> CurrentControlSnapshot:
        self.calls.append((task_id, attempt_id))
        return self.snapshot


@dataclass(slots=True)
class _AdmissionProvider:
    snapshot: CurrentAdmissionSnapshot
    calls: int = 0

    def current_snapshot(self) -> CurrentAdmissionSnapshot:
        self.calls += 1
        return self.snapshot


@dataclass(frozen=True, slots=True)
class _SourceProvider:
    records: tuple[AuthoritativeSourceRecord, ...]
    provider_ref: str = "store:source:s3"

    def resolve_source(
        self,
        *,
        task_id: UUID,
        source_task_revision: int,
        source_ref: str,
    ) -> tuple[AuthoritativeSourceRecord, ...]:
        del task_id, source_task_revision, source_ref
        return self.records


@dataclass(frozen=True, slots=True)
class _EvidenceProvider:
    records: tuple[AuthoritativeEvidenceRecord, ...] = ()
    provider_ref: str = "store:evidence:s3"

    def resolve_evidence(
        self,
        *,
        task_id: UUID,
        source_task_revision: int,
        evidence_ref: str,
    ) -> tuple[AuthoritativeEvidenceRecord, ...]:
        del task_id, source_task_revision, evidence_ref
        return self.records


@dataclass(frozen=True, slots=True)
class _ObservationProvider:
    records: tuple[AuthoritativeObservationRecord, ...] = ()
    provider_ref: str = "store:observation:s3"

    def resolve_observation(
        self,
        *,
        task_id: UUID,
        source_task_revision: int,
        observation_ref: str,
    ) -> tuple[AuthoritativeObservationRecord, ...]:
        del task_id, source_task_revision, observation_ref
        return self.records


@dataclass(frozen=True, slots=True)
class _AttemptProvider:
    records: tuple[AgentExecutionAttempt, ...]
    provider_ref: str = "store:attempt:s3"

    def resolve_attempt(
        self,
        *,
        task_id: UUID,
        attempt_id: str,
    ) -> tuple[AgentExecutionAttempt, ...]:
        del task_id, attempt_id
        return self.records


def _fixture(*, epoch: int = 1, source_sha256: str = SHA_A) -> _Fixture:
    source = ContextSourceReference(
        task_id=TASK_ID,
        source_task_revision=9,
        source_ref="repo:src",
        source_revision="git:c011-s3-fixture",
        content_sha256=source_sha256,
        freshness=ContextFreshness.CURRENT,
        freshness_checked_at=NOW - timedelta(seconds=1),
        redaction_state=RedactionState.REDACTED,
        size_bytes=64,
    )
    context = ReadOnlyContextManifest(
        task_id=TASK_ID,
        source_task_revision=9,
        sources=(source,),
        total_size_bytes=64,
        created_at=NOW,
        expires_at=DEADLINE,
    )
    step = SourceStepSemantics(
        step_id=STEP_ID,
        sequence=1,
        description="Inspect one deterministic S3 read-only lane.",
        status=PlanStepStatus.PENDING,
        source_step_payload_sha256=SHA_B,
    )
    budget = WorkerBudgetEnvelope(
        max_context_bytes=1024,
        max_result_bytes=4096,
        max_claims=4,
        max_tokens=1000,
        max_runtime_ms=60_000,
        deadline_at=DEADLINE,
    )
    assignment = AssignmentSemanticSpec(
        task_id=TASK_ID,
        source_task_revision=9,
        task_contract_sha256=SHA_C,
        source_steps=(step,),
        acceptance_basis_sha256=SHA_D,
        acceptance_target_refs=("target:s3",),
        context_manifest_sha256=contract_sha256(context),
        autonomy_policy_sha256=SHA_E,
        tool_policy_sha256=SHA_F,
        worker_role=ParallelCognitionRole.PARALLEL,
        objective="Return one bounded deterministic S3 fixture payload.",
        granted_source_refs=("repo:src",),
        capability_selection_basis_sha256=SHA_A,
        root_coordination_epoch=epoch,
        budget=budget,
    )
    return _Fixture(context=context, assignment=assignment)


def _attempt(
    fixture: _Fixture,
    state: AgentLifecycleState,
    *,
    attempt_id: str = "attempt:s3-lane-1",
    runtime_session_id: str = "session:s3-lane-1",
) -> AgentExecutionAttempt:
    precreation = {
        AgentLifecycleState.PROPOSED,
        AgentLifecycleState.ADMITTED,
        AgentLifecycleState.DENIED,
    }
    provisioned = state not in precreation
    started = state in {
        AgentLifecycleState.STARTED,
        AgentLifecycleState.RESULT_RECEIVED,
        AgentLifecycleState.CLEANUP_COMPLETE,
        AgentLifecycleState.RECONCILED,
        AgentLifecycleState.REJECTED,
        AgentLifecycleState.VERIFY_REQUIRED,
        AgentLifecycleState.CLOSED,
    }
    return AgentExecutionAttempt(
        attempt_id=attempt_id,
        task_id=TASK_ID,
        source_task_revision=9,
        assignment_id=fixture.assignment.assignment_id,
        context_manifest_sha256=contract_sha256(fixture.context),
        runtime_session_id=runtime_session_id if provisioned else None,
        backend_id="fake:c011-s3" if provisioned else None,
        profile_id="profile:deterministic-s3" if provisioned else None,
        root_coordination_epoch=fixture.assignment.root_coordination_epoch,
        cancellation_epoch=0,
        created_at=NOW + timedelta(seconds=1),
        started_at=NOW + timedelta(seconds=2) if started else None,
        deadline_at=DEADLINE,
        isolation=(
            IsolationReferences(
                process_ref="isolation:process:none",
                session_ref="isolation:session:s3",
                context_ref="isolation:context:s3",
            )
            if provisioned
            else None
        ),
        lifecycle_state=state,
    )


def _record_path(
    store: SQLiteCoordinationStore,
    lease: RootLeaseHandle,
    fixture: _Fixture,
    states: tuple[AgentLifecycleState, ...],
) -> AgentExecutionAttempt:
    current: AgentExecutionAttempt | None = None
    for offset, state in enumerate(states):
        current = _attempt(fixture, state)
        store.record_attempt_transition(
            lease,
            current,
            idempotency_key=f"s3:path:{state.value}",
            occurred_at=NOW + timedelta(milliseconds=offset),
        )
    assert current is not None
    return current


def _expectation(fixture: _Fixture) -> ControlExpectation:
    return ControlExpectation(
        task_id=TASK_ID,
        source_task_revision=9,
        task_state_sha256=SHA_A,
        autonomy_policy_sha256=SHA_B,
        tool_policy_sha256=SHA_C,
        context_manifest_sha256=contract_sha256(fixture.context),
        plan_seal_sha256=SHA_D,
        assignment_id=fixture.assignment.assignment_id,
        root_coordination_epoch=fixture.assignment.root_coordination_epoch,
        cancellation_generation=0,
        deadline_at=DEADLINE,
    )


def _snapshot(
    expectation: ControlExpectation,
    *,
    captured_at: datetime,
    attempt: AgentExecutionAttempt | None = None,
    task_id: UUID = TASK_ID,
    cancellation_requested: bool = False,
) -> CurrentControlSnapshot:
    return CurrentControlSnapshot(
        task_id=task_id,
        source_task_revision=expectation.source_task_revision,
        task_state_sha256=expectation.task_state_sha256,
        autonomy_policy_sha256=expectation.autonomy_policy_sha256,
        tool_policy_sha256=expectation.tool_policy_sha256,
        context_manifest_sha256=expectation.context_manifest_sha256,
        plan_seal_sha256=expectation.plan_seal_sha256,
        root_coordination_epoch=expectation.root_coordination_epoch,
        cancellation_generation=expectation.cancellation_generation,
        cancellation_requested=cancellation_requested,
        root_lease_active=True,
        authority_ceiling_intact=True,
        sources_current=True,
        attempt_binding=(None if attempt is None else AttemptRuntimeBinding.from_attempt(attempt)),
        captured_at=captured_at,
    )


def _payload(
    fixture: _Fixture,
    attempt: AgentExecutionAttempt,
    *,
    claim: ProposedClaim | None = None,
) -> AgentPayload:
    current_claim = claim or ProposedClaim(
        claim_key="claim:s3-one",
        statement="The deterministic S3 fixture was observed.",
        source_refs=("repo:src",),
    )
    return AgentPayload(
        task_id=TASK_ID,
        source_task_revision=9,
        assignment_id=fixture.assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        context_manifest_sha256=contract_sha256(fixture.context),
        summary="One deterministic S3 fixture result.",
        claims=(current_claim,),
        cited_source_refs=current_claim.source_refs,
        cited_evidence_refs=current_claim.evidence_refs,
        cited_observation_refs=current_claim.observation_refs,
    )


def _result(
    fixture: _Fixture,
    attempt: AgentExecutionAttempt,
    *,
    outcome_at: datetime,
    cleanup_at: datetime,
    claim: ProposedClaim | None = None,
) -> FakeBackendResult:
    script = FakeBackendScript(
        payload=_payload(fixture, attempt, claim=claim),
        outcome_state=AgentLifecycleState.RESULT_RECEIVED,
        cleanup_state=CleanupState.CLEANUP_COMPLETE,
        outcome_at=outcome_at,
        cleanup_at=cleanup_at,
        tokens=10,
        runtime_ms=100,
    )
    request = FakeBackendRequest(
        assignment=fixture.assignment,
        attempt=attempt,
        context=fixture.context,
        script_sha256=contract_sha256(script),
        requested_at=attempt.started_at + timedelta(milliseconds=1),  # type: ignore[operator]
    )
    return FakeBackendResult.from_request_script(
        request,
        script,
        backend_id="fake:c011-s3",
        profile_id="profile:deterministic-s3",
    )


def _store_and_lease(tmp_path: Path) -> tuple[SQLiteCoordinationStore, RootLeaseHandle]:
    store = SQLiteCoordinationStore(tmp_path / "coordination.sqlite3")
    lease = store.acquire_root_lease(
        TASK_ID,
        root_owner_ref="root:luna-s3-fixture",
        root_instance_id=ROOT_ID,
        ttl_seconds=3600,
        now=NOW,
        idempotency_key="s3:lease",
    )
    return store, lease


def _admission_snapshot(lease: RootLeaseHandle) -> CurrentAdmissionSnapshot:
    request = "Inspect one bounded current-state admission fixture."
    preparation = TaskPreparer().prepare(
        request=request,
        scope=TaskScope(workspace_root="C:/workspace"),
        context_candidates=(
            ContextCandidate(
                source=ContextSource.from_text(
                    kind=ContextSourceKind.USER_MESSAGE,
                    locator="user:c011-s3-admission",
                    text=request,
                    verified=True,
                ),
                required=True,
                priority=100,
            ),
        ),
        context_budget=ContextBudget(),
        required_conditions=("Admission remains bounded and read-only.",),
        forbidden_outcomes=("Worker authority expands.",),
        evidence_required=("Deterministic admission receipt",),
        task_id=TASK_ID,
    )
    assert preparation.contract is not None
    backchain = LocalJudgmentBuilder().acceptance_from_basis(
        contract=preparation.contract,
        specification=preparation.specification_judgment,
    )
    plan = AdaptivePlanner().plan(preparation)
    state = TaskState(
        task_id=TASK_ID,
        contract=preparation.contract,
        plan=plan.steps,
        specification_judgment=preparation.specification_judgment,
        acceptance_target_ids=tuple(item.target_id for item in backchain.targets),
        acceptance_basis_fingerprint=backchain.acceptance_basis_fingerprint,
    )
    specification = state.specification_judgment
    acceptance_basis = state.acceptance_basis_fingerprint
    assert specification is not None
    assert acceptance_basis is not None
    capability = GeneralCapabilitySelector().select(
        task_id=TASK_ID,
        step_id=state.plan[0].step_id,
        specification_basis_fingerprint=(specification.specification_basis_fingerprint),
        acceptance_basis_fingerprint=acceptance_basis,
        decision_basis_fingerprint=SHA_B,
        retrieval_strategy_fingerprint=SHA_C,
        decision_control_action=DecisionControlAction.CONTINUE.value,
        retrieval_decision=RetrievalDecision.ANSWER_DIRECT.value,
        verification_depth=VerificationDepth.TARGETED.value,
        considered_tool_names=(),
    )
    source = ContextSourceReference(
        task_id=TASK_ID,
        source_task_revision=state.revision,
        source_ref="repo:src",
        source_revision="git:c011-s3-admission",
        content_sha256=SHA_A,
        freshness=ContextFreshness.CURRENT,
        freshness_checked_at=NOW,
        redaction_state=RedactionState.REDACTED,
        size_bytes=64,
    )
    return CurrentAdmissionSnapshot(
        task_state=state,
        tool_policy=ToolPolicy(),
        context_sources=(source,),
        capability_selection=capability,
        root_lease=lease.record,
        cancellation_generation=0,
        cancellation_requested=False,
        delegation_enabled=True,
    )


def _hierarchical_budget(*, max_total_tokens: int = 3000) -> HierarchicalBudgetEnvelope:
    return HierarchicalBudgetEnvelope(
        max_total_workers=3,
        max_concurrent_workers=3,
        delegation_depth=1,
        max_worker_context_bytes=1024,
        max_worker_result_bytes=4096,
        max_worker_tokens=1000,
        max_worker_runtime_ms=60_000,
        max_total_context_bytes=3072,
        max_total_result_bytes=12_288,
        max_total_tokens=max_total_tokens,
        max_total_runtime_ms=180_000,
        overall_deadline_at=DEADLINE,
    )


def _delegation_intent(
    snapshot: CurrentAdmissionSnapshot,
    *,
    worker_count: int,
    max_total_tokens: int = 3000,
) -> DelegationIntent:
    step_sequence = snapshot.task_state.plan[0].sequence
    worker_budget = WorkerBudgetEnvelope(
        max_context_bytes=1024,
        max_result_bytes=4096,
        max_claims=4,
        max_tokens=1000,
        max_runtime_ms=60_000,
        deadline_at=DEADLINE,
    )
    return DelegationIntent(
        disposition=DelegationDisposition.DELEGATE,
        assignments=tuple(
            AssignmentIntent(
                worker_role=(
                    ParallelCognitionRole.PARALLEL
                    if index != 2
                    else ParallelCognitionRole.INDEPENDENT_REVIEWER
                ),
                objective=f"Inspect independent bounded lane {index}.",
                independent_value_basis=f"lane:{index}:independent-value",
                source_step_sequences=(step_sequence,),
                budget=worker_budget,
            )
            for index in range(worker_count)
        ),
        source_refs=("repo:src",),
        budget=_hierarchical_budget(max_total_tokens=max_total_tokens),
    )


def test_admission_zero_workers_three_workers_and_fresh_recheck(tmp_path: Path) -> None:
    _, lease = _store_and_lease(tmp_path)
    snapshot = _admission_snapshot(lease)
    provider = _AdmissionProvider(snapshot)
    engine = AdmissionEngine(snapshot_provider=provider, clock=_Clock(NOW + timedelta(seconds=1)))
    zero = engine.admit(
        DelegationIntent(
            disposition=DelegationDisposition.NO_DELEGATION,
            assignments=(),
            source_refs=(),
            budget=_hierarchical_budget(),
        )
    )
    assert zero.disposition is AdmissionDisposition.ADMIT
    assert zero.reason_codes == (AdmissionReason.NO_DELEGATION,)
    assert zero.plan is not None and zero.plan.worker_count == 0

    intent = _delegation_intent(snapshot, worker_count=3)
    first = engine.admit(intent)
    second = engine.admit(
        intent.model_copy(update={"assignments": tuple(reversed(intent.assignments))})
    )
    assert first == second
    assert first.disposition is AdmissionDisposition.ADMIT
    assert first.reason_codes == (AdmissionReason.ADMITTED,)
    assert first.plan is not None and first.plan.worker_count == 3
    assert first.executable is False
    assert all(not item.delegation_authority for item in first.plan.assignments)

    provider.snapshot = snapshot.model_copy(update={"cancellation_requested": True})
    denied = engine.admit(intent)
    assert denied.disposition is AdmissionDisposition.DENY
    assert AdmissionReason.CANCELLATION_REQUESTED in denied.reason_codes
    assert denied.plan is None
    assert provider.calls == 4


@pytest.mark.parametrize(
    ("worker_count", "max_total_tokens", "expected"),
    (
        (4, 4000, AdmissionReason.WORKER_LIMIT_EXCEEDED),
        (3, 2999, AdmissionReason.AGGREGATE_TOKEN_BUDGET_EXCEEDED),
    ),
)
def test_admission_budget_violation_denies_the_whole_plan(
    tmp_path: Path,
    worker_count: int,
    max_total_tokens: int,
    expected: AdmissionReason,
) -> None:
    _, lease = _store_and_lease(tmp_path)
    snapshot = _admission_snapshot(lease)
    decision = AdmissionEngine(
        snapshot_provider=_AdmissionProvider(snapshot),
        clock=_Clock(NOW + timedelta(seconds=1)),
    ).admit(
        _delegation_intent(
            snapshot,
            worker_count=worker_count,
            max_total_tokens=max_total_tokens,
        )
    )
    assert decision.disposition is AdmissionDisposition.DENY
    assert expected in decision.reason_codes
    assert decision.plan is None


def _digest(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _reconciliation_assignment_id(index: int) -> str:
    return f"c011-assignment:sha256:{_digest(f'assignment:{index}')}"


def _claim_resolution(
    index: int,
    *,
    statement: str = "The issued claim is supported.",
    claim_key: str = "claim:issued",
    eligible: bool = True,
    result_variant: int = 1,
) -> ClaimResolutionReceipt:
    assignment_id = _reconciliation_assignment_id(index)
    attempt_id = f"attempt:reconcile-{index}"
    payload_id = f"c011-payload:sha256:{_digest(f'payload:{index}:{result_variant}')}"
    result_id = f"c011-fake-result:sha256:{_digest(f'result:{index}:{result_variant}')}"
    receipt_id = "c011-execution-receipt:sha256:" + _digest(f"execution:{index}:{result_variant}")
    admission_id = "c011-fence-decision:sha256:" + _digest(
        f"result-admission:{index}:{result_variant}"
    )
    adoption_id = "c011-fence-decision:sha256:" + _digest(f"pre-adoption:{index}:{result_variant}")
    status = ResolutionStatus.RESOLVED_CURRENT if eligible else ResolutionStatus.STALE
    currentness = ArtifactCurrentness.CURRENT if eligible else ArtifactCurrentness.STALE
    reference = ReferenceResolutionReceipt(
        kind=ReferenceKind.SOURCE,
        task_id=TASK_ID,
        source_task_revision=9,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        payload_id=payload_id,
        claim_key=claim_key,
        requested_ref="repo:src",
        status=status,
        provider_ref="store:source:s3",
        source_provider_ref="store:source:s3",
        candidate_count=1,
        source_candidate_count=1,
        resolved_task_id=TASK_ID,
        resolved_source_task_revision=9,
        resolved_identity="repo:src:identity",
        resolved_revision="git:c011-s3-reconcile",
        resolved_content_sha256=SHA_A,
        resolved_currentness=currentness,
        source_ref="repo:src",
        source_identity="repo:src:identity",
        source_revision="git:c011-s3-reconcile",
        source_content_sha256=SHA_A,
        source_currentness=currentness,
        currentness_checked_at=NOW,
        source_currentness_checked_at=NOW,
        resolved_at=NOW + timedelta(seconds=10),
        result_admission_decision_id=admission_id,
        pre_adoption_decision_id=adoption_id,
        provenance_refs=("store:source:s3",),
        eligible_for_claim_support=eligible,
        quarantine_required=not eligible,
    )
    return ClaimResolutionReceipt(
        task_id=TASK_ID,
        source_task_revision=9,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        attempt_integrity_id=(
            "c011-attempt-state:sha256:" + _digest(f"attempt-state:{index}:{result_variant}")
        ),
        context_manifest_sha256=SHA_B,
        payload_id=payload_id,
        payload_sha256=_digest(f"payload-content:{index}:{result_variant}"),
        execution_receipt_id=receipt_id,
        execution_receipt_sha256=_digest(f"execution-content:{index}:{result_variant}"),
        result_id=result_id,
        result_sha256=_digest(f"result-content:{index}:{result_variant}"),
        result_admission_decision_id=admission_id,
        pre_adoption_decision_id=adoption_id,
        root_coordination_epoch=1,
        cancellation_epoch=0,
        claim_key=claim_key,
        statement=statement,
        source_refs=("repo:src",),
        reference_receipts=(reference,),
        support_disposition=(
            ClaimSupportDisposition.QUALIFIED
            if eligible
            else ClaimSupportDisposition.VERIFY_REQUIRED
        ),
        reason_codes=(("ALL_REFERENCES_CURRENT",) if eligible else ("SOURCE_STALE",)),
        provenance_refs=("resolver:s3", reference.resolution_receipt_id),
        resolved_at=NOW + timedelta(seconds=10),
        root_consideration_eligible=eligible,
        quarantine_required=not eligible,
    )


def _claim_schema() -> RootIssuedClaimSchema:
    assignments = tuple(_reconciliation_assignment_id(index) for index in range(3))
    return RootIssuedClaimSchema(
        task_id=TASK_ID,
        source_task_revision=9,
        plan_seal_sha256=SHA_C,
        assignment_ids=assignments,
        claims=(
            IssuedClaimSpec(
                claim_key="claim:issued",
                required_assignment_ids=assignments,
            ),
        ),
        issued_at=NOW,
        expires_at=DEADLINE,
    )


def test_reconciliation_is_arrival_order_independent_and_accept_is_not_adoption() -> None:
    schema = _claim_schema()
    resolutions = tuple(_claim_resolution(index) for index in range(3))
    reconciler = DeterministicReconciler()
    first = reconciler.reconcile(
        schema=schema,
        resolutions=resolutions,
        reconciled_at=NOW + timedelta(seconds=20),
    )
    second = reconciler.reconcile(
        schema=schema,
        resolutions=tuple(reversed(resolutions)),
        reconciled_at=NOW + timedelta(seconds=20),
    )
    assert first == second
    assert first.disposition is ReconciliationDisposition.ACCEPT
    assert first.eligible_for_root_consideration is True
    assert first.automatically_adopted is False
    assert first.state_mutation_authority is False
    assert first.completion_authority is False
    assert first.user_facing_voice_authority is False


def test_reconciliation_conflict_defeats_a_two_to_one_majority() -> None:
    receipt = DeterministicReconciler().reconcile(
        schema=_claim_schema(),
        resolutions=(
            _claim_resolution(0, statement="statement:a"),
            _claim_resolution(1, statement="statement:a"),
            _claim_resolution(2, statement="statement:b"),
        ),
        reconciled_at=NOW + timedelta(seconds=20),
    )
    assert receipt.disposition is ReconciliationDisposition.CONFLICT
    assert receipt.majority_vote_used is False
    assert receipt.eligible_for_root_consideration is False
    assert receipt.claims[0].statement is None
    assert "STATEMENT_CONFLICT" in receipt.claims[0].reason_codes


@pytest.mark.parametrize("case", ("duplicate", "unissued", "multiple", "ineligible"))
def test_reconciliation_malformed_or_ineligible_inputs_return_verify(case: str) -> None:
    resolutions = list(_claim_resolution(index) for index in range(3))
    if case == "duplicate":
        resolutions.append(resolutions[0])
    elif case == "unissued":
        resolutions.append(_claim_resolution(0, claim_key="claim:worker-invented"))
    elif case == "multiple":
        resolutions.append(_claim_resolution(0, result_variant=2))
    else:
        resolutions[1] = _claim_resolution(1, eligible=False)
    receipt = DeterministicReconciler().reconcile(
        schema=_claim_schema(),
        resolutions=tuple(resolutions),
        reconciled_at=NOW + timedelta(seconds=20),
    )
    assert receipt.disposition is ReconciliationDisposition.VERIFY
    assert receipt.eligible_for_root_consideration is False


@dataclass(frozen=True, slots=True)
class _ResolutionCase:
    fixture: _Fixture
    claim: ProposedClaim
    result: FakeBackendResult
    receipt: AgentExecutionReceipt
    cleanup_attempt: AgentExecutionAttempt
    result_admission: FenceDecision
    pre_adoption: FenceDecision
    source: AuthoritativeSourceRecord
    evidence: AuthoritativeEvidenceRecord
    observation: AuthoritativeObservationRecord
    resolved_at: datetime


def _resolution_case() -> _ResolutionCase:
    source_content = b"authoritative current C-011 S3 source bytes"
    source_digest = sha256(source_content).hexdigest()
    fixture = _fixture(source_sha256=source_digest)
    started = _attempt(fixture, AgentLifecycleState.STARTED)
    claim = ProposedClaim(
        claim_key="claim:s3-resolved",
        statement="All typed references resolve through authoritative stores.",
        source_refs=("repo:src",),
        evidence_refs=("evidence:s3",),
        observation_refs=("observation:s3",),
    )
    result = _result(
        fixture,
        started,
        outcome_at=NOW + timedelta(seconds=4),
        cleanup_at=NOW + timedelta(seconds=5),
        claim=claim,
    )
    cleanup_attempt = _attempt(fixture, AgentLifecycleState.CLEANUP_COMPLETE)
    assert started.started_at is not None
    receipt = AgentExecutionReceipt(
        task_id=TASK_ID,
        source_task_revision=9,
        assignment_id=fixture.assignment.assignment_id,
        attempt_id=started.attempt_id,
        attempt_integrity_id=cleanup_attempt.attempt_integrity_id,
        context_manifest_sha256=contract_sha256(fixture.context),
        payload_id=result.payload.payload_id,
        payload_sha256=contract_sha256(result.payload),
        runtime_session_id=started.runtime_session_id,
        backend_id=started.backend_id,
        profile_id=started.profile_id,
        root_coordination_epoch=started.root_coordination_epoch,
        cancellation_epoch=started.cancellation_epoch,
        budget=fixture.assignment.budget,
        usage=result.usage,
        started_at=started.started_at,
        outcome_at=result.script.outcome_at,
        deadline_at=DEADLINE,
        cleanup_at=result.script.cleanup_at,
        outcome_state=AgentLifecycleState.RESULT_RECEIVED,
        cleanup_state=CleanupState.CLEANUP_COMPLETE,
        late_result=False,
        event_refs=("event:c011-s3:fixture",),
    )
    expectation = _expectation(fixture)
    result_checked_at = NOW + timedelta(seconds=6)
    result_admission = evaluate_control_fence(
        phase=ControlFencePhase.RESULT_ADMISSION,
        expectation=expectation,
        current=_snapshot(
            expectation,
            captured_at=result_checked_at,
            attempt=started,
        ),
        checked_at=result_checked_at,
        attempt_id=started.attempt_id,
        attempt_binding=AttemptRuntimeBinding.from_attempt(started),
        result=result,
    )
    assert result_admission.disposition is ControlDisposition.ALLOW
    resolved_at = NOW + timedelta(seconds=7)
    pre_adoption = evaluate_control_fence(
        phase=ControlFencePhase.PRE_ADOPTION,
        expectation=expectation,
        current=_snapshot(
            expectation,
            captured_at=resolved_at,
            attempt=cleanup_attempt,
        ),
        checked_at=resolved_at,
        attempt_id=cleanup_attempt.attempt_id,
        attempt_binding=AttemptRuntimeBinding.from_attempt(cleanup_attempt),
        subject_artifact_sha256=claim_resolution_subject_sha256(
            result=result,
            receipt=receipt,
            claim=claim,
        ),
    )
    assert pre_adoption.disposition is ControlDisposition.ALLOW
    source = AuthoritativeSourceRecord(
        task_id=TASK_ID,
        source_task_revision=9,
        source_ref="repo:src",
        source_identity="repo:src:identity",
        source_revision="git:c011-s3-fixture",
        content=source_content,
        currentness=ArtifactCurrentness.CURRENT,
        currentness_checked_at=result_checked_at,
        provenance_refs=("git:c011-s3-fixture",),
    )
    source_binding = source.binding
    evidence = AuthoritativeEvidenceRecord(
        task_id=TASK_ID,
        source_task_revision=9,
        evidence_ref="evidence:s3",
        evidence_identity="evidence:s3:identity",
        evidence_revision="evidence:revision:1",
        content=b"authoritative evidence bytes",
        source=source_binding,
        currentness=ArtifactCurrentness.CURRENT,
        currentness_checked_at=result_checked_at,
        provenance_refs=("store:evidence:s3",),
    )
    observation = AuthoritativeObservationRecord(
        task_id=TASK_ID,
        source_task_revision=9,
        observation_ref="observation:s3",
        observation_identity="observation:s3:identity",
        observation_revision="observation:revision:1",
        content=b"authoritative observation bytes",
        source=source_binding,
        currentness=ArtifactCurrentness.CURRENT,
        currentness_checked_at=result_checked_at,
        provenance_refs=("store:observation:s3",),
    )
    return _ResolutionCase(
        fixture=fixture,
        claim=claim,
        result=result,
        receipt=receipt,
        cleanup_attempt=cleanup_attempt,
        result_admission=result_admission,
        pre_adoption=pre_adoption,
        source=source,
        evidence=evidence,
        observation=observation,
        resolved_at=resolved_at,
    )


def _resolve_case(
    case: _ResolutionCase,
    *,
    sources: tuple[AuthoritativeSourceRecord, ...] | None = None,
    evidence: tuple[AuthoritativeEvidenceRecord, ...] | None = None,
    observations: tuple[AuthoritativeObservationRecord, ...] | None = None,
    pre_adoption: FenceDecision | None = None,
) -> ClaimResolutionReceipt:
    resolver = AuthoritativeResolver(
        source_provider=_SourceProvider((case.source,) if sources is None else sources),
        evidence_provider=_EvidenceProvider((case.evidence,) if evidence is None else evidence),
        observation_provider=_ObservationProvider(
            (case.observation,) if observations is None else observations
        ),
        attempt_provider=_AttemptProvider((case.cleanup_attempt,)),
        resolver_ref="resolver:c011-s3",
    )
    return resolver.resolve_claim(
        result=case.result,
        receipt=case.receipt,
        claim=case.claim,
        result_admission=case.result_admission,
        pre_adoption=case.pre_adoption if pre_adoption is None else pre_adoption,
        resolved_at=case.resolved_at,
    )


def test_authoritative_resolution_qualifies_all_typed_current_references() -> None:
    resolved = _resolve_case(_resolution_case())
    assert resolved.support_disposition is ClaimSupportDisposition.QUALIFIED
    assert resolved.root_consideration_eligible is True
    assert resolved.quarantine_required is False
    assert resolved.reason_codes == ("ALL_REFERENCES_CURRENT",)
    assert {item.kind for item in resolved.reference_receipts} == {
        ReferenceKind.SOURCE,
        ReferenceKind.EVIDENCE,
        ReferenceKind.OBSERVATION,
    }
    assert all(
        item.status is ResolutionStatus.RESOLVED_CURRENT for item in resolved.reference_receipts
    )
    distilled = resolved.to_claim_record()
    assert distilled.statement == resolved.statement
    assert len(distilled.evidence_lineage) == 3
    assert resolved.completion_authority is False


@pytest.mark.parametrize(
    ("case_name", "kind", "expected"),
    (
        ("missing", ReferenceKind.SOURCE, ResolutionStatus.MISSING),
        ("cross_task", ReferenceKind.SOURCE, ResolutionStatus.UNBOUND),
        ("stale", ReferenceKind.SOURCE, ResolutionStatus.STALE),
        ("digest_changed", ReferenceKind.SOURCE, ResolutionStatus.DIGEST_CHANGED),
        ("fabricated_evidence", ReferenceKind.EVIDENCE, ResolutionStatus.UNBOUND),
    ),
)
def test_authoritative_resolution_rejects_noncurrent_or_fabricated_records(
    case_name: str,
    kind: ReferenceKind,
    expected: ResolutionStatus,
) -> None:
    case = _resolution_case()
    sources: tuple[AuthoritativeSourceRecord, ...] | None = None
    evidence: tuple[AuthoritativeEvidenceRecord, ...] | None = None
    if case_name == "missing":
        sources = ()
    elif case_name == "cross_task":
        sources = (case.source.model_copy(update={"task_id": OTHER_TASK_ID}),)
    elif case_name == "stale":
        sources = (case.source.model_copy(update={"currentness": ArtifactCurrentness.STALE}),)
    elif case_name == "digest_changed":
        sources = (case.source.model_copy(update={"content": b"changed source bytes"}),)
    else:
        evidence = (case.evidence.model_copy(update={"evidence_ref": "evidence:fabricated"}),)
    resolved = _resolve_case(case, sources=sources, evidence=evidence)
    by_kind = {item.kind: item for item in resolved.reference_receipts}
    assert by_kind[kind].status is expected
    assert resolved.support_disposition is ClaimSupportDisposition.VERIFY_REQUIRED
    assert resolved.root_consideration_eligible is False
    assert resolved.quarantine_required is True


def test_resolution_rejects_pre_adoption_fence_for_another_claim_subject() -> None:
    case = _resolution_case()
    bad_pre_adoption = case.pre_adoption.model_copy(
        update={"subject_artifact_sha256": SHA_F, "decision_id": ""}
    )
    bad_pre_adoption = FenceDecision.model_validate(bad_pre_adoption.model_dump(mode="json"))
    resolved = _resolve_case(case, pre_adoption=bad_pre_adoption)
    assert "PRE_ADOPTION_FENCE_MISMATCH" in resolved.reason_codes
    assert resolved.support_disposition is ClaimSupportDisposition.VERIFY_REQUIRED


def test_bad_current_snapshot_is_durably_denied_and_precreation_is_closed(
    tmp_path: Path,
) -> None:
    store, lease = _store_and_lease(tmp_path)
    fixture = _fixture()
    _record_path(
        store,
        lease,
        fixture,
        (AgentLifecycleState.PROPOSED, AgentLifecycleState.ADMITTED),
    )
    expectation = _expectation(fixture)
    checked_at = NOW + timedelta(seconds=3)
    provider = _Provider(
        _snapshot(
            expectation,
            captured_at=checked_at + timedelta(seconds=1),
            task_id=OTHER_TASK_ID,
        )
    )
    controller = ControlFenceController(
        provider=provider,
        recorder=store,
        clock=_Clock(checked_at),
    )

    outcome = controller.check(
        phase=ControlFencePhase.BEFORE_CREATION,
        expectation=expectation,
        lease=lease,
        attempt_id="attempt:s3-lane-1",
        idempotency_key="s3:fence:before-creation",
    )

    assert isinstance(outcome, FenceDecision)
    assert outcome.disposition is ControlDisposition.DENY
    assert set(outcome.reasons) >= {"TASK_MISMATCH", "SNAPSHOT_FROM_FUTURE"}
    assert provider.calls == [(TASK_ID, "attempt:s3-lane-1")]
    assert store.load_control_artifact(outcome.decision_id) == outcome
    closed = store.load_attempt("attempt:s3-lane-1")
    assert closed.lifecycle_state is AgentLifecycleState.CLOSED
    assert closed.started_at is None
    assert closed.runtime_session_id is None
    assert closed.cancellation_epoch == 1
    transitions = tuple(
        event.to_state
        for event in store.events_for_attempt("attempt:s3-lane-1")
        if event.to_state is not None
    )
    assert transitions[-4:] == (
        AgentLifecycleState.CANCEL_REQUESTED,
        AgentLifecycleState.CANCELLED,
        AgentLifecycleState.CLEANUP_COMPLETE,
        AgentLifecycleState.CLOSED,
    )
    SQLiteCoordinationStore(store.path).verify_integrity()


def test_before_execution_allow_binds_exact_current_created_attempt(tmp_path: Path) -> None:
    store, lease = _store_and_lease(tmp_path)
    fixture = _fixture()
    created = _record_path(
        store,
        lease,
        fixture,
        (
            AgentLifecycleState.PROPOSED,
            AgentLifecycleState.ADMITTED,
            AgentLifecycleState.CREATED,
        ),
    )
    expectation = _expectation(fixture)
    checked_at = NOW + timedelta(seconds=3)
    provider = _Provider(_snapshot(expectation, captured_at=checked_at, attempt=created))
    outcome = ControlFenceController(
        provider=provider,
        recorder=store,
        clock=_Clock(checked_at),
    ).check(
        phase=ControlFencePhase.BEFORE_EXECUTION,
        expectation=expectation,
        lease=lease,
        attempt_id=created.attempt_id,
        attempt_binding=AttemptRuntimeBinding.from_attempt(created),
        idempotency_key="s3:fence:before-execution",
    )
    assert isinstance(outcome, FenceDecision)
    assert outcome.disposition is ControlDisposition.ALLOW
    assert outcome.reasons == ("CURRENT_STATE_MATCH",)


def test_cancellation_after_creation_denies_execution_and_closes_attempt(
    tmp_path: Path,
) -> None:
    store, lease = _store_and_lease(tmp_path)
    fixture = _fixture()
    created = _record_path(
        store,
        lease,
        fixture,
        (
            AgentLifecycleState.PROPOSED,
            AgentLifecycleState.ADMITTED,
            AgentLifecycleState.CREATED,
        ),
    )
    expectation = _expectation(fixture)
    checked_at = NOW + timedelta(seconds=3)
    outcome = ControlFenceController(
        provider=_Provider(
            _snapshot(
                expectation,
                captured_at=checked_at,
                attempt=created,
                cancellation_requested=True,
            )
        ),
        recorder=store,
        clock=_Clock(checked_at),
    ).check(
        phase=ControlFencePhase.BEFORE_EXECUTION,
        expectation=expectation,
        lease=lease,
        attempt_id=created.attempt_id,
        attempt_binding=AttemptRuntimeBinding.from_attempt(created),
        idempotency_key="s3:fence:cancel-before-execution",
    )
    assert isinstance(outcome, FenceDecision)
    assert outcome.disposition is ControlDisposition.DENY
    assert "CANCELLATION_REQUESTED" in outcome.reasons
    closed = store.load_attempt(created.attempt_id)
    assert closed.lifecycle_state is AgentLifecycleState.CLOSED
    assert closed.started_at is None
    assert closed.cancellation_epoch == 1


def test_inflight_cancellation_quarantines_result(tmp_path: Path) -> None:
    store, lease = _store_and_lease(tmp_path)
    fixture = _fixture()
    started = _record_path(
        store,
        lease,
        fixture,
        (
            AgentLifecycleState.PROPOSED,
            AgentLifecycleState.ADMITTED,
            AgentLifecycleState.CREATED,
            AgentLifecycleState.STARTED,
        ),
    )
    result = _result(
        fixture,
        started,
        outcome_at=NOW + timedelta(seconds=4),
        cleanup_at=NOW + timedelta(seconds=5),
    )
    expectation = _expectation(fixture)
    checked_at = NOW + timedelta(seconds=6)
    outcome = ControlFenceController(
        provider=_Provider(
            _snapshot(
                expectation,
                captured_at=checked_at,
                attempt=started,
                cancellation_requested=True,
            )
        ),
        recorder=store,
        clock=_Clock(checked_at),
    ).check(
        phase=ControlFencePhase.RESULT_ADMISSION,
        expectation=expectation,
        lease=lease,
        attempt_id=started.attempt_id,
        attempt_binding=AttemptRuntimeBinding.from_attempt(started),
        result=result,
        idempotency_key="s3:fence:cancelled-result",
    )
    assert isinstance(outcome, ResultQuarantineRecord)
    assert "CANCELLATION_REQUESTED" in outcome.decision.reasons
    assert outcome.eligible_for_reconciliation is False


def test_late_result_is_atomically_quarantined_and_low_level_admission_fails(
    tmp_path: Path,
) -> None:
    store, lease = _store_and_lease(tmp_path)
    fixture = _fixture()
    started = _record_path(
        store,
        lease,
        fixture,
        (
            AgentLifecycleState.PROPOSED,
            AgentLifecycleState.ADMITTED,
            AgentLifecycleState.CREATED,
            AgentLifecycleState.STARTED,
        ),
    )
    result = _result(
        fixture,
        started,
        outcome_at=NOW + timedelta(seconds=4),
        cleanup_at=NOW + timedelta(seconds=5),
    )
    store.start_fake_invocation(
        lease,
        result.request,
        idempotency_key="s3:fake:start",
        occurred_at=NOW + timedelta(seconds=3),
    )
    expectation = _expectation(fixture)
    received_at = DEADLINE + timedelta(seconds=1)
    provider = _Provider(_snapshot(expectation, captured_at=received_at, attempt=started))
    outcome = ControlFenceController(
        provider=provider,
        recorder=store,
        clock=_Clock(received_at),
    ).check(
        phase=ControlFencePhase.RESULT_ADMISSION,
        expectation=expectation,
        lease=lease,
        attempt_id=started.attempt_id,
        attempt_binding=AttemptRuntimeBinding.from_attempt(started),
        result=result,
        idempotency_key="s3:fence:late-result",
    )
    assert isinstance(outcome, ResultQuarantineRecord)
    assert "DEADLINE_REACHED" in outcome.decision.reasons
    assert store.quarantines_for_attempt(started.attempt_id) == (outcome,)
    assert store.load_attempt(started.attempt_id).lifecycle_state is (AgentLifecycleState.STARTED)
    with pytest.raises(CoordinationStoreConflictError, match="late fake result"):
        store.record_fake_result(
            lease,
            result,
            idempotency_key="s3:fake:late-result",
            occurred_at=received_at,
        )
    SQLiteCoordinationStore(store.path).verify_integrity()


def test_wrong_runtime_binding_is_quarantined_even_with_same_attempt_id(
    tmp_path: Path,
) -> None:
    store, lease = _store_and_lease(tmp_path)
    fixture = _fixture()
    started = _record_path(
        store,
        lease,
        fixture,
        (
            AgentLifecycleState.PROPOSED,
            AgentLifecycleState.ADMITTED,
            AgentLifecycleState.CREATED,
            AgentLifecycleState.STARTED,
        ),
    )
    wrong = _attempt(
        fixture,
        AgentLifecycleState.STARTED,
        runtime_session_id="session:wrong-but-self-consistent",
    )
    result = _result(
        fixture,
        wrong,
        outcome_at=NOW + timedelta(seconds=4),
        cleanup_at=NOW + timedelta(seconds=5),
    )
    expectation = _expectation(fixture)
    received_at = NOW + timedelta(seconds=6)
    provider = _Provider(_snapshot(expectation, captured_at=received_at, attempt=started))
    outcome = ControlFenceController(
        provider=provider,
        recorder=store,
        clock=_Clock(received_at),
    ).check(
        phase=ControlFencePhase.RESULT_ADMISSION,
        expectation=expectation,
        lease=lease,
        attempt_id=started.attempt_id,
        attempt_binding=AttemptRuntimeBinding.from_attempt(started),
        result=result,
        idempotency_key="s3:fence:wrong-runtime",
    )
    assert isinstance(outcome, ResultQuarantineRecord)
    assert "RESULT_RUNTIME_BINDING_MISMATCH" in outcome.decision.reasons


def test_v1_store_migrates_once_and_downgrade_or_unversioned_tables_fail_closed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "migration.sqlite3"
    store = SQLiteCoordinationStore(database)
    store.acquire_root_lease(
        TASK_ID,
        root_owner_ref="root:luna-s3-migration",
        root_instance_id=ROOT_ID,
        ttl_seconds=60,
        now=NOW,
        idempotency_key="s3:migration:lease",
    )
    events_before = store.events_for_task(TASK_ID)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE s3_control_artifacts")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()

    migrated = SQLiteCoordinationStore(database)
    assert migrated.events_for_task(TASK_ID) == events_before
    assert COORDINATION_STORE_SCHEMA_VERSION == 2
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute("SELECT COUNT(*) FROM s3_control_artifacts").fetchone() == (0,)
    SQLiteCoordinationStore(database).verify_integrity()

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    with pytest.raises(CoordinationStoreError, match=r"legacy.*table set"):
        SQLiteCoordinationStore(database)

    unversioned = tmp_path / "unversioned.sqlite3"
    with sqlite3.connect(unversioned) as connection:
        connection.execute("CREATE TABLE foreign_state (value TEXT)")
        connection.commit()
    with pytest.raises(CoordinationStoreError, match="unversioned"):
        SQLiteCoordinationStore(unversioned)


def test_s3_control_artifact_tamper_fails_closed(tmp_path: Path) -> None:
    store, lease = _store_and_lease(tmp_path)
    fixture = _fixture()
    _record_path(
        store,
        lease,
        fixture,
        (AgentLifecycleState.PROPOSED, AgentLifecycleState.ADMITTED),
    )
    expectation = _expectation(fixture)
    checked_at = NOW + timedelta(seconds=3)
    outcome = ControlFenceController(
        provider=_Provider(_snapshot(expectation, captured_at=checked_at, task_id=OTHER_TASK_ID)),
        recorder=store,
        clock=_Clock(checked_at),
    ).check(
        phase=ControlFencePhase.BEFORE_CREATION,
        expectation=expectation,
        lease=lease,
        attempt_id="attempt:s3-lane-1",
        idempotency_key="s3:fence:tamper",
    )
    assert isinstance(outcome, FenceDecision)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE s3_control_artifacts SET artifact_type = 'UNKNOWN' WHERE artifact_id = ?",
            (outcome.decision_id,),
        )
        connection.commit()
    with pytest.raises(CoordinationStoreIntegrityError, match="unknown type"):
        SQLiteCoordinationStore(store.path)
