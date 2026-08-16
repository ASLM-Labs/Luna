"""Deterministic, non-authoritative comparisons of verification episodes."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from luna.contracts.base import LunaContractModel, stable_payload
from luna.contracts.enums import CompletionStatus
from luna.verification.episode import (
    VerificationEpisodeManifest,
    compute_artifact_sha256,
)
from luna.verification.models import (
    ClaimAssessment,
    ClaimKind,
    ClaimStatus,
    EvidenceDisagreement,
    EvidenceRejectionCode,
    EvidenceRequirementAssessment,
    EvidenceStrength,
    VerificationReport,
)

VERIFICATION_DELTA_SEMANTICS_VERSION = "1"


class VerificationEvidenceState(LunaContractModel):
    """Report-derived state of one exact episode evidence input."""

    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted: bool
    rejection_code: EvidenceRejectionCode | None = None
    rejection_reason: str | None = Field(
        default=None,
        min_length=1,
        max_length=4000,
    )
    strength: EvidenceStrength | None = None
    qualifying: bool | None = None
    strength_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_consistency(self) -> VerificationEvidenceState:
        if self.accepted and self.rejection_code is not None:
            raise ValueError("accepted evidence cannot carry a rejection")

        if (self.rejection_code is None) != (self.rejection_reason is None):
            raise ValueError(
                "rejection code and reason must be present together"
            )

        if (self.strength is None) != (self.qualifying is None):
            raise ValueError(
                "strength and qualifying must be present together"
            )

        if self.strength is None and self.strength_reasons:
            raise ValueError(
                "strength reasons require a strength assessment"
            )

        return self


class VerificationEvidenceChange(LunaContractModel):
    """Before/after state for one evidence identity."""

    evidence_id: UUID
    before: VerificationEvidenceState | None = None
    after: VerificationEvidenceState | None = None

    @model_validator(mode="after")
    def validate_change(self) -> VerificationEvidenceChange:
        if self.before is None and self.after is None:
            raise ValueError(
                "evidence change requires a before or after state"
            )
        if self.before == self.after:
            raise ValueError(
                "evidence change must describe an actual change"
            )
        return self


class VerificationEvidenceIdentityConflict(LunaContractModel):
    """Same evidence ID bound to different immutable payload digests."""

    evidence_id: UUID
    before_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_distinct_hashes(
        self,
    ) -> VerificationEvidenceIdentityConflict:
        if self.before_payload_sha256 == self.after_payload_sha256:
            raise ValueError(
                "identity conflict requires different payload digests"
            )
        return self


class VerificationClaimState(LunaContractModel):
    """Semantic verifier output for one contract claim."""

    kind: ClaimKind
    text: str = Field(min_length=1, max_length=4000)
    status: ClaimStatus
    considered_evidence_ids: tuple[UUID, ...] = ()
    qualifying_evidence_ids: tuple[UUID, ...] = ()
    reasons: tuple[str, ...] = ()


class VerificationClaimChange(LunaContractModel):
    """Before/after semantic state of one verification claim."""

    claim_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^(required|forbidden_absent):sha256:[0-9a-f]{64}$",
    )
    before: VerificationClaimState | None = None
    after: VerificationClaimState | None = None

    @model_validator(mode="after")
    def validate_change(self) -> VerificationClaimChange:
        if self.before is None and self.after is None:
            raise ValueError(
                "claim change requires a before or after state"
            )
        if self.before == self.after:
            raise ValueError(
                "claim change must describe an actual change"
            )
        return self


class VerificationRequirementState(LunaContractModel):
    """Semantic verifier output for one evidence requirement."""

    status: ClaimStatus
    matched_evidence_ids: tuple[UUID, ...] = ()
    recognized_rules: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


class VerificationRequirementChange(LunaContractModel):
    """Before/after state of one evidence requirement."""

    requirement: str = Field(min_length=1, max_length=4000)
    before: VerificationRequirementState | None = None
    after: VerificationRequirementState | None = None

    @model_validator(mode="after")
    def validate_change(self) -> VerificationRequirementChange:
        if self.before is None and self.after is None:
            raise ValueError(
                "requirement change requires a before or after state"
            )
        if self.before == self.after:
            raise ValueError(
                "requirement change must describe an actual change"
            )
        return self


class VerificationDisagreementState(LunaContractModel):
    """Semantic state of one unresolved evidence disagreement."""

    supporting_evidence_ids: tuple[UUID, ...]
    contradicting_evidence_ids: tuple[UUID, ...]
    strongest_support: EvidenceStrength
    strongest_contradiction: EvidenceStrength
    unresolved: bool


class VerificationDisagreementChange(LunaContractModel):
    """Before/after disagreement state for one claim."""

    claim_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^(required|forbidden_absent):sha256:[0-9a-f]{64}$",
    )
    before: VerificationDisagreementState | None = None
    after: VerificationDisagreementState | None = None

    @model_validator(mode="after")
    def validate_change(self) -> VerificationDisagreementChange:
        if self.before is None and self.after is None:
            raise ValueError(
                "disagreement change requires a before or after state"
            )
        if self.before == self.after:
            raise ValueError(
                "disagreement change must describe an actual change"
            )
        return self


class _VerificationDeltaIdentityPayload(LunaContractModel):
    """Canonical content used to derive delta identity."""

    delta_semantics_version: str
    task_id: UUID
    before_episode_id: str
    after_episode_id: str

    contract_changed: bool
    policy_changed: bool
    verifier_semantics_changed: bool
    verification_time_changed: bool
    verification_basis_changed: bool
    source_task_revision_changed: bool
    verification_output_changed: bool

    before_completion_status: CompletionStatus
    after_completion_status: CompletionStatus

    evidence_changes: tuple[VerificationEvidenceChange, ...]
    evidence_identity_conflicts: tuple[
        VerificationEvidenceIdentityConflict,
        ...,
    ]
    claim_changes: tuple[VerificationClaimChange, ...]
    evidence_requirement_changes: tuple[
        VerificationRequirementChange,
        ...,
    ]
    disagreement_changes: tuple[
        VerificationDisagreementChange,
        ...,
    ]

    verification_authority: Literal[False] = False
    completion_authority: Literal[False] = False


class VerificationDelta(LunaContractModel):
    """Content-addressed comparison of two frozen verification episodes."""

    delta_id: str = Field(
        pattern=r"^verification-delta:sha256:[0-9a-f]{64}$"
    )
    task_id: UUID

    before_episode_id: str = Field(
        pattern=r"^verification-episode:sha256:[0-9a-f]{64}$"
    )
    after_episode_id: str = Field(
        pattern=r"^verification-episode:sha256:[0-9a-f]{64}$"
    )

    delta_semantics_version: str = Field(
        default=VERIFICATION_DELTA_SEMANTICS_VERSION,
        min_length=1,
        max_length=100,
    )

    contract_changed: bool
    policy_changed: bool
    verifier_semantics_changed: bool
    verification_time_changed: bool
    verification_basis_changed: bool
    source_task_revision_changed: bool
    verification_output_changed: bool

    before_completion_status: CompletionStatus
    after_completion_status: CompletionStatus

    evidence_changes: tuple[VerificationEvidenceChange, ...] = ()
    evidence_identity_conflicts: tuple[
        VerificationEvidenceIdentityConflict,
        ...,
    ] = ()
    claim_changes: tuple[VerificationClaimChange, ...] = ()
    evidence_requirement_changes: tuple[
        VerificationRequirementChange,
        ...,
    ] = ()
    disagreement_changes: tuple[
        VerificationDisagreementChange,
        ...,
    ] = ()

    verification_authority: Literal[False] = False
    completion_authority: Literal[False] = False


def _unique_map[K: Hashable, T](
    items: tuple[T, ...],
    key: Callable[[T], K],
    *,
    label: str,
) -> dict[K, T]:
    result: dict[K, T] = {}

    for item in items:
        item_key = key(item)
        if item_key in result:
            raise ValueError(
                f"duplicate {label} identity in verification report"
            )
        result[item_key] = item

    return result


def _validate_report_binding(
    *,
    episode: VerificationEpisodeManifest,
    report: VerificationReport,
    label: str,
) -> None:
    if report.task_id != episode.task_id:
        raise ValueError(
            f"{label} report task does not match episode"
        )

    if report.report_id != episode.verification_report_id:
        raise ValueError(
            f"{label} report ID does not match episode"
        )

    if (
        compute_artifact_sha256(report)
        != episode.verification_report_sha256
    ):
        raise ValueError(
            f"{label} report digest does not match episode"
        )

    if (
        compute_artifact_sha256(report.policy)
        != episode.verification_policy_sha256
    ):
        raise ValueError(
            f"{label} report policy digest does not match episode"
        )

    if report.generated_at != episode.verification_time:
        raise ValueError(
            f"{label} report verification time does not match episode"
        )

    input_ids = {
        item.evidence_id
        for item in episode.input_evidence
    }

    referenced_ids = set(report.accepted_evidence_ids)

    referenced_ids.update(
        item.evidence_id
        for item in report.rejected_evidence
    )
    referenced_ids.update(
        item.evidence_id
        for item in report.evidence_strength_assessments
    )

    for claim_assessment in report.claim_assessments:
        referenced_ids.update(
            claim_assessment.considered_evidence_ids
        )
        referenced_ids.update(
            claim_assessment.qualifying_evidence_ids
        )

    for requirement_assessment in report.evidence_requirement_assessments:
        referenced_ids.update(
            requirement_assessment.matched_evidence_ids
        )

    for disagreement in report.disagreements:
        referenced_ids.update(
            disagreement.supporting_evidence_ids
        )
        referenced_ids.update(
            disagreement.contradicting_evidence_ids
        )

    if not referenced_ids.issubset(input_ids):
        raise ValueError(
            f"{label} report references evidence absent from episode"
        )


def _evidence_states(
    episode: VerificationEpisodeManifest,
    report: VerificationReport,
) -> dict[UUID, VerificationEvidenceState]:
    refs = _unique_map(
        episode.input_evidence,
        lambda item: item.evidence_id,
        label="evidence",
    )
    rejections = _unique_map(
        report.rejected_evidence,
        lambda item: item.evidence_id,
        label="rejection",
    )
    strengths = _unique_map(
        report.evidence_strength_assessments,
        lambda item: item.evidence_id,
        label="strength assessment",
    )

    accepted = set(report.accepted_evidence_ids)
    states: dict[UUID, VerificationEvidenceState] = {}

    for evidence_id, ref in refs.items():
        rejection = rejections.get(evidence_id)
        strength = strengths.get(evidence_id)

        states[evidence_id] = VerificationEvidenceState(
            payload_sha256=ref.payload_sha256,
            accepted=evidence_id in accepted,
            rejection_code=(
                rejection.code
                if rejection is not None
                else None
            ),
            rejection_reason=(
                rejection.reason
                if rejection is not None
                else None
            ),
            strength=(
                strength.strength
                if strength is not None
                else None
            ),
            qualifying=(
                strength.qualifying
                if strength is not None
                else None
            ),
            strength_reasons=(
                strength.reasons
                if strength is not None
                else ()
            ),
        )

    return states


def _claim_state(
    item: ClaimAssessment,
) -> VerificationClaimState:
    return VerificationClaimState(
        kind=item.claim.kind,
        text=item.claim.text,
        status=item.status,
        considered_evidence_ids=item.considered_evidence_ids,
        qualifying_evidence_ids=item.qualifying_evidence_ids,
        reasons=item.reasons,
    )


def _claim_states(
    report: VerificationReport,
) -> dict[str, VerificationClaimState]:
    assessments = _unique_map(
        report.claim_assessments,
        lambda item: item.claim.claim_id,
        label="claim",
    )

    return {
        claim_id: _claim_state(item)
        for claim_id, item in assessments.items()
    }


def _requirement_state(
    item: EvidenceRequirementAssessment,
) -> VerificationRequirementState:
    return VerificationRequirementState(
        status=item.status,
        matched_evidence_ids=item.matched_evidence_ids,
        recognized_rules=item.recognized_rules,
        reasons=item.reasons,
    )


def _requirement_states(
    report: VerificationReport,
) -> dict[str, VerificationRequirementState]:
    assessments = _unique_map(
        report.evidence_requirement_assessments,
        lambda item: item.requirement,
        label="evidence requirement",
    )

    return {
        requirement: _requirement_state(item)
        for requirement, item in assessments.items()
    }


def _disagreement_state(
    item: EvidenceDisagreement,
) -> VerificationDisagreementState:
    return VerificationDisagreementState(
        supporting_evidence_ids=item.supporting_evidence_ids,
        contradicting_evidence_ids=item.contradicting_evidence_ids,
        strongest_support=item.strongest_support,
        strongest_contradiction=item.strongest_contradiction,
        unresolved=item.unresolved,
    )


def _disagreement_states(
    report: VerificationReport,
) -> dict[str, VerificationDisagreementState]:
    disagreements = _unique_map(
        report.disagreements,
        lambda item: item.claim_id,
        label="disagreement",
    )

    return {
        claim_id: _disagreement_state(item)
        for claim_id, item in disagreements.items()
    }


def _semantic_report_payload(
    report: VerificationReport,
) -> dict[str, object]:
    return {
        "claim_assessments": tuple(
            stable_payload(item)
            for item in report.claim_assessments
        ),
        "evidence_requirement_assessments": tuple(
            stable_payload(item)
            for item in report.evidence_requirement_assessments
        ),
        "evidence_strength_assessments": tuple(
            stable_payload(item)
            for item in report.evidence_strength_assessments
        ),
        "disagreements": tuple(
            stable_payload(item)
            for item in report.disagreements
        ),
        "accepted_evidence_ids": tuple(
            str(item)
            for item in report.accepted_evidence_ids
        ),
        "rejected_evidence": tuple(
            stable_payload(item)
            for item in report.rejected_evidence
        ),
        "unmatched_requirement_ids": (
            report.unmatched_requirement_ids
        ),
        "completion_status": report.completion_status.value,
        "rationale": report.rationale,
    }


def build_verification_delta(
    *,
    before_episode: VerificationEpisodeManifest,
    before_report: VerificationReport,
    after_episode: VerificationEpisodeManifest,
    after_report: VerificationReport,
) -> VerificationDelta:
    """Compare integrity-bound episodes without granting authority."""

    if before_episode.task_id != after_episode.task_id:
        raise ValueError(
            "verification delta requires episodes from the same task"
        )

    _validate_report_binding(
        episode=before_episode,
        report=before_report,
        label="before",
    )
    _validate_report_binding(
        episode=after_episode,
        report=after_report,
        label="after",
    )

    before_evidence = _evidence_states(
        before_episode,
        before_report,
    )
    after_evidence = _evidence_states(
        after_episode,
        after_report,
    )

    evidence_changes = tuple(
        VerificationEvidenceChange(
            evidence_id=evidence_id,
            before=before_evidence.get(evidence_id),
            after=after_evidence.get(evidence_id),
        )
        for evidence_id in sorted(
            set(before_evidence) | set(after_evidence),
            key=str,
        )
        if (
            before_evidence.get(evidence_id)
            != after_evidence.get(evidence_id)
        )
    )

    evidence_identity_conflicts = tuple(
        VerificationEvidenceIdentityConflict(
            evidence_id=evidence_id,
            before_payload_sha256=(
                before_evidence[evidence_id].payload_sha256
            ),
            after_payload_sha256=(
                after_evidence[evidence_id].payload_sha256
            ),
        )
        for evidence_id in sorted(
            set(before_evidence) & set(after_evidence),
            key=str,
        )
        if (
            before_evidence[evidence_id].payload_sha256
            != after_evidence[evidence_id].payload_sha256
        )
    )

    before_claims = _claim_states(before_report)
    after_claims = _claim_states(after_report)

    claim_changes = tuple(
        VerificationClaimChange(
            claim_id=claim_id,
            before=before_claims.get(claim_id),
            after=after_claims.get(claim_id),
        )
        for claim_id in sorted(
            set(before_claims) | set(after_claims)
        )
        if (
            before_claims.get(claim_id)
            != after_claims.get(claim_id)
        )
    )

    before_requirements = _requirement_states(before_report)
    after_requirements = _requirement_states(after_report)

    evidence_requirement_changes = tuple(
        VerificationRequirementChange(
            requirement=requirement,
            before=before_requirements.get(requirement),
            after=after_requirements.get(requirement),
        )
        for requirement in sorted(
            set(before_requirements) | set(after_requirements)
        )
        if (
            before_requirements.get(requirement)
            != after_requirements.get(requirement)
        )
    )

    before_disagreements = _disagreement_states(before_report)
    after_disagreements = _disagreement_states(after_report)

    disagreement_changes = tuple(
        VerificationDisagreementChange(
            claim_id=claim_id,
            before=before_disagreements.get(claim_id),
            after=after_disagreements.get(claim_id),
        )
        for claim_id in sorted(
            set(before_disagreements) | set(after_disagreements)
        )
        if (
            before_disagreements.get(claim_id)
            != after_disagreements.get(claim_id)
        )
    )

    identity_payload = _VerificationDeltaIdentityPayload(
        delta_semantics_version=(
            VERIFICATION_DELTA_SEMANTICS_VERSION
        ),
        task_id=before_episode.task_id,
        before_episode_id=before_episode.episode_id,
        after_episode_id=after_episode.episode_id,
        contract_changed=(
            before_episode.task_contract_sha256
            != after_episode.task_contract_sha256
        ),
        policy_changed=(
            before_episode.verification_policy_sha256
            != after_episode.verification_policy_sha256
        ),
        verifier_semantics_changed=(
            before_episode.verifier_semantics_version
            != after_episode.verifier_semantics_version
        ),
        verification_time_changed=(
            before_episode.verification_time
            != after_episode.verification_time
        ),
        verification_basis_changed=(
            before_episode.verification_basis_fingerprint
            != after_episode.verification_basis_fingerprint
        ),
        source_task_revision_changed=(
            before_episode.source_task_revision
            != after_episode.source_task_revision
        ),
        verification_output_changed=(
            _semantic_report_payload(before_report)
            != _semantic_report_payload(after_report)
        ),
        before_completion_status=(
            before_report.completion_status
        ),
        after_completion_status=(
            after_report.completion_status
        ),
        evidence_changes=evidence_changes,
        evidence_identity_conflicts=(
            evidence_identity_conflicts
        ),
        claim_changes=claim_changes,
        evidence_requirement_changes=(
            evidence_requirement_changes
        ),
        disagreement_changes=disagreement_changes,
    )

    delta_digest = compute_artifact_sha256(
        identity_payload
    )

    return VerificationDelta.model_validate(
        {
            "delta_id": (
                f"verification-delta:sha256:{delta_digest}"
            ),
            **stable_payload(identity_payload),
        }
    )
