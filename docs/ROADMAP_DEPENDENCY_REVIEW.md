# Luna Roadmap Dependency Review

## Status

- Review type: capability dependency / implementation-order review
- Baseline: post-Phase-19 main with C-011 and C-012 design documentation merged
- Purpose: choose implementation order from dependency and evidence needs, not novelty
- Authority: planning document only; it does not mark any queued capability as implemented

## Decision rule

The next capability should be chosen by asking:

```text
What does this capability depend on?
What existing Luna foundation can prove it works?
What downstream capabilities does it unlock?
What failure modes appear if it is implemented too early?
What evaluation evidence is required before calling it complete?
```

Dependencies are separated into:

- **Hard prerequisite:** required for a credible implementation or promotion claim.
- **Preferred prerequisite:** not strictly required, but materially reduces rework,
  ambiguity, context pollution, unsafe coupling, or weak evaluation.
- **Existing foundation:** already-built Luna infrastructure that can support the work.

## Reviewed capability set

This review covers the currently established queue entries discussed in the roadmap:

- C-001 — Adaptive Knowledge Retrieval
- C-002 — Capability Lineage Mapping
- C-003 — Experience Distillation
- C-004 — Pre-deployment Inheritance
- C-005 — Advanced Debugging Transfer
- C-006 — Cross-Agent Experience Mining
- C-011 — Single-Voice Parallel Cognition
- C-012 — Self-Optimization Sandbox

This document deliberately does **not** invent canonical C-007 through C-010 IDs.
If the canonical roadmap assigns those IDs elsewhere, they should be incorporated
by a later delta review using the repository as source of truth.

## Dependency map

```text
                     C-002
          Capability Lineage Mapping
                       |
             +---------+---------+
             |                   |
             v                   v
           C-001               C-003
    Adaptive Retrieval   Experience Distillation
             |                   |
             |           +-------+-------+
             |           |               |
             |           v               v
             |         C-005           C-006
             |   Debugging Transfer   Cross-Agent Mining
             |           |               |
             +-----------+-------+-------+
                                 |
                                 v
                               C-004
                    Pre-deployment Inheritance
                                 |
                                 v
                               C-011
                 Single-Voice Parallel Cognition
                                 |
                                 v
                               C-012
                   Self-Optimization Sandbox
```

The arrows above represent **recommended implementation flow**, not all hard
dependencies.

## Capability dependency matrix

| Order | Capability | Hard prerequisites | Preferred prerequisites | Existing Luna foundation | Main unlocks | Primary risk if too early |
|---|---|---|---|---|---|---|
| 1 | C-002 Capability Lineage Mapping | Stable repository metadata/evidence contracts | Phase 19 evaluation vocabulary | MANIFEST/SHA lineage, verifiers, phase reports, handoff/roadmap, Phase 19 metrics | Makes later capability dependencies and side effects explicit | Later work remains manually coupled and difficult to audit |
| 2 | C-001 Adaptive Knowledge Retrieval | Evidence/provenance boundaries | C-002 | Memory/context architecture, RAG/research concepts, tool/evidence discipline | Better source selection for research, workers, debugging, self-optimization | Retrieval becomes “search more” instead of evidence-aware routing |
| 3 | C-003 Experience Distillation | Governed traces and evaluation criteria | C-002, C-001 | Phase 19 trajectory reconstruction, taxonomy, integrity, held-out/OOD gates | Reusable lessons/invariants for C-005, C-006, C-004, C-012 | Raw anecdotes or correlations become false “lessons” |
| 4 | C-005 Advanced Debugging Transfer | C-003 | C-002, C-001 | Changed-basis self-correction, verification, failure taxonomy, coding traces | First narrow, measurable demonstration of distilled experience becoming capability | Symptom-fixing heuristics are mistaken for transferable debugging skill |
| 5 | C-006 Cross-Agent Experience Mining | C-003 | C-002, C-005 | Provenance, trace governance, contamination checks, independent evidence rules | Trusted external lessons for inheritance | External agent style/bias is copied instead of generalized |
| 6 | C-004 Pre-deployment Inheritance | C-003, governed source provenance | C-006, C-002, C-005 | Dataset governance, Phase 19F gate, experience evaluation | Stronger initial behavior without repeating known failures | “Inheritance” degenerates into unverified data copying |
| 7 | C-011 Single-Voice Parallel Cognition | Single authoritative Luna state and runtime authority boundary | C-002, C-001, C-003 | Worker contract design, shared-weight concept, admission policy, result distillation, cost/latency evaluation design | Parallel research/draft/test/verification without multi-persona fragmentation | Worker sprawl, context pollution, duplicated work, authority drift |
| 8 | C-012 Self-Optimization Sandbox | Phase 19F Improvement Gate, sandbox/rollback boundaries | C-002, C-001, C-003, C-011 | Candidate evidence contracts, controlled replay, independent verification, promotion separation | Safe generation/evaluation of optimization candidates | Self-certification, recursive scope growth, efficiency hiding quality regression |

## Recommended implementation order

### 1. C-002 — Capability Lineage Mapping

**Why first:** every later capability needs a reliable answer to:

```text
capability
  -> prerequisites
  -> implementation components
  -> evidence
  -> metrics
  -> downstream dependencies
  -> regression blast radius
```

C-002 should become the roadmap's navigation and impact-analysis layer.

Minimum completion evidence should include:

- a canonical capability registry;
- explicit hard vs preferred prerequisites;
- implementation-component references;
- verifier/evaluation references;
- downstream dependency references;
- status and evidence freshness;
- deterministic validation for broken/missing lineage links;
- no self-reported “implemented” status without repository evidence.

### 2. C-001 — Adaptive Knowledge Retrieval

**Why second:** Luna should know when internal/context knowledge is enough and when
fresh external evidence is required.

The capability should route among:

```text
model/internal knowledge
working context
verified memory
project/document RAG
web/research gateway
structured APIs
```

It should measure missed retrieval, unnecessary retrieval, stale evidence,
source-authority mistakes, contradiction handling, latency, and cost.

### 3. C-003 — Experience Distillation

**Why third:** Phase 19 created governed traces; C-003 turns them into reusable
lessons without preserving raw failure noise or hidden reasoning.

Canonical transformation:

```text
experience
  -> evidence-backed lesson
  -> invariant / heuristic / strategy
  -> generalization test
  -> reusable capability candidate
```

A model's explanation of why it succeeded is not enough. Distillation requires
observable evidence and cross-case validation.

### 4. C-005 — Advanced Debugging Transfer

**Why before broad inheritance:** debugging is a narrow, highly testable vertical
for proving that experience distillation actually transfers.

Target decomposition:

```text
error observation
  -> localization
  -> hypothesis ranking
  -> broken assumption
  -> minimal repair
  -> tool/action
  -> targeted verification
  -> full regression
  -> changed-basis replan when needed
  -> process lesson
```

### 5. C-006 — Cross-Agent Experience Mining

Only after Luna can distill its own experience should it ingest lessons from Sol,
Codex, previous Luna versions, curated traces, or community sources.

External experience must be:

- source-attributed;
- normalized;
- separated from authoritative truth;
- checked for contradictory assumptions;
- generalized before transfer;
- validated against Luna's own environment.

### 6. C-004 — Pre-deployment Inheritance

Inheritance is the adoption layer, not the mining layer.

```text
external / historical experience
        |
        v
distill + generalize + validate
        |
        v
capability candidate
        |
        v
pre-deployment inheritance
        |
        v
fixed evaluation / Improvement Gate
```

The goal is to inherit lessons without inheriting another system's accidental
tool language, persona, environment assumptions, or failure habits.

### 7. C-011 — Single-Voice Parallel Cognition

C-011 should come after retrieval and experience foundations are measurable.

Canonical boundary remains:

> One mind. Many hands. One voice.

> Workers prepare. Evidence supports. Luna decides. Runtime executes.

Workers are temporary evidence/draft producers. Main Luna retains authoritative
state, decision authority, and the single user-facing voice.

Admission remains cost-aware:

> Parallelize when useful, not because possible.

Context adoption remains distilled:

> Distill worker context before state adoption.

Parallelism is evaluated by outcome:

> Measure parallelism by quality + latency + compute, not worker count.

### 8. C-012 — Self-Optimization Sandbox

C-012 should be last in this sequence because it composes many earlier abilities:

```text
observe opportunity
  -> retrieve evidence
  -> understand capability dependencies
  -> generate candidate
  -> run controlled experiment
  -> interpret result
  -> changed-basis replan
  -> independent verification
  -> Improvement Gate
  -> external promotion authority
```

Canonical boundary:

> Optimize freely in the sandbox; promote only with evidence.

> A system may propose its own improvement. It may not certify itself improved.

## Cross-cutting gates

Every queued capability implementation should inherit these project-level gates:

- repository reality outranks planning prose;
- observable evidence outranks self-report;
- contradictory evidence triggers stop/reinspection;
- changed-basis replanning replaces blind retry;
- learning does not grant runtime authority;
- evaluation does not grant promotion authority;
- critical safety regressions remain zero-tolerance;
- non-critical changes use meaningful thresholds and confidence where applicable;
- provenance, rollback, exact scope, and deterministic verification remain first-class.

## First implementation recommendation

**Recommended next implementation:** C-002 — Capability Lineage Mapping.

Do **not** assign a new numbered product phase merely from this review if the
canonical phase-number roadmap has a conflicting Phase 20 definition. First
implement C-002 on its own branch/subphase naming that does not overwrite an
existing phase contract.

Suggested branch:

```text
capability/c002-lineage-foundation
```

Suggested first implementation boundary:

```text
canonical capability registry
+ dependency edge model
+ evidence references
+ status/evidence freshness
+ deterministic lineage verifier
+ dependency/blast-radius query
```

Explicitly out of first C-002 scope:

```text
automatic capability promotion
automatic roadmap mutation
model self-certification
C-011 worker execution
C-012 self-optimization execution
real training
```

## Review conclusion

Recommended sequence:

```text
C-002
 -> C-001
 -> C-003
 -> C-005
 -> C-006
 -> C-004
 -> C-011
 -> C-012
```

This order is intentionally conservative. It builds the map before adding more
routes, teaches Luna to retrieve before asking parallel workers to retrieve, and
teaches Luna to distill and verify experience before allowing that experience
to influence inheritance or self-optimization.\n\n<!-- C002_IDENTITY_FINDING_BEGIN -->\n\n## C-002 identity-lineage finding\n\nC-002 source inspection detected that this review's shorthand entries `C-005 Advanced Debugging\nTransfer` and `C-006 Cross-Agent Experience Mining` do not match the explicit capability queue in\n`docs/LUNA_ROADMAP.md`, where C-005 is `Experience <-> Capability Flywheel`, C-006 is `Vicarious\nExperience Inheritance`, C-007 is the debugging capability, and C-009 is Cross-Agent Experience\nMining.\n\nThis review remains historical planning evidence, but those conflicting ID/title pairs are not\nauthoritative lineage edges. A Delta Review must resolve the numbering/order before a future\nimplementation relies on those edges.\n\n<!-- C002_IDENTITY_FINDING_END -->\n

<!-- C001_IMPLEMENTATION_CHECKPOINT_BEGIN -->

## C-001 implementation checkpoint

C-001 implements the evidence-aware source-selection layer described by this review. The router is
read-only and non-executing: it chooses a governed source family or `STOP_REINSPECT`, but existing
Phase 9/12B/14 components retain memory, context, and research execution authority.

The C-002 identity-lineage finding above remains unresolved planning history; C-001 does not silently
renumber later capability IDs.

<!-- C001_IMPLEMENTATION_CHECKPOINT_END -->
