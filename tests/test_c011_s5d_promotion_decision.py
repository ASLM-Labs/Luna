from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from luna.parallel_cognition import (
    S5DEvidenceClass,
    S5DEvidenceItem,
    S5DEvidenceReference,
    S5DEvidenceRequirement,
    S5DEvidenceState,
    S5DExternalEvidenceSnapshot,
    S5DPromotionDisposition,
    S5DPromotionPolicy,
    S5DRequestedTransition,
    evaluate_s5d_promotion,
)

EVALUATED_AT = datetime(2026, 9, 1, 12, tzinfo=UTC)
TARGET_BRANCH = "capability/c011-single-voice-parallel-cognition"
TARGET_COMMIT = "a0b75112341c296f03b519624c5aa8ec68bbf7bf"
TARGET_TREE = "f17e4c64b7e4d62d0b45f400dc46282a75979ec2"

VERIFIED_CLASS = {
    S5DEvidenceRequirement.REAL_PROVIDER_EXECUTION: (
        S5DEvidenceClass.REAL_PROVIDER_OBSERVATION
    ),
    S5DEvidenceRequirement.HARDWARE_RESOURCE_ATTESTATION: (
        S5DEvidenceClass.EXTERNAL_ATTESTATION
    ),
    S5DEvidenceRequirement.SAFETY_CONTAINMENT_ATTESTATION: (
        S5DEvidenceClass.EXTERNAL_ATTESTATION
    ),
    S5DEvidenceRequirement.S5C_LEDGER_INTEGRITY: (
        S5DEvidenceClass.REPOSITORY_RECEIPT
    ),
    S5DEvidenceRequirement.REAL_EQUAL_COMPUTE_NON_INFERIORITY: (
        S5DEvidenceClass.REAL_EQUAL_COMPUTE_COMPARISON
    ),
    S5DEvidenceRequirement.EVALUATOR_INDEPENDENCE_ATTESTATION: (
        S5DEvidenceClass.EXTERNAL_ATTESTATION
    ),
    S5DEvidenceRequirement.CONTAMINATION_PROVENANCE_ATTESTATION: (
        S5DEvidenceClass.EXTERNAL_ATTESTATION
    ),
    S5DEvidenceRequirement.EXTERNAL_LEDGER_ANCHOR: (
        S5DEvidenceClass.EXTERNAL_ATTESTATION
    ),
}

INDEPENDENT_REQUIREMENTS = frozenset(
    {
        S5DEvidenceRequirement.HARDWARE_RESOURCE_ATTESTATION,
        S5DEvidenceRequirement.SAFETY_CONTAINMENT_ATTESTATION,
        S5DEvidenceRequirement.REAL_EQUAL_COMPUTE_NON_INFERIORITY,
        S5DEvidenceRequirement.EVALUATOR_INDEPENDENCE_ATTESTATION,
        S5DEvidenceRequirement.CONTAMINATION_PROVENANCE_ATTESTATION,
        S5DEvidenceRequirement.EXTERNAL_LEDGER_ANCHOR,
    }
)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _reference(requirement: S5DEvidenceRequirement) -> S5DEvidenceReference:
    return S5DEvidenceReference(
        locator=f"receipt:{requirement.value.lower()}",
        content_sha256=_digest(requirement.value),
        source_revision="fixture-v1",
    )


def _open_item(requirement: S5DEvidenceRequirement) -> S5DEvidenceItem:
    return S5DEvidenceItem(
        requirement=requirement,
        state=S5DEvidenceState.OPEN,
        evidence_class=S5DEvidenceClass.NONE,
        limitations=(f"{requirement.value} evidence has not been supplied",),
    )


def _observed_item(
    requirement: S5DEvidenceRequirement,
    *,
    state: S5DEvidenceState,
    evidence_class: S5DEvidenceClass,
    observed_at: datetime = datetime(2026, 8, 30, tzinfo=UTC),
    valid_until: datetime | None = None,
    independently_attested: bool = False,
    limitations: tuple[str, ...] = (),
) -> S5DEvidenceItem:
    return S5DEvidenceItem(
        requirement=requirement,
        state=state,
        evidence_class=evidence_class,
        evidence_refs=(_reference(requirement),),
        observed_at_utc=observed_at,
        valid_until_utc=valid_until,
        provenance_complete=True,
        independently_attested=independently_attested,
        limitations=limitations,
    )


def _policy(**updates: object) -> S5DPromotionPolicy:
    values: dict[str, object] = {
        "target_branch": TARGET_BRANCH,
        "target_commit_oid": TARGET_COMMIT,
        "target_tree_oid": TARGET_TREE,
        "evaluated_at_utc": EVALUATED_AT,
    }
    values.update(updates)
    return S5DPromotionPolicy(**values)  # type: ignore[arg-type]


def _snapshot(
    items: tuple[S5DEvidenceItem, ...],
    **updates: object,
) -> S5DExternalEvidenceSnapshot:
    values: dict[str, object] = {
        "target_branch": TARGET_BRANCH,
        "target_commit_oid": TARGET_COMMIT,
        "target_tree_oid": TARGET_TREE,
        "evaluated_at_utc": EVALUATED_AT,
        "items": items,
    }
    values.update(updates)
    return S5DExternalEvidenceSnapshot(**values)  # type: ignore[arg-type]


def _current_items() -> tuple[S5DEvidenceItem, ...]:
    partial = {
        S5DEvidenceRequirement.HARDWARE_RESOURCE_ATTESTATION,
        S5DEvidenceRequirement.SAFETY_CONTAINMENT_ATTESTATION,
    }
    items: list[S5DEvidenceItem] = []
    for requirement in S5DEvidenceRequirement:
        if requirement is S5DEvidenceRequirement.REAL_PROVIDER_EXECUTION:
            items.append(
                _observed_item(
                    requirement,
                    state=S5DEvidenceState.VERIFIED,
                    evidence_class=S5DEvidenceClass.REAL_PROVIDER_OBSERVATION,
                )
            )
        elif requirement is S5DEvidenceRequirement.S5C_LEDGER_INTEGRITY:
            items.append(
                _observed_item(
                    requirement,
                    state=S5DEvidenceState.VERIFIED,
                    evidence_class=S5DEvidenceClass.REPOSITORY_RECEIPT,
                )
            )
        elif requirement in partial:
            items.append(
                _observed_item(
                    requirement,
                    state=S5DEvidenceState.PARTIAL,
                    evidence_class=S5DEvidenceClass.REPOSITORY_RECEIPT,
                    limitations=("external attestation is absent",),
                )
            )
        else:
            items.append(_open_item(requirement))
    return tuple(items)


def _all_verified_items(
    *,
    observed_at: datetime = datetime(2026, 8, 30, tzinfo=UTC),
) -> tuple[S5DEvidenceItem, ...]:
    return tuple(
        _observed_item(
            requirement,
            state=S5DEvidenceState.VERIFIED,
            evidence_class=VERIFIED_CLASS[requirement],
            observed_at=observed_at,
            independently_attested=requirement in INDEPENDENT_REQUIREMENTS,
        )
        for requirement in S5DEvidenceRequirement
    )


def test_current_repository_evidence_blocks_promotion_without_authority() -> None:
    decision = evaluate_s5d_promotion(
        policy=_policy(),
        snapshot=_snapshot(_current_items()),
        requested_transition=S5DRequestedTransition.CANARY,
    )

    assert decision.disposition is S5DPromotionDisposition.BLOCKED_INSUFFICIENT_EVIDENCE
    assert decision.satisfied_requirements == (
        S5DEvidenceRequirement.REAL_PROVIDER_EXECUTION,
        S5DEvidenceRequirement.S5C_LEDGER_INTEGRITY,
    )
    assert decision.partial_requirements == (
        S5DEvidenceRequirement.HARDWARE_RESOURCE_ATTESTATION,
        S5DEvidenceRequirement.SAFETY_CONTAINMENT_ATTESTATION,
    )
    assert decision.open_requirements == (
        S5DEvidenceRequirement.REAL_EQUAL_COMPUTE_NON_INFERIORITY,
        S5DEvidenceRequirement.EVALUATOR_INDEPENDENCE_ATTESTATION,
        S5DEvidenceRequirement.CONTAMINATION_PROVENANCE_ATTESTATION,
        S5DEvidenceRequirement.EXTERNAL_LEDGER_ANCHOR,
    )
    assert decision.owner_review_ready is False
    assert decision.capability_status_after == "QUEUED"
    assert decision.rollout_stage_after == "BLOCKED"
    assert decision.transition_applied is False
    assert decision.provider_call_executed is False
    assert decision.runtime_authority is False
    assert decision.task_state_authority is False
    assert decision.root_context_adoption_authority is False
    assert decision.completion_authority is False
    assert decision.user_facing_voice_authority is False
    assert decision.canary_authority is False
    assert decision.active_authority is False
    assert decision.promotion_authority is False


def test_complete_evidence_only_reaches_owner_review_and_never_promotes() -> None:
    decision = evaluate_s5d_promotion(
        policy=_policy(),
        snapshot=_snapshot(_all_verified_items()),
        requested_transition=S5DRequestedTransition.ACTIVE,
    )

    assert decision.disposition is S5DPromotionDisposition.READY_FOR_OWNER_REVIEW
    assert decision.satisfied_requirements == tuple(S5DEvidenceRequirement)
    assert decision.owner_review_ready is True
    assert decision.capability_status_after == "QUEUED"
    assert decision.rollout_stage_after == "BLOCKED"
    assert decision.transition_applied is False
    assert decision.promotion_authority is False


@pytest.mark.parametrize(
    ("requirement", "evidence_class"),
    [
        (
            S5DEvidenceRequirement.REAL_PROVIDER_EXECUTION,
            S5DEvidenceClass.DETERMINISTIC_FIXTURE,
        ),
        (
            S5DEvidenceRequirement.REAL_EQUAL_COMPUTE_NON_INFERIORITY,
            S5DEvidenceClass.DETERMINISTIC_FIXTURE,
        ),
    ],
)
def test_fixture_evidence_cannot_be_laundered_as_verified(
    requirement: S5DEvidenceRequirement,
    evidence_class: S5DEvidenceClass,
) -> None:
    with pytest.raises(ValidationError, match="wrong evidence class"):
        _observed_item(
            requirement,
            state=S5DEvidenceState.VERIFIED,
            evidence_class=evidence_class,
            independently_attested=requirement in INDEPENDENT_REQUIREMENTS,
        )


def test_verified_external_evidence_requires_independent_attestation() -> None:
    with pytest.raises(ValidationError, match="independent attestation"):
        _observed_item(
            S5DEvidenceRequirement.HARDWARE_RESOURCE_ATTESTATION,
            state=S5DEvidenceState.VERIFIED,
            evidence_class=S5DEvidenceClass.EXTERNAL_ATTESTATION,
        )


def test_open_evidence_cannot_claim_a_reference() -> None:
    with pytest.raises(ValidationError, match="cannot claim observations"):
        S5DEvidenceItem(
            requirement=S5DEvidenceRequirement.EXTERNAL_LEDGER_ANCHOR,
            state=S5DEvidenceState.OPEN,
            evidence_class=S5DEvidenceClass.NONE,
            evidence_refs=(
                _reference(S5DEvidenceRequirement.EXTERNAL_LEDGER_ANCHOR),
            ),
            limitations=("external anchor is absent",),
        )


def test_snapshot_requires_the_exact_ordered_evidence_inventory() -> None:
    with pytest.raises(ValidationError, match="canonical evidence inventory"):
        _snapshot(tuple(reversed(_current_items())))


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("target_branch", "other", "target branch"),
        ("target_commit_oid", "1" * 40, "target commit"),
        ("target_tree_oid", "2" * 40, "target tree"),
        (
            "evaluated_at_utc",
            datetime(2026, 9, 1, 13, tzinfo=UTC),
            "evaluation time",
        ),
    ],
)
def test_frozen_policy_target_drift_blocks_review(
    field: str,
    value: object,
    reason: str,
) -> None:
    snapshot = _snapshot(_all_verified_items(), **{field: value})
    decision = evaluate_s5d_promotion(
        policy=_policy(),
        snapshot=snapshot,
        requested_transition=S5DRequestedTransition.CANARY,
    )

    assert decision.disposition is S5DPromotionDisposition.BLOCKED_INSUFFICIENT_EVIDENCE
    assert any(reason in item for item in decision.blocked_reasons)


def test_stale_verified_evidence_is_downgraded_and_blocks_review() -> None:
    stale_requirement = S5DEvidenceRequirement.REAL_PROVIDER_EXECUTION
    items = list(_all_verified_items())
    items[0] = _observed_item(
        stale_requirement,
        state=S5DEvidenceState.VERIFIED,
        evidence_class=S5DEvidenceClass.REAL_PROVIDER_OBSERVATION,
        observed_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    decision = evaluate_s5d_promotion(
        policy=_policy(),
        snapshot=_snapshot(tuple(items)),
        requested_transition=S5DRequestedTransition.CANARY,
    )

    assert decision.disposition is S5DPromotionDisposition.BLOCKED_INSUFFICIENT_EVIDENCE
    assert stale_requirement in decision.partial_requirements
    assert stale_requirement not in decision.satisfied_requirements


def test_rejected_evidence_has_a_distinct_fail_closed_disposition() -> None:
    requirement = S5DEvidenceRequirement.REAL_PROVIDER_EXECUTION
    items = list(_all_verified_items())
    items[0] = _observed_item(
        requirement,
        state=S5DEvidenceState.REJECTED,
        evidence_class=S5DEvidenceClass.REAL_PROVIDER_OBSERVATION,
        limitations=("provider receipt signature is invalid",),
    )
    decision = evaluate_s5d_promotion(
        policy=_policy(),
        snapshot=_snapshot(tuple(items)),
        requested_transition=S5DRequestedTransition.CANARY,
    )

    assert decision.disposition is S5DPromotionDisposition.BLOCKED_REJECTED_EVIDENCE
    assert decision.rejected_requirements == (requirement,)


@pytest.mark.parametrize("artifact", ["evidence", "policy", "snapshot", "decision"])
def test_content_addressed_ids_reject_tampering(artifact: str) -> None:
    policy = _policy()
    snapshot = _snapshot(_current_items())
    decision = evaluate_s5d_promotion(
        policy=policy,
        snapshot=snapshot,
        requested_transition=S5DRequestedTransition.CANARY,
    )
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
    payload[field] = f"c011-s5d-{artifact}:sha256:{'0' * 64}"

    with pytest.raises(ValidationError, match="does not match canonical content"):
        type(model).model_validate(payload)


def test_s5d_module_has_no_provider_execution_or_runtime_wiring() -> None:
    project_root = Path(__file__).resolve().parents[1]
    source = (
        project_root / "src" / "luna" / "parallel_cognition" / "promotion_decision.py"
    ).read_text(encoding="utf-8")
    runtime_files = tuple((project_root / "src" / "luna" / "runtime").glob("*.py"))

    assert "native_real_driver" not in source
    assert "subprocess" not in source
    assert "http" not in source
    assert all(
        "promotion_decision" not in path.read_text(encoding="utf-8")
        for path in runtime_files
    )
