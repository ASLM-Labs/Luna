# C-002 Capability Lineage Foundation Report

Status: IMPLEMENTED_UNVERIFIED

## Implemented boundary

C-002 now provides:

- canonical capability records for C-001 through C-012;
- hard vs preferred prerequisite fields;
- source, foundation, implementation, verifier, evidence, metric, authority, and rollback metadata;
- evidence freshness and evidence revision state;
- deterministic duplicate/unknown/self/cycle validation;
- verified-status evidence gates;
- direct and transitive blast-radius queries;
- hard-only vs hard+preferred query modes;
- deterministic `scripts/verify_c002.py` evidence output.

C-002 remains read-only governance. It has no runtime, promotion, training, roadmap-mutation,
worker-execution, or self-optimization authority.

## Identity reconciliation finding

Source inspection found an important planning inconsistency that C-002 must not hide:

- canonical `docs/LUNA_ROADMAP.md` defines **C-005** as `Experience <-> Capability Flywheel`;
- canonical `docs/LUNA_ROADMAP.md` defines **C-006** as `Vicarious Experience Inheritance`;
- the same roadmap defines **C-007** as `Debugging Capability Decomposition & Transfer`;
- the same roadmap defines **C-009** as `Cross-Agent Experience Mining`;
- `docs/ROADMAP_DEPENDENCY_REVIEW.md` later uses the labels `C-005 Advanced Debugging Transfer`
  and `C-006 Cross-Agent Experience Mining` in its recommended order.

C-002 does **not silently remap** those conflicting IDs. The canonical registry preserves the explicit
capability-queue identities. Any future renumbering or dependency-order correction requires an explicit
Delta Review before those conflicting planning labels become authoritative lineage edges.

This finding also means the external convenience plan `LUNA_GUNCEL_YOL_HARITASI_V3.md` should be
checked against the canonical registry when it is next reviewed; repository truth remains primary.

## Current evidence state

C-002 is `IMPLEMENTED_UNVERIFIED` with `PARTIAL` evidence while local implementation evidence exists
but merge containment and final CI evidence have not yet converted the capability to `VERIFIED`.

`VERIFIED` must not be self-assigned by this implementation.

## Explicitly out of scope

- automatic capability promotion;
- automatic roadmap mutation;
- model self-certification;
- C-001 retrieval implementation;
- C-003 experience-distillation implementation;
- C-011 worker execution;
- C-012 optimization execution;
- real training;
- external actions.
