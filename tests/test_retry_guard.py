from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

from luna.contracts.enums import ObservationStatus
from luna.planning import AttemptBasis, AttemptRecord, RetryGuard, RetryReason


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _basis(*, evidence: tuple[str, ...] = ()) -> AttemptBasis:
    return AttemptBasis(
        action_key="write:README.md",
        context_fingerprint=_digest("context"),
        evidence_refs=evidence,
        assumption_revision=0,
        execution_strategy="minimal_patch",
        verification_strategy="pytest",
        scope_fingerprint=_digest("scope"),
    )


def _record(basis: AttemptBasis, outcome: ObservationStatus) -> AttemptRecord:
    return AttemptRecord(
        task_id=uuid4(),
        step_id=uuid4(),
        basis=basis,
        observation_id=uuid4(),
        outcome=outcome,
    )


def test_same_failed_action_same_basis_is_blocked() -> None:
    basis = _basis()
    decision = RetryGuard().evaluate(
        basis,
        [_record(basis, ObservationStatus.FAILURE)],
    )

    assert not decision.allowed
    assert decision.reason is RetryReason.BLIND_RETRY_BLOCKED


def test_new_evidence_allows_a_retry() -> None:
    previous = _basis()
    current = _basis(evidence=("observation:new",))
    decision = RetryGuard().evaluate(
        current,
        [_record(previous, ObservationStatus.FAILURE)],
    )

    assert decision.allowed
    assert decision.reason is RetryReason.CHANGED_BASIS
    assert decision.changed_dimensions == ("evidence",)


def test_already_successful_identical_action_is_not_repeated() -> None:
    basis = _basis()
    decision = RetryGuard().evaluate(
        basis,
        [_record(basis, ObservationStatus.SUCCESS)],
    )

    assert not decision.allowed
    assert decision.reason is RetryReason.ALREADY_SUCCEEDED
