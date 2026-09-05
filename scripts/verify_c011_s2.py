"""Deterministic RFC-C011 S2 durable-event and recovery gate."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.capabilities import (  # noqa: E402
    CapabilityStatus,
    build_canonical_capability_registry,
)
from luna.contracts.enums import PlanStepStatus  # noqa: E402
from luna.parallel_cognition.events import (  # noqa: E402
    CoordinationEvent,
    CoordinationEventKind,
    FakeBackendRequest,
    FakeBackendScript,
    FakeInvocationState,
    RecoveryDisposition,
    RootLeaseHandle,
)
from luna.parallel_cognition.fake_backend import (  # noqa: E402
    FakeBackendInDoubt,
    SQLiteIdempotentFakeBackend,
)
from luna.parallel_cognition.models import (  # noqa: E402
    AgentExecutionAttempt,
    AgentLifecycleState,
    AgentPayload,
    AssignmentSemanticSpec,
    CleanupState,
    ContextFreshness,
    ContextSourceReference,
    IsolationReferences,
    ParallelCognitionRole,
    ReadOnlyContextManifest,
    RedactionState,
    SourceStepSemantics,
    WorkerBudgetEnvelope,
    contract_sha256,
)
from luna.parallel_cognition.store import (  # noqa: E402
    CoordinationStoreConflictError,
    CoordinationStoreLeaseError,
    SQLiteCoordinationStore,
)

REQUIRED_FILES = (
    "src/luna/parallel_cognition/__init__.py",
    "src/luna/parallel_cognition/models.py",
    "src/luna/parallel_cognition/events.py",
    "src/luna/parallel_cognition/store.py",
    "src/luna/parallel_cognition/fake_backend.py",
    "tests/test_c011_s2_durable_recovery.py",
    "scripts/verify_c011_s2.py",
    "c011_s2_verification.json",
    "docs/C011_S2_DURABLE_EVENT_RECOVERY_REPORT.md",
    "docs/C011_S2_UPDATE_MANIFEST.json",
    "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
)

DECLARED_SCOPE_FILES = frozenset(
    {
        "LUNA_HANDOFF.md",
        "MANIFEST.json",
        "SHA256SUMS.txt",
        "c011_s2_verification.json",
        "docs/C011_S2_DURABLE_EVENT_RECOVERY_REPORT.md",
        "docs/C011_S2_UPDATE_MANIFEST.json",
        "docs/LUNA_ROADMAP.md",
        "docs/NEURAL_NATIVE_BRIDGE_UPDATE_MANIFEST.json",
        "docs/NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json",
        "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        "scripts/check.bat",
        "scripts/verify_c011_s2.py",
        "src/luna/parallel_cognition/__init__.py",
        "src/luna/parallel_cognition/events.py",
        "src/luna/parallel_cognition/fake_backend.py",
        "src/luna/parallel_cognition/store.py",
        "tests/test_c011_s2_durable_recovery.py",
        "tests/test_project_metadata.py",
    }
)

S2_READY = "C011_S2_READY_FOR_FINAL_GATE"
S2_ACCEPTED = "C011_S2_DURABLE_RECOVERY_ACCEPTED"
S2_HISTORICAL_BLOCK = "C011_S2_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION"
S3_BLOCK = "C011_S3_BLOCKED_PENDING_SEPARATE_OWNER_AUTHORIZATION"
NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
TASK_ID = UUID("11111111-1111-4111-8111-111111111111")
STEP_ID = UUID("22222222-2222-4222-8222-222222222222")


def _canonical_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _metadata_integrity() -> bool:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("phase") != "19F":
        return False
    if manifest.get("capability") != "C-007":
        return False
    if manifest.get("capability_status") != "IMPLEMENTED_UNVERIFIED":
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    if manifest.get("metadata_scope") != "release_artifact_allowlist_v2":
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False

    sums: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            return False
        digest, relative = line.split("  ", 1)
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            return False
        sums[relative] = digest
    if set(sums) != set(files):
        return False

    for relative, metadata in files.items():
        if not isinstance(relative, str) or not isinstance(metadata, dict):
            return False
        path = ROOT / relative
        if not path.is_file():
            return False
        canonical = _canonical_bytes(path)
        digest = sha256(canonical).hexdigest()
        if metadata.get("sha256") != digest:
            return False
        if metadata.get("size_bytes") != len(canonical):
            return False
        if sums.get(relative) != digest:
            return False
    return True


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _package_and_runtime_boundaries() -> tuple[bool, bool]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project.get("project", {}).get("dependencies")
    dependency_boundary = dependencies == ["pydantic>=2.12,<3"]

    forbidden_roots = {
        "aiohttp",
        "http",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    forbidden_luna_prefixes = (
        "luna.agents",
        "luna.cli",
        "luna.desktop",
        "luna.neural",
        "luna.operations",
        "luna.runtime",
        "luna.tools",
    )
    package_root = ROOT / "src" / "luna" / "parallel_cognition"
    s2_boundary_files = (
        package_root / "models.py",
        package_root / "events.py",
        package_root / "store.py",
        package_root / "fake_backend.py",
    )
    package_imports = set().union(
        *(_imported_modules(path) for path in s2_boundary_files)
    )
    isolated_package = all(
        module.split(".", 1)[0] not in forbidden_roots
        and not module.startswith(forbidden_luna_prefixes)
        for module in package_imports
    )
    runtime_paths = tuple((ROOT / "src" / "luna" / "runtime").glob("*.py"))
    runtime_imports = set().union(*(_imported_modules(path) for path in runtime_paths))
    no_production_wiring = all(
        not module.startswith("luna.parallel_cognition") for module in runtime_imports
    ) and all(
        "parallel_cognition" not in path.read_text(encoding="utf-8")
        for path in runtime_paths
    )
    return dependency_boundary and isolated_package, no_production_wiring


def _receipt_and_scoped_metadata_truth() -> bool:
    receipt = json.loads(
        (ROOT / "c011_s2_verification.json").read_text(encoding="utf-8")
    )
    update_manifest = json.loads(
        (ROOT / "docs" / "C011_S2_UPDATE_MANIFEST.json").read_text(encoding="utf-8")
    )
    report = (
        ROOT / "docs" / "C011_S2_DURABLE_EVENT_RECOVERY_REPORT.md"
    ).read_text(encoding="utf-8")

    stage_status = receipt.get("stage_status")
    full_gate = receipt.get("verification", {}).get("full_local_gate", {})
    manifest_status = update_manifest.get("stage_status")
    manifest_verification = update_manifest.get("verification", {})
    manifest_full_gate = manifest_verification.get("full_local_gate", {})

    def verification_matches(
        verification: object,
        *,
        expected_preflight: str,
        expected_full_gate: str,
    ) -> bool:
        if not isinstance(verification, dict):
            return False
        full = verification.get("full_local_gate", {})
        if not isinstance(full, dict):
            return False
        return bool(
            verification.get("new_s2_durable_recovery_tests", {}).get("status")
            == expected_preflight
            and verification.get(
                "targeted_s2_s1_c7_solo_metadata_suite", {}
            ).get("status")
            == expected_preflight
            and verification.get("ruff_changed_scope") == expected_preflight
            and verification.get("mypy_strict") == expected_preflight
            and full.get("status") == expected_full_gate
            and full.get("ruff") == expected_full_gate
            and full.get("mypy_strict") == expected_full_gate
        )

    stage_truth = (
        stage_status == S2_READY
        and manifest_status == S2_READY
        and full_gate.get("status") == "PENDING"
        and manifest_full_gate.get("status") == "PENDING"
        and verification_matches(
            receipt.get("verification"),
            expected_preflight="PASS",
            expected_full_gate="PENDING",
        )
        and verification_matches(
            manifest_verification,
            expected_preflight="PASS",
            expected_full_gate="PENDING",
        )
    ) or (
        stage_status == S2_ACCEPTED
        and manifest_status == S2_ACCEPTED
        and full_gate.get("status") == "PASS"
        and manifest_full_gate.get("status") == "PASS"
        and verification_matches(
            receipt.get("verification"),
            expected_preflight="PASS",
            expected_full_gate="PASS",
        )
        and verification_matches(
            manifest_verification,
            expected_preflight="PASS",
            expected_full_gate="PASS",
        )
    )
    durable_properties = receipt.get("durable_properties")
    expected_properties = {
        "store_issued_event_sequence": True,
        "append_only_hash_chain": True,
        "task_scoped_root_lease": True,
        "monotonic_coordination_epoch": True,
        "stale_epoch_fencing": True,
        "idempotent_event_append": True,
        "idempotent_fake_result_persistence": True,
        "store_authored_execution_receipt": True,
        "ambiguous_inflight_blind_replay": False,
    }
    expected_gates = {
        "research_saturation_gate": "NOT_READY",
        "target_spec": "BLOCKED",
        "controlled_execution": "NONE",
    }
    common = (
        receipt.get("capability") == "C-011"
        and receipt.get("stage") == "S2_DURABLE_EVENT_RECOVERY_CORE"
        and receipt.get("capability_status") == "QUEUED"
        and receipt.get("production_behavior_changed") is False
        and receipt.get("live_c011_execution") is False
        and receipt.get("controlled_c011_execution") is False
        and receipt.get("backend_kind") == "DETERMINISTIC_IN_PROCESS_FAKE_ONLY"
        and receipt.get("store_schema_version") == 1
        and durable_properties == expected_properties
        and receipt.get("aslm_gates") == expected_gates
        and update_manifest.get("capability") == "C-011"
        and update_manifest.get("stage") == "S2_DURABLE_EVENT_RECOVERY_CORE"
        and update_manifest.get("capability_status") == "QUEUED"
        and update_manifest.get("next_code_gate") == S3_BLOCK
        and update_manifest.get("production_behavior_changed") is False
        and update_manifest.get("controlled_c011_execution") is False
        and update_manifest.get("aslm_gates") == expected_gates
        and update_manifest.get("scope_file_count") == len(DECLARED_SCOPE_FILES)
        and isinstance(update_manifest.get("scope_files"), list)
        and set(update_manifest["scope_files"]) == DECLARED_SCOPE_FILES
        and stage_status in report
    )
    return bool(stage_truth and common)


def _governance_truth() -> bool:
    rfc = (
        ROOT / "docs" / "rfcs" / "RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md"
    ).read_text(encoding="utf-8")
    handoff = (ROOT / "LUNA_HANDOFF.md").read_text(encoding="utf-8")
    report = (
        ROOT / "docs" / "C011_S2_DURABLE_EVENT_RECOVERY_REPORT.md"
    ).read_text(encoding="utf-8")
    current_documents = (rfc, handoff, report)
    unchanged_gates = (
        "Research Saturation Gate: NOT_READY",
        "Target Spec: BLOCKED",
        "controlled execution: NONE",
    )
    return bool(
        all(S2_HISTORICAL_BLOCK in document for document in (rfc, handoff))
        and all(S3_BLOCK in document for document in current_documents)
        and all(
            marker in document
            for document in current_documents
            for marker in unchanged_gates
        )
    )


def _fake_contracts(
    *,
    attempt_id: str,
    base_time: datetime = NOW,
) -> tuple[FakeBackendRequest, FakeBackendScript]:
    deadline = base_time + timedelta(minutes=5)
    context = ReadOnlyContextManifest(
        task_id=TASK_ID,
        source_task_revision=7,
        sources=(
            ContextSourceReference(
                task_id=TASK_ID,
                source_task_revision=7,
                source_ref="repo:src",
                source_revision="git:8c82cab",
                content_sha256="a" * 64,
                freshness=ContextFreshness.CURRENT,
                freshness_checked_at=base_time - timedelta(seconds=1),
                redaction_state=RedactionState.REDACTED,
                size_bytes=10,
            ),
        ),
        total_size_bytes=10,
        created_at=base_time,
        expires_at=deadline,
    )
    assignment = AssignmentSemanticSpec(
        task_id=TASK_ID,
        source_task_revision=7,
        task_contract_sha256="b" * 64,
        source_steps=(
            SourceStepSemantics(
                step_id=STEP_ID,
                sequence=1,
                description="Verify the bounded durable S2 fixture.",
                status=PlanStepStatus.PENDING,
                source_step_payload_sha256="c" * 64,
            ),
        ),
        acceptance_basis_sha256="d" * 64,
        acceptance_target_refs=("target:s2",),
        context_manifest_sha256=contract_sha256(context),
        autonomy_policy_sha256="e" * 64,
        tool_policy_sha256="f" * 64,
        worker_role=ParallelCognitionRole.PARALLEL,
        objective="Return one deterministic read-only S2 fixture.",
        granted_source_refs=("repo:src",),
        capability_selection_basis_sha256="0" * 64,
        root_coordination_epoch=1,
        budget=WorkerBudgetEnvelope(
            max_context_bytes=100,
            max_result_bytes=10_000,
            max_claims=0,
            max_tokens=100,
            max_runtime_ms=1_000,
            deadline_at=deadline,
        ),
    )
    attempt = AgentExecutionAttempt(
        attempt_id=attempt_id,
        task_id=TASK_ID,
        source_task_revision=7,
        assignment_id=assignment.assignment_id,
        context_manifest_sha256=contract_sha256(context),
        runtime_session_id=f"session:{attempt_id.removeprefix('attempt:')}",
        backend_id="fake:c011-s2",
        profile_id="profile:deterministic",
        root_coordination_epoch=1,
        cancellation_epoch=0,
        created_at=base_time,
        started_at=base_time + timedelta(seconds=1),
        deadline_at=deadline,
        isolation=IsolationReferences(
            process_ref="isolation:in-process-fixture",
            session_ref=f"isolation:{attempt_id}:session",
            context_ref="isolation:read-only-context",
        ),
        lifecycle_state=AgentLifecycleState.STARTED,
    )
    payload = AgentPayload(
        task_id=TASK_ID,
        source_task_revision=7,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        context_manifest_sha256=contract_sha256(context),
        summary="Deterministic S2 fixture result.",
        uncertainty=("Live execution remains outside S2.",),
    )
    script = FakeBackendScript(
        payload=payload,
        outcome_state=AgentLifecycleState.RESULT_RECEIVED,
        cleanup_state=CleanupState.CLEANUP_COMPLETE,
        outcome_at=base_time + timedelta(seconds=2),
        cleanup_at=base_time + timedelta(seconds=3),
        tokens=10,
        runtime_ms=20,
    )
    request = FakeBackendRequest(
        assignment=assignment,
        attempt=attempt,
        context=context,
        script_sha256=contract_sha256(script),
        requested_at=base_time + timedelta(seconds=1),
    )
    return request, script


def _fake_backend_checks(root: Path) -> tuple[bool, bool]:
    database = root / "fake-backend.sqlite3"
    backend = SQLiteIdempotentFakeBackend(database)
    request, script = _fake_contracts(attempt_id="attempt:s2-complete")
    first = backend.execute(request, script, idempotency_key="fake:complete:1")

    reopened = SQLiteIdempotentFakeBackend(database)
    second = reopened.execute(request, script, idempotency_key="fake:complete:1")
    persisted = reopened.lookup("fake:complete:1")
    durable_idempotency = bool(
        first == second
        and persisted is not None
        and persisted.result == first
        and persisted.state is FakeInvocationState.COMPLETED
        and persisted.durable_completion_count == 1
        and reopened.durable_completion_count() == 1
        and reopened.journal_mode() == "wal"
        and reopened.verify_integrity()
    )

    ambiguous_request, ambiguous_script = _fake_contracts(
        attempt_id="attempt:s2-in-doubt"
    )
    reserved = reopened.reserve(
        ambiguous_request,
        idempotency_key="fake:in-doubt:1",
    )
    replay_denied = False
    try:
        SQLiteIdempotentFakeBackend(database).execute(
            ambiguous_request,
            ambiguous_script,
            idempotency_key="fake:in-doubt:1",
        )
    except FakeBackendInDoubt:
        replay_denied = True
    return durable_idempotency, bool(
        replay_denied
        and reserved.state is FakeInvocationState.RESERVED
        and reserved.durable_completion_count == 0
        and SQLiteIdempotentFakeBackend(database).durable_completion_count() == 1
    )


def _attempt_snapshot(
    request: FakeBackendRequest,
    state: AgentLifecycleState,
) -> AgentExecutionAttempt:
    source = request.attempt
    precreation = {
        AgentLifecycleState.PROPOSED,
        AgentLifecycleState.ADMITTED,
        AgentLifecycleState.DENIED,
    }
    provisioned = state not in precreation
    started = provisioned and state is not AgentLifecycleState.CREATED
    return AgentExecutionAttempt(
        attempt_id=source.attempt_id,
        task_id=source.task_id,
        source_task_revision=source.source_task_revision,
        assignment_id=source.assignment_id,
        context_manifest_sha256=source.context_manifest_sha256,
        runtime_session_id=source.runtime_session_id if provisioned else None,
        backend_id=source.backend_id if provisioned else None,
        profile_id=source.profile_id if provisioned else None,
        root_coordination_epoch=source.root_coordination_epoch,
        cancellation_epoch=source.cancellation_epoch,
        created_at=source.created_at,
        started_at=source.started_at if started else None,
        deadline_at=source.deadline_at,
        isolation=source.isolation if provisioned else None,
        lifecycle_state=state,
    )


def _record_through_started(
    store: SQLiteCoordinationStore,
    lease: RootLeaseHandle,
    request: FakeBackendRequest,
    *,
    key_prefix: str,
) -> tuple[CoordinationEvent, ...]:
    recorded: list[CoordinationEvent] = []
    base_time = request.attempt.created_at
    for offset_ms, state in (
        (0, AgentLifecycleState.PROPOSED),
        (100, AgentLifecycleState.ADMITTED),
        (500, AgentLifecycleState.CREATED),
        (1_000, AgentLifecycleState.STARTED),
    ):
        recorded.append(
            store.record_attempt_transition(
                lease,
                _attempt_snapshot(request, state),
                idempotency_key=f"{key_prefix}:transition:{state.value}",
                occurred_at=base_time + timedelta(milliseconds=offset_ms),
            )
        )
    return tuple(recorded)


def _coordination_store_checks(root: Path) -> dict[str, bool]:
    database = root / "coordination.sqlite3"
    store = SQLiteCoordinationStore(database)
    lease = store.acquire_root_lease(
        TASK_ID,
        root_owner_ref="root:luna-s2-verifier",
        root_instance_id=UUID("33333333-3333-4333-8333-333333333333"),
        ttl_seconds=10,
        now=NOW,
        idempotency_key="lease:epoch:1",
    )
    request, script = _fake_contracts(attempt_id="attempt:s2-complete")

    illegal_rejected = False
    try:
        store.record_attempt_transition(
            lease,
            _attempt_snapshot(request, AgentLifecycleState.CREATED),
            idempotency_key="complete:illegal-skip",
            occurred_at=NOW,
        )
    except CoordinationStoreConflictError:
        illegal_rejected = True

    legal_events = _record_through_started(
        store,
        lease,
        request,
        key_prefix="complete",
    )
    repeated_proposed = store.record_attempt_transition(
        lease,
        _attempt_snapshot(request, AgentLifecycleState.PROPOSED),
        idempotency_key="complete:transition:PROPOSED",
        occurred_at=NOW,
    )
    store.start_fake_invocation(
        lease,
        request,
        idempotency_key="complete:fake-reserved",
        occurred_at=NOW + timedelta(seconds=1),
    )
    backend = SQLiteIdempotentFakeBackend(root / "coordination-fake.sqlite3")
    result = backend.execute(
        request,
        script,
        idempotency_key="complete:backend",
    )
    store.record_fake_result(
        lease,
        result,
        idempotency_key="complete:fake-result",
        occurred_at=script.outcome_at,
    )
    events_before_finalize = store.events_for_attempt(request.attempt.attempt_id)
    started_before_finalize = (
        store.load_attempt(request.attempt.attempt_id).lifecycle_state
        is AgentLifecycleState.STARTED
    )
    receipt = store.finalize_fake_execution(
        lease,
        request.attempt.attempt_id,
        idempotency_key="complete:receipt",
        occurred_at=script.cleanup_at,
    )
    finalized_attempt_events = store.events_for_attempt(request.attempt.attempt_id)

    ambiguous_request, _ = _fake_contracts(
        attempt_id="attempt:s2-store-in-doubt",
        base_time=NOW + timedelta(seconds=4),
    )
    _record_through_started(
        store,
        lease,
        ambiguous_request,
        key_prefix="ambiguous",
    )
    ambiguous_reservation = store.start_fake_invocation(
        lease,
        ambiguous_request,
        idempotency_key="ambiguous:fake-reserved",
        occurred_at=ambiguous_request.requested_at,
    )

    reopened = SQLiteCoordinationStore(database)
    persisted_lease = reopened.current_root_lease(TASK_ID)
    second_lease = reopened.acquire_root_lease(
        TASK_ID,
        root_owner_ref="root:luna-s2-recovery",
        root_instance_id=UUID("44444444-4444-4444-8444-444444444444"),
        ttl_seconds=10,
        now=NOW + timedelta(seconds=11),
        idempotency_key="lease:epoch:2",
    )
    stale_fenced = False
    try:
        store.record_attempt_transition(
            lease,
            _attempt_snapshot(ambiguous_request, AgentLifecycleState.FAILED),
            idempotency_key="ambiguous:stale-epoch-write",
            occurred_at=NOW + timedelta(seconds=11),
        )
    except CoordinationStoreLeaseError:
        stale_fenced = True

    ambiguous_recovery = reopened.inspect_attempt(
        second_lease,
        ambiguous_request.attempt.attempt_id,
        idempotency_key="recovery:ambiguous",
        decided_at=NOW + timedelta(seconds=12),
    )
    completed_recovery = reopened.inspect_attempt(
        second_lease,
        request.attempt.attempt_id,
        idempotency_key="recovery:completed",
        decided_at=NOW + timedelta(seconds=13),
    )
    stored_receipt = reopened.load_execution_receipt(request.attempt.attempt_id)
    stored_payload = reopened.load_payload(receipt.payload_id)
    attempt_events = reopened.events_for_attempt(request.attempt.attempt_id)
    task_events = reopened.events_for_task(TASK_ID)
    finalized_event_refs = {event.event_ref for event in finalized_attempt_events}
    receipt_events = tuple(
        event
        for event in attempt_events
        if event.kind is CoordinationEventKind.EXECUTION_RECEIPT_RECORDED
    )
    finalize_events = finalized_attempt_events[len(events_before_finalize) :]
    exact_receipt_event_refs = tuple(
        sorted(event.event_ref for event in finalized_attempt_events[:-1])
    )
    transition_pairs = tuple(
        (event.from_state, event.to_state)
        for event in attempt_events
        if event.kind is CoordinationEventKind.ATTEMPT_TRANSITION
    )
    expected_pairs = (
        (None, AgentLifecycleState.PROPOSED),
        (AgentLifecycleState.PROPOSED, AgentLifecycleState.ADMITTED),
        (AgentLifecycleState.ADMITTED, AgentLifecycleState.CREATED),
        (AgentLifecycleState.CREATED, AgentLifecycleState.STARTED),
        (AgentLifecycleState.STARTED, AgentLifecycleState.RESULT_RECEIVED),
        (
            AgentLifecycleState.RESULT_RECEIVED,
            AgentLifecycleState.CLEANUP_COMPLETE,
        ),
    )
    chain_valid = all(
        event.task_sequence == index
        and (
            event.previous_event_sha256
            == (None if index == 1 else task_events[index - 2].event_sha256)
        )
        and event.runtime_authored
        for index, event in enumerate(task_events, start=1)
    )
    reopened.verify_integrity()
    return {
        "root_lease_epoch_is_monotonic_and_stale_epoch_is_fenced": bool(
            lease.record.epoch == 1
            and persisted_lease == lease.record
            and second_lease.record.epoch == 2
            and stale_fenced
            and reopened.journal_mode() == "wal"
        ),
        "attempt_transition_is_legal_idempotent_and_hash_chained": bool(
            illegal_rejected
            and legal_events[0] == repeated_proposed
            and transition_pairs == expected_pairs
            and chain_valid
        ),
        "receipt_and_event_references_are_store_authored_and_durable": bool(
            stored_receipt == receipt
            and stored_payload == result.payload
            and started_before_finalize
            and receipt.event_refs == exact_receipt_event_refs
            and set(receipt.event_refs)
            == finalized_event_refs - {finalized_attempt_events[-1].event_ref}
            and tuple(event.kind for event in finalize_events)
            == (
                CoordinationEventKind.ATTEMPT_TRANSITION,
                CoordinationEventKind.ATTEMPT_TRANSITION,
                CoordinationEventKind.EXECUTION_RECEIPT_RECORDED,
            )
            and tuple(event.to_state for event in finalize_events[:2])
            == (
                AgentLifecycleState.RESULT_RECEIVED,
                AgentLifecycleState.CLEANUP_COMPLETE,
            )
            and len(receipt_events) == 1
            and receipt_events[0].artifact_ref == receipt.receipt_id
            and receipt_events[0].artifact_sha256 == contract_sha256(receipt)
            and completed_recovery.disposition is RecoveryDisposition.RECEIPT_REUSED
            and completed_recovery.receipt_ref == receipt.receipt_id
            and completed_recovery.receipt_sha256 == contract_sha256(receipt)
        ),
        "recovery_inspection_never_blindly_replays_ambiguous_work": bool(
            ambiguous_reservation.state is FakeInvocationState.RESERVED
            and ambiguous_reservation.durable_completion_count == 0
            and ambiguous_recovery.disposition is RecoveryDisposition.NO_REPLAY
            and ambiguous_recovery.receipt_ref is None
            and reopened.load_attempt(ambiguous_request.attempt.attempt_id).lifecycle_state
            is AgentLifecycleState.STARTED
        ),
    }


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    package_boundary, no_runtime_wiring = _package_and_runtime_boundaries()
    c011 = build_canonical_capability_registry().get("C-011")
    with TemporaryDirectory(prefix="luna-c011-s2-verifier-") as temp:
        root = Path(temp)
        durable_idempotency, replay_denied = _fake_backend_checks(root)
        store_checks = _coordination_store_checks(root)
        checks = {
            "required_files_present": not missing,
            "metadata_integrity": _metadata_integrity(),
            "parallel_cognition_dependency_boundary": package_boundary,
            "production_runtime_has_no_c011_wiring": no_runtime_wiring,
            "c011_capability_remains_queued": c011.status is CapabilityStatus.QUEUED,
            "fake_backend_reopen_is_durably_idempotent": durable_idempotency,
            "ambiguous_fake_invocation_is_not_blindly_replayed": replay_denied,
            **store_checks,
            "scoped_s2_receipt_report_manifest_truthful": (
                _receipt_and_scoped_metadata_truth()
            ),
            "governance_gates_are_truthful": _governance_truth(),
        }
    output = {
        "capability": "C-011",
        "stage": "S2_DURABLE_EVENT_RECOVERY_CORE",
        "checks": checks,
        "missing": missing,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
