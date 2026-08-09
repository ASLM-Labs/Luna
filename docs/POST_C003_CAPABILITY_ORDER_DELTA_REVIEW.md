# Post-C-003 Capability Order Delta Review

Status: REVIEWED / PLANNING-ONLY
Date: 2026-08-09
Baseline main: `258bafb`
Source archive SHA256: `5c2fbe48a421b570988a5207e11e4fe25de354943f4841cc8d3fb2a67763e293`

## Purpose

Resolve the historical capability-ID shorthand drift before beginning the next implementation, reconcile the post-C-003 project checkpoint, and select one canonical next capability without silent renumbering.

## Evidence boundary

This review uses the canonical capability queue in `docs/LUNA_ROADMAP.md`, the existing C-002 capability-lineage registry, the historical dependency review, and the merged C-003 source tree.

Operational merge/CI closure and repository evidence-state are kept distinct. C-001, C-002, and C-003 are operationally closed project checkpoints, but this planning review does not rewrite C-002 `CapabilityStatus` / `EvidenceFreshness` records to self-certify `VERIFIED`. A future evidence-state reconciliation may do that only with repository-stored closure evidence.

## Identity correction

The historical review used two shorthand IDs whose titles conflict with the explicit queue:

| Historical shorthand | Canonical identity | Decision |
| --- | --- | --- |
| C-005 Advanced Debugging Transfer | C-007 Debugging Capability Decomposition & Transfer | Correct the planning reference to C-007; do not rename C-005. |
| C-006 Cross-Agent Experience Mining | C-009 Cross-Agent Experience Mining | Correct the planning reference to C-009; do not rename C-006. |

Canonical identities preserved:

- C-004 — Pre-deployment Experience Inheritance
- C-005 — Experience <-> Capability Flywheel
- C-006 — Vicarious Experience Inheritance
- C-007 — Debugging Capability Decomposition & Transfer
- C-008 — Sol -> Luna Capability Mining
- C-009 — Cross-Agent Experience Mining
- C-010 — External Mentor / Review Boundary
- C-011 — Single-Voice Parallel Cognition
- C-012 — Self-Optimization Sandbox

## Decision: C-007 is next

C-003 now produces evidence-backed, review-required lesson candidates. The next step should not immediately broaden inheritance or external-agent ingestion. It should first test whether distilled experience can support one narrow, measurable capability.

C-007 is that vertical:

```text
error observation
-> failure localization
-> hypothesis generation/ranking
-> broken-assumption detection
-> state/context inspection
-> minimal-repair planning
-> correct tool selection
-> patch/action
-> targeted verification
-> full regression verification
-> changed-basis replan if needed
-> prevention/process lesson
```

This is directly measurable against the existing Phase 19 cognitive dimensions and matches Luna's existing changed-basis, evidence, verification, and failure-taxonomy governance.

## Preferred implementation sequence

```text
C-002 Capability Lineage & Dependency Mapping       CLOSED
 -> C-001 Adaptive Knowledge Retrieval              CLOSED
 -> C-003 Experience Distillation                   CLOSED
 -> C-007 Debugging Capability Decomposition & Transfer   NEXT
 -> C-005 Experience <-> Capability Flywheel
 -> C-010 External Mentor / Review Boundary
 -> C-008 Sol -> Luna Capability Mining
 -> C-009 Cross-Agent Experience Mining
 -> C-006 Vicarious Experience Inheritance
 -> C-004 Pre-deployment Experience Inheritance
 -> C-011 Single-Voice Parallel Cognition
 -> C-012 Self-Optimization Sandbox
```

This is a preferred implementation sequence. It does not convert every arrow into a hard runtime dependency.

## Why the remaining order is conservative

### C-005 after C-007

The flywheel should be built around at least one concrete, independently measurable capability transfer. Otherwise the loop risks becoming a governance abstraction without demonstrated transfer quality.

### C-010 before external mining

The task-time / review-time external-mentor boundary should be explicit before Luna begins to mine external agent behavior as a normal learning source. This prevents mentor dependence from leaking into active task execution.

### C-008 before C-009

C-008 provides a narrow source-specific mining contract for observable Sol behavior. C-009 can then generalize the same discipline across multiple agents, versions, and curated traces without inventing a broad cross-agent pipeline first.

### C-009 before C-006

Mining/comparison should produce reviewed, provenance-bound candidates before vicarious inheritance attempts to transfer another actor's lesson into Luna's prevention/capability stack.

### C-006 before C-004

Vicarious inheritance proves the controlled transfer mechanism. C-004 is the broader adoption layer that lets a future generation begin with validated inherited lessons before deployment.

### C-011 and C-012 remain later

C-011 composes retrieval, evidence, and distillation into bounded parallel work while preserving one authoritative Luna voice/state. C-012 remains last because it composes candidate generation, sandboxing, independent evidence, rollback, and Phase 19F gating.

## Product-design queue persistence

The Discord design discussed after C-003 is recorded as a queued product-design item, not a capability implementation claim:

- substantially fewer visible channels;
- one obvious destination per common action;
- `#genel` as the normal community chat;
- Luna invoked by mention/reply in allowed channels;
- bounded temporary participation after an explicit invitation to join a discussion;
- natural exit on dismissal, inactivity, or topic departure;
- governed, user-controllable useful preference memory without unnecessary profiling;
- Discord focused on community, support, knowledge, and light interaction rather than heavy repository coding;
- channel architecture, roles, permissions, onboarding, public release notes, and private developer surfaces designed as one system.

No part of this item is claimed implemented by Phase 17 today.

## Guardrails preserved

- Phase 20 remains Final Conformance Comparison and Release Candidate.
- Phase 21 remains Post-v0.1 Research.
- No automatic roadmap mutation.
- No model self-certification.
- No runtime, training, memory-commit, promotion, worker, deployment, or external-action authority is granted by this review.
- Historical planning evidence is preserved; conflicting shorthand is superseded explicitly rather than erased.

## Next step

After this Delta Review passes the normal local/CI gates, is merged, contained in `origin/main`, and the working tree is clean, create:

`capability/c007-debugging-capability-transfer`

Do not begin C-007 implementation on the Delta Review branch.
