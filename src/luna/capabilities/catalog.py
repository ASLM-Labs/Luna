"""Canonical C-002 capability catalog derived from the current Luna roadmap."""

from __future__ import annotations

from luna.capabilities.models import CapabilityRecord, CapabilityStatus, EvidenceFreshness
from luna.capabilities.registry import CapabilityRegistry

_SOURCE_REVISION = "roadmap-after-legacy-reconciliation"
_QUEUE_BOUNDARY = "Planning metadata only; this record grants no runtime or promotion authority."
_QUEUE_ROLLBACK = (
    "Disable or remove the future capability implementation; queued metadata has no runtime effect."
)


def _queued(
    capability_id: str,
    name: str,
    scope: str,
    *,
    preferred: tuple[str, ...] = (),
    foundation_refs: tuple[str, ...] = (),
) -> CapabilityRecord:
    return CapabilityRecord(
        capability_id=capability_id,
        name=name,
        status=CapabilityStatus.QUEUED,
        scope=scope,
        preferred_prerequisites=preferred,
        source_refs=(f"docs/LUNA_ROADMAP.md#{capability_id}",),
        foundation_refs=foundation_refs,
        authority_boundary=_QUEUE_BOUNDARY,
        rollback_or_disable_path=_QUEUE_ROLLBACK,
        source_revision=_SOURCE_REVISION,
        evidence_freshness=EvidenceFreshness.MISSING,
    )


def build_canonical_capability_registry() -> CapabilityRegistry:
    """Build the repository's current capability identity/lineage registry."""

    records = (
        _queued(
            "C-001",
            "Adaptive Knowledge Retrieval",
            "Evidence-aware routing among internal, memory, RAG, research, web, and API sources.",
            preferred=("C-002",),
        ),
        CapabilityRecord(
            capability_id="C-002",
            name="Capability Lineage & Dependency Mapping",
            status=CapabilityStatus.IMPLEMENTED_UNVERIFIED,
            scope=(
                "Canonical capability identities, explicit dependency edges, repository evidence "
                "references, freshness state, deterministic validation, and blast-radius queries."
            ),
            source_refs=(
                "docs/LUNA_ROADMAP.md#C-002",
                "docs/ROADMAP_DEPENDENCY_REVIEW.md#C-002",
            ),
            foundation_refs=(
                "MANIFEST.json",
                "SHA256SUMS.txt",
                "Phase 19 evaluation vocabulary",
            ),
            implementation_components=(
                "src/luna/capabilities/models.py",
                "src/luna/capabilities/registry.py",
                "src/luna/capabilities/catalog.py",
            ),
            verifier_refs=(
                "tests/test_c002_capability_lineage.py",
                "scripts/verify_c002.py",
            ),
            evidence_refs=(
                "docs/C002_CAPABILITY_LINEAGE_REPORT.md",
                "c002_verification.json",
            ),
            metrics=(
                "broken_dependency_reference_count",
                "dependency_cycle_count",
                "stale_verified_evidence_count",
                "blast_radius_node_count",
            ),
            authority_boundary=(
                "C-002 is a read-only governance/query layer. It cannot grant runtime authority, "
                "promote a model, mutate the roadmap automatically, or execute dependent "
                "capabilities."
            ),
            rollback_or_disable_path=(
                "Remove C-002 query/catalog wiring and restore the prior capability metadata; no "
                "runtime behavior depends on C-002 for execution authority."
            ),
            source_revision=_SOURCE_REVISION,
            evidence_revision="c002-local-gate",
            evidence_freshness=EvidenceFreshness.PARTIAL,
        ),
        _queued(
            "C-003",
            "Experience Distillation",
            "Transform governed experience into evidence-backed reusable lessons and invariants.",
            preferred=("C-002", "C-001"),
            foundation_refs=("Phase 19 governed traces",),
        ),
        _queued(
            "C-004",
            "Pre-deployment Experience Inheritance",
            (
                "Adopt validated lessons before deployment without inheriting accidental "
                "source-agent behavior."
            ),
            preferred=("C-002", "C-003"),
            foundation_refs=("Phase 19F Improvement Gate",),
        ),
        _queued(
            "C-005",
            "Experience <-> Capability Flywheel",
            (
                "Iterate from experience to capability to verified new experience without "
                "self-certification."
            ),
            preferred=("C-002", "C-003"),
        ),
        _queued(
            "C-006",
            "Vicarious Experience Inheritance",
            (
                "Learn validated invariants from another actor's success or failure before paying "
                "the same cost."
            ),
            preferred=("C-002", "C-003"),
        ),
        _queued(
            "C-007",
            "Debugging Capability Decomposition & Transfer",
            (
                "Treat debugging as a measurable stack from observation through diagnosis, repair, "
                "and regression."
            ),
            preferred=("C-002", "C-003", "C-001"),
        ),
        _queued(
            "C-008",
            "Sol -> Luna Capability Mining",
            (
                "Decompose useful observable Sol behaviors and map prerequisites, coverage, "
                "metrics, and risks."
            ),
            preferred=("C-002", "C-003"),
        ),
        _queued(
            "C-009",
            "Cross-Agent Experience Mining",
            (
                "Compare multiple agents and traces to extract validated transferable "
                "strengths and failure lessons."
            ),
            preferred=("C-002", "C-003", "C-007"),
        ),
        _queued(
            "C-010",
            "External Mentor / Review Boundary",
            (
                "Keep external-model mentoring in reviewed learning/review workflows rather than "
                "task-time dependency."
            ),
            preferred=("C-002", "C-003"),
        ),
        _queued(
            "C-011",
            "Single-Voice Parallel Cognition",
            (
                "Temporary isolated workers prepare evidence/drafts while Main Luna keeps "
                "one state and one voice."
            ),
            preferred=("C-002", "C-001", "C-003"),
            foundation_refs=("single authoritative Luna runtime state",),
        ),
        _queued(
            "C-012",
            "Self-Optimization Sandbox",
            (
                "Generate bounded sandbox optimization candidates that still require independent "
                "evidence and gating."
            ),
            preferred=("C-002", "C-001", "C-003", "C-011"),
            foundation_refs=("Phase 19F Improvement Gate", "sandbox/rollback boundaries"),
        ),
    )
    return CapabilityRegistry(records)
