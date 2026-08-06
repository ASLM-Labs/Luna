"""Stable claim identifiers derived from the authoritative task contract."""

from __future__ import annotations

from hashlib import sha256

from luna.contracts.task import TaskContract
from luna.verification.models import ClaimKind, VerificationClaim


def _claim_id(prefix: str, text: str) -> str:
    normalized = " ".join(text.split())
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    return f"{prefix}:sha256:{digest}"


def required_condition_claim_id(condition: str) -> str:
    """Return the evidence requirement_id for one required condition."""
    return _claim_id("required", condition)


def forbidden_absence_claim_id(outcome: str) -> str:
    """Return the evidence requirement_id proving a forbidden outcome is absent."""
    return _claim_id("forbidden_absent", outcome)


def claims_from_contract(contract: TaskContract) -> tuple[VerificationClaim, ...]:
    """Build deterministic claims in contract order."""
    claims: list[VerificationClaim] = [
        VerificationClaim(
            claim_id=required_condition_claim_id(condition),
            kind=ClaimKind.REQUIRED_CONDITION,
            text=condition,
        )
        for condition in contract.required_conditions
    ]
    claims.extend(
        VerificationClaim(
            claim_id=forbidden_absence_claim_id(outcome),
            kind=ClaimKind.FORBIDDEN_OUTCOME_ABSENT,
            text=outcome,
        )
        for outcome in contract.forbidden_outcomes
    )
    return tuple(claims)
