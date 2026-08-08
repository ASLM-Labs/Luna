# Luna Legacy Roadmap Reconciliation

## Purpose

This document reconciles the historical planning document
`LUNA_GUNCELLENMIS_FAZ_PLANI_V2.md` with the current repository roadmap after
Phase 19 and the queued C-011 / C-012 capability designs.

The historical plan is not reintroduced wholesale. Repository implementation,
current verifiers, current handoff state, and current roadmap remain the source
of truth for completed work.

The historical plan contributes only still-relevant canonical intent that was
not yet persisted in the repository roadmap.

## Reconciliation decision

### PRESERVE

The following historical planning intent remains valid and is now persisted:

1. **Phase 20 is reserved for Final Conformance Comparison and Release Candidate.**
2. **Phase 21 is reserved for post-v0.1 research.**
3. New roadmap discoveries must use an explicit **Delta Review** instead of
   silently rewriting the roadmap.
4. Uncontrolled self-modification remains prohibited.
5. Automatic deployment / external actions require a separate security design
   and owner-confirmation boundary.

### SUPERSEDE

Historical detailed phase/subphase contents for already-completed Phase 12-19
work are superseded by the actual repository implementation, current reports,
verifiers, tests, manifests, merge history, and current roadmap.

In particular, historical Phase 19 subphase names must not overwrite the current
Phase 19A-F governance architecture that was actually implemented and merged.

### DO NOT IMPORT

The following historical items are not copied back into the live roadmap merely
because they existed in the old plan:

- obsolete branch names;
- obsolete test counts or baselines;
- historical Phase 12-19 implementation sequences already replaced by real work;
- Atlas architecture or migration assumptions;
- claims that a real model training run occurred when repository governance did
  not execute or verify one.

## Canonical Phase 20 reservation

# Phase 20 — Final Conformance Comparison and Release Candidate

Phase 20 is the formal closing/release-candidate phase.

Its purpose is not to introduce C-002 or another queued capability. It compares
the completed Luna system against its governing requirements and evidence.

### Comparison sources

Phase 20 should compare, where still applicable:

1. the operational architecture requirements;
2. Sol/Codex Luna design guidance that remains accepted;
3. the current versioned roadmap and reconciliation records;
4. the real Luna repository implementation;
5. local and CI test evidence;
6. frozen runtime/model/research/behavior evaluation evidence.

Historical Atlas architecture is not a conformance authority.

### Requirement matrix contract

Each requirement should be represented as:

```text
requirement
source
implemented_component
test_or_eval
evidence_artifact
status
known_limitation
follow_up
```

Allowed conformance states:

```text
PASS
PARTIAL
DEFERRED_WITH_REASON
REJECTED_WITH_REASON
MISSING
```

### Release-candidate conditions

At minimum:

- critical runtime safety gates pass;
- model compatibility gates pass where the model path is included;
- research gates pass where research is included;
- desktop / Discord / voice are included only if their own gates remain green;
- known limitations are published;
- release manifest and hashes are current;
- rollback and upgrade plan are documented;
- no unresolved critical evidence contradiction exists.

Expected closing artifacts:

```text
LUNA_FINAL_CONFORMANCE_MATRIX.md
LUNA_KNOWN_LIMITATIONS.md
LUNA_RELEASE_MANIFEST.json
v0.1-rc1
```

The exact final artifact names may be versioned later, but changing them requires
an explicit roadmap/RFC decision rather than silent drift.

## Canonical Phase 21 reservation

# Phase 21 — Post-v0.1 Research

Phase 21 remains a research umbrella after the v0.1 release-candidate path.

Historical research themes include:

- subagent / parallel-work research;
- multi-model routing;
- self-improvement research;
- automatic deployment / external-action research.

Current roadmap capability designs refine some of those themes:

### C-011 relationship

**C-011 — Single-Voice Parallel Cognition** is the current governed design for
parallel work without fragmenting Luna's authoritative state, identity, or
user-facing voice.

C-011 remains QUEUED. Its existence does not mean the historical Phase 21
subagent research boundary has already been implemented.

### C-012 relationship

**C-012 — Self-Optimization Sandbox** is the current governed design for
producing bounded optimization candidates in sandbox / controlled replay.

C-012 remains QUEUED and preserves the historical safety boundary:

> Optimization candidates may be proposed and tested; production self-promotion
> and uncontrolled self-modification are not allowed.

### Multi-model routing

Multi-model routing remains a later research topic unless explicitly promoted by
a future roadmap decision after a reliable baseline and evaluation contract.

### External actions

Automatic deployment or external actions require separate security governance,
explicit owner-confirmation UX, rollback, and evidence-bound authorization.

### Permanent boundary

Uncontrolled self-modification remains prohibited.

## Delta Review rule

New findings do not silently rewrite the roadmap.

Every material roadmap discovery should pass through:

```text
new finding
  -> current capability / phase counterpart
  -> genuinely new requirement?
  -> conflict with current architecture?
  -> dependency-order impact?
  -> new acceptance/evaluation needed?
  -> decision: ADD / ADAPT / DEFER / REJECT / SUPERSEDE
```

A Delta Review should record:

```text
source
finding
current_repository_reality
affected_capabilities
affected_phase_reservations
dependency_impact
evaluation_impact
authority_impact
decision
reason
follow_up
```

Repository reality outranks stale planning prose.

## C-002 naming consequence

Because Phase 20 is canonically reserved for Final Conformance + Release
Candidate, C-002 must **not** use `Phase 20A`.

Current recommended implementation identity:

```text
Capability: C-002 — Capability Lineage Mapping
Branch: capability/c002-lineage-foundation
```

C-002 remains the recommended next implementation from the dependency review.
Only its phase numbering changes: it is a capability implementation, not Phase
20A.

## Result

The roadmap now preserves both truths:

```text
NEXT CAPABILITY IMPLEMENTATION
C-002 Capability Lineage Mapping

RESERVED CLOSING PHASE
Phase 20 Final Conformance Comparison + Release Candidate

POST-v0.1 RESEARCH
Phase 21
```

This prevents a capability branch from silently consuming a historically
reserved release phase number.
