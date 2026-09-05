from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from luna.capabilities import CapabilityStatus, build_canonical_capability_registry
from luna.contracts.enums import PlanStepStatus
from luna.parallel_cognition import (
    AdoptionDecision,
    AdoptionDisposition,
    AdoptionReceipt,
    AgentExecutionAttempt,
    AgentExecutionReceipt,
    AgentLifecycleState,
    AgentPayload,
    AgentResourceUsage,
    AssignmentSemanticSpec,
    ClaimFreshness,
    ClaimRecord,
    ClaimSupportDisposition,
    CleanupState,
    ContextFreshness,
    ContextSourceReference,
    ContradictionState,
    DistilledHandoff,
    EvidenceResolutionState,
    IsolationReferences,
    ParallelCognitionRole,
    ProposedClaim,
    ReadOnlyContextManifest,
    RedactionState,
    ResolvedEvidenceLineage,
    SourceStepSemantics,
    WorkerBudgetEnvelope,
    canonical_contract_json,
    contract_sha256,
    reconstruct_contract,
    validate_c011_contract_chain,
)
from luna.parallel_cognition.models import C011ContractModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_TASK_ID = UUID("22222222-2222-4222-8222-222222222222")
STEP_ONE_ID = UUID("33333333-3333-4333-8333-333333333333")
STEP_TWO_ID = UUID("44444444-4444-4444-8444-444444444444")
NOW = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
DEADLINE = NOW + timedelta(minutes=10)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def _source(
    source_ref: str,
    *,
    digest: str,
    size_bytes: int,
    freshness: ContextFreshness = ContextFreshness.CURRENT,
    redaction: RedactionState = RedactionState.REDACTED,
) -> ContextSourceReference:
    return ContextSourceReference(
        task_id=TASK_ID,
        source_task_revision=7,
        source_ref=source_ref,
        source_revision="git:09a5dcc",
        content_sha256=digest,
        freshness=freshness,
        freshness_checked_at=NOW - timedelta(minutes=2),
        redaction_state=redaction,
        size_bytes=size_bytes,
    )


def _build_chain() -> dict[str, C011ContractModel | tuple[ClaimRecord, ...]]:
    context = ReadOnlyContextManifest(
        task_id=TASK_ID,
        source_task_revision=7,
        sources=(
            _source("repo:tests", digest=SHA_B, size_bytes=20),
            _source("repo:src", digest=SHA_A, size_bytes=30),
        ),
        total_size_bytes=50,
        created_at=NOW,
        expires_at=DEADLINE,
    )
    step_one = SourceStepSemantics(
        step_id=STEP_ONE_ID,
        sequence=1,
        description="Inspect the immutable contract basis.",
        status=PlanStepStatus.PENDING,
        source_step_payload_sha256=SHA_A,
    )
    step_two = SourceStepSemantics(
        step_id=STEP_TWO_ID,
        sequence=2,
        description="Reconcile bounded evidence.",
        status=PlanStepStatus.PENDING,
        expectation_payload_sha256=SHA_B,
        dependency_step_ids=(STEP_ONE_ID,),
        source_step_payload_sha256=SHA_C,
    )
    budget = WorkerBudgetEnvelope(
        max_context_bytes=1000,
        max_result_bytes=20000,
        max_claims=4,
        max_tokens=2000,
        max_runtime_ms=600000,
        deadline_at=DEADLINE,
    )
    assignment = AssignmentSemanticSpec(
        task_id=TASK_ID,
        source_task_revision=7,
        task_contract_sha256=SHA_D,
        source_steps=(step_two, step_one),
        acceptance_basis_sha256=SHA_E,
        acceptance_target_refs=("target:tamper", "target:roundtrip"),
        context_manifest_sha256=contract_sha256(context),
        autonomy_policy_sha256=SHA_A,
        tool_policy_sha256=SHA_B,
        worker_role=ParallelCognitionRole.PARALLEL,
        objective="Inspect one independent evidence lane.",
        granted_source_refs=("repo:tests", "repo:src"),
        capability_selection_basis_sha256=SHA_F,
        root_coordination_epoch=3,
        budget=budget,
    )
    attempt = AgentExecutionAttempt(
        attempt_id="attempt:lane-1",
        task_id=TASK_ID,
        source_task_revision=7,
        assignment_id=assignment.assignment_id,
        context_manifest_sha256=contract_sha256(context),
        runtime_session_id="session:lane-1",
        backend_id="backend:fixture",
        profile_id="profile:readonly",
        root_coordination_epoch=3,
        cancellation_epoch=0,
        created_at=NOW,
        started_at=NOW + timedelta(seconds=1),
        deadline_at=DEADLINE,
        isolation=IsolationReferences(
            process_ref="isolation:process:fixture",
            session_ref="isolation:session:fixture",
            context_ref="isolation:context:fixture",
        ),
        lifecycle_state=AgentLifecycleState.CLEANUP_COMPLETE,
        display_name="Lane One",
    )
    proposed_claim = ProposedClaim(
        claim_key="claim:one",
        statement="The S1 contract basis is immutable.",
        source_refs=("repo:src",),
        evidence_refs=("evidence:one",),
    )
    payload = AgentPayload(
        task_id=TASK_ID,
        source_task_revision=7,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        context_manifest_sha256=contract_sha256(context),
        summary="One structurally supported claim was returned.",
        claims=(proposed_claim,),
        cited_source_refs=("repo:src",),
        cited_evidence_refs=("evidence:one",),
        assumptions=("Runtime authorship remains unestablished in S1.",),
        uncertainty=("Authoritative evidence resolution begins in S3.",),
        recommended_next_action="Verify the claim at the root boundary.",
    )
    usage = AgentResourceUsage(
        context_bytes=context.total_size_bytes,
        result_bytes=len(canonical_contract_json(payload).encode("utf-8")),
        claims_count=len(payload.claims),
        tokens=200,
        runtime_ms=5000,
    )
    receipt = AgentExecutionReceipt(
        task_id=TASK_ID,
        source_task_revision=7,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        attempt_integrity_id=attempt.attempt_integrity_id,
        context_manifest_sha256=contract_sha256(context),
        payload_id=payload.payload_id,
        payload_sha256=contract_sha256(payload),
        runtime_session_id="session:lane-1",
        backend_id="backend:fixture",
        profile_id="profile:readonly",
        root_coordination_epoch=3,
        cancellation_epoch=0,
        budget=budget,
        usage=usage,
        started_at=NOW + timedelta(seconds=1),
        outcome_at=NOW + timedelta(minutes=1),
        deadline_at=DEADLINE,
        cleanup_at=NOW + timedelta(minutes=1, seconds=1),
        outcome_state=AgentLifecycleState.RESULT_RECEIVED,
        cleanup_state=CleanupState.CLEANUP_COMPLETE,
        late_result=False,
        event_refs=("event:result", "event:cleanup"),
    )
    lineage = ResolvedEvidenceLineage(
        task_id=TASK_ID,
        source_task_revision=7,
        evidence_ref="evidence:one",
        evidence_sha256=SHA_A,
        source_ref="repo:src",
        source_sha256=SHA_B,
        resolution_state=EvidenceResolutionState.RESOLVED_CURRENT,
        freshness_checked_at=NOW + timedelta(minutes=1, seconds=2),
        resolver_ref="resolver:s3-placeholder",
        resolution_receipt_sha256=SHA_C,
    )
    claim = ClaimRecord(
        task_id=TASK_ID,
        source_task_revision=7,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        payload_id=payload.payload_id,
        source_claim_key="claim:one",
        statement="The S1 contract basis is immutable.",
        support_disposition=ClaimSupportDisposition.QUALIFIED,
        evidence_lineage=(lineage,),
        freshness=ClaimFreshness.CURRENT,
        contradiction_state=ContradictionState.NONE,
        qualification_reason="Current digest-bound lineage is structurally complete.",
    )
    claims = (claim,)
    handoff = DistilledHandoff(
        task_id=TASK_ID,
        source_task_revision=7,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        context_manifest_sha256=contract_sha256(context),
        payload_id=payload.payload_id,
        payload_sha256=contract_sha256(payload),
        receipt_id=receipt.receipt_id,
        receipt_sha256=contract_sha256(receipt),
        qualified_claims=claims,
        assumptions=payload.assumptions,
        uncertainty=payload.uncertainty,
        recommended_next_action=payload.recommended_next_action,
        created_at=NOW + timedelta(minutes=2),
    )
    adoption = AdoptionReceipt(
        task_id=TASK_ID,
        root_coordination_epoch=3,
        handoff_id=handoff.handoff_id,
        handoff_sha256=contract_sha256(handoff),
        considered_claim_ids=(claim.claim_record_id,),
        decisions=(
            AdoptionDecision(
                claim_record_id=claim.claim_record_id,
                disposition=AdoptionDisposition.ADOPTED,
                reason="Root fixture adopts the qualified claim.",
                evidence_refs=("root-evidence:one",),
            ),
        ),
        current_root_state_revision=7,
        resulting_root_state_revision=8,
        authoritative_evidence_basis=("root-evidence:one",),
        root_owner_ref="root:luna",
        adopted_at=NOW + timedelta(minutes=3),
    )
    return {
        "context": context,
        "assignment": assignment,
        "attempt": attempt,
        "payload": payload,
        "receipt": receipt,
        "claim": claim,
        "claims": claims,
        "handoff": handoff,
        "adoption": adoption,
    }


def _rebuild(model: C011ContractModel, **updates: Any) -> C011ContractModel:
    identity_fields = {
        ReadOnlyContextManifest: "context_manifest_id",
        AssignmentSemanticSpec: "assignment_id",
        AgentExecutionAttempt: "attempt_integrity_id",
        AgentPayload: "payload_id",
        AgentExecutionReceipt: "receipt_id",
        ClaimRecord: "claim_record_id",
        DistilledHandoff: "handoff_id",
        AdoptionReceipt: "adoption_receipt_id",
    }
    payload = model.model_dump(mode="json")
    payload.update(updates)
    identity_field = identity_fields.get(type(model))
    if identity_field is not None:
        payload.pop(identity_field, None)
    return type(model).model_validate(payload)


def _validate_chain(
    chain: dict[str, C011ContractModel | tuple[ClaimRecord, ...]],
) -> None:
    validate_c011_contract_chain(
        context=chain["context"],  # type: ignore[arg-type]
        assignment=chain["assignment"],  # type: ignore[arg-type]
        attempt=chain["attempt"],  # type: ignore[arg-type]
        payload=chain["payload"],  # type: ignore[arg-type]
        receipt=chain["receipt"],  # type: ignore[arg-type]
        claims=chain["claims"],  # type: ignore[arg-type]
        handoff=chain["handoff"],  # type: ignore[arg-type]
        adoption=chain["adoption"],  # type: ignore[arg-type]
    )


def test_c011_contract_models_are_frozen_and_forbid_unknown_fields() -> None:
    chain = _build_chain()
    context = chain["context"]
    assert isinstance(context, ReadOnlyContextManifest)

    with pytest.raises(ValidationError, match="frozen"):
        context.total_size_bytes = 99

    payload = context.model_dump(mode="json")
    payload["secret"] = "must-not-enter-context"
    with pytest.raises(ValidationError, match="Extra inputs"):
        ReadOnlyContextManifest.model_validate(payload)

    payload = context.model_dump(mode="json")
    payload["schema_version"] = "2.0"
    with pytest.raises(ValidationError, match="unsupported schema_version"):
        ReadOnlyContextManifest.model_validate(payload)


def test_c011_canonical_round_trip_is_byte_stable_for_all_primary_models() -> None:
    chain = _build_chain()
    primary = (
        chain["context"],
        chain["assignment"],
        chain["attempt"],
        chain["payload"],
        chain["receipt"],
        chain["claim"],
        chain["handoff"],
        chain["adoption"],
    )
    for model in primary:
        assert isinstance(model, C011ContractModel)
        encoded = canonical_contract_json(model)
        restored = reconstruct_contract(type(model), encoded)
        assert restored == model
        assert canonical_contract_json(restored) == encoded
        assert contract_sha256(restored) == contract_sha256(model)


def test_c011_set_like_order_is_normalized_and_hashes_are_domain_separated() -> None:
    first = _build_chain()
    second = _build_chain()
    context = first["context"]
    assignment = first["assignment"]
    assert isinstance(context, ReadOnlyContextManifest)
    assert isinstance(assignment, AssignmentSemanticSpec)
    assert isinstance(second["context"], ReadOnlyContextManifest)
    assert isinstance(second["assignment"], AssignmentSemanticSpec)

    assert context == second["context"]
    assert assignment == second["assignment"]
    assert tuple(item.source_ref for item in context.sources) == (
        "repo:src",
        "repo:tests",
    )
    assert assignment.granted_source_refs == ("repo:src", "repo:tests")
    assert contract_sha256(context) != contract_sha256(assignment)


def test_c011_assignment_id_changes_for_every_semantic_dimension() -> None:
    assignment = _build_chain()["assignment"]
    assert isinstance(assignment, AssignmentSemanticSpec)
    base = assignment.model_dump(mode="json")

    def nested_step(payload: dict[str, Any]) -> None:
        payload["source_steps"][0]["description"] = "Changed complete step semantics."

    def dependency(payload: dict[str, Any]) -> None:
        payload["source_steps"][1]["dependency_step_ids"] = []

    def budget(payload: dict[str, Any]) -> None:
        payload["budget"]["max_tokens"] += 1

    mutators: tuple[Callable[[dict[str, Any]], None], ...] = (
        lambda item: item.update(task_id=str(OTHER_TASK_ID)),
        lambda item: item.update(source_task_revision=8),
        lambda item: item.update(task_contract_sha256=SHA_E),
        nested_step,
        dependency,
        lambda item: item.update(acceptance_basis_sha256=SHA_F),
        lambda item: item["acceptance_target_refs"].append("target:new"),
        lambda item: item.update(context_manifest_sha256=SHA_A),
        lambda item: item.update(autonomy_policy_sha256=SHA_C),
        lambda item: item.update(tool_policy_sha256=SHA_D),
        lambda item: item.update(worker_role="INDEPENDENT_REVIEWER"),
        lambda item: item.update(objective="A materially changed objective."),
        lambda item: item["granted_source_refs"].append("repo:docs"),
        lambda item: item.update(capability_selection_basis_sha256=SHA_A),
        lambda item: item.update(root_coordination_epoch=4),
        budget,
    )
    for mutate in mutators:
        changed = deepcopy(base)
        changed.pop("assignment_id")
        mutate(changed)
        rebuilt = AssignmentSemanticSpec.model_validate(changed)
        assert rebuilt.assignment_id != assignment.assignment_id


def test_c011_reconstruction_rejects_old_identity_after_content_tamper() -> None:
    assignment = _build_chain()["assignment"]
    assert isinstance(assignment, AssignmentSemanticSpec)
    payload = assignment.model_dump(mode="json")
    payload["objective"] = "Tampered objective with the old identity."
    with pytest.raises(ValidationError, match="assignment_id"):
        AssignmentSemanticSpec.model_validate(payload)

    context = _build_chain()["context"]
    assert isinstance(context, ReadOnlyContextManifest)
    context_payload = context.model_dump(mode="json")
    context_payload["total_size_bytes"] += 1
    context_payload.pop("context_manifest_id")
    with pytest.raises(ValidationError, match="size accounting"):
        ReadOnlyContextManifest.model_validate(context_payload)

    bypassed_copy = assignment.model_copy(update={"completion_authority": True})
    with pytest.raises(ValidationError):
        canonical_contract_json(bypassed_copy)


def test_c011_attempt_identity_is_distinct_from_assignment_and_display_name() -> None:
    attempt = _build_chain()["attempt"]
    assert isinstance(attempt, AgentExecutionAttempt)
    renamed = _rebuild(attempt, display_name="Presentation Only")
    assert isinstance(renamed, AgentExecutionAttempt)
    assert renamed.attempt_id == attempt.attempt_id
    assert renamed.attempt_integrity_id != attempt.attempt_integrity_id

    second = _rebuild(
        attempt,
        attempt_id="attempt:lane-2",
        runtime_session_id="session:lane-2",
    )
    assert isinstance(second, AgentExecutionAttempt)
    assert second.assignment_id == attempt.assignment_id
    assert second.attempt_id != attempt.attempt_id


def test_c011_attempt_rejects_naive_reverse_or_false_lifecycle_timestamps() -> None:
    attempt = _build_chain()["attempt"]
    assert isinstance(attempt, AgentExecutionAttempt)
    base = attempt.model_dump(mode="json")
    base.pop("attempt_integrity_id")

    naive = deepcopy(base)
    naive["created_at"] = datetime(2026, 8, 24, 9, 0).isoformat()
    with pytest.raises(ValidationError, match="timezone-aware"):
        AgentExecutionAttempt.model_validate(naive)

    reverse = deepcopy(base)
    reverse["started_at"] = (DEADLINE + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="before its deadline"):
        AgentExecutionAttempt.model_validate(reverse)

    precreated = deepcopy(base)
    precreated["lifecycle_state"] = "ADMITTED"
    with pytest.raises(ValidationError, match="runtime provisioning"):
        AgentExecutionAttempt.model_validate(precreated)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("runtime_usage", {"tokens": 1}),
        ("cleanup_state", "CLEANUP_COMPLETE"),
        ("permission_grants", ["write"]),
        ("hidden_reasoning", "not a payload field"),
        ("completion_authority", True),
    ),
)
def test_c011_agent_payload_rejects_authoritative_or_hidden_fields(
    field: str,
    value: object,
) -> None:
    payload = _build_chain()["payload"]
    assert isinstance(payload, AgentPayload)
    raw = payload.model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValidationError):
        AgentPayload.model_validate(raw)


def test_c011_receipt_rejects_budget_timestamp_and_late_flag_incoherence() -> None:
    receipt = _build_chain()["receipt"]
    assert isinstance(receipt, AgentExecutionReceipt)
    raw = receipt.model_dump(mode="json")
    raw.pop("receipt_id")

    over_budget = deepcopy(raw)
    over_budget["usage"]["tokens"] = over_budget["budget"]["max_tokens"] + 1
    with pytest.raises(ValidationError, match="exceeds"):
        AgentExecutionReceipt.model_validate(over_budget)

    reverse = deepcopy(raw)
    reverse["cleanup_at"] = (NOW - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="monotonic"):
        AgentExecutionReceipt.model_validate(reverse)

    false_late = deepcopy(raw)
    false_late["late_result"] = True
    with pytest.raises(ValidationError, match="late-result flag"):
        AgentExecutionReceipt.model_validate(false_late)


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"freshness": "STALE"}, "current freshness"),
        ({"contradiction_state": "UNRESOLVED"}, "contradiction"),
    ),
)
def test_c011_claim_qualification_rejects_stale_or_conflicted_support(
    updates: dict[str, object],
    message: str,
) -> None:
    claim = _build_chain()["claim"]
    assert isinstance(claim, ClaimRecord)
    raw = claim.model_dump(mode="json")
    raw.pop("claim_record_id")
    raw.update(updates)
    with pytest.raises(ValidationError, match=message):
        ClaimRecord.model_validate(raw)

    unresolved = claim.model_dump(mode="json")
    unresolved.pop("claim_record_id")
    unresolved["evidence_lineage"][0]["resolution_state"] = "UNRESOLVED"
    with pytest.raises(ValidationError, match="current resolved"):
        ClaimRecord.model_validate(unresolved)


def test_c011_handoff_and_adoption_reject_unqualified_or_incomplete_claim_sets() -> None:
    chain = _build_chain()
    claim = chain["claim"]
    handoff = chain["handoff"]
    adoption = chain["adoption"]
    assert isinstance(claim, ClaimRecord)
    assert isinstance(handoff, DistilledHandoff)
    assert isinstance(adoption, AdoptionReceipt)

    rejected_claim = _rebuild(
        claim,
        support_disposition="REJECTED",
        freshness="UNKNOWN",
        evidence_lineage=[],
    )
    handoff_raw = handoff.model_dump(mode="json")
    handoff_raw.pop("handoff_id")
    handoff_raw["qualified_claims"] = [rejected_claim.model_dump(mode="json")]
    with pytest.raises(ValidationError, match="only qualified"):
        DistilledHandoff.model_validate(handoff_raw)

    incomplete = adoption.model_dump(mode="json")
    incomplete.pop("adoption_receipt_id")
    incomplete["decisions"] = []
    with pytest.raises(ValidationError, match="exhaust"):
        AdoptionReceipt.model_validate(incomplete)

    rollback = adoption.model_dump(mode="json")
    rollback.pop("adoption_receipt_id")
    rollback["resulting_root_state_revision"] = 6
    with pytest.raises(ValidationError, match="roll back"):
        AdoptionReceipt.model_validate(rollback)


def test_c011_full_structural_chain_accepts_exact_internal_bindings() -> None:
    _validate_chain(_build_chain())


@pytest.mark.parametrize(
    ("artifact", "updates", "message"),
    (
        ("assignment", {"context_manifest_sha256": SHA_F}, "context digest"),
        ("attempt", {"assignment_id": "c011-assignment:sha256:" + SHA_A}, "attempt"),
        ("receipt", {"runtime_session_id": "session:wrong"}, "runtime binding"),
        ("receipt", {"backend_id": "backend:wrong"}, "runtime binding"),
        ("receipt", {"profile_id": "profile:wrong"}, "runtime binding"),
        ("receipt", {"root_coordination_epoch": 4}, "runtime binding"),
        ("receipt", {"payload_sha256": SHA_F}, "artifact binding"),
        ("handoff", {"receipt_sha256": SHA_F}, "handoff artifact"),
        ("adoption", {"current_root_state_revision": 8}, "stale root"),
    ),
)
def test_c011_chain_rejects_cross_artifact_replay_or_recomputed_hashes(
    artifact: str,
    updates: dict[str, object],
    message: str,
) -> None:
    chain = _build_chain()
    model = chain[artifact]
    assert isinstance(model, C011ContractModel)
    chain[artifact] = _rebuild(model, **updates)
    with pytest.raises(ValueError, match=message):
        _validate_chain(chain)


@pytest.mark.parametrize(
    ("outcome", "cleanup", "late"),
    (
        (AgentLifecycleState.FAILED, CleanupState.CLEANUP_COMPLETE, False),
        (AgentLifecycleState.RESULT_RECEIVED, CleanupState.CLEANUP_FAILED, False),
    ),
)
def test_c011_failed_or_unclean_execution_cannot_enter_handoff(
    outcome: AgentLifecycleState,
    cleanup: CleanupState,
    late: bool,
) -> None:
    chain = _build_chain()
    receipt = chain["receipt"]
    handoff = chain["handoff"]
    assert isinstance(receipt, AgentExecutionReceipt)
    assert isinstance(handoff, DistilledHandoff)
    changed_receipt = _rebuild(
        receipt,
        outcome_state=outcome.value,
        cleanup_state=cleanup.value,
        late_result=late,
    )
    assert isinstance(changed_receipt, AgentExecutionReceipt)
    chain["receipt"] = changed_receipt
    chain["handoff"] = _rebuild(
        handoff,
        receipt_id=changed_receipt.receipt_id,
        receipt_sha256=contract_sha256(changed_receipt),
    )
    with pytest.raises(ValueError, match=r"execution|cleanup"):
        _validate_chain(chain)


def test_c011_package_has_no_live_runtime_wiring_and_capability_remains_queued() -> None:
    models_source = (
        PROJECT_ROOT / "src" / "luna" / "parallel_cognition" / "models.py"
    ).read_text(encoding="utf-8")
    assert "luna.runtime" not in models_source
    assert "luna.tools" not in models_source
    assert "subprocess" not in models_source
    assert "socket" not in models_source

    runtime_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "src" / "luna" / "runtime").glob("*.py")
    )
    assert "parallel_cognition" not in runtime_sources
    assert build_canonical_capability_registry().get("C-011").status is CapabilityStatus.QUEUED
