"""Deterministic memory-candidate policy and secret handling."""

from __future__ import annotations

from luna.audit.redaction import SecretRedactor
from luna.memory.models import (
    MemoryCandidate,
    MemoryDecisionStatus,
    MemoryPolicy,
    MemoryPolicyDecision,
    MemoryRejectionCode,
    MemorySensitivity,
    MemorySourceKind,
    MemoryType,
    SECRET_PLACEHOLDER,
)


class MemoryPolicyEvaluator:
    """Reject unverifiable, unstable, stale, or unsafe memory proposals."""

    def __init__(self, explicit_secrets: tuple[str, ...] = ()) -> None:
        self._redactor = SecretRedactor(explicit_secrets)

    def evaluate(
        self,
        candidate: MemoryCandidate,
        policy: MemoryPolicy,
    ) -> MemoryPolicyDecision:
        codes: list[MemoryRejectionCode] = []
        reasons: list[str] = []

        if candidate.source_kind is MemorySourceKind.MODEL_INFERENCE:
            codes.append(MemoryRejectionCode.MODEL_INFERENCE_UNVERIFIED)
            reasons.append("model inference cannot be committed as verified memory")

        if candidate.confidence < policy.minimum_confidence:
            codes.append(MemoryRejectionCode.LOW_CONFIDENCE)
            reasons.append("candidate confidence is below the memory policy threshold")

        if (
            candidate.memory_type is MemoryType.PREFERENCE
            and not candidate.explicit_persistence
            and candidate.occurrence_count < policy.minimum_preference_occurrences
        ):
            codes.append(MemoryRejectionCode.ONE_OFF_PREFERENCE)
            reasons.append("one occurrence is not a stable persistent preference")

        if (
            candidate.memory_type in policy.require_expiry_for
            and candidate.expires_at is None
        ):
            codes.append(MemoryRejectionCode.EXPIRY_REQUIRED)
            reasons.append("dynamic memory type requires an expiry timestamp")

        statement_redaction = self._redactor.redact_text(candidate.statement)
        source_redaction = self._redactor.redact_text(candidate.source_ref)

        if source_redaction.redactions_applied:
            codes.append(MemoryRejectionCode.PLAINTEXT_SECRET)
            reasons.append("plaintext secret detected in memory provenance")

        if candidate.sensitivity is MemorySensitivity.SECRET:
            assert candidate.secret_ref is not None
            matched_scheme = next(
                (
                    scheme
                    for scheme in policy.allowed_secret_schemes
                    if candidate.secret_ref.casefold().startswith(scheme)
                ),
                None,
            )
            opaque_reference = (
                not any(character.isspace() for character in candidate.secret_ref)
                and "=" not in candidate.secret_ref
            )
            reference_name = (
                candidate.secret_ref[len(matched_scheme) :]
                if matched_scheme is not None
                else candidate.secret_ref
            )
            reference_redaction = self._redactor.redact_text(reference_name)
            if (
                matched_scheme is None
                or not opaque_reference
                or reference_redaction.redactions_applied
            ):
                codes.append(MemoryRejectionCode.INVALID_SECRET_REFERENCE)
                reasons.append("secret_ref must use an approved opaque reference scheme")
            sanitized_statement = SECRET_PLACEHOLDER
        else:
            if statement_redaction.redactions_applied:
                codes.append(MemoryRejectionCode.PLAINTEXT_SECRET)
                reasons.append("plaintext secret detected outside SECRET_REFERENCE memory")
            sanitized_statement = candidate.statement

        if codes:
            unique_codes = tuple(dict.fromkeys(codes))
            unique_reasons = tuple(dict.fromkeys(reasons))
            return MemoryPolicyDecision(
                candidate_id=candidate.candidate_id,
                status=MemoryDecisionStatus.REJECT,
                rejection_codes=unique_codes,
                reasons=unique_reasons,
            )

        return MemoryPolicyDecision(
            candidate_id=candidate.candidate_id,
            status=MemoryDecisionStatus.COMMIT,
            sanitized_statement=sanitized_statement,
        )
