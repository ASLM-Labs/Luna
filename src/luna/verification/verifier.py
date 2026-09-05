"""Deterministic requirement-to-evidence verification rules."""

from __future__ import annotations

import re
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
    EvidenceDisagreement,
    EvidenceRejection,
    EvidenceRejectionCode,
    EvidenceRequirementAssessment,
    EvidenceStrength,
    EvidenceStrengthAssessment,
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

_STRENGTH_RANK = {
    EvidenceStrength.WEAK: 0,
    EvidenceStrength.MODERATE: 1,
    EvidenceStrength.STRONG: 2,
    EvidenceStrength.DETERMINISTIC: 3,
}


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


_OR_PATTERN = re.compile(r"\bor\b", flags=re.IGNORECASE)


def _recognized_rule_clauses(
    requirement: str,
) -> tuple[tuple[_EvidenceRule, ...], ...]:
    """Split only explicit standalone OR alternatives.

    Rules inside one clause retain the existing conjunctive semantics.
    Empty or unmapped clauses remain visible so verification fails closed.
    """
    return tuple(
        _recognized_rules(clause.strip())
        for clause in _OR_PATTERN.split(requirement)
    )


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


def _strongest(values: Iterable[EvidenceStrength]) -> EvidenceStrength:
    return max(values, key=_STRENGTH_RANK.__getitem__)


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

        strength_assessments = tuple(
            self._assess_strength(item, policy) for item in accepted
        )
        strength_by_id = {
            item.evidence_id: item for item in strength_assessments
        }

        claims = claims_from_contract(contract)
        claim_ids = {claim.claim_id for claim in claims}
        assessments = tuple(
            self._assess_claim(
                claim=claim,
                evidence=tuple(
                    item for item in accepted if item.requirement_id == claim.claim_id
                ),
                policy=policy,
                strength_by_id=strength_by_id,
            )
            for claim in claims
        )
        disagreements = tuple(
            disagreement
            for claim, assessment in zip(claims, assessments, strict=True)
            if (
                disagreement := self._disagreement_for(
                    claim=claim,
                    assessment=assessment,
                    evidence=tuple(
                        item for item in accepted if item.requirement_id == claim.claim_id
                    ),
                    strength_by_id=strength_by_id,
                )
            )
            is not None
        )
        evidence_requirements = tuple(
            self._assess_evidence_requirement(
                requirement=requirement,
                evidence=tuple(accepted),
                policy=policy,
                strength_by_id=strength_by_id,
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
            disagreements=disagreements,
        )
        return VerificationReport(
            task_id=contract.task_id,
            policy=policy,
            claim_assessments=assessments,
            evidence_requirement_assessments=evidence_requirements,
            evidence_strength_assessments=strength_assessments,
            disagreements=disagreements,
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
    def _assess_strength(
        evidence: Evidence,
        policy: VerificationPolicy,
    ) -> EvidenceStrengthAssessment:
        reasons: list[str] = []

        if evidence.source_kind is EvidenceSourceKind.MODEL_INFERENCE:
            strength = EvidenceStrength.WEAK
            reasons.append("model inference is never direct verification evidence")
        elif evidence.source_kind is EvidenceSourceKind.MEMORY:
            strength = EvidenceStrength.WEAK
            reasons.append("memory is contextual provenance, not current direct proof")
        elif evidence.source_kind is EvidenceSourceKind.DOCUMENT:
            strength = EvidenceStrength.MODERATE
            reasons.append("document evidence is indirect unless independently verified")
        elif evidence.source_kind is EvidenceSourceKind.TOOL_OUTPUT:
            strength = EvidenceStrength.MODERATE
            reasons.append("generic tool output is direct observation but not a verifier")
        elif evidence.source_kind in {
            EvidenceSourceKind.DIFF,
            EvidenceSourceKind.MEASUREMENT,
        }:
            strength = EvidenceStrength.STRONG
            reasons.append("structured current-state evidence is strongly machine-checkable")
        elif evidence.source_kind in {
            EvidenceSourceKind.TEST_RESULT,
            EvidenceSourceKind.HASH,
        }:
            strength = (
                EvidenceStrength.DETERMINISTIC
                if evidence.reproducible and evidence.confidence >= 0.95
                else EvidenceStrength.STRONG
            )
            reasons.append("test/hash evidence has deterministic verification semantics")
        else:
            strength = EvidenceStrength.WEAK
            reasons.append("evidence source has no stronger Phase 12F authority mapping")

        if not evidence.reproducible:
            reasons.append("evidence is not marked reproducible")
            if _STRENGTH_RANK[strength] > _STRENGTH_RANK[EvidenceStrength.MODERATE]:
                strength = EvidenceStrength.MODERATE
        if evidence.confidence < policy.min_confidence:
            reasons.append("evidence confidence is below policy threshold")
            strength = EvidenceStrength.WEAK

        qualifying = (
            evidence.source_kind in _DIRECT_SOURCE_KINDS
            and (not policy.require_reproducible or evidence.reproducible)
            and evidence.confidence >= policy.min_confidence
            and _STRENGTH_RANK[strength] >= _STRENGTH_RANK[policy.minimum_strength]
        )
        if qualifying:
            reasons.append("evidence meets current minimum strength policy")
        else:
            reasons.append("evidence does not meet current minimum strength policy")

        return EvidenceStrengthAssessment(
            evidence_id=evidence.evidence_id,
            strength=strength,
            qualifying=qualifying,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    @staticmethod
    def _qualifies(
        evidence: Evidence,
        strength_by_id: dict[UUID, EvidenceStrengthAssessment],
    ) -> bool:
        assessment = strength_by_id.get(evidence.evidence_id)
        return bool(assessment is not None and assessment.qualifying)

    def _assess_claim(
        self,
        *,
        claim: VerificationClaim,
        evidence: tuple[Evidence, ...],
        policy: VerificationPolicy,
        strength_by_id: dict[UUID, EvidenceStrengthAssessment],
    ) -> ClaimAssessment:
        del policy
        if not evidence:
            return ClaimAssessment(
                claim=claim,
                status=ClaimStatus.UNVERIFIED,
                reasons=("no current evidence is linked to this claim",),
            )

        qualifying = tuple(
            item for item in evidence if self._qualifies(item, strength_by_id)
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
                reasons=("current strong reproducible direct evidence passes",),
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
                "evidence exists but is below the current direct/reproducible/strength threshold",
            ),
        )

    @staticmethod
    def _disagreement_for(
        *,
        claim: VerificationClaim,
        assessment: ClaimAssessment,
        evidence: tuple[Evidence, ...],
        strength_by_id: dict[UUID, EvidenceStrengthAssessment],
    ) -> EvidenceDisagreement | None:
        if assessment.status is not ClaimStatus.CONFLICTING:
            return None
        qualifying = tuple(
            item
            for item in evidence
            if item.evidence_id in assessment.qualifying_evidence_ids
        )
        supporting = tuple(
            item.evidence_id
            for item in qualifying
            if item.result is EvidenceResult.PASS
        )
        contradicting = tuple(
            item.evidence_id
            for item in qualifying
            if item.result is EvidenceResult.FAIL
        )
        if not supporting or not contradicting:
            return None
        return EvidenceDisagreement(
            claim_id=claim.claim_id,
            supporting_evidence_ids=supporting,
            contradicting_evidence_ids=contradicting,
            strongest_support=_strongest(
                strength_by_id[item].strength for item in supporting
            ),
            strongest_contradiction=_strongest(
                strength_by_id[item].strength for item in contradicting
            ),
        )

    def _assess_evidence_requirement(
        self,
        *,
        requirement: str,
        evidence: tuple[Evidence, ...],
        policy: VerificationPolicy,
        strength_by_id: dict[UUID, EvidenceStrengthAssessment],
    ) -> EvidenceRequirementAssessment:
        del policy

        clauses = _recognized_rule_clauses(requirement)
        rules = tuple(
            dict.fromkeys(
                rule
                for clause in clauses
                for rule in clause
            )
        )
        qualifying = tuple(
            item
            for item in evidence
            if self._qualifies(item, strength_by_id)
        )

        if not rules:
            return EvidenceRequirementAssessment(
                requirement=requirement,
                status=ClaimStatus.UNVERIFIED,
                reasons=(
                    "evidence requirement has no deterministic Phase 12F mapping",
                ),
            )

        # Preserve historical conjunctive semantics when there is no
        # explicit standalone OR alternative.
        if len(clauses) == 1:
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
                    recognized_rules=tuple(
                        rule.value for rule in rules
                    ),
                    reasons=(
                        "missing strong qualifying evidence for: "
                        + ", ".join(missing),
                    ),
                )

            return EvidenceRequirementAssessment(
                requirement=requirement,
                status=ClaimStatus.PASS,
                matched_evidence_ids=_dedupe_ids(matched),
                recognized_rules=tuple(
                    rule.value for rule in rules
                ),
                reasons=(
                    "all deterministic evidence requirements are satisfied",
                ),
            )

        # An explicit OR branch with no deterministic mapping is not
        # silently discarded. The requirement fails closed.
        unmapped_alternatives = tuple(
            index + 1
            for index, clause in enumerate(clauses)
            if not clause
        )
        if unmapped_alternatives:
            return EvidenceRequirementAssessment(
                requirement=requirement,
                status=ClaimStatus.UNVERIFIED,
                recognized_rules=tuple(
                    rule.value for rule in rules
                ),
                reasons=(
                    "evidence requirement contains unmapped OR "
                    "alternative(s): "
                    + ", ".join(
                        str(index)
                        for index in unmapped_alternatives
                    ),
                ),
            )

        partial_matches: list[UUID] = []
        satisfied_matches: list[UUID] = []

        for clause in clauses:
            clause_matches: list[UUID] = []
            clause_complete = True

            # Rules inside one clause retain AND semantics.
            for rule in clause:
                rule_matches = [
                    item.evidence_id
                    for item in qualifying
                    if _evidence_matches_rule(item, rule)
                ]

                if not rule_matches:
                    clause_complete = False

                clause_matches.extend(rule_matches)

            partial_matches.extend(clause_matches)

            # Clauses themselves use OR semantics.
            if clause_complete:
                satisfied_matches.extend(clause_matches)

        if satisfied_matches:
            return EvidenceRequirementAssessment(
                requirement=requirement,
                status=ClaimStatus.PASS,
                matched_evidence_ids=_dedupe_ids(
                    satisfied_matches
                ),
                recognized_rules=tuple(
                    rule.value for rule in rules
                ),
                reasons=(
                    "at least one deterministic evidence alternative "
                    "is satisfied",
                ),
            )

        return EvidenceRequirementAssessment(
            requirement=requirement,
            status=ClaimStatus.UNVERIFIED,
            matched_evidence_ids=_dedupe_ids(
                partial_matches
            ),
            recognized_rules=tuple(
                rule.value for rule in rules
            ),
            reasons=(
                "no deterministic evidence alternative is fully satisfied",
            ),
        )

    @staticmethod
    def _completion_status(
        *,
        contract: TaskContract,
        assessments: tuple[ClaimAssessment, ...],
        evidence_requirements: tuple[EvidenceRequirementAssessment, ...],
        disagreements: tuple[EvidenceDisagreement, ...],
    ) -> tuple[CompletionStatus, tuple[str, ...]]:
        statuses = tuple(item.status for item in assessments)
        evidence_statuses = tuple(item.status for item in evidence_requirements)

        if disagreements or ClaimStatus.CONFLICTING in statuses:
            return (
                CompletionStatus.CONFLICTING_EVIDENCE,
                ("current strong qualifying evidence contains unresolved disagreement",),
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
                "all required and forbidden-absence claims have current strong qualifying evidence",
                "all deterministic evidence requirements are satisfied",
                "no unresolved evidence disagreement remains",
            ),
        )
