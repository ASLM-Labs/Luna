"""Deterministic, non-authoritative verification diagnostics."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from luna.contracts.base import LunaContractModel
from luna.contracts.enums import CompletionStatus
from luna.verification.delta import (
    VerificationEvidenceIdentityConflict,
    build_verification_delta,
)
from luna.verification.episode import (
    VerificationEpisodeManifest,
    compute_artifact_sha256,
    validate_verification_episode_report_binding,
)
from luna.verification.models import (
    ClaimKind,
    ClaimStatus,
    EvidenceRejectionCode,
    EvidenceStrength,
    VerificationReport,
)

VERIFICATION_DIAGNOSTIC_SEMANTICS_VERSION = "1"


class DiagnosticClaimGap(LunaContractModel):
    """One unresolved verifier claim without causal reinterpretation."""

    claim_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^(required|forbidden_absent):sha256:[0-9a-f]{64}$",
    )
    kind: ClaimKind
    text: str = Field(min_length=1, max_length=4000)
    status: ClaimStatus
    considered_evidence_ids: tuple[UUID, ...] = ()
    qualifying_evidence_ids: tuple[UUID, ...] = ()
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_unresolved(self) -> DiagnosticClaimGap:
        if self.status is ClaimStatus.PASS:
            raise ValueError("diagnostic claim gap cannot have PASS status")
        return self


class DiagnosticRequirementGap(LunaContractModel):
    """One unresolved human-readable evidence requirement."""

    requirement: str = Field(min_length=1, max_length=4000)
    status: ClaimStatus
    matched_evidence_ids: tuple[UUID, ...] = ()
    recognized_rules: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_unresolved(self) -> DiagnosticRequirementGap:
        if self.status is ClaimStatus.PASS:
            raise ValueError(
                "diagnostic requirement gap cannot have PASS status"
            )
        return self


class DiagnosticRejectedEvidenceIssue(LunaContractModel):
    """One verifier-rejected evidence payload bound to its episode identity."""

    evidence_id: UUID
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code: EvidenceRejectionCode
    reason: str = Field(min_length=1, max_length=4000)

class DiagnosticNonQualifyingEvidenceIssue(LunaContractModel):
    """Accepted evidence that does not satisfy current strength policy."""

    evidence_id: UUID
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    strength: EvidenceStrength
    reasons: tuple[str, ...] = Field(min_length=1)

class DiagnosticEvidenceRef(LunaContractModel):
    """Reference to one exact frozen evidence payload."""

    evidence_id: UUID
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DiagnosticDisagreement(LunaContractModel):
    """One unresolved verifier disagreement bound to exact evidence payloads."""

    claim_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^(required|forbidden_absent):sha256:[0-9a-f]{64}$",
    )
    supporting_evidence: tuple[DiagnosticEvidenceRef, ...] = Field(
        min_length=1
    )
    contradicting_evidence: tuple[DiagnosticEvidenceRef, ...] = Field(
        min_length=1
    )
    strongest_support: EvidenceStrength
    strongest_contradiction: EvidenceStrength
    unresolved: Literal[True] = True

    @model_validator(mode="after")
    def validate_disjoint_sides(self) -> DiagnosticDisagreement:
        supporting_ids = {
            item.evidence_id
            for item in self.supporting_evidence
        }
        contradicting_ids = {
            item.evidence_id
            for item in self.contradicting_evidence
        }

        if supporting_ids & contradicting_ids:
            raise ValueError(
                "diagnostic disagreement evidence sides must be disjoint"
            )

        return self

class DiagnosticProgress(LunaContractModel):
    """Non-causal progress projection between verification episodes."""

    resolved_claim_ids: tuple[str, ...] = ()
    regressed_claim_ids: tuple[str, ...] = ()
    remaining_claim_ids: tuple[str, ...] = ()

    resolved_requirements: tuple[str, ...] = ()
    regressed_requirements: tuple[str, ...] = ()
    remaining_requirements: tuple[str, ...] = ()


class _VerificationDiagnosticIdentityPayload(LunaContractModel):
    """Semantic content that defines diagnostic assessment identity."""

    diagnostic_semantics_version: str
    task_id: UUID
    completion_status: CompletionStatus
    claim_gaps: tuple[DiagnosticClaimGap, ...]
    requirement_gaps: tuple[DiagnosticRequirementGap, ...]
    rejected_evidence_issues: tuple[DiagnosticRejectedEvidenceIssue, ...]
    nonqualifying_evidence_issues: tuple[
        DiagnosticNonQualifyingEvidenceIssue,
        ...,
    ]
    disagreements: tuple[DiagnosticDisagreement, ...]
    evidence_identity_conflicts: tuple[
        VerificationEvidenceIdentityConflict,
        ...,
    ] = ()
    progress: DiagnosticProgress | None = None

    execution_authority: bool
    verification_authority: bool
    completion_authority: bool


def _verification_diagnostic_identity_payload(
    *,
    diagnostic_semantics_version: str,
    task_id: UUID,
    completion_status: CompletionStatus,
    claim_gaps: tuple[DiagnosticClaimGap, ...],
    requirement_gaps: tuple[DiagnosticRequirementGap, ...],
    rejected_evidence_issues: tuple[DiagnosticRejectedEvidenceIssue, ...],
    nonqualifying_evidence_issues: tuple[
        DiagnosticNonQualifyingEvidenceIssue,
        ...,
    ],
    disagreements: tuple[DiagnosticDisagreement, ...],
    evidence_identity_conflicts: tuple[
        VerificationEvidenceIdentityConflict,
        ...,
    ],
    progress: DiagnosticProgress | None,
    execution_authority: bool,
    verification_authority: bool,
    completion_authority: bool,
) -> _VerificationDiagnosticIdentityPayload:
    """Return the canonical semantic payload bound by an assessment ID."""
    return _VerificationDiagnosticIdentityPayload(
        diagnostic_semantics_version=diagnostic_semantics_version,
        task_id=task_id,
        completion_status=completion_status,
        claim_gaps=claim_gaps,
        requirement_gaps=requirement_gaps,
        rejected_evidence_issues=rejected_evidence_issues,
        nonqualifying_evidence_issues=nonqualifying_evidence_issues,
        disagreements=disagreements,
        evidence_identity_conflicts=evidence_identity_conflicts,
        progress=progress,
        execution_authority=execution_authority,
        verification_authority=verification_authority,
        completion_authority=completion_authority,
    )


class VerificationDiagnosticAssessment(LunaContractModel):
    """Agent-facing explanation of current verification state."""

    assessment_id: str = Field(
        pattern=r"^verification-diagnostic:sha256:[0-9a-f]{64}$"
    )
    diagnostic_semantics_version: str = Field(
        default=VERIFICATION_DIAGNOSTIC_SEMANTICS_VERSION,
        min_length=1,
        max_length=100,
    )

    task_id: UUID
    episode_id: str = Field(
        pattern=r"^verification-episode:sha256:[0-9a-f]{64}$"
    )
    verification_report_id: UUID
    completion_status: CompletionStatus

    claim_gaps: tuple[DiagnosticClaimGap, ...] = ()
    requirement_gaps: tuple[DiagnosticRequirementGap, ...] = ()
    rejected_evidence_issues: tuple[DiagnosticRejectedEvidenceIssue, ...]
    nonqualifying_evidence_issues: tuple[
        DiagnosticNonQualifyingEvidenceIssue,
        ...,
    ]
    disagreements: tuple[DiagnosticDisagreement, ...] = ()
    evidence_identity_conflicts: tuple[
        VerificationEvidenceIdentityConflict,
        ...,
    ] = ()

    previous_episode_id: str | None = Field(
        default=None,
        pattern=r"^verification-episode:sha256:[0-9a-f]{64}$",
    )
    delta_id: str | None = Field(
        default=None,
        pattern=r"^verification-delta:sha256:[0-9a-f]{64}$",
    )
    progress: DiagnosticProgress | None = None

    execution_authority: Literal[False] = False
    verification_authority: Literal[False] = False
    completion_authority: Literal[False] = False


def compute_verification_diagnostic_assessment_id(
    assessment: VerificationDiagnosticAssessment,
) -> str:
    """Compute semantic identity independently of occurrence provenance."""
    identity_payload = _verification_diagnostic_identity_payload(
        diagnostic_semantics_version=(
            assessment.diagnostic_semantics_version
        ),
        task_id=assessment.task_id,
        completion_status=assessment.completion_status,
        claim_gaps=assessment.claim_gaps,
        requirement_gaps=assessment.requirement_gaps,
        rejected_evidence_issues=assessment.rejected_evidence_issues,
        nonqualifying_evidence_issues=(
            assessment.nonqualifying_evidence_issues
        ),
        disagreements=assessment.disagreements,
        evidence_identity_conflicts=(
            assessment.evidence_identity_conflicts
        ),
        progress=assessment.progress,
        execution_authority=assessment.execution_authority,
        verification_authority=assessment.verification_authority,
        completion_authority=assessment.completion_authority,
    )

    digest = compute_artifact_sha256(identity_payload)
    return f"verification-diagnostic:sha256:{digest}"


def validate_verification_diagnostic_assessment_integrity(
    assessment: VerificationDiagnosticAssessment,
) -> VerificationDiagnosticAssessment:
    """Validate semantic content against its content-addressed identity."""
    expected_id = compute_verification_diagnostic_assessment_id(
        assessment
    )

    if assessment.assessment_id != expected_id:
        raise ValueError(
            "verification diagnostic assessment ID "
            "does not match semantic payload"
        )

    return assessment


def validate_verification_diagnostic_assessment_binding(
    *,
    assessment: VerificationDiagnosticAssessment,
    episode: VerificationEpisodeManifest,
    report: VerificationReport,
    previous_episode: VerificationEpisodeManifest | None = None,
    previous_report: VerificationReport | None = None,
) -> VerificationDiagnosticAssessment:
    """Bind a diagnostic assessment to its canonical verification inputs."""
    validate_verification_diagnostic_assessment_integrity(assessment)

    validate_verification_episode_report_binding(
        episode=episode,
        report=report,
    )

    if assessment.episode_id != episode.episode_id:
        raise ValueError(
            "verification diagnostic episode provenance "
            "does not match episode"
        )

    if assessment.verification_report_id != report.report_id:
        raise ValueError(
            "verification diagnostic report provenance "
            "does not match report"
        )

    expected = build_verification_diagnostic_assessment(
        episode=episode,
        report=report,
        previous_episode=previous_episode,
        previous_report=previous_report,
    )

    if assessment.assessment_id != expected.assessment_id:
        raise ValueError(
            "verification diagnostic semantic payload "
            "does not match bound verification inputs"
        )

    if assessment.previous_episode_id != expected.previous_episode_id:
        raise ValueError(
            "verification diagnostic previous episode provenance "
            "does not match verification inputs"
        )

    if assessment.delta_id != expected.delta_id:
        raise ValueError(
            "verification diagnostic delta provenance "
            "does not match verification inputs"
        )

    if assessment != expected:
        raise ValueError(
            "verification diagnostic assessment "
            "does not match canonical projection"
        )

    return assessment

def build_verification_diagnostic_assessment(
    *,
    episode: VerificationEpisodeManifest,
    report: VerificationReport,
    previous_episode: VerificationEpisodeManifest | None = None,
    previous_report: VerificationReport | None = None,
) -> VerificationDiagnosticAssessment:
    """Project verified report state into deterministic diagnostic gaps."""
    validate_verification_episode_report_binding(
        episode=episode,
        report=report,
    )

    claim_gaps = tuple(
        DiagnosticClaimGap(
            claim_id=item.claim.claim_id,
            kind=item.claim.kind,
            text=item.claim.text,
            status=item.status,
            considered_evidence_ids=item.considered_evidence_ids,
            qualifying_evidence_ids=item.qualifying_evidence_ids,
            reasons=item.reasons,
        )
        for item in report.claim_assessments
        if item.status is not ClaimStatus.PASS
    )

    requirement_gaps = tuple(
        DiagnosticRequirementGap(
            requirement=item.requirement,
            status=item.status,
            matched_evidence_ids=item.matched_evidence_ids,
            recognized_rules=item.recognized_rules,
            reasons=item.reasons,
        )
        for item in report.evidence_requirement_assessments
        if item.status is not ClaimStatus.PASS
    )

    evidence_refs = {
        item.evidence_id: item
        for item in episode.input_evidence
    }

    rejected_evidence_issues = tuple(
        DiagnosticRejectedEvidenceIssue(
            evidence_id=item.evidence_id,
            payload_sha256=evidence_refs[item.evidence_id].payload_sha256,
            code=item.code,
            reason=item.reason,
        )
        for item in report.rejected_evidence
    )
    nonqualifying_evidence_issues = tuple(
        DiagnosticNonQualifyingEvidenceIssue(
            evidence_id=item.evidence_id,
            payload_sha256=evidence_refs[item.evidence_id].payload_sha256,
            strength=item.strength,
            reasons=item.reasons,
        )
        for item in report.evidence_strength_assessments
        if not item.qualifying
    )
    disagreements = tuple(
        DiagnosticDisagreement(
            claim_id=item.claim_id,
            supporting_evidence=tuple(
                DiagnosticEvidenceRef(
                    evidence_id=evidence_id,
                    payload_sha256=(
                        evidence_refs[evidence_id].payload_sha256
                    ),
                )
                for evidence_id in item.supporting_evidence_ids
            ),
            contradicting_evidence=tuple(
                DiagnosticEvidenceRef(
                    evidence_id=evidence_id,
                    payload_sha256=(
                        evidence_refs[evidence_id].payload_sha256
                    ),
                )
                for evidence_id in item.contradicting_evidence_ids
            ),
            strongest_support=item.strongest_support,
            strongest_contradiction=item.strongest_contradiction,
            unresolved=True,
        )
        for item in report.disagreements
    )
    if (previous_episode is None) != (previous_report is None):
        raise ValueError(
            "previous episode and report must be provided together"
        )

    previous_episode_id: str | None = None
    delta_id: str | None = None
    progress: DiagnosticProgress | None = None
    evidence_identity_conflicts: tuple[
        VerificationEvidenceIdentityConflict,
        ...,
    ] = ()

    if previous_episode is not None and previous_report is not None:
        delta = build_verification_delta(
            before_episode=previous_episode,
            before_report=previous_report,
            after_episode=episode,
            after_report=report,
        )

        resolved_claim_ids = tuple(
            change.claim_id
            for change in delta.claim_changes
            if (
                change.before is not None
                and change.after is not None
                and change.before.status is not ClaimStatus.PASS
                and change.after.status is ClaimStatus.PASS
            )
        )
        regressed_claim_ids = tuple(
            change.claim_id
            for change in delta.claim_changes
            if (
                change.before is not None
                and change.after is not None
                and change.before.status is ClaimStatus.PASS
                and change.after.status is not ClaimStatus.PASS
            )
        )
        remaining_claim_ids = tuple(
            assessment.claim.claim_id
            for assessment in report.claim_assessments
            if assessment.status is not ClaimStatus.PASS
        )

        resolved_requirements = tuple(
            change.requirement
            for change in delta.evidence_requirement_changes
            if (
                change.before is not None
                and change.after is not None
                and change.before.status is not ClaimStatus.PASS
                and change.after.status is ClaimStatus.PASS
            )
        )
        regressed_requirements = tuple(
            change.requirement
            for change in delta.evidence_requirement_changes
            if (
                change.before is not None
                and change.after is not None
                and change.before.status is ClaimStatus.PASS
                and change.after.status is not ClaimStatus.PASS
            )
        )
        remaining_requirements = tuple(
            assessment.requirement
            for assessment in report.evidence_requirement_assessments
            if assessment.status is not ClaimStatus.PASS
        )

        progress = DiagnosticProgress(
            resolved_claim_ids=resolved_claim_ids,
            regressed_claim_ids=regressed_claim_ids,
            remaining_claim_ids=remaining_claim_ids,
            resolved_requirements=resolved_requirements,
            regressed_requirements=regressed_requirements,
            remaining_requirements=remaining_requirements,
        )

        previous_episode_id = previous_episode.episode_id
        delta_id = delta.delta_id
        evidence_identity_conflicts = delta.evidence_identity_conflicts

    identity_payload = _verification_diagnostic_identity_payload(
        diagnostic_semantics_version=(
            VERIFICATION_DIAGNOSTIC_SEMANTICS_VERSION
        ),
        task_id=episode.task_id,
        completion_status=report.completion_status,
        claim_gaps=claim_gaps,
        requirement_gaps=requirement_gaps,
        rejected_evidence_issues=rejected_evidence_issues,
        nonqualifying_evidence_issues=nonqualifying_evidence_issues,
        disagreements=disagreements,
        evidence_identity_conflicts=evidence_identity_conflicts,
        progress=progress,
        execution_authority=False,
        verification_authority=False,
        completion_authority=False,
    )

    assessment_digest = compute_artifact_sha256(identity_payload)

    return VerificationDiagnosticAssessment(
        assessment_id=(
            f"verification-diagnostic:sha256:{assessment_digest}"
        ),
        task_id=episode.task_id,
        episode_id=episode.episode_id,
        verification_report_id=report.report_id,
        completion_status=report.completion_status,
        claim_gaps=claim_gaps,
        requirement_gaps=requirement_gaps,
        rejected_evidence_issues=rejected_evidence_issues,
        nonqualifying_evidence_issues=nonqualifying_evidence_issues,
        disagreements=disagreements,
        evidence_identity_conflicts=evidence_identity_conflicts,
        previous_episode_id=previous_episode_id,
        delta_id=delta_id,
        progress=progress,
    )
