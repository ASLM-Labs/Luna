"""Versioned deterministic-verification and completion-gate contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from luna.contracts.base import LunaContractModel, require_utc, utc_now
from luna.contracts.enums import CompletionStatus


class ClaimKind(StrEnum):
    """Contract claim category."""

    REQUIRED_CONDITION = "REQUIRED_CONDITION"
    FORBIDDEN_OUTCOME_ABSENT = "FORBIDDEN_OUTCOME_ABSENT"


class ClaimStatus(StrEnum):
    """Deterministic outcome for one requirement claim."""

    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTING = "CONFLICTING"


class EvidenceRejectionCode(StrEnum):
    """Why an evidence record was excluded from current verification."""

    WRONG_TASK = "WRONG_TASK"
    REVISION_MISSING = "REVISION_MISSING"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"
    FRESHNESS_MISSING = "FRESHNESS_MISSING"
    STALE = "STALE"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"


class VerificationClaim(LunaContractModel):
    """One required or forbidden-absence claim derived from TaskContract."""

    claim_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^(required|forbidden_absent):sha256:[0-9a-f]{64}$",
    )
    kind: ClaimKind
    text: str = Field(min_length=1, max_length=4000)


class EvidenceRejection(LunaContractModel):
    """Traceable evidence exclusion."""

    evidence_id: UUID
    code: EvidenceRejectionCode
    reason: str = Field(min_length=1, max_length=4000)


class ClaimAssessment(LunaContractModel):
    """Deterministic assessment for one contract claim."""

    claim: VerificationClaim
    status: ClaimStatus
    considered_evidence_ids: tuple[UUID, ...] = ()
    qualifying_evidence_ids: tuple[UUID, ...] = ()
    reasons: tuple[str, ...] = ()

    @field_validator(
        "considered_evidence_ids",
        "qualifying_evidence_ids",
    )
    @classmethod
    def validate_unique_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("evidence IDs must be unique")
        return values

    @field_validator("reasons")
    @classmethod
    def validate_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("assessment reasons must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("assessment reasons must be unique")
        return cleaned


class EvidenceRequirementAssessment(LunaContractModel):
    """Whether a human-readable contract evidence requirement was met."""

    requirement: str = Field(min_length=1, max_length=4000)
    status: ClaimStatus
    matched_evidence_ids: tuple[UUID, ...] = ()
    recognized_rules: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @field_validator("matched_evidence_ids")
    @classmethod
    def validate_matched_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("matched evidence IDs must be unique")
        return values

    @field_validator("recognized_rules", "reasons")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("assessment text entries must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("assessment text entries must be unique")
        return cleaned


class VerificationPolicy(LunaContractModel):
    """Hard rules used by DeterministicVerifier."""

    current_revision: str = Field(min_length=1, max_length=500)
    expected_environment_fingerprint: str | None = Field(
        default=None,
        max_length=1000,
    )
    max_freshness_seconds: int = Field(default=3600, ge=0)
    min_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    require_reproducible: bool = True
    require_revision: bool = True
    require_freshness: bool = True
    future_clock_tolerance_seconds: int = Field(default=5, ge=0)


class VerificationReport(LunaContractModel):
    """Full deterministic requirement-to-evidence verification report."""

    report_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    policy: VerificationPolicy
    claim_assessments: tuple[ClaimAssessment, ...]
    evidence_requirement_assessments: tuple[EvidenceRequirementAssessment, ...]
    accepted_evidence_ids: tuple[UUID, ...] = ()
    rejected_evidence: tuple[EvidenceRejection, ...] = ()
    unmatched_requirement_ids: tuple[str, ...] = ()
    completion_status: CompletionStatus
    rationale: tuple[str, ...]
    generated_at: datetime = Field(default_factory=utc_now)

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("accepted_evidence_ids")
    @classmethod
    def validate_accepted_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("accepted evidence IDs must be unique")
        return values

    @field_validator("unmatched_requirement_ids", "rationale")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("report text entries must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("report text entries must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_verified_complete(self) -> VerificationReport:
        if self.completion_status is CompletionStatus.VERIFIED_COMPLETE:
            if any(
                item.status is not ClaimStatus.PASS
                for item in self.claim_assessments
            ):
                raise ValueError("VERIFIED_COMPLETE requires all claims to PASS")
            if any(
                item.status is not ClaimStatus.PASS
                for item in self.evidence_requirement_assessments
            ):
                raise ValueError(
                    "VERIFIED_COMPLETE requires all evidence requirements to PASS"
                )
            if self.rejected_evidence:
                rejected_current_claims = {
                    item.evidence_id for item in self.rejected_evidence
                }
                if rejected_current_claims & set(self.accepted_evidence_ids):
                    raise ValueError(
                        "evidence cannot be both accepted and rejected"
                    )
        return self

    def semantic_signature(self) -> tuple[object, ...]:
        """Return stable fields for deterministic regression tests."""
        return (
            self.task_id,
            self.policy,
            tuple(
                (
                    item.claim.claim_id,
                    item.status,
                    item.considered_evidence_ids,
                    item.qualifying_evidence_ids,
                    item.reasons,
                )
                for item in self.claim_assessments
            ),
            tuple(
                (
                    item.requirement,
                    item.status,
                    item.matched_evidence_ids,
                    item.recognized_rules,
                    item.reasons,
                )
                for item in self.evidence_requirement_assessments
            ),
            self.accepted_evidence_ids,
            tuple(
                (item.evidence_id, item.code, item.reason)
                for item in self.rejected_evidence
            ),
            self.unmatched_requirement_ids,
            self.completion_status,
            self.rationale,
        )


class CompletionDecision(LunaContractModel):
    """Authoritative completion decision produced only by CompletionGate."""

    decision_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    report_id: UUID
    status: CompletionStatus
    reasons: tuple[str, ...]
    deterministic: bool = True
    decided_at: datetime = Field(default_factory=utc_now)

    @field_validator("decided_at")
    @classmethod
    def validate_decided_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("reasons")
    @classmethod
    def validate_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if not cleaned or any(not value for value in cleaned):
            raise ValueError("completion decision requires non-empty reasons")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("completion reasons must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_deterministic_flag(self) -> CompletionDecision:
        if not self.deterministic:
            raise ValueError("Luna 0.1 completion decisions must be deterministic")
        return self


class CompletionGateResult(LunaContractModel):
    """Verification report and its audited completion decision."""

    report: VerificationReport
    decision: CompletionDecision
    verification_event_id: UUID
    completion_event_id: UUID

    @model_validator(mode="after")
    def validate_links(self) -> CompletionGateResult:
        if self.report.task_id != self.decision.task_id:
            raise ValueError("report and decision task IDs must match")
        if self.report.report_id != self.decision.report_id:
            raise ValueError("decision must reference the verification report")
        if self.report.completion_status is not self.decision.status:
            raise ValueError("report and decision statuses must match")
        return self
