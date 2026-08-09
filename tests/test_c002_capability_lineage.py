from __future__ import annotations

import pytest
from pydantic import ValidationError

from luna.capabilities import (
    CapabilityRecord,
    CapabilityRegistry,
    CapabilityStatus,
    DependencyKind,
    EvidenceFreshness,
    build_canonical_capability_registry,
)


def _record(
    capability_id: str,
    *,
    name: str | None = None,
    hard: tuple[str, ...] = (),
    preferred: tuple[str, ...] = (),
) -> CapabilityRecord:
    return CapabilityRecord(
        capability_id=capability_id,
        name=name or capability_id,
        status=CapabilityStatus.QUEUED,
        scope="fixture capability",
        hard_prerequisites=hard,
        preferred_prerequisites=preferred,
        source_refs=("fixture:roadmap",),
        authority_boundary="fixture has no runtime authority",
        rollback_or_disable_path="remove fixture metadata",
        source_revision="fixture-revision",
        evidence_freshness=EvidenceFreshness.MISSING,
    )


def test_canonical_registry_preserves_current_roadmap_identities() -> None:
    registry = build_canonical_capability_registry()

    assert tuple(record.capability_id for record in registry.records) == tuple(
        f"C-{index:03d}" for index in range(1, 13)
    )
    assert registry.get("C-005").name == "Experience <-> Capability Flywheel"
    assert registry.get("C-006").name == "Vicarious Experience Inheritance"
    assert registry.get("C-007").name == "Debugging Capability Decomposition & Transfer"
    assert registry.get("C-009").name == "Cross-Agent Experience Mining"


def test_c002_is_implemented_unverified_and_has_repository_evidence() -> None:
    record = build_canonical_capability_registry().get("C-002")

    assert record.status is CapabilityStatus.IMPLEMENTED_UNVERIFIED
    assert record.evidence_freshness is EvidenceFreshness.PARTIAL
    assert record.implementation_components
    assert record.verifier_refs
    assert record.evidence_refs
    assert "runtime authority" in record.authority_boundary


def test_unknown_duplicate_self_and_mixed_dependencies_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate capability ID"):
        CapabilityRegistry((_record("C-001"), _record("C-001", name="other")))

    with pytest.raises(ValueError, match="unknown capability dependency"):
        CapabilityRegistry((_record("C-001", hard=("C-999",)),))

    with pytest.raises(ValidationError, match="cannot depend on itself"):
        _record("C-001", hard=("C-001",))

    with pytest.raises(ValidationError, match="both hard and preferred"):
        _record("C-001", hard=("C-002",), preferred=("C-002",))


def test_dependency_cycles_are_rejected() -> None:
    with pytest.raises(ValueError, match="dependency cycle"):
        CapabilityRegistry(
            (
                _record("C-001", hard=("C-002",)),
                _record("C-002", hard=("C-001",)),
            )
        )


def test_verified_status_requires_current_evidence_and_repository_refs() -> None:
    with pytest.raises(ValidationError, match="implementation components"):
        CapabilityRecord(
            capability_id="C-001",
            name="verified-without-evidence",
            status=CapabilityStatus.VERIFIED,
            scope="fixture",
            source_refs=("fixture:roadmap",),
            authority_boundary="none",
            rollback_or_disable_path="disable",
            source_revision="r1",
            evidence_revision="r1",
            evidence_freshness=EvidenceFreshness.CURRENT,
        )


def test_dependency_kind_query_is_explicit() -> None:
    registry = CapabilityRegistry(
        (
            _record("C-001"),
            _record("C-002", hard=("C-001",)),
            _record("C-003", preferred=("C-001",)),
        )
    )

    assert registry.dependencies("C-002", kind=DependencyKind.HARD) == ("C-001",)
    assert registry.dependencies("C-003", kind=DependencyKind.PREFERRED) == ("C-001",)


def test_blast_radius_is_deterministic_and_can_exclude_preferred_edges() -> None:
    registry = CapabilityRegistry(
        (
            _record("C-001"),
            _record("C-002", hard=("C-001",)),
            _record("C-003", preferred=("C-001",)),
            _record("C-004", hard=("C-002",)),
        )
    )

    all_edges = registry.blast_radius("C-001")
    hard_only = registry.blast_radius("C-001", include_preferred=False)

    assert all_edges.direct_dependents == ("C-002", "C-003")
    assert all_edges.indirect_dependents == ("C-004",)
    assert ("C-001", "C-002", "C-004") in all_edges.dependency_paths
    assert hard_only.direct_dependents == ("C-002",)
    assert hard_only.indirect_dependents == ("C-004",)
