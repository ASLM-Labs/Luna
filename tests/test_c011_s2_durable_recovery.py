from __future__ import annotations

import ast
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest
from pydantic import ValidationError

from luna.contracts.enums import PlanStepStatus
from luna.parallel_cognition.events import (
    CoordinationEvent,
    CoordinationEventKind,
    FakeBackendRequest,
    FakeBackendResult,
    FakeBackendScript,
    RecoveryDisposition,
    RootLeaseHandle,
    RootLeaseStatus,
    validate_attempt_transition,
)
from luna.parallel_cognition.fake_backend import (
    FakeBackendInDoubt,
    SQLiteIdempotentFakeBackend,
)
from luna.parallel_cognition.models import (
    AgentExecutionAttempt,
    AgentLifecycleState,
    AgentPayload,
    AssignmentSemanticSpec,
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
from luna.parallel_cognition.store import (
    COORDINATION_STORE_SCHEMA_VERSION,
    CoordinationStoreConflictError,
    CoordinationStoreError,
    CoordinationStoreIntegrityError,
    CoordinationStoreLeaseError,
    SQLiteCoordinationStore,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_ID = UUID("11000000-0000-4000-8000-000000000011")
OTHER_TASK_ID = UUID("22000000-0000-4000-8000-000000000022")
ROOT_INSTANCE_ID = UUID("33000000-0000-4000-8000-000000000033")
OTHER_ROOT_INSTANCE_ID = UUID("44000000-0000-4000-8000-000000000044")
STEP_ID = UUID("55000000-0000-4000-8000-000000000055")
NOW = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
CREATED_AT = NOW + timedelta(seconds=1)
STARTED_AT = NOW + timedelta(seconds=4)
REQUESTED_AT = NOW + timedelta(seconds=5)
OUTCOME_AT = NOW + timedelta(seconds=6)
CLEANUP_AT = NOW + timedelta(seconds=7)
DEADLINE = NOW + timedelta(minutes=5)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


@dataclass(frozen=True, slots=True)
class _Contracts:
    context: ReadOnlyContextManifest
    assignment: AssignmentSemanticSpec


def _contracts(*, epoch: int = 1) -> _Contracts:
    source = ContextSourceReference(
        task_id=TASK_ID,
        source_task_revision=7,
        source_ref="repo:src",
        source_revision="git:c011-s2-fixture",
        content_sha256=SHA_A,
        freshness=ContextFreshness.CURRENT,
        freshness_checked_at=NOW - timedelta(seconds=1),
        redaction_state=RedactionState.REDACTED,
        size_bytes=32,
    )
    context = ReadOnlyContextManifest(
        task_id=TASK_ID,
        source_task_revision=7,
        sources=(source,),
        total_size_bytes=32,
        created_at=NOW,
        expires_at=DEADLINE,
    )
    step = SourceStepSemantics(
        step_id=STEP_ID,
        sequence=1,
        description="Inspect one deterministic read-only lane.",
        status=PlanStepStatus.PENDING,
        source_step_payload_sha256=SHA_B,
    )
    budget = WorkerBudgetEnvelope(
        max_context_bytes=1024,
        max_result_bytes=20_000,
        max_claims=4,
        max_tokens=1000,
        max_runtime_ms=60_000,
        deadline_at=DEADLINE,
    )
    assignment = AssignmentSemanticSpec(
        task_id=TASK_ID,
        source_task_revision=7,
        task_contract_sha256=SHA_C,
        source_steps=(step,),
        acceptance_basis_sha256=SHA_D,
        acceptance_target_refs=("target:s2",),
        context_manifest_sha256=contract_sha256(context),
        autonomy_policy_sha256=SHA_E,
        tool_policy_sha256=SHA_F,
        worker_role=ParallelCognitionRole.PARALLEL,
        objective="Return one bounded deterministic fixture payload.",
        granted_source_refs=("repo:src",),
        capability_selection_basis_sha256=SHA_A,
        root_coordination_epoch=epoch,
        budget=budget,
    )
    return _Contracts(context=context, assignment=assignment)


def _attempt(
    contracts: _Contracts,
    state: AgentLifecycleState,
    *,
    attempt_id: str = "attempt:s2-lane-1",
) -> AgentExecutionAttempt:
    precreation = {
        AgentLifecycleState.PROPOSED,
        AgentLifecycleState.ADMITTED,
        AgentLifecycleState.DENIED,
    }
    provisioned = state not in precreation
    started = provisioned and state is not AgentLifecycleState.CREATED
    return AgentExecutionAttempt(
        attempt_id=attempt_id,
        task_id=TASK_ID,
        source_task_revision=7,
        assignment_id=contracts.assignment.assignment_id,
        context_manifest_sha256=contract_sha256(contracts.context),
        runtime_session_id="session:s2-lane-1" if provisioned else None,
        backend_id="fake:c011-s2" if provisioned else None,
        profile_id="profile:deterministic" if provisioned else None,
        root_coordination_epoch=contracts.assignment.root_coordination_epoch,
        cancellation_epoch=0,
        created_at=CREATED_AT,
        started_at=STARTED_AT if started else None,
        deadline_at=DEADLINE,
        isolation=(
            IsolationReferences(
                process_ref="isolation:process:none",
                session_ref="isolation:session:fixture",
                context_ref="isolation:context:fixture",
            )
            if provisioned
            else None
        ),
        lifecycle_state=state,
        display_name="S2 Fixture Lane",
    )


def _payload(contracts: _Contracts, *, attempt_id: str) -> AgentPayload:
    claim = ProposedClaim(
        claim_key="claim:s2-one",
        statement="The deterministic fixture was observed.",
        source_refs=("repo:src",),
    )
    return AgentPayload(
        task_id=TASK_ID,
        source_task_revision=7,
        assignment_id=contracts.assignment.assignment_id,
        attempt_id=attempt_id,
        context_manifest_sha256=contract_sha256(contracts.context),
        summary="One deterministic fixture result.",
        claims=(claim,),
        cited_source_refs=("repo:src",),
        assumptions=("This is an isolated fake-backend fixture.",),
        uncertainty=("No live worker execution is represented.",),
        recommended_next_action="Keep the result quarantined for root review.",
    )


def _script(contracts: _Contracts, *, attempt_id: str) -> FakeBackendScript:
    return FakeBackendScript(
        payload=_payload(contracts, attempt_id=attempt_id),
        outcome_state=AgentLifecycleState.RESULT_RECEIVED,
        cleanup_state=CleanupState.CLEANUP_COMPLETE,
        outcome_at=OUTCOME_AT,
        cleanup_at=CLEANUP_AT,
        tokens=17,
        runtime_ms=1000,
    )


def _request(
    contracts: _Contracts,
    attempt: AgentExecutionAttempt,
    script: FakeBackendScript,
) -> FakeBackendRequest:
    return FakeBackendRequest(
        assignment=contracts.assignment,
        attempt=attempt,
        context=contracts.context,
        script_sha256=contract_sha256(script),
        requested_at=REQUESTED_AT,
    )


def _acquire(
    store: SQLiteCoordinationStore,
    *,
    task_id: UUID = TASK_ID,
    root_instance_id: UUID = ROOT_INSTANCE_ID,
    now: datetime = NOW,
    ttl_seconds: float = 120.0,
    key: str = "lease:acquire:one",
) -> RootLeaseHandle:
    return store.acquire_root_lease(
        task_id,
        "root:owner",
        root_instance_id=root_instance_id,
        ttl_seconds=ttl_seconds,
        now=now,
        idempotency_key=key,
    )


def _record_to_started(
    store: SQLiteCoordinationStore,
    lease: RootLeaseHandle,
    contracts: _Contracts,
    *,
    key_prefix: str = "lane",
) -> AgentExecutionAttempt:
    states_and_times = (
        (AgentLifecycleState.PROPOSED, NOW + timedelta(seconds=1)),
        (AgentLifecycleState.ADMITTED, NOW + timedelta(seconds=2)),
        (AgentLifecycleState.CREATED, NOW + timedelta(seconds=3)),
        (AgentLifecycleState.STARTED, STARTED_AT),
    )
    current: AgentExecutionAttempt | None = None
    for sequence, (state, occurred_at) in enumerate(states_and_times, start=1):
        current = _attempt(contracts, state)
        store.record_attempt_transition(
            lease,
            current,
            idempotency_key=f"{key_prefix}:state:{sequence}",
            occurred_at=occurred_at,
        )
    assert current is not None
    return current


def test_coordination_and_fake_schema_use_wal(tmp_path: Path) -> None:
    coordination_path = tmp_path / "c.db"
    fake_path = tmp_path / "f.db"
    store = SQLiteCoordinationStore(coordination_path)
    backend = SQLiteIdempotentFakeBackend(fake_path)

    assert store.journal_mode() == "wal"
    assert backend.journal_mode() == "wal"
    with sqlite3.connect(coordination_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (
            COORDINATION_STORE_SCHEMA_VERSION,
        )
        fake_invocation_foreign_keys = {
            str(row[3])
            for row in connection.execute(
                "PRAGMA foreign_key_list(fake_invocations)"
            ).fetchall()
        }
        assert {
            "attempt_id",
            "start_event_id",
            "result_event_id",
            "receipt_event_id",
        }.issubset(fake_invocation_foreign_keys)
    with sqlite3.connect(fake_path) as connection:
        assert connection.execute("PRAGMA synchronous").fetchone() == (2,)


def test_lease_renew_release_expiry_epoch_and_old_token_fencing(
    tmp_path: Path,
) -> None:
    store = SQLiteCoordinationStore(tmp_path / "c.db")
    first = _acquire(store, ttl_seconds=10)

    assert first.token not in repr(first)
    assert first.token not in first.record.model_dump_json()
    with pytest.raises(CoordinationStoreLeaseError):
        _acquire(store, ttl_seconds=10)
    renewed = store.renew_root_lease(
        first,
        ttl_seconds=30,
        now=NOW + timedelta(seconds=1),
        idempotency_key="lease:renew:one",
    )
    assert renewed.record.epoch == first.record.epoch == 1
    assert renewed.record.lease_version == first.record.lease_version + 1
    assert renewed.token != first.token
    assert (
        store.renew_root_lease(
            first,
            ttl_seconds=30,
            now=NOW + timedelta(seconds=1),
            idempotency_key="lease:renew:one",
        )
        == renewed
    )
    forged_token = "attacker-controlled-token"
    forged_record = first.record.model_copy(
        update={"token_sha256": sha256(forged_token.encode("utf-8")).hexdigest()}
    )
    forged_handle = RootLeaseHandle(record=forged_record, token=forged_token)
    with pytest.raises(CoordinationStoreLeaseError):
        store.renew_root_lease(
            forged_handle,
            ttl_seconds=30,
            now=NOW + timedelta(seconds=1),
            idempotency_key="lease:renew:one",
        )
    wrong_token_handle = object.__new__(RootLeaseHandle)
    object.__setattr__(wrong_token_handle, "record", first.record)
    object.__setattr__(wrong_token_handle, "token", "wrong-prior-token")
    with pytest.raises(CoordinationStoreLeaseError):
        store.renew_root_lease(
            wrong_token_handle,
            ttl_seconds=30,
            now=NOW + timedelta(seconds=1),
            idempotency_key="lease:renew:one",
        )
    with pytest.raises(CoordinationStoreLeaseError):
        store.record_attempt_transition(
            first,
            _attempt(_contracts(), AgentLifecycleState.PROPOSED),
            idempotency_key="old-token:denied",
            occurred_at=NOW + timedelta(seconds=2),
        )

    third = store.renew_root_lease(
        renewed,
        ttl_seconds=60,
        now=NOW + timedelta(seconds=2),
        idempotency_key="lease:renew:two",
    )
    assert third.record.lease_version == renewed.record.lease_version + 1
    with pytest.raises(CoordinationStoreLeaseError):
        _acquire(store, ttl_seconds=10)
    with pytest.raises(CoordinationStoreLeaseError):
        store.renew_root_lease(
            first,
            ttl_seconds=30,
            now=NOW + timedelta(seconds=1),
            idempotency_key="lease:renew:one",
        )

    released = store.release_root_lease(
        third,
        now=NOW + timedelta(seconds=3),
        idempotency_key="lease:release:one",
    )
    assert released.status is RootLeaseStatus.RELEASED
    assert store.current_root_lease(TASK_ID) == released
    with pytest.raises(CoordinationStoreLeaseError):
        store.renew_root_lease(
            third,
            ttl_seconds=90,
            now=NOW + timedelta(seconds=4),
        )

    expiring = _acquire(
        store,
        task_id=OTHER_TASK_ID,
        root_instance_id=ROOT_INSTANCE_ID,
        ttl_seconds=2,
        key="lease:expiring",
    )
    takeover = _acquire(
        store,
        task_id=OTHER_TASK_ID,
        root_instance_id=OTHER_ROOT_INSTANCE_ID,
        now=NOW + timedelta(seconds=3),
        key="lease:takeover",
    )
    assert takeover.record.epoch == expiring.record.epoch + 1
    assert [event.kind for event in store.events_for_task(OTHER_TASK_ID)] == [
        CoordinationEventKind.ROOT_LEASE_ACQUIRED,
        CoordinationEventKind.ROOT_LEASE_EXPIRED,
        CoordinationEventKind.ROOT_LEASE_ACQUIRED,
    ]
    with pytest.raises(CoordinationStoreLeaseError):
        store.renew_root_lease(
            expiring,
            ttl_seconds=30,
            now=NOW + timedelta(seconds=4),
        )


def test_competing_root_lease_has_one_winner_without_sleep(tmp_path: Path) -> None:
    database = tmp_path / "c.db"
    first_store = SQLiteCoordinationStore(database)
    second_store = SQLiteCoordinationStore(database)
    barrier = Barrier(2)

    def compete(
        store: SQLiteCoordinationStore,
        instance_id: UUID,
        key: str,
    ) -> tuple[str, RootLeaseHandle | None]:
        barrier.wait()
        try:
            handle = _acquire(
                store,
                root_instance_id=instance_id,
                key=key,
            )
        except CoordinationStoreConflictError:
            return ("lost", None)
        return ("won", handle)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(compete, first_store, ROOT_INSTANCE_ID, "race:first"),
            pool.submit(compete, second_store, OTHER_ROOT_INSTANCE_ID, "race:second"),
        )
        outcomes = tuple(future.result() for future in futures)

    assert [outcome for outcome, _ in outcomes].count("won") == 1
    assert [outcome for outcome, _ in outcomes].count("lost") == 1
    assert SQLiteCoordinationStore(database).current_root_lease(TASK_ID).status is (
        RootLeaseStatus.ACTIVE
    )


def test_event_idempotency_conflict_default_deny_and_legal_path(
    tmp_path: Path,
) -> None:
    store = SQLiteCoordinationStore(tmp_path / "c.db")
    lease = _acquire(store)
    contracts = _contracts()
    proposed = _attempt(contracts, AgentLifecycleState.PROPOSED)
    first = store.record_attempt_transition(
        lease,
        proposed,
        idempotency_key="attempt:proposed",
        occurred_at=NOW + timedelta(seconds=1),
    )
    repeated = store.record_attempt_transition(
        lease,
        proposed,
        idempotency_key="attempt:proposed",
        occurred_at=NOW + timedelta(seconds=1),
    )
    assert repeated == first
    assert first.runtime_authored is True
    assert first.event_sha256

    with pytest.raises(CoordinationStoreConflictError):
        store.record_attempt_transition(
            lease,
            _attempt(contracts, AgentLifecycleState.ADMITTED),
            idempotency_key="attempt:proposed",
            occurred_at=NOW + timedelta(seconds=2),
        )
    with pytest.raises(CoordinationStoreConflictError, match="PROPOSED->STARTED"):
        store.record_attempt_transition(
            lease,
            _attempt(contracts, AgentLifecycleState.STARTED),
            idempotency_key="attempt:illegal-start",
            occurred_at=NOW + timedelta(seconds=2),
        )

    for sequence, state in enumerate(
        (
            AgentLifecycleState.ADMITTED,
            AgentLifecycleState.CREATED,
            AgentLifecycleState.STARTED,
        ),
        start=2,
    ):
        store.record_attempt_transition(
            lease,
            _attempt(contracts, state),
            idempotency_key=f"attempt:legal:{sequence}",
            occurred_at=NOW + timedelta(seconds=sequence),
        )
    assert store.load_attempt(proposed.attempt_id).lifecycle_state is (
        AgentLifecycleState.STARTED
    )
    events = store.events_for_task(TASK_ID)
    assert tuple(event.task_sequence for event in events) == tuple(
        range(1, len(events) + 1)
    )
    assert events[0].previous_event_sha256 is None
    assert all(
        current.previous_event_sha256 == previous.event_sha256
        for previous, current in pairwise(events)
    )

    tampered = first.model_dump(mode="json")
    tampered["event_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="event_sha256"):
        CoordinationEvent.model_validate(tampered)


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    (
        (AgentLifecycleState.PROPOSED, AgentLifecycleState.CANCEL_REQUESTED),
        (AgentLifecycleState.CREATED, AgentLifecycleState.FAILED),
        (AgentLifecycleState.CANCEL_REQUESTED, AgentLifecycleState.RESULT_RECEIVED),
        (AgentLifecycleState.CLOSED, AgentLifecycleState.PROPOSED),
    ),
)
def test_ambiguous_or_backward_transition_is_default_denied(
    from_state: AgentLifecycleState,
    to_state: AgentLifecycleState,
) -> None:
    with pytest.raises(ValueError, match="unsupported C-011 attempt transition"):
        validate_attempt_transition(from_state, to_state)


def test_fake_backend_reopen_returns_cached_result_and_reserved_is_in_doubt(
    tmp_path: Path,
) -> None:
    contracts = _contracts()
    started = _attempt(contracts, AgentLifecycleState.STARTED)
    script = _script(contracts, attempt_id=started.attempt_id)
    request = _request(contracts, started, script)
    database = tmp_path / "f.db"
    backend = SQLiteIdempotentFakeBackend(database)

    result = backend.execute(request, script, idempotency_key="fake:complete")
    assert backend.durable_completion_count() == 1
    reopened = SQLiteIdempotentFakeBackend(database)
    assert reopened.execute(request, script, idempotency_key="fake:complete") == result
    assert reopened.durable_completion_count() == 1
    assert reopened.verify_integrity()

    reserved = reopened.reserve(request, idempotency_key="fake:reserved")
    assert reserved.durable_completion_count == 0
    with pytest.raises(FakeBackendInDoubt, match="replay denied"):
        reopened.execute(request, script, idempotency_key="fake:reserved")
    assert reopened.durable_completion_count() == 1


def test_store_authors_receipt_and_reopen_resolves_every_event_ref(
    tmp_path: Path,
) -> None:
    coordination_path = tmp_path / "c.db"
    fake_path = tmp_path / "f.db"
    store = SQLiteCoordinationStore(coordination_path)
    lease = _acquire(store)
    contracts = _contracts()
    started = _record_to_started(store, lease, contracts)
    script = _script(contracts, attempt_id=started.attempt_id)
    request = _request(contracts, started, script)
    store.start_fake_invocation(
        lease,
        request,
        idempotency_key="coordination:fake:start",
        occurred_at=REQUESTED_AT,
    )
    backend = SQLiteIdempotentFakeBackend(fake_path)
    result = backend.execute(request, script, idempotency_key="backend:dispatch")
    assert isinstance(result, FakeBackendResult)
    completed = store.record_fake_result(
        lease,
        result,
        idempotency_key="coordination:fake:result",
        occurred_at=CLEANUP_AT,
    )
    assert completed.durable_completion_count == 1
    events_before_finalize = store.events_for_attempt(started.attempt_id)
    assert store.load_attempt(started.attempt_id).lifecycle_state is (
        AgentLifecycleState.STARTED
    )
    receipt = store.finalize_fake_execution(
        lease,
        started.attempt_id,
        idempotency_key="coordination:fake:receipt",
        occurred_at=CLEANUP_AT + timedelta(milliseconds=2),
    )

    events = store.events_for_attempt(started.attempt_id)
    event_refs = {event.event_ref for event in events}
    assert receipt.event_refs
    assert receipt.event_refs == tuple(
        sorted(event.event_ref for event in events[:-1])
    )
    assert set(receipt.event_refs) == event_refs - {events[-1].event_ref}
    assert events[len(events_before_finalize) :] == events[-3:]
    assert [event.kind for event in events[-3:]] == [
        CoordinationEventKind.ATTEMPT_TRANSITION,
        CoordinationEventKind.ATTEMPT_TRANSITION,
        CoordinationEventKind.EXECUTION_RECEIPT_RECORDED,
    ]
    assert [event.to_state for event in events[-3:-1]] == [
        AgentLifecycleState.RESULT_RECEIVED,
        AgentLifecycleState.CLEANUP_COMPLETE,
    ]
    assert store.load_attempt(started.attempt_id).lifecycle_state is (
        AgentLifecycleState.CLEANUP_COMPLETE
    )
    assert events[-1].artifact_ref == receipt.receipt_id
    assert events[-1].artifact_sha256 == contract_sha256(receipt)
    assert (
        store.finalize_fake_execution(
            lease,
            started.attempt_id,
            idempotency_key="coordination:fake:receipt",
            occurred_at=CLEANUP_AT + timedelta(milliseconds=2),
        )
        == receipt
    )
    assert store.events_for_attempt(started.attempt_id) == events
    assert store.load_payload(started.attempt_id) == script.payload
    assert store.load_execution_receipt(receipt.receipt_id) == receipt
    recovery = store.inspect_attempt(
        lease,
        started.attempt_id,
        idempotency_key="recovery:receipt",
        decided_at=CLEANUP_AT + timedelta(milliseconds=3),
    )
    assert recovery.disposition is RecoveryDisposition.RECEIPT_REUSED
    assert recovery.receipt_ref == receipt.receipt_id

    reopened_store = SQLiteCoordinationStore(coordination_path)
    reopened_backend = SQLiteIdempotentFakeBackend(fake_path)
    assert reopened_store.load_execution_receipt(started.attempt_id) == receipt
    assert reopened_backend.execute(
        request,
        script,
        idempotency_key="backend:dispatch",
    ) == result
    assert reopened_backend.durable_completion_count() == 1
    reopened_store.verify_integrity()


def test_started_or_reserved_crash_is_inspected_without_replay(tmp_path: Path) -> None:
    store = SQLiteCoordinationStore(tmp_path / "c.db")
    lease = _acquire(store)
    contracts = _contracts()
    started = _record_to_started(store, lease, contracts)
    script = _script(contracts, attempt_id=started.attempt_id)
    request = _request(contracts, started, script)
    store.start_fake_invocation(
        lease,
        request,
        idempotency_key="crash:reserved",
        occurred_at=REQUESTED_AT,
    )

    recovery = store.inspect_attempt(
        lease,
        started.attempt_id,
        idempotency_key="crash:inspect",
        decided_at=REQUESTED_AT + timedelta(milliseconds=1),
    )
    repeated = store.inspect_attempt(
        lease,
        started.attempt_id,
        idempotency_key="crash:inspect",
        decided_at=REQUESTED_AT + timedelta(milliseconds=2),
    )
    assert recovery.disposition is RecoveryDisposition.NO_REPLAY
    assert repeated == recovery
    assert recovery.receipt_ref is None
    assert "ambiguous" in recovery.reason
    assert all(
        member.value != "REPLAY" and "BLIND_REPLAY" not in member.value
        for member in RecoveryDisposition
    )


def test_durable_result_can_be_finalized_without_backend_execute(tmp_path: Path) -> None:
    store = SQLiteCoordinationStore(tmp_path / "c.db")
    lease = _acquire(store)
    contracts = _contracts()
    started = _record_to_started(store, lease, contracts)
    script = _script(contracts, attempt_id=started.attempt_id)
    request = _request(contracts, started, script)
    store.start_fake_invocation(
        lease,
        request,
        idempotency_key="manual:start",
        occurred_at=REQUESTED_AT,
    )
    result = FakeBackendResult.from_request_script(
        request,
        script,
        backend_id="fake:c011-s2",
        profile_id="profile:deterministic",
    )
    store.record_fake_result(
        lease,
        result,
        idempotency_key="manual:result",
        occurred_at=CLEANUP_AT,
    )
    recovery = store.inspect_attempt(
        lease,
        started.attempt_id,
        idempotency_key="manual:inspect",
        decided_at=CLEANUP_AT + timedelta(milliseconds=1),
    )
    assert recovery.disposition is RecoveryDisposition.MANUAL_RECONCILIATION

    receipt = store.finalize_fake_execution(
        lease,
        started.attempt_id,
        idempotency_key="manual:receipt",
        occurred_at=CLEANUP_AT + timedelta(milliseconds=2),
    )
    assert (
        store.inspect_attempt(
            lease,
            started.attempt_id,
            idempotency_key="manual:inspect",
            decided_at=CLEANUP_AT + timedelta(milliseconds=3),
        )
        == recovery
    )
    refreshed = store.inspect_attempt(
        lease,
        started.attempt_id,
        idempotency_key="manual:inspect:after-receipt",
        decided_at=CLEANUP_AT + timedelta(milliseconds=4),
    )
    assert refreshed.disposition is RecoveryDisposition.RECEIPT_REUSED
    assert refreshed.receipt_ref == receipt.receipt_id
    assert receipt.payload_id == script.payload.payload_id
    assert store.load_attempt(started.attempt_id).lifecycle_state is (
        AgentLifecycleState.CLEANUP_COMPLETE
    )
    assert not (tmp_path / "f.db").exists()


def test_finalize_rolls_back_generated_outcome_cleanup_and_receipt_together(
    tmp_path: Path,
) -> None:
    database = tmp_path / "c.db"
    store = SQLiteCoordinationStore(database)
    lease = _acquire(store)
    contracts = _contracts()
    started = _record_to_started(store, lease, contracts)
    script = _script(contracts, attempt_id=started.attempt_id)
    request = _request(contracts, started, script)
    store.start_fake_invocation(
        lease,
        request,
        idempotency_key="rollback:start",
        occurred_at=REQUESTED_AT,
    )
    result = FakeBackendResult.from_request_script(
        request,
        script,
        backend_id="fake:c011-s2",
        profile_id="profile:deterministic",
    )
    store.record_fake_result(
        lease,
        result,
        idempotency_key="rollback:result",
        occurred_at=CLEANUP_AT,
    )
    events_before_finalize = store.events_for_attempt(started.attempt_id)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_s2_receipt
            BEFORE INSERT ON coordination_events
            WHEN NEW.kind = 'EXECUTION_RECEIPT_RECORDED'
            BEGIN
                SELECT RAISE(ABORT, 'forced receipt failure');
            END
            """
        )
        connection.commit()

    with pytest.raises(CoordinationStoreError):
        store.finalize_fake_execution(
            lease,
            started.attempt_id,
            idempotency_key="rollback:receipt",
            occurred_at=CLEANUP_AT + timedelta(milliseconds=2),
        )

    reopened = SQLiteCoordinationStore(database)
    assert reopened.events_for_attempt(started.attempt_id) == events_before_finalize
    assert reopened.load_attempt(started.attempt_id).lifecycle_state is (
        AgentLifecycleState.STARTED
    )
    with pytest.raises(CoordinationStoreError, match="receipt was not found"):
        reopened.load_execution_receipt(started.attempt_id)
    reopened.verify_integrity()

    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER reject_s2_receipt")
        connection.commit()

    receipt = store.finalize_fake_execution(
        lease,
        started.attempt_id,
        idempotency_key="rollback:receipt",
        occurred_at=CLEANUP_AT + timedelta(milliseconds=2),
    )
    reopened_after_retry = SQLiteCoordinationStore(database)
    assert reopened_after_retry.load_execution_receipt(receipt.receipt_id) == receipt
    assert [
        event.kind
        for event in reopened_after_retry.events_for_attempt(started.attempt_id)[-3:]
    ] == [
        CoordinationEventKind.ATTEMPT_TRANSITION,
        CoordinationEventKind.ATTEMPT_TRANSITION,
        CoordinationEventKind.EXECUTION_RECEIPT_RECORDED,
    ]


@pytest.mark.parametrize(
    "mutation",
    ("event", "event_head", "lease_head", "attempt_head"),
)
def test_tamper_and_projection_corruption_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    database = tmp_path / "c.db"
    store = SQLiteCoordinationStore(database)
    lease = _acquire(store)
    store.record_attempt_transition(
        lease,
        _attempt(_contracts(), AgentLifecycleState.PROPOSED),
        idempotency_key="tamper:attempt",
        occurred_at=NOW + timedelta(seconds=1),
    )
    store.verify_integrity()

    with sqlite3.connect(database) as connection:
        if mutation == "event":
            connection.execute(
                "UPDATE coordination_events SET event_sha256 = ? "
                "WHERE task_sequence = 1",
                ("0" * 64,),
            )
        elif mutation == "event_head":
            connection.execute(
                "UPDATE coordination_event_heads SET event_sha256 = ?",
                ("0" * 64,),
            )
        elif mutation == "lease_head":
            connection.execute(
                "UPDATE root_lease_heads SET record_sha256 = ?",
                ("0" * 64,),
            )
        else:
            connection.execute(
                "UPDATE attempt_heads SET lifecycle_state = 'FAILED'"
            )
        connection.commit()

    with pytest.raises(CoordinationStoreIntegrityError):
        store.verify_integrity()


def test_future_coordination_schema_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "c.db"
    SQLiteCoordinationStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"PRAGMA user_version = {COORDINATION_STORE_SCHEMA_VERSION + 1}"
        )
    with pytest.raises(CoordinationStoreError, match=r"unsupported.*schema"):
        SQLiteCoordinationStore(database)


def test_s2_remains_isolated_and_all_worker_authority_is_false() -> None:
    contracts = _contracts()
    started = _attempt(contracts, AgentLifecycleState.STARTED)
    script = _script(contracts, attempt_id=started.attempt_id)
    request = _request(contracts, started, script)
    authority_fields = (
        "write_authority",
        "network_authority",
        "process_authority",
        "tool_authority",
        "external_action_authority",
        "delegation_authority",
        "memory_commit_authority",
        "state_mutation_authority",
        "completion_authority",
        "user_facing_voice_authority",
    )
    for contract in (
        contracts.context,
        contracts.assignment,
        started,
        script.payload,
        request,
    ):
        for field_name in authority_fields:
            if hasattr(contract, field_name):
                assert getattr(contract, field_name) is False

    forbidden_import_roots = {
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
        "luna.modeling",
        "luna.runtime",
        "luna.tools",
    }
    for relative_path in (
        "src/luna/parallel_cognition/events.py",
        "src/luna/parallel_cognition/fake_backend.py",
        "src/luna/parallel_cognition/store.py",
    ):
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert not any(
            imported_name == forbidden
            or imported_name.startswith(f"{forbidden}.")
            for imported_name in imported
            for forbidden in forbidden_import_roots
        )

    runtime_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "src" / "luna" / "runtime").rglob("*.py")
    )
    assert "parallel_cognition" not in runtime_sources
    facade = (
        PROJECT_ROOT / "src" / "luna" / "parallel_cognition" / "__init__.py"
    ).read_text(encoding="utf-8")
    assert "SQLiteCoordinationStore" not in facade
    assert "SQLiteIdempotentFakeBackend" not in facade
