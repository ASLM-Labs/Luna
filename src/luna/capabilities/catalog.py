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
        CapabilityRecord(
            capability_id="C-001",
            name="Adaptive Knowledge Retrieval",
            status=CapabilityStatus.IMPLEMENTED_UNVERIFIED,
            scope=(
                "Evidence-aware deterministic routing among internal knowledge, working context, "
                "verified memory, project RAG, Research Gateway/web, and structured APIs."
            ),
            preferred_prerequisites=("C-002",),
            source_refs=(
                "docs/LUNA_ROADMAP.md#C-001",
                "docs/ROADMAP_DEPENDENCY_REVIEW.md#C-001",
            ),
            foundation_refs=(
                "Phase 9 verified memory",
                "Phase 12B layered context",
                "Phase 14 Research Gateway / evidence RAG",
                "C-002 capability lineage",
            ),
            implementation_components=(
                "src/luna/retrieval/models.py",
                "src/luna/retrieval/router.py",
            ),
            verifier_refs=(
                "tests/test_c001_adaptive_knowledge_retrieval.py",
                "scripts/verify_c001.py",
            ),
            evidence_refs=(
                "docs/C001_ADAPTIVE_KNOWLEDGE_RETRIEVAL_REPORT.md",
                "c001_verification.json",
            ),
            metrics=(
                "source_selection_accuracy",
                "unnecessary_retrieval_rate",
                "missed_retrieval_rate",
                "stale_answer_rate",
                "evidence_sufficiency",
                "contradiction_detection_rate",
                "provenance_citation_correctness",
                "retrieval_latency",
                "retrieval_cost",
            ),
            authority_boundary=(
                "C-001 is a read-only routing layer with no runtime or promotion authority. It "
                "does not fetch network data directly, authorize external actions, or commit "
                "retrieval results to long-term memory automatically."
            ),
            rollback_or_disable_path=(
                "Disable C-001 routing and fall back to explicit caller-selected sources; existing "
                "Phase 9 memory, Phase 12B context, and Phase 14 research boundaries remain intact."
            ),
            source_revision="c001-adaptive-retrieval-foundation",
            evidence_revision="c001-local-gate",
            evidence_freshness=EvidenceFreshness.PARTIAL,
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
        CapabilityRecord(
            capability_id="C-003",
            name="Experience Distillation",
            status=CapabilityStatus.IMPLEMENTED_UNVERIFIED,
            scope=(
                "Transform governed Phase 19 experience into evidence-backed, cross-case reusable "
                "lesson candidates without hidden reasoning, held-out contamination, or "
                "self-certification."
            ),
            preferred_prerequisites=("C-002", "C-001"),
            source_refs=(
                "docs/LUNA_ROADMAP.md#C-003",
                "docs/ROADMAP_DEPENDENCY_REVIEW.md#C-003",
            ),
            foundation_refs=(
                "Phase 19 governed structured traces",
                "Phase 19 leak-free split governance",
                "C-001 adaptive knowledge retrieval",
                "C-002 capability lineage",
            ),
            implementation_components=(
                "src/luna/experience/models.py",
                "src/luna/experience/distillation.py",
            ),
            verifier_refs=(
                "tests/test_c003_experience_distillation.py",
                "scripts/verify_c003.py",
            ),
            evidence_refs=(
                "docs/C003_EXPERIENCE_DISTILLATION_REPORT.md",
                "c003_verification.json",
            ),
            metrics=(
                "cross_case_support_group_count",
                "cross_task_support_family_count",
                "contradiction_rejection_rate",
                "unobserved_evidence_rejection_rate",
                "heldout_contamination_rejection_rate",
                "self_report_rejection_rate",
                "review_candidate_rate",
            ),
            authority_boundary=(
                "C-003 produces review-required lesson candidates only. It grants no runtime, "
                "training, memory-commit, or promotion authority and cannot use model self-report "
                "as independent evidence."
            ),
            rollback_or_disable_path=(
                "Disable C-003 distillation and retain the original governed traces; no distilled "
                "candidate is automatically committed to memory, training, runtime, or promotion."
            ),
            source_revision="c003-experience-distillation-foundation",
            evidence_revision="c003-local-gate",
            evidence_freshness=EvidenceFreshness.PARTIAL,
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
        CapabilityRecord(
            capability_id="C-007",
            name="Debugging Capability Decomposition & Transfer",
            status=CapabilityStatus.IMPLEMENTED_UNVERIFIED,
            scope=(
                "Decompose debugging into observable diagnosis, repair, verification, "
                "changed-basis replanning, and prevention stages, then test reviewed C-003 "
                "lessons on unseen paired held-out debugging cases."
            ),
            preferred_prerequisites=("C-002", "C-003", "C-001"),
            source_refs=(
                "docs/LUNA_ROADMAP.md#C-007",
                "docs/POST_C003_CAPABILITY_ORDER_DELTA_REVIEW.md#Decision-C-007-is-next",
            ),
            foundation_refs=(
                "C-003 Experience Distillation",
                "Phase 12D failure recovery and minimal change",
                "Phase 19 cognitive quality and failure taxonomy",
                "Phase 19F improvement governance",
            ),
            implementation_components=(
                "src/luna/debugging/models.py",
                "src/luna/debugging/evaluator.py",
            ),
            verifier_refs=(
                "tests/test_c007_debugging_capability_transfer.py",
                "scripts/verify_c007.py",
            ),
            evidence_refs=(
                "docs/C007_DEBUGGING_CAPABILITY_TRANSFER_REPORT.md",
                "c007_verification.json",
            ),
            metrics=(
                "repair_success_delta",
                "diagnosis_quality_delta",
                "failure_localization_delta",
                "hypothesis_quality_delta",
                "broken_assumption_detection_delta",
                "minimal_repair_planning_delta",
                "tool_selection_delta",
                "targeted_verification_delta",
                "full_regression_verification_delta",
                "changed_basis_replan_delta",
                "prevention_lesson_delta",
                "heldout_contamination_rejection_rate",
            ),
            authority_boundary=(
                "C-007 evaluates controlled lesson-to-debugging transfer only. A C-003 candidate "
                "requires explicit review binding; transfer evidence grants no runtime, training, "
                "memory-commit, promotion, deployment, or external-action authority."
            ),
            rollback_or_disable_path=(
                "Disable the C-007 evaluator and retain C-003 lesson candidates plus the existing "
                "Phase 12D/19 debugging foundations; no evaluated lesson is automatically adopted."
            ),
            source_revision="c007-debugging-capability-transfer-foundation",
            evidence_revision="c007-local-gate",
            evidence_freshness=EvidenceFreshness.PARTIAL,
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
