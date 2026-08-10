"""SQLite-backed checkpoint persistence and restart-safe continuity."""

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
from luna.continuity.service import ContinuityService
from luna.continuity.store import (
    CheckpointNotFoundError,
    ContinuityConflictError,
    ContinuityError,
    ContinuityIntegrityError,
    SQLiteContinuityStore,
)

__all__ = [
    "CheckpointEnvelope",
    "CheckpointNotFoundError",
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
]
