"""Deterministic requirement-to-evidence verification rules."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from luna.contracts.base import utc_now
from luna.contracts.enums import (
    CompletionStatus,
    EvidenceResult,
    EvidenceSourceKind,
)
from luna.contracts.evidence import Evidence
from luna.contracts.task import TaskContract
from luna.verification.claims import claims_from_contract
from luna.verification.models import (
    ClaimAssessment,
    ClaimStatus,
    EvidenceRejection,
    EvidenceRejectionCode,
    EvidenceRequirementAssessment,
    VerificationClaim,
    VerificationPolicy,
    VerificationReport,
)

_DIRECT_SOURCE_KINDS = frozenset(
    {
        EvidenceSourceKind.TOOL_OUTPUT,
        EvidenceSourceKind.TEST_RESULT,
        EvidenceSourceKind.DIFF,
        EvidenceSourceKind.HASH,
        EvidenceSourceKind.MEASUREMENT,
    }
)


class _EvidenceRule(StrEnum):
    ANY_DIRECT = "ANY_DIRECT"
    OBSERVATION_LINK = "OBSERVATION_LINK"
    TOOL_OUTPUT = "TOOL_OUTPUT"
    TEST_RESULT = "TEST_RESULT"
    DIFF = "DIFF"
    HASH = "HASH"
    MEASUREMENT = "MEASUREMENT"
    DOCUMENT = "DOCUMENT"
    MEMORY = "MEMORY"


def _dedupe_ids(values: Iterable[UUID]) -> tuple[UUID, ...]:
    return tuple(dict.fromkeys(values))


def _dedupe_text(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _recognized_rules(requirement: str) -> tuple[_EvidenceRule, ...]:
    text = requirement.casefold()
    compact = "".join(character for character in text if character.isalnum())
    rules: list[_EvidenceRule] = []

    if "test" in text:
        rules.append(_EvidenceRule.TEST_RESULT)
    if "hash" in text or "sha256" in compact:
        rules.append(_EvidenceRule.HASH)
    if "diff" in text or "değişiklik" in text or "degisiklik" in text:
        rules.append(_EvidenceRule.DIFF)
    if "measurement" in text or "ölçüm" in text or "olcum" in text:
        rules.append(_EvidenceRule.MEASUREMENT)
    if "document" in text or "belge" in text:
        rules.append(_EvidenceRule.DOCUMENT)
    if "memory" in text or "hafıza" in text or "hafiza" in text:
        rules.append(_EvidenceRule.MEMORY)
    if "observation" in text or "gözlem" in text or "gozlem" in text:
        rules.append(_EvidenceRule.OBSERVATION_LINK)
    if "toolresult" in compact or "tooloutput" in compact or "araççıktısı" in compact:
        rules.append(_EvidenceRule.TOOL_OUTPUT)
    if "evidence" in text or "kanıt" in text or "kanit" in text:
        rules.append(_EvidenceRule.ANY_DIRECT)

    return tuple(dict.fromkeys(rules))


def _evidence_matches_rule(evidence: Evidence, rule: _EvidenceRule) -> bool:
    if rule is _EvidenceRule.ANY_DIRECT:
        return evidence.source_kind in _DIRECT_SOURCE_KINDS
    if rule is _EvidenceRule.OBSERVATION_LINK:
        return evidence.source_ref.startswith("observation:")
    if rule is _EvidenceRule.TOOL_OUTPUT:
        return evidence.source_kind is EvidenceSourceKind.TOOL_OUTPUT
    if rule is _EvidenceRule.TEST_RESULT:
        return evidence.source_kind is EvidenceSourceKind.TEST_RESULT
    if rule is _EvidenceRule.DIFF:
        return evidence.source_kind is EvidenceSourceKind.DIFF
    if rule is _EvidenceRule.HASH:
        return evidence.source_kind is EvidenceSourceKind.HASH
    if rule is _EvidenceRule.MEASUREMENT:
        return evidence.source_kind is EvidenceSourceKind.MEASUREMENT
    if rule is _EvidenceRule.DOCUMENT:
        return evidence.source_kind is EvidenceSourceKind.DOCUMENT
    if rule is _EvidenceRule.MEMORY:
        return evidence.source_kind is EvidenceSourceKind.MEMORY
    return False


class DeterministicVerifier:
    """Verify current evidence without model judgment or hidden heuristics."""

    def verify(
        self,
        *,
        contract: TaskContract,
        evidence: Iterable[Evidence],
        policy: VerificationPolicy,
        now: datetime | None = None,
    ) -> VerificationReport:
        verification_time = now or utc_now()
        accepted: list[Evidence] = []
        rejected: list[EvidenceRejection] = []

        for item in evidence:
            rejection = self._rejection_for(
                contract=contract,
                evidence=item,
                policy=policy,
                now=verification_time,
            )
            if rejection is None:
                accepted.append(item)
            else:
                rejected.append(rejection)

        claims = claims_from_contract(contract)
        claim_ids = {claim.claim_id for claim in claims}
        assessments = tuple(
            self._assess_claim(
                claim=claim,
                evidence=tuple(
                    item for item in accepted if item.requirement_id == claim.claim_id
                ),
                policy=policy,
            )
            for claim in claims
        )
        evidence_requirements = tuple(
            self._assess_evidence_requirement(
                requirement=requirement,
                evidence=tuple(accepted),
                policy=policy,
            )
            for requirement in contract.evidence_required
        )
        unmatched = tuple(
            sorted(
                {
                    item.requirement_id
                    for item in accepted
                    if item.requirement_id not in claim_ids
                }
            )
        )

        completion_status, rationale = self._completion_status(
            contract=contract,
            assessments=assessments,
            evidence_requirements=evidence_requirements,
        )
        return VerificationReport(
            task_id=contract.task_id,
            policy=policy,
            claim_assessments=assessments,
            evidence_requirement_assessments=evidence_requirements,
            accepted_evidence_ids=_dedupe_ids(item.evidence_id for item in accepted),
            rejected_evidence=tuple(rejected),
            unmatched_requirement_ids=unmatched,
            completion_status=completion_status,
            rationale=rationale,
            generated_at=verification_time,
        )

    @staticmethod
    def _rejection_for(
        *,
        contract: TaskContract,
        evidence: Evidence,
        policy: VerificationPolicy,
        now: datetime,
    ) -> EvidenceRejection | None:
        if evidence.task_id != contract.task_id:
            return EvidenceRejection(
                evidence_id=evidence.evidence_id,
                code=EvidenceRejectionCode.WRONG_TASK,
                reason="evidence task_id does not match the task contract",
            )
        if policy.require_revision and evidence.revision is None:
            return EvidenceRejection(
                evidence_id=evidence.evidence_id,
                code=EvidenceRejectionCode.REVISION_MISSING,
                reason="current verification requires an explicit revision",
            )
        if (
            evidence.revision is not None
            and evidence.revision != policy.current_revision
        ):
            return EvidenceRejection(
                evidence_id=evidence.evidence_id,
                code=EvidenceRejectionCode.REVISION_MISMATCH,
                reason=(
                    f"evidence revision {evidence.revision!r} does not match "
                    f"current revision {policy.current_revision!r}"
                ),
            )
        if (
            policy.expected_environment_fingerprint is not None
            and evidence.environment_fingerprint
            != policy.expected_environment_fingerprint
        ):
            return EvidenceRejection(
                evidence_id=evidence.evidence_id,
                code=EvidenceRejectionCode.ENVIRONMENT_MISMATCH,
                reason="evidence environment does not match verification policy",
            )
        if policy.require_freshness and evidence.freshness_seconds is None:
            return EvidenceRejection(
                evidence_id=evidence.evidence_id,
                code=EvidenceRejectionCode.FRESHNESS_MISSING,
                reason="current verification requires explicit freshness",
            )
        if (
            evidence.freshness_seconds is not None
            and evidence.freshness_seconds > policy.max_freshness_seconds
        ):
            return EvidenceRejection(
                evidence_id=evidence.evidence_id,
                code=EvidenceRejectionCode.STALE,
                reason=(
                    f"evidence freshness {evidence.freshness_seconds}s exceeds "
                    f"{policy.max_freshness_seconds}s"
                ),
            )
        tolerance = timedelta(seconds=policy.future_clock_tolerance_seconds)
        if evidence.observed_at > now + tolerance:
            return EvidenceRejection(
                evidence_id=evidence.evidence_id,
                code=EvidenceRejectionCode.FUTURE_TIMESTAMP,
                reason="evidence timestamp is beyond the allowed clock tolerance",
            )
        return None

    @staticmethod
    def _qualifies(evidence: Evidence, policy: VerificationPolicy) -> bool:
        if evidence.source_kind not in _DIRECT_SOURCE_KINDS:
            return False
        if policy.require_reproducible and not evidence.reproducible:
            return False
        return evidence.confidence >= policy.min_confidence

    def _assess_claim(
        self,
        *,
        claim: VerificationClaim,
        evidence: tuple[Evidence, ...],
        policy: VerificationPolicy,
    ) -> ClaimAssessment:
        if not evidence:
            return ClaimAssessment(
                claim=claim,
                status=ClaimStatus.UNVERIFIED,
                reasons=("no current evidence is linked to this claim",),
            )

        qualifying = tuple(
            item for item in evidence if self._qualifies(item, policy)
        )
        pass_ids = tuple(
            item.evidence_id
            for item in qualifying
            if item.result is EvidenceResult.PASS
        )
        fail_ids = tuple(
            item.evidence_id
            for item in qualifying
            if item.result is EvidenceResult.FAIL
        )
        blocked_ids = tuple(
            item.evidence_id
            for item in qualifying
            if item.result is EvidenceResult.BLOCKED
        )
        inconclusive_ids = tuple(
            item.evidence_id
            for item in qualifying
            if item.result is EvidenceResult.INCONCLUSIVE
        )

        considered_ids = _dedupe_ids(item.evidence_id for item in evidence)
        qualifying_ids = _dedupe_ids(item.evidence_id for item in qualifying)

        if pass_ids and fail_ids:
            return ClaimAssessment(
                claim=claim,
                status=ClaimStatus.CONFLICTING,
                considered_evidence_ids=considered_ids,
                qualifying_evidence_ids=qualifying_ids,
                reasons=("current qualifying PASS and FAIL evidence conflict",),
            )
        if fail_ids:
            return ClaimAssessment(
                claim=claim,
                status=ClaimStatus.FAIL,
                considered_evidence_ids=considered_ids,
                qualifying_evidence_ids=qualifying_ids,
                reasons=("current qualifying evidence reports failure",),
            )
        if pass_ids:
            return ClaimAssessment(
                claim=claim,
                status=ClaimStatus.PASS,
                considered_evidence_ids=considered_ids,
                qualifying_evidence_ids=qualifying_ids,
                reasons=("current reproducible direct evidence passes",),
            )
        if blocked_ids:
            return ClaimAssessment(
                claim=claim,
                status=ClaimStatus.BLOCKED,
                considered_evidence_ids=considered_ids,
                qualifying_evidence_ids=qualifying_ids,
                reasons=("current qualifying evidence is blocked",),
            )
        if inconclusive_ids:
            return ClaimAssessment(
                claim=claim,
                status=ClaimStatus.INCONCLUSIVE,
                considered_evidence_ids=considered_ids,
                qualifying_evidence_ids=qualifying_ids,
                reasons=("current qualifying evidence is inconclusive",),
            )
        return ClaimAssessment(
            claim=claim,
            status=ClaimStatus.INCONCLUSIVE,
            considered_evidence_ids=considered_ids,
            reasons=(
                "evidence exists but is not direct, reproducible, or confident enough",
            ),
        )

    def _assess_evidence_requirement(
        self,
        *,
        requirement: str,
        evidence: tuple[Evidence, ...],
        policy: VerificationPolicy,
    ) -> EvidenceRequirementAssessment:
        rules = _recognized_rules(requirement)
        qualifying = tuple(
            item for item in evidence if self._qualifies(item, policy)
        )
        if not rules:
            return EvidenceRequirementAssessment(
                requirement=requirement,
                status=ClaimStatus.UNVERIFIED,
                reasons=(
                    "evidence requirement has no deterministic Phase 7 mapping",
                ),
            )

        matched: list[UUID] = []
        missing: list[str] = []
        for rule in rules:
            rule_matches = [
                item.evidence_id
                for item in qualifying
                if _evidence_matches_rule(item, rule)
            ]
            if rule_matches:
                matched.extend(rule_matches)
            else:
                missing.append(rule.value)

        if missing:
            return EvidenceRequirementAssessment(
                requirement=requirement,
                status=ClaimStatus.UNVERIFIED,
                matched_evidence_ids=_dedupe_ids(matched),
                recognized_rules=tuple(rule.value for rule in rules),
                reasons=(
                    "missing qualifying evidence for: " + ", ".join(missing),
                ),
            )
        return EvidenceRequirementAssessment(
            requirement=requirement,
            status=ClaimStatus.PASS,
            matched_evidence_ids=_dedupe_ids(matched),
            recognized_rules=tuple(rule.value for rule in rules),
            reasons=("all deterministic evidence requirements are satisfied",),
        )

    @staticmethod
    def _completion_status(
        *,
        contract: TaskContract,
        assessments: tuple[ClaimAssessment, ...],
        evidence_requirements: tuple[EvidenceRequirementAssessment, ...],
    ) -> tuple[CompletionStatus, tuple[str, ...]]:
        statuses = tuple(item.status for item in assessments)
        evidence_statuses = tuple(item.status for item in evidence_requirements)

        if ClaimStatus.CONFLICTING in statuses:
            return (
                CompletionStatus.CONFLICTING_EVIDENCE,
                ("current qualifying evidence contains unresolved conflict",),
            )
        if ClaimStatus.FAIL in statuses:
            return (
                CompletionStatus.FAILED,
                ("at least one required claim has current qualifying FAIL evidence",),
            )
        if ClaimStatus.BLOCKED in statuses:
            return (
                CompletionStatus.BLOCKED,
                ("at least one required claim is blocked",),
            )
        if ClaimStatus.INCONCLUSIVE in statuses:
            return (
                CompletionStatus.INCONCLUSIVE,
                ("at least one required claim remains inconclusive",),
            )
        if (
            ClaimStatus.UNVERIFIED in statuses
            or ClaimStatus.UNVERIFIED in evidence_statuses
        ):
            return (
                CompletionStatus.UNVERIFIED,
                ("required claim or evidence requirement is not verified",),
            )
        if contract.unknowns:
            return (
                CompletionStatus.UNVERIFIED,
                ("task contract contains unresolved unknowns",),
            )
        return (
            CompletionStatus.VERIFIED_COMPLETE,
            (
                "all required and forbidden-absence claims have current "
                "qualifying evidence",
                "all deterministic evidence requirements are satisfied",
            ),
        )
