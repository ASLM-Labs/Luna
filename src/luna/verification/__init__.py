"""Deterministic requirement verification and completion gating."""

from luna.verification.claims import (
    forbidden_absence_claim_id,
    required_condition_claim_id,
)
from luna.verification.evidence_store import (
    EVIDENCE_STORE_SCHEMA_VERSION,
    CurrentVerificationEvidenceProvider,
    EvidenceStoreConflictError,
    EvidenceStoreError,
    SQLiteEvidenceStore,
    VerifiedEvidenceRegistry,
)
from luna.verification.gate import CompletionGate, CompletionGateError
from luna.verification.knowledge_evolution import (
    KnowledgeVerificationClaimBinding,
    KnowledgeVerificationClaimRole,
    VerificationKnowledgeEvolutionAdapter,
)
from luna.verification.models import (
    ClaimKind,
    ClaimStatus,
    CompletionDecision,
    CompletionGateResult,
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
from luna.verification.strategy import (
    VerificationDepth,
    VerificationStrategy,
    VerificationStrategySelector,
)
from luna.verification.verifier import DeterministicVerifier

__all__ = [
    "EVIDENCE_STORE_SCHEMA_VERSION",
    "ClaimKind",
    "ClaimStatus",
    "CompletionDecision",
    "CompletionGate",
    "CompletionGateError",
    "CompletionGateResult",
    "CurrentVerificationEvidenceProvider",
    "DeterministicVerifier",
    "EvidenceDisagreement",
    "EvidenceRejection",
    "EvidenceRejectionCode",
    "EvidenceRequirementAssessment",
    "EvidenceStoreConflictError",
    "EvidenceStoreError",
    "EvidenceStrength",
    "EvidenceStrengthAssessment",
    "KnowledgeVerificationClaimBinding",
    "KnowledgeVerificationClaimRole",
    "SQLiteEvidenceStore",
    "VerificationClaim",
    "VerificationDepth",
    "VerificationKnowledgeEvolutionAdapter",
    "VerificationPolicy",
    "VerificationReport",
    "VerificationStrategy",
    "VerificationStrategySelector",
    "VerifiedEvidenceRegistry",
    "forbidden_absence_claim_id",
    "required_condition_claim_id",
]
