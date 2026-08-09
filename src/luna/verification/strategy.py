"""Risk- and evidence-aware verification strategy selection for Wave 2."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.enums import RiskLevel
from luna.contracts.plan import PlanStep
from luna.contracts.task import TaskContract
from luna.verification.models import EvidenceStrength


class VerificationDepth(StrEnum):
    """Amount of verification required before completion may be considered."""

    TARGETED = "TARGETED"
    BROAD = "BROAD"
    REGRESSION = "REGRESSION"


class VerificationStrategy(LunaContractModel):
    """Advisory verification plan that may strengthen, never weaken, gate policy."""

    depth: VerificationDepth
    required_checks: tuple[str, ...] = Field(min_length=1)
    minimum_strength_floor: EvidenceStrength = EvidenceStrength.STRONG
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("required_checks", "reason_codes")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("verification strategy entries cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("verification strategy entries must be unique")
        return cleaned


class VerificationStrategySelector:
    """Select deterministic verification depth from explicit task risk and contract needs."""

    def select(
        self,
        *,
        contract: TaskContract,
        step: PlanStep | None = None,
    ) -> VerificationStrategy:
        checks = list(contract.evidence_required)
        reasons: list[str] = ["contract_evidence_required"]

        if step is not None and step.expectation is not None:
            checks.append(step.expectation.verification_method)
            reasons.append("step_expectation_present")

        high_risk = contract.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        broad_contract = (
            len(contract.required_conditions) + len(contract.forbidden_outcomes) >= 3
            or contract.scope.write_allowed
        )

        if high_risk:
            depth = VerificationDepth.REGRESSION
            minimum_strength = EvidenceStrength.DETERMINISTIC
            reasons.append("high_or_critical_risk")
        elif broad_contract:
            depth = VerificationDepth.BROAD
            minimum_strength = EvidenceStrength.STRONG
            reasons.append("broad_or_mutating_contract")
        else:
            depth = VerificationDepth.TARGETED
            minimum_strength = EvidenceStrength.STRONG
            reasons.append("bounded_low_risk_contract")

        if depth is VerificationDepth.REGRESSION:
            checks.append("Run relevant regression checks after targeted verification.")
        elif depth is VerificationDepth.BROAD:
            checks.append("Verify adjacent contract-relevant behavior after the targeted check.")
        else:
            checks.append("Verify the directly affected contract requirement.")

        return VerificationStrategy(
            depth=depth,
            required_checks=tuple(dict.fromkeys(checks)),
            minimum_strength_floor=minimum_strength,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )
