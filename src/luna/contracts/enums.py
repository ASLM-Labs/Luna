"""Stable enumerations for Luna 0.1 runtime contracts."""

from __future__ import annotations

from enum import StrEnum


class RiskLevel(StrEnum):
    """Task risk classification."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TaskPhase(StrEnum):
    """Allowed phases in the Luna task lifecycle."""

    CREATED = "CREATED"
    CONTRACTED = "CONTRACTED"
    CONTEXT_READY = "CONTEXT_READY"
    PLANNED = "PLANNED"
    ACTING = "ACTING"
    OBSERVING = "OBSERVING"
    REPLANNING = "REPLANNING"
    VERIFYING = "VERIFYING"
    REPORTING = "REPORTING"
    CHECKPOINTED = "CHECKPOINTED"
    CLOSED = "CLOSED"


class PlanStepStatus(StrEnum):
    """Lifecycle of an individual plan step."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    SKIPPED_WITH_REASON = "SKIPPED_WITH_REASON"


class ObservationStatus(StrEnum):
    """Normalized outcome of an action or tool event."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class EvidenceResult(StrEnum):
    """Result asserted by a single evidence record."""

    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"


class EvidenceSourceKind(StrEnum):
    """Origin of an evidence record."""

    TOOL_OUTPUT = "TOOL_OUTPUT"
    TEST_RESULT = "TEST_RESULT"
    DIFF = "DIFF"
    HASH = "HASH"
    MEASUREMENT = "MEASUREMENT"
    DOCUMENT = "DOCUMENT"
    MEMORY = "MEMORY"
    MODEL_INFERENCE = "MODEL_INFERENCE"


class CompletionStatus(StrEnum):
    """Only valid task completion decisions in Luna 0.1."""

    VERIFIED_COMPLETE = "VERIFIED_COMPLETE"
    UNVERIFIED = "UNVERIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
