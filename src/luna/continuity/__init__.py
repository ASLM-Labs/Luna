"""SQLite-backed checkpoint persistence and restart-safe continuity."""

from luna.continuity.cognitive import (
    CognitiveContinuityProjection,
    CognitiveOwnerBinding,
    CognitiveOwnerKind,
    CognitiveOwnerResolution,
    CognitiveOwnerResolutionReason,
    CognitiveOwnerResolutionStatus,
    CognitiveRehydrationManifest,
    StoredCognitiveRehydrationManifest,
    build_cognitive_continuity_projection,
    build_cognitive_owner_resolution,
    build_cognitive_rehydration_manifest,
    compute_cognitive_continuity_projection_id,
    compute_cognitive_rehydration_manifest_id,
)
from luna.continuity.identity_adapter import (
    build_identity_owner_binding,
    resolve_identity_owner_binding,
)
from luna.continuity.memory_adapter import (
    build_memory_owner_binding,
    resolve_memory_owner_binding,
)
from luna.continuity.models import (
    CheckpointEnvelope,
    ContinuityIntegrity,
    ResumeCompatibilityDimension,
    ResumeCompatibilityVector,
    ResumeDecision,
    ResumePolicy,
    ResumeStatus,
    StoredCheckpoint,
)
from luna.continuity.semantic_bridge import (
    CognitiveSemanticClaimBinding,
    bind_cognitive_semantic_claim,
)
from luna.continuity.service import ContinuityService
from luna.continuity.session_adapter import (
    build_session_owner_binding,
    resolve_session_owner_binding,
)
from luna.continuity.store import (
    CheckpointNotFoundError,
    CognitiveManifestNotFoundError,
    ContinuityConflictError,
    ContinuityError,
    ContinuityIntegrityError,
    SQLiteContinuityStore,
)
from luna.continuity.verification_evidence_adapter import (
    build_verification_evidence_owner_binding,
    resolve_verification_evidence_owner_binding,
)

__all__ = [
    "CheckpointEnvelope",
    "CheckpointNotFoundError",
    "CognitiveContinuityProjection",
    "CognitiveManifestNotFoundError",
    "CognitiveOwnerBinding",
    "CognitiveOwnerKind",
    "CognitiveOwnerResolution",
    "CognitiveOwnerResolutionReason",
    "CognitiveOwnerResolutionStatus",
    "CognitiveRehydrationManifest",
    "CognitiveSemanticClaimBinding",
    "ContinuityConflictError",
    "ContinuityError",
    "ContinuityIntegrity",
    "ContinuityIntegrityError",
    "ContinuityService",
    "ResumeCompatibilityDimension",
    "ResumeCompatibilityVector",
    "ResumeDecision",
    "ResumePolicy",
    "ResumeStatus",
    "SQLiteContinuityStore",
    "StoredCheckpoint",
    "StoredCognitiveRehydrationManifest",
    "bind_cognitive_semantic_claim",
    "build_cognitive_continuity_projection",
    "build_cognitive_owner_resolution",
    "build_cognitive_rehydration_manifest",
    "build_identity_owner_binding",
    "build_memory_owner_binding",
    "build_session_owner_binding",
    "build_verification_evidence_owner_binding",
    "compute_cognitive_continuity_projection_id",
    "compute_cognitive_rehydration_manifest_id",
    "resolve_identity_owner_binding",
    "resolve_memory_owner_binding",
    "resolve_session_owner_binding",
    "resolve_verification_evidence_owner_binding",
]
