from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import cast
from uuid import UUID

import pytest

from luna.context import ContextBudget, ContextCandidate, ContextSource, ContextSourceKind
from luna.contracts import TaskScope, TaskState
from luna.contracts.base import utc_now
from luna.contracts.enums import PlanStepStatus
from luna.parallel_cognition.admission import (
    AdmissionDecision,
    AdmissionEngine,
    AdmittedPlan,
    AssignmentIntent,
    CurrentAdmissionSnapshot,
    DelegationDisposition,
    DelegationIntent,
    HierarchicalBudgetEnvelope,
)
from luna.parallel_cognition.context_broker import (
    FocusedContextBroker,
    FocusedContextError,
)
from luna.parallel_cognition.controls import (
    AttemptRuntimeBinding,
    ControlFenceController,
    CurrentControlSnapshot,
)
from luna.parallel_cognition.events import RootLeaseHandle
from luna.parallel_cognition.live import (
    BackendSafetyCapabilities,
    FocusedContextBundle,
    LiveBackendRequest,
    LiveBackendResult,
    LiveInvocationState,
    S4IntegrationStatus,
    S4RuntimePolicy,
)
from luna.parallel_cognition.live_runtime import (
    LiveExecutionAuthorization,
    LiveHandoffReuseFenceController,
    ParallelCognitionRuntimeService,
    RuntimeKillSwitch,
)
from luna.parallel_cognition.live_store import (
    LiveInvocationConflictError,
    LiveInvocationIntegrityError,
    SQLiteLiveInvocationJournal,
)
from luna.parallel_cognition.models import (
    AgentExecutionAttempt,
    AgentExecutionReceipt,
    AgentLifecycleState,
    AssignmentSemanticSpec,
    ClaimFreshness,
    ClaimRecord,
    ClaimSupportDisposition,
    ContextFreshness,
    ContextSourceReference,
    ContradictionState,
    DistilledHandoff,
    EvidenceResolutionState,
    IsolationReferences,
    ParallelCognitionRole,
    ReadOnlyContextManifest,
    RedactionState,
    ResolvedEvidenceLineage,
    SourceStepSemantics,
    WorkerBudgetEnvelope,
    contract_sha256,
)
from luna.parallel_cognition.store import (
    CoordinationStoreNotFoundError,
    SQLiteCoordinationStore,
)
from luna.parallel_cognition.subprocess_backend import (
    InterruptibleWorkerBackend,
    SubprocessWorkerBackend,
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

TASK_ID = UUID("81000000-0000-4000-8000-000000000011")
ROOT_ID = UUID("82000000-0000-4000-8000-000000000022")
ROOT_OWNER = "root:luna-s4-fixture"


def _digest(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _MaterialProvider:
    content: bytes

    def read_source(self, source: ContextSourceReference) -> bytes:
        del source
        return self.content


@dataclass(frozen=True, slots=True)
class _ContractFixture:
    content: bytes
    context: ReadOnlyContextManifest
    assignment: AssignmentSemanticSpec
    focused: FocusedContextBundle
    request: LiveBackendRequest


def _contract_fixture(
    *,
    max_runtime_ms: int = 2000,
    redaction_state: RedactionState = RedactionState.NOT_REQUIRED,
    content: bytes = b"verified read-only context\n",
) -> _ContractFixture:
    now = utc_now()
    deadline = now + timedelta(seconds=10)
    source = ContextSourceReference(
        task_id=TASK_ID,
        source_task_revision=7,
        source_ref="repo:src",
        source_revision="git:c011-s4-fixture",
        content_sha256=sha256(content).hexdigest(),
        freshness=ContextFreshness.CURRENT,
        freshness_checked_at=now - timedelta(milliseconds=1),
        redaction_state=redaction_state,
        size_bytes=len(content),
    )
    context = ReadOnlyContextManifest(
        task_id=TASK_ID,
        source_task_revision=7,
        sources=(source,),
        total_size_bytes=len(content),
        created_at=now,
        expires_at=deadline,
    )
    assignment = AssignmentSemanticSpec(
        task_id=TASK_ID,
        source_task_revision=7,
        task_contract_sha256=_digest("contract"),
        source_steps=(
            SourceStepSemantics(
                step_id=UUID("83000000-0000-4000-8000-000000000033"),
                sequence=1,
                description="Inspect one bounded S4 lane.",
                status=PlanStepStatus.PENDING,
                source_step_payload_sha256=_digest("step"),
            ),
        ),
        acceptance_basis_sha256=_digest("acceptance"),
        acceptance_target_refs=("target:s4",),
        context_manifest_sha256=contract_sha256(context),
        autonomy_policy_sha256=_digest("autonomy"),
        tool_policy_sha256=_digest("tools"),
        worker_role=ParallelCognitionRole.PARALLEL,
        objective="Return one concise cited result.",
        granted_source_refs=("repo:src",),
        capability_selection_basis_sha256=_digest("capability"),
        root_coordination_epoch=1,
        budget=WorkerBudgetEnvelope(
            max_context_bytes=4096,
            max_result_bytes=8192,
            max_claims=4,
            max_tokens=1000,
            max_runtime_ms=max_runtime_ms,
            deadline_at=deadline,
        ),
    )
    focused = FocusedContextBroker(
        provider=_MaterialProvider(content)
    ).materialize(assignment=assignment, manifest=context)
    attempt = AgentExecutionAttempt(
        attempt_id="attempt:s4-unit",
        task_id=TASK_ID,
        source_task_revision=7,
        assignment_id=assignment.assignment_id,
        context_manifest_sha256=contract_sha256(context),
        runtime_session_id="session:s4-unit",
        backend_id="subprocess:c011-s4-test",
        profile_id="profile:c011-s4-test",
        root_coordination_epoch=1,
        cancellation_epoch=0,
        created_at=now,
        started_at=now,
        deadline_at=deadline,
        isolation=IsolationReferences(
            process_ref="s4-process:test",
            session_ref="s4-session:test",
            context_ref="s4-context:test",
        ),
        lifecycle_state=AgentLifecycleState.STARTED,
    )
    request = LiveBackendRequest(
        assignment=assignment,
        attempt=attempt,
        context=context,
        focused_context_id=focused.focused_context_id,
        focused_context_sha256=contract_sha256(focused),
        requested_at=now,
    )
    return _ContractFixture(
        content=content,
        context=context,
        assignment=assignment,
        focused=focused,
        request=request,
    )


def _driver_script(tmp_path: Path) -> Path:
    script = tmp_path / "s4_driver.py"
    script.write_text(
        """
import json
import os
from pathlib import Path
import sys
import time

mode, request_name, result_name, cancel_name = sys.argv[1:]
request_path = Path(request_name)
result_path = Path(result_name)
cancel_path = Path(cancel_name)
request = json.loads(request_path.read_text(encoding="utf-8"))
if mode.startswith("success"):
    if mode == "success-slow":
        time.sleep(0.15)
    source_ref = request["context"][0]["source_ref"]
    result_path.write_text(
        json.dumps(
            {
                "summary": "driver:" + os.environ.get("LUNA_TEST_SECRET", "not-inherited"),
                "claims": [
                    {
                        "claim_key": "claim:s4",
                        "statement": "The focused source was inspected.",
                        "source_refs": [source_ref],
                    }
                ],
                "recommended_next_action": request_name,
                "tokens": 12,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
elif mode == "oversized-final":
    result_path.write_bytes(b"x" * 2_000_000)
elif mode == "cooperative":
    while not cancel_path.exists():
        time.sleep(0.005)
elif mode == "hang":
    while True:
        time.sleep(0.01)
else:
    raise SystemExit(9)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return script


def _subprocess_backend(tmp_path: Path, *, mode: str) -> SubprocessWorkerBackend:
    environment = {"PYTHONIOENCODING": "utf-8"}
    if "SYSTEMROOT" in os.environ:
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return SubprocessWorkerBackend(
        command_template=(
            str(Path(sys.executable).resolve()),
            str(_driver_script(tmp_path).resolve()),
            mode,
            "{request}",
            "{result}",
            "{cancel}",
        ),
        backend_id="subprocess:c011-s4-test",
        profile_id="profile:c011-s4-test",
        environment=environment,
    )


def _active_policy(**updates: object) -> S4RuntimePolicy:
    return S4RuntimePolicy.model_validate(
        {
            "enabled": True,
            "kill_switch_engaged": False,
            "poll_interval_ms": 5,
            "cooperative_cancel_grace_ms": 20,
            "terminate_grace_ms": 20,
            "hard_kill_grace_ms": 500,
            **updates,
        }
    )


def test_focused_context_is_exact_redacted_and_authority_negative() -> None:
    secret = b"api_key=sk-abcdefghijklmnop\n"
    fixture = _contract_fixture(
        content=secret,
        redaction_state=RedactionState.REDACTED,
    )

    document = fixture.focused.documents[0]
    assert document.manifest_content_sha256 == sha256(secret).hexdigest()
    assert "sk-abcdefghijklmnop" not in document.content
    assert document.redactions_applied
    assert fixture.focused.available_tools == ()
    assert fixture.focused.credential_refs == ()
    assert fixture.focused.inherited_memory_refs == ()
    assert fixture.focused.write_authority is False
    assert fixture.focused.network_authority is False
    assert fixture.focused.tool_authority is False
    assert fixture.focused.completion_authority is False


def test_focused_context_rejects_false_redaction_and_changed_digest() -> None:
    secret = b"api_key=sk-abcdefghijklmnop\n"
    now = utc_now()
    fixture = _contract_fixture()
    source_raw = fixture.context.sources[0].model_dump(mode="json")
    source_raw.update(
        {
            "content_sha256": sha256(secret).hexdigest(),
            "size_bytes": len(secret),
            "redaction_state": RedactionState.NOT_REQUIRED.value,
            "freshness_checked_at": now - timedelta(seconds=1),
        }
    )
    context_raw = fixture.context.model_dump(mode="json")
    context_raw.pop("context_manifest_id", None)
    context_raw.update(
        {
            "sources": (ContextSourceReference.model_validate(source_raw),),
            "total_size_bytes": len(secret),
        }
    )
    false_clean = ReadOnlyContextManifest.model_validate(context_raw)
    assignment_raw = fixture.assignment.model_dump(mode="json")
    assignment_raw.pop("assignment_id", None)
    assignment_raw["context_manifest_sha256"] = contract_sha256(false_clean)
    assignment = AssignmentSemanticSpec.model_validate(assignment_raw)
    broker = FocusedContextBroker(provider=_MaterialProvider(secret))
    with pytest.raises(FocusedContextError, match="redaction unnecessary"):
        broker.materialize(assignment=assignment, manifest=false_clean)

    changed = FocusedContextBroker(provider=_MaterialProvider(b"changed"))
    with pytest.raises(FocusedContextError, match=r"size changed|digest changed"):
        changed.materialize(
            assignment=fixture.assignment,
            manifest=fixture.context,
        )


def test_subprocess_backend_succeeds_without_ambient_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUNA_TEST_SECRET", "must-not-cross")
    fixture = _contract_fixture()
    backend = _subprocess_backend(tmp_path, mode="success")

    result = backend.execute(
        request=fixture.request,
        context=fixture.focused,
        policy=_active_policy(),
        cancellation_probe=lambda: False,
    )

    assert result.outcome_state is AgentLifecycleState.RESULT_RECEIVED
    assert result.cleanup_state.value == AgentLifecycleState.CLEANUP_COMPLETE.value
    assert result.payload.summary == "driver:not-inherited"
    assert result.payload.claims[0].source_refs == ("repo:src",)
    assert result.hard_termination_used is False
    assert result.payload.recommended_next_action is not None
    assert not Path(result.payload.recommended_next_action).exists()
    assert backend.safety_capabilities.accepted


def test_subprocess_backend_bounds_last_moment_oversized_result(tmp_path: Path) -> None:
    fixture = _contract_fixture()
    backend = _subprocess_backend(tmp_path, mode="oversized-final")

    result = backend.execute(
        request=fixture.request,
        context=fixture.focused,
        policy=_active_policy(),
        cancellation_probe=lambda: False,
    )

    driver_limit = fixture.assignment.budget.max_result_bytes + 65_536
    assert result.outcome_state is AgentLifecycleState.FAILED
    assert result.reason == "worker result exceeded its bounded driver ceiling"
    assert result.raw_output_size_bytes == driver_limit + 1


@pytest.mark.parametrize(
    ("mode", "cancel", "expected"),
    (
        ("cooperative", True, AgentLifecycleState.CANCELLED),
        ("hang", False, AgentLifecycleState.TIMED_OUT),
    ),
)
def test_subprocess_backend_cancellation_timeout_and_cleanup(
    tmp_path: Path,
    mode: str,
    cancel: bool,
    expected: AgentLifecycleState,
) -> None:
    fixture = _contract_fixture(max_runtime_ms=80)
    backend = _subprocess_backend(tmp_path, mode=mode)

    result = backend.execute(
        request=fixture.request,
        context=fixture.focused,
        policy=_active_policy(cooperative_cancel_grace_ms=300),
        cancellation_probe=lambda: cancel,
    )

    assert result.outcome_state is expected
    assert result.cleanup_state.value == AgentLifecycleState.CLEANUP_COMPLETE.value
    assert result.cancel_requested_at is not None
    assert result.payload.claims == ()
    if mode == "hang":
        assert result.hard_termination_used is True


def test_live_journal_reservation_is_durable_and_never_replayed(
    tmp_path: Path,
) -> None:
    fixture = _contract_fixture()
    journal = SQLiteLiveInvocationJournal(tmp_path / "live.sqlite3")

    first = journal.reserve(invocation_key="s4:one", request=fixture.request)
    second = journal.reserve(invocation_key="s4:one", request=fixture.request)

    assert first == second
    assert first.record.state is LiveInvocationState.RESERVED
    assert journal.load("s4:one") == first
    journal.verify_integrity()

    other_attempt = fixture.request.attempt.model_copy(
        update={"attempt_id": "attempt:s4-other", "attempt_integrity_id": ""}
    )
    other_request = fixture.request.model_copy(
        update={"request_id": "", "attempt": other_attempt}
    )
    with pytest.raises(LiveInvocationConflictError):
        journal.reserve(invocation_key="s4:one", request=other_request)

    with sqlite3_connect(journal.path) as connection:
        connection.execute(
            "UPDATE live_invocations SET request_sha256 = ? WHERE invocation_key = ?",
            ("0" * 64, "s4:one"),
        )
        connection.commit()
    with pytest.raises(LiveInvocationIntegrityError):
        journal.verify_integrity()


class sqlite3_connect:
    """Tiny typed context wrapper used only for deliberate journal tampering."""

    def __init__(self, path: Path) -> None:
        import sqlite3

        self._connection = sqlite3.connect(path)

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self._connection

    def __exit__(self, *args: object) -> None:
        self._connection.close()


@dataclass(slots=True)
class _Clock:
    def now(self) -> datetime:
        return utc_now()


@dataclass(slots=True)
class _AdmissionSnapshotProvider:
    snapshot: CurrentAdmissionSnapshot

    def current_snapshot(self) -> CurrentAdmissionSnapshot:
        return self.snapshot


@dataclass(slots=True)
class _FixedPlanProvider:
    decision: AdmissionDecision
    lease: RootLeaseHandle
    calls: int = 0

    def authorization_for(self, state: TaskState) -> LiveExecutionAuthorization:
        del state
        self.calls += 1
        return LiveExecutionAuthorization(
            decision=self.decision,
            lease=self.lease,
        )


@dataclass(slots=True)
class _CurrentControlProvider:
    plan: AdmittedPlan
    store: SQLiteCoordinationStore

    def current_control_snapshot(
        self,
        task_id: UUID,
        attempt_id: str,
    ) -> CurrentControlSnapshot:
        plan = self.plan
        attempt: AgentExecutionAttempt | None = None
        try:
            candidate = self.store.load_attempt(attempt_id)
            if candidate.lifecycle_state not in {
                AgentLifecycleState.PROPOSED,
                AgentLifecycleState.ADMITTED,
                AgentLifecycleState.DENIED,
            }:
                attempt = candidate
        except CoordinationStoreNotFoundError:
            pass
        context_sha256 = plan.seal.context_manifest_sha256
        assert context_sha256 is not None
        return CurrentControlSnapshot(
            task_id=task_id,
            source_task_revision=plan.seal.source_task_revision,
            task_state_sha256=plan.seal.task_state_sha256,
            autonomy_policy_sha256=plan.seal.autonomy_policy_sha256,
            tool_policy_sha256=plan.seal.tool_policy_sha256,
            context_manifest_sha256=context_sha256,
            plan_seal_sha256=plan.plan_seal_sha256,
            root_coordination_epoch=plan.seal.root_coordination_epoch,
            cancellation_generation=plan.seal.cancellation_generation,
            cancellation_requested=False,
            root_lease_active=True,
            authority_ceiling_intact=True,
            sources_current=True,
            attempt_binding=(
                None if attempt is None else AttemptRuntimeBinding.from_attempt(attempt)
            ),
            captured_at=utc_now(),
        )


@dataclass(slots=True)
class _CountingBackend:
    delegate: SubprocessWorkerBackend
    calls: int = 0
    active: int = 0
    max_active: int = 0
    lock: Lock = field(default_factory=Lock)

    @property
    def backend_id(self) -> str:
        return self.delegate.backend_id

    @property
    def profile_id(self) -> str:
        return self.delegate.profile_id

    @property
    def safety_capabilities(self) -> BackendSafetyCapabilities:
        return self.delegate.safety_capabilities

    def execute(
        self,
        *,
        request: LiveBackendRequest,
        context: FocusedContextBundle,
        policy: S4RuntimePolicy,
        cancellation_probe,
    ) -> LiveBackendResult:  # type: ignore[no-untyped-def]
        with self.lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            return self.delegate.execute(
                request=request,
                context=context,
                policy=policy,
                cancellation_probe=cancellation_probe,
            )
        finally:
            with self.lock:
                self.active -= 1


@dataclass(frozen=True, slots=True)
class _Qualifier:
    source_sha256: str

    def qualify(
        self,
        *,
        assignment: AssignmentSemanticSpec,
        cleanup_attempt: AgentExecutionAttempt,
        result: LiveBackendResult,
        receipt: AgentExecutionReceipt,
        qualified_at: datetime,
    ) -> DistilledHandoff | None:
        claims: list[ClaimRecord] = []
        for proposed in result.payload.claims:
            lineage = tuple(
                ResolvedEvidenceLineage(
                    task_id=assignment.task_id,
                    source_task_revision=assignment.source_task_revision,
                    evidence_ref=source_ref,
                    evidence_sha256=self.source_sha256,
                    source_ref=source_ref,
                    source_sha256=self.source_sha256,
                    resolution_state=EvidenceResolutionState.RESOLVED_CURRENT,
                    freshness_checked_at=qualified_at,
                    resolver_ref="root:s4-test-qualifier",
                    resolution_receipt_sha256=_digest(
                        f"resolution:{assignment.assignment_id}:{source_ref}"
                    ),
                )
                for source_ref in proposed.source_refs
            )
            claims.append(
                ClaimRecord(
                    task_id=assignment.task_id,
                    source_task_revision=assignment.source_task_revision,
                    assignment_id=assignment.assignment_id,
                    attempt_id=cleanup_attempt.attempt_id,
                    payload_id=result.payload.payload_id,
                    source_claim_key=proposed.claim_key,
                    statement=proposed.statement,
                    support_disposition=ClaimSupportDisposition.QUALIFIED,
                    evidence_lineage=lineage,
                    freshness=ClaimFreshness.CURRENT,
                    contradiction_state=ContradictionState.NONE,
                    qualification_reason="deterministic current source resolution",
                )
            )
        if not claims:
            return None
        return DistilledHandoff(
            task_id=assignment.task_id,
            source_task_revision=assignment.source_task_revision,
            assignment_id=assignment.assignment_id,
            attempt_id=cleanup_attempt.attempt_id,
            context_manifest_sha256=assignment.context_manifest_sha256,
            payload_id=result.payload.payload_id,
            payload_sha256=contract_sha256(result.payload),
            receipt_id=receipt.receipt_id,
            receipt_sha256=contract_sha256(receipt),
            qualified_claims=tuple(claims),
            assumptions=result.payload.assumptions,
            uncertainty=result.payload.uncertainty,
            conflicts=result.payload.conflicts,
            recommended_next_action=result.payload.recommended_next_action,
            created_at=qualified_at,
        )


@dataclass(frozen=True, slots=True)
class _AdmissionFixture:
    state: TaskState
    decision: AdmissionDecision
    store: SQLiteCoordinationStore
    lease: RootLeaseHandle
    content: bytes


def _admission_fixture(tmp_path: Path, *, worker_count: int) -> _AdmissionFixture:
    now = utc_now()
    deadline = now + timedelta(seconds=20)
    content = b"verified read-only context\n"
    store = SQLiteCoordinationStore(tmp_path / "coordination.sqlite3")
    lease = store.acquire_root_lease(
        TASK_ID,
        root_owner_ref=ROOT_OWNER,
        root_instance_id=ROOT_ID,
        ttl_seconds=30,
        now=now,
        idempotency_key="s4:lease",
    )
    request = "Inspect one bounded current S4 admission fixture."
    preparation = TaskPreparer().prepare(
        request=request,
        scope=TaskScope(workspace_root="C:/workspace"),
        context_candidates=(
            ContextCandidate(
                source=ContextSource.from_text(
                    kind=ContextSourceKind.USER_MESSAGE,
                    locator="user:c011-s4-admission",
                    text=request,
                    verified=True,
                ),
                required=True,
                priority=100,
            ),
        ),
        context_budget=ContextBudget(),
        required_conditions=("S4 remains bounded and read-only.",),
        forbidden_outcomes=("Worker authority expands.",),
        evidence_required=("Deterministic live receipt",),
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
    assert specification is not None and acceptance_basis is not None
    capability = GeneralCapabilitySelector().select(
        task_id=TASK_ID,
        step_id=state.plan[0].step_id,
        specification_basis_fingerprint=specification.specification_basis_fingerprint,
        acceptance_basis_fingerprint=acceptance_basis,
        decision_basis_fingerprint=_digest("decision"),
        retrieval_strategy_fingerprint=_digest("retrieval"),
        decision_control_action=DecisionControlAction.CONTINUE.value,
        retrieval_decision=RetrievalDecision.ANSWER_DIRECT.value,
        verification_depth=VerificationDepth.TARGETED.value,
        considered_tool_names=(),
    )
    source = ContextSourceReference(
        task_id=TASK_ID,
        source_task_revision=state.revision,
        source_ref="repo:src",
        source_revision="git:c011-s4-admission",
        content_sha256=sha256(content).hexdigest(),
        freshness=ContextFreshness.CURRENT,
        freshness_checked_at=now,
        redaction_state=RedactionState.NOT_REQUIRED,
        size_bytes=len(content),
    )
    snapshot = CurrentAdmissionSnapshot(
        task_state=state,
        tool_policy=ToolPolicy(),
        context_sources=(source,),
        capability_selection=capability,
        root_lease=lease.record,
        cancellation_generation=0,
        cancellation_requested=False,
        delegation_enabled=True,
    )
    per_worker_context = 0 if worker_count == 0 else 4096
    per_worker_result = 0 if worker_count == 0 else 8192
    per_worker_tokens = 0 if worker_count == 0 else 1000
    per_worker_runtime = 0 if worker_count == 0 else 5000
    budget = HierarchicalBudgetEnvelope(
        max_total_workers=worker_count,
        max_concurrent_workers=worker_count,
        delegation_depth=1,
        max_worker_context_bytes=per_worker_context,
        max_worker_result_bytes=per_worker_result,
        max_worker_tokens=per_worker_tokens,
        max_worker_runtime_ms=per_worker_runtime,
        max_total_context_bytes=4096 * worker_count,
        max_total_result_bytes=8192 * worker_count,
        max_total_tokens=1000 * worker_count,
        max_total_runtime_ms=5000 * worker_count,
        overall_deadline_at=deadline,
    )
    if worker_count == 0:
        intent = DelegationIntent(
            disposition=DelegationDisposition.NO_DELEGATION,
            assignments=(),
            source_refs=(),
            budget=budget,
        )
    else:
        worker_budget = WorkerBudgetEnvelope(
            max_context_bytes=4096,
            max_result_bytes=8192,
            max_claims=4,
            max_tokens=1000,
            max_runtime_ms=5000,
            deadline_at=deadline,
        )
        intent = DelegationIntent(
            disposition=DelegationDisposition.DELEGATE,
            assignments=tuple(
                AssignmentIntent(
                    worker_role=(
                        ParallelCognitionRole.INDEPENDENT_REVIEWER
                        if index == worker_count - 1
                        else ParallelCognitionRole.PARALLEL
                    ),
                    objective=f"Inspect independent bounded lane {index}.",
                    independent_value_basis=f"lane:{index}:independent-value",
                    source_step_sequences=(state.plan[0].sequence,),
                    budget=worker_budget,
                )
                for index in range(worker_count)
            ),
            source_refs=("repo:src",),
            budget=budget,
        )
    decision = AdmissionEngine(
        snapshot_provider=_AdmissionSnapshotProvider(snapshot),
        clock=_Clock(),
    ).admit(intent)
    assert decision.plan is not None
    return _AdmissionFixture(
        state=state,
        decision=decision,
        store=store,
        lease=lease,
        content=content,
    )


def _service(
    tmp_path: Path,
    *,
    fixture: _AdmissionFixture,
    policy: S4RuntimePolicy,
    kill_switch: RuntimeKillSwitch,
    mode: str = "success-slow",
):
    plan = fixture.decision.plan
    assert plan is not None
    provider = _FixedPlanProvider(fixture.decision, fixture.lease)
    control_provider = _CurrentControlProvider(plan, fixture.store)
    backend = _CountingBackend(_subprocess_backend(tmp_path, mode=mode))
    journal = SQLiteLiveInvocationJournal(tmp_path / "live.sqlite3")
    service = ParallelCognitionRuntimeService(
        policy=policy,
        kill_switch=kill_switch,
        plan_provider=provider,
        context_broker=FocusedContextBroker(
            provider=_MaterialProvider(fixture.content)
        ),
        backend=cast(InterruptibleWorkerBackend, backend),
        qualifier=_Qualifier(sha256(fixture.content).hexdigest()),
        control_fences=ControlFenceController(
            provider=control_provider,
            recorder=fixture.store,
            clock=_Clock(),
        ),
        reuse_fences=LiveHandoffReuseFenceController(
            provider=control_provider,
            clock=_Clock(),
            journal=journal,
        ),
        coordination_store=fixture.store,
        live_journal=journal,
    )
    return service, provider, backend, journal


def test_s4_default_off_and_dynamic_kill_switch_do_not_admit(
    tmp_path: Path,
) -> None:
    fixture = _admission_fixture(tmp_path, worker_count=1)
    disabled, disabled_provider, disabled_backend, _ = _service(
        tmp_path,
        fixture=fixture,
        policy=S4RuntimePolicy(),
        kill_switch=RuntimeKillSwitch(),
    )
    result = disabled.collect_for_root(
        state=fixture.state,
        root_owner_ref=ROOT_OWNER,
        cancellation_probe=lambda: False,
    )
    assert result.status is S4IntegrationStatus.DISABLED
    assert disabled_provider.calls == 0
    assert disabled_backend.calls == 0

    engaged = RuntimeKillSwitch()
    engaged.engage()
    killed, killed_provider, killed_backend, _ = _service(
        tmp_path,
        fixture=fixture,
        policy=_active_policy(),
        kill_switch=engaged,
    )
    result = killed.collect_for_root(
        state=fixture.state,
        root_owner_ref=ROOT_OWNER,
        cancellation_probe=lambda: False,
    )
    assert result.status is S4IntegrationStatus.KILL_SWITCHED
    assert killed_provider.calls == 0
    assert killed_backend.calls == 0


def test_s4_zero_workers_preserves_solo_path(tmp_path: Path) -> None:
    fixture = _admission_fixture(tmp_path, worker_count=0)
    service, provider, backend, _ = _service(
        tmp_path,
        fixture=fixture,
        policy=_active_policy(),
        kill_switch=RuntimeKillSwitch(),
    )

    result = service.collect_for_root(
        state=fixture.state,
        root_owner_ref=ROOT_OWNER,
        cancellation_probe=lambda: False,
    )

    assert result.status is S4IntegrationStatus.NO_DELEGATION
    assert result.handoffs == ()
    assert result.attempts == ()
    assert provider.calls == 1
    assert backend.calls == 0


def test_s4_runs_three_lanes_concurrently_reuses_receipts_and_keeps_one_voice(
    tmp_path: Path,
) -> None:
    fixture = _admission_fixture(tmp_path, worker_count=3)
    before = fixture.state.model_dump(mode="json")
    service, provider, backend, journal = _service(
        tmp_path,
        fixture=fixture,
        policy=_active_policy(),
        kill_switch=RuntimeKillSwitch(),
    )

    first = service.collect_for_root(
        state=fixture.state,
        root_owner_ref=ROOT_OWNER,
        cancellation_probe=lambda: False,
    )
    assert first.status is S4IntegrationStatus.COMPLETE, first.model_dump(mode="json")
    assert len(first.handoffs) == 3, [
        (item.outcome_state, item.reason) for item in first.attempts
    ]
    second = service.collect_for_root(
        state=fixture.state,
        root_owner_ref=ROOT_OWNER,
        cancellation_probe=lambda: False,
    )

    assert len(first.attempts) == 3
    assert len(first.consideration_receipts) == 3
    assert backend.calls == 3
    assert backend.max_active == 3
    assert all(item.user_facing_voice_authority is False for item in first.handoffs)
    assert all(item.completion_authority is False for item in first.handoffs)
    assert first.user_facing_voice_authority is False
    assert first.task_state_mutated is False
    assert fixture.state.model_dump(mode="json") == before
    assert all(item.reused_durable_result for item in second.attempts)
    assert tuple(item.handoff_id for item in second.handoffs) == tuple(
        item.handoff_id for item in first.handoffs
    )
    assert provider.calls == 2
    rendered = first.render_for_root_context()
    assert "driver:not-inherited" not in rendered
    assert "hidden_reasoning" not in rendered
    assert "The focused source was inspected." in rendered
    fixture.store.verify_integrity()
    journal.verify_integrity()
    with sqlite3_connect(journal.path) as connection:
        reuse_count = int(
            connection.execute("SELECT COUNT(*) FROM handoff_reuse_fences").fetchone()[0]
        )
        connection.execute(
            "UPDATE handoff_reuse_fences SET decision_sha256 = ? "
            "WHERE rowid = (SELECT MIN(rowid) FROM handoff_reuse_fences)",
            ("0" * 64,),
        )
        connection.commit()
    assert reuse_count == 3
    with pytest.raises(LiveInvocationIntegrityError):
        journal.verify_integrity()


@dataclass(slots=True)
class _UnsafeBackend:
    @property
    def backend_id(self) -> str:
        return "unsafe:test"

    @property
    def profile_id(self) -> str:
        return "unsafe:test"

    @property
    def safety_capabilities(self) -> BackendSafetyCapabilities:
        return BackendSafetyCapabilities(
            bounded_driver_calls=False,
            cooperative_cancellation=False,
            hard_termination=False,
            isolated_ephemeral_scratch=False,
            explicit_environment_only=False,
            shell_disabled=False,
        )

    def execute(self, **kwargs: object) -> LiveBackendResult:
        del kwargs
        raise AssertionError("unsafe backend must never execute")


def test_s4_denies_backend_without_bounded_root_liveness(tmp_path: Path) -> None:
    fixture = _admission_fixture(tmp_path, worker_count=1)
    plan = fixture.decision.plan
    assert plan is not None
    provider = _FixedPlanProvider(fixture.decision, fixture.lease)
    control_provider = _CurrentControlProvider(plan, fixture.store)
    journal = SQLiteLiveInvocationJournal(tmp_path / "live.sqlite3")
    service = ParallelCognitionRuntimeService(
        policy=_active_policy(),
        kill_switch=RuntimeKillSwitch(),
        plan_provider=provider,
        context_broker=FocusedContextBroker(
            provider=_MaterialProvider(fixture.content)
        ),
        backend=cast(InterruptibleWorkerBackend, _UnsafeBackend()),
        qualifier=_Qualifier(sha256(fixture.content).hexdigest()),
        control_fences=ControlFenceController(
            provider=control_provider,
            recorder=fixture.store,
            clock=_Clock(),
        ),
        reuse_fences=LiveHandoffReuseFenceController(
            provider=control_provider,
            clock=_Clock(),
            journal=journal,
        ),
        coordination_store=fixture.store,
        live_journal=journal,
    )

    result = service.collect_for_root(
        state=fixture.state,
        root_owner_ref=ROOT_OWNER,
        cancellation_probe=lambda: False,
    )

    assert result.status is S4IntegrationStatus.DENIED
    assert result.reason_codes == ("S4_BACKEND_SAFETY_CAPABILITIES_INCOMPLETE",)
    assert provider.calls == 0
