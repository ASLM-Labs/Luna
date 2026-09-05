from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from luna.parallel_cognition import (
    RealEqualComputeEvidenceClass,
    RealEqualComputeEvidenceReference,
    RealEqualComputeEvidenceState,
    RealEqualComputePreflightDisposition,
    RealEqualComputePreflightPolicy,
    RealEqualComputePreflightSnapshot,
    RealEqualComputePrerequisite,
    RealEqualComputePrerequisiteEvidence,
    evaluate_real_equal_compute_preflight,
)

EVALUATED_AT = datetime(2026, 9, 1, 4, 0, 25, tzinfo=UTC)
TARGET_BRANCH = "capability/c011-single-voice-parallel-cognition"
TARGET_COMMIT = "dcc0c25e1e34d7ce4ea8bcb2c77bfa17e7ca64ff"
TARGET_TREE = "ce68639c9e593b30ee4b3d8405377359d7bfa867"

VERIFIED_CLASS = {
    RealEqualComputePrerequisite.CURRENT_ASSET_BINDING: (
        RealEqualComputeEvidenceClass.REAL_PROVIDER_MEASUREMENT
    ),
    RealEqualComputePrerequisite.MEASURED_TOKEN_ACCOUNTING: (
        RealEqualComputeEvidenceClass.REAL_PROVIDER_MEASUREMENT
    ),
    RealEqualComputePrerequisite.SOLO_RUNTIME_CONTRACT: (
        RealEqualComputeEvidenceClass.REPOSITORY_SOURCE
    ),
    RealEqualComputePrerequisite.ULTRA_SOLO_RUNTIME_CONTRACT: (
        RealEqualComputeEvidenceClass.REPOSITORY_SOURCE
    ),
    RealEqualComputePrerequisite.PARALLEL_RUNTIME_CONTRACT: (
        RealEqualComputeEvidenceClass.REPOSITORY_SOURCE
    ),
    RealEqualComputePrerequisite.REPRESENTATIVE_FROZEN_SUITE: (
        RealEqualComputeEvidenceClass.REPOSITORY_RECEIPT
    ),
    RealEqualComputePrerequisite.INDEPENDENT_EVALUATOR_ATTESTATION: (
        RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION
    ),
    RealEqualComputePrerequisite.CONTAMINATION_PROVENANCE_ATTESTATION: (
        RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION
    ),
    RealEqualComputePrerequisite.HARDWARE_RESOURCE_ATTESTATION: (
        RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION
    ),
    RealEqualComputePrerequisite.SAFETY_CONTAINMENT_ATTESTATION: (
        RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION
    ),
    RealEqualComputePrerequisite.EXTERNAL_LEDGER_ANCHOR: (
        RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION
    ),
}

EXTERNAL_REQUIREMENTS = frozenset(
    {
        RealEqualComputePrerequisite.INDEPENDENT_EVALUATOR_ATTESTATION,
        RealEqualComputePrerequisite.CONTAMINATION_PROVENANCE_ATTESTATION,
        RealEqualComputePrerequisite.HARDWARE_RESOURCE_ATTESTATION,
        RealEqualComputePrerequisite.SAFETY_CONTAINMENT_ATTESTATION,
        RealEqualComputePrerequisite.EXTERNAL_LEDGER_ANCHOR,
    }
)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _reference(
    prerequisite: RealEqualComputePrerequisite,
) -> RealEqualComputeEvidenceReference:
    return RealEqualComputeEvidenceReference(
        locator=f"fixture:{prerequisite.value.lower()}",
        content_sha256=_digest(prerequisite.value),
        source_revision="fixture-v1",
    )


def _open(
    prerequisite: RealEqualComputePrerequisite,
) -> RealEqualComputePrerequisiteEvidence:
    return RealEqualComputePrerequisiteEvidence(
        prerequisite=prerequisite,
        state=RealEqualComputeEvidenceState.OPEN,
        evidence_class=RealEqualComputeEvidenceClass.NONE,
        limitations=(f"{prerequisite.value} evidence is absent",),
    )


def _observed(
    prerequisite: RealEqualComputePrerequisite,
    *,
    state: RealEqualComputeEvidenceState,
    evidence_class: RealEqualComputeEvidenceClass,
    independently_attested: bool = False,
    limitations: tuple[str, ...] = (),
) -> RealEqualComputePrerequisiteEvidence:
    return RealEqualComputePrerequisiteEvidence(
        prerequisite=prerequisite,
        state=state,
        evidence_class=evidence_class,
        evidence_refs=(_reference(prerequisite),),
        observed_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        provenance_complete=True,
        independently_attested=independently_attested,
        limitations=limitations,
    )


def _policy(**updates: object) -> RealEqualComputePreflightPolicy:
    values: dict[str, object] = {
        "target_branch": TARGET_BRANCH,
        "target_commit_oid": TARGET_COMMIT,
        "target_tree_oid": TARGET_TREE,
        "evaluated_at_utc": EVALUATED_AT,
    }
    values.update(updates)
    return RealEqualComputePreflightPolicy(**values)  # type: ignore[arg-type]


def _snapshot(
    items: tuple[RealEqualComputePrerequisiteEvidence, ...],
    **updates: object,
) -> RealEqualComputePreflightSnapshot:
    values: dict[str, object] = {
        "target_branch": TARGET_BRANCH,
        "target_commit_oid": TARGET_COMMIT,
        "target_tree_oid": TARGET_TREE,
        "evaluated_at_utc": EVALUATED_AT,
        "items": items,
    }
    values.update(updates)
    return RealEqualComputePreflightSnapshot(**values)  # type: ignore[arg-type]


def _current_items() -> tuple[RealEqualComputePrerequisiteEvidence, ...]:
    partial = {
        RealEqualComputePrerequisite.CURRENT_ASSET_BINDING,
        RealEqualComputePrerequisite.REPRESENTATIVE_FROZEN_SUITE,
        RealEqualComputePrerequisite.HARDWARE_RESOURCE_ATTESTATION,
        RealEqualComputePrerequisite.SAFETY_CONTAINMENT_ATTESTATION,
    }
    rejected = {
        RealEqualComputePrerequisite.MEASURED_TOKEN_ACCOUNTING,
        RealEqualComputePrerequisite.PARALLEL_RUNTIME_CONTRACT,
    }
    items: list[RealEqualComputePrerequisiteEvidence] = []
    for prerequisite in RealEqualComputePrerequisite:
        if prerequisite in partial:
            items.append(
                _observed(
                    prerequisite,
                    state=RealEqualComputeEvidenceState.PARTIAL,
                    evidence_class=RealEqualComputeEvidenceClass.REPOSITORY_RECEIPT,
                    limitations=("the repository receipt is not external attestation",),
                )
            )
        elif prerequisite in rejected:
            items.append(
                _observed(
                    prerequisite,
                    state=RealEqualComputeEvidenceState.REJECTED,
                    evidence_class=RealEqualComputeEvidenceClass.REPOSITORY_SOURCE,
                    limitations=("the current implementation cannot support this claim",),
                )
            )
        else:
            items.append(_open(prerequisite))
    return tuple(items)


def _all_verified_items() -> tuple[RealEqualComputePrerequisiteEvidence, ...]:
    return tuple(
        _observed(
            prerequisite,
            state=RealEqualComputeEvidenceState.VERIFIED,
            evidence_class=VERIFIED_CLASS[prerequisite],
            independently_attested=prerequisite in EXTERNAL_REQUIREMENTS,
        )
        for prerequisite in RealEqualComputePrerequisite
    )


def test_current_basis_rejects_execution_without_calling_a_model() -> None:
    decision = evaluate_real_equal_compute_preflight(
        policy=_policy(),
        snapshot=_snapshot(_current_items()),
    )

    assert (
        decision.disposition
        is RealEqualComputePreflightDisposition.BLOCKED_REJECTED_BASIS
    )
    assert decision.rejected_prerequisites == (
        RealEqualComputePrerequisite.MEASURED_TOKEN_ACCOUNTING,
        RealEqualComputePrerequisite.PARALLEL_RUNTIME_CONTRACT,
    )
    assert decision.preflight_ready is False
    assert decision.owner_authorization_recorded is True
    assert decision.execution_attempted is False
    assert decision.provider_call_executed is False
    assert decision.real_model_execution_completed is False
    assert decision.capability_status_after == "QUEUED"
    assert decision.rollout_stage_after == "BLOCKED"
    assert decision.task_state_authority is False
    assert decision.root_context_adoption_authority is False
    assert decision.completion_authority is False
    assert decision.user_facing_voice_authority is False
    assert decision.canary_authority is False
    assert decision.active_authority is False
    assert decision.promotion_authority is False


def test_complete_prerequisites_only_reach_non_executing_readiness() -> None:
    decision = evaluate_real_equal_compute_preflight(
        policy=_policy(),
        snapshot=_snapshot(_all_verified_items()),
    )

    assert (
        decision.disposition
        is RealEqualComputePreflightDisposition.READY_FOR_AUTHORIZED_EXECUTION
    )
    assert decision.verified_prerequisites == tuple(RealEqualComputePrerequisite)
    assert decision.preflight_ready is True
    assert decision.execution_attempted is False
    assert decision.provider_call_executed is False
    assert decision.promotion_authority is False


@pytest.mark.parametrize(
    "prerequisite",
    [
        RealEqualComputePrerequisite.CURRENT_ASSET_BINDING,
        RealEqualComputePrerequisite.MEASURED_TOKEN_ACCOUNTING,
    ],
)
def test_repository_source_cannot_verify_real_measurement(
    prerequisite: RealEqualComputePrerequisite,
) -> None:
    with pytest.raises(ValidationError, match="wrong evidence class"):
        _observed(
            prerequisite,
            state=RealEqualComputeEvidenceState.VERIFIED,
            evidence_class=RealEqualComputeEvidenceClass.REPOSITORY_SOURCE,
        )


def test_verified_external_prerequisite_requires_independent_attestation() -> None:
    with pytest.raises(ValidationError, match="requires attestation"):
        _observed(
            RealEqualComputePrerequisite.HARDWARE_RESOURCE_ATTESTATION,
            state=RealEqualComputeEvidenceState.VERIFIED,
            evidence_class=RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION,
        )


def test_open_prerequisite_cannot_claim_a_reference() -> None:
    prerequisite = RealEqualComputePrerequisite.ULTRA_SOLO_RUNTIME_CONTRACT
    with pytest.raises(ValidationError, match="cannot claim observations"):
        RealEqualComputePrerequisiteEvidence(
            prerequisite=prerequisite,
            state=RealEqualComputeEvidenceState.OPEN,
            evidence_class=RealEqualComputeEvidenceClass.NONE,
            evidence_refs=(_reference(prerequisite),),
            limitations=("runtime contract is absent",),
        )


def test_snapshot_requires_exact_ordered_prerequisite_inventory() -> None:
    with pytest.raises(ValidationError, match="canonical prerequisite inventory"):
        _snapshot(tuple(reversed(_current_items())))


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("target_branch", "other", "target branch"),
        ("target_commit_oid", "1" * 40, "target commit"),
        ("target_tree_oid", "2" * 40, "target tree"),
        (
            "evaluated_at_utc",
            datetime(2026, 9, 1, 4, 1, tzinfo=UTC),
            "evaluation time",
        ),
    ],
)
def test_frozen_target_drift_blocks_otherwise_ready_preflight(
    field: str,
    value: object,
    reason: str,
) -> None:
    decision = evaluate_real_equal_compute_preflight(
        policy=_policy(),
        snapshot=_snapshot(_all_verified_items(), **{field: value}),
    )

    assert (
        decision.disposition
        is RealEqualComputePreflightDisposition.BLOCKED_PREREQUISITES
    )
    assert any(reason in item for item in decision.blocked_reasons)


@pytest.mark.parametrize("artifact", ["evidence", "policy", "snapshot", "decision"])
def test_content_addressed_ids_reject_tampering(artifact: str) -> None:
    policy = _policy()
    snapshot = _snapshot(_current_items())
    decision = evaluate_real_equal_compute_preflight(policy=policy, snapshot=snapshot)
    models = {
        "evidence": snapshot.items[0],
        "policy": policy,
        "snapshot": snapshot,
        "decision": decision,
    }
    model = models[artifact]
    field = {
        "evidence": "evidence_id",
        "policy": "policy_id",
        "snapshot": "snapshot_id",
        "decision": "decision_id",
    }[artifact]
    payload = model.model_dump(mode="json")
    payload[field] = f"c011-real-equal-compute-{artifact}:sha256:{'0' * 64}"

    with pytest.raises(ValidationError, match="does not match content"):
        type(model).model_validate(payload)


def test_preflight_module_has_no_provider_execution_or_runtime_wiring() -> None:
    project_root = Path(__file__).resolve().parents[1]
    source = (
        project_root
        / "src"
        / "luna"
        / "parallel_cognition"
        / "equal_compute_preflight.py"
    ).read_text(encoding="utf-8")
    runtime_files = tuple((project_root / "src" / "luna" / "runtime").glob("*.py"))

    assert "native_real_driver" not in source
    assert "subprocess" not in source
    assert "http" not in source
    assert all(
        "equal_compute_preflight" not in path.read_text(encoding="utf-8")
        for path in runtime_files
    )
